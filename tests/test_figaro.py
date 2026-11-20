"""Accounting and malformed-input regressions using the preserved FIGARO slices.

Run with ``python -m unittest discover -s tests -v`` from the repository root.
Fixtures stay in data/raw; each negative test mutates an in-memory copy.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from figaro import PipelineError, build_year, categories, load_json, parse_document


def observation_key(document, *, use, supplier, country, role="uses"):
    """Address one published observation through all seven JSON-stat dimensions."""
    codes = {
        "freq": "A",
        "ind_use": use,
        "ind_ava": supplier,
        "c_dest": "DE" if role == "uses" else country,
        "unit": "MIO_EUR",
        "c_orig": country if role == "uses" else "DE",
        "time": next(iter(document["dimension"]["time"]["category"]["index"])),
    }
    indices = [
        document["dimension"][dimension]["category"]["index"][codes[dimension]]
        for dimension in document["id"]
    ]
    # An explicit mixed-radix calculation is independent of the parser's reshape.
    index = 0
    for coordinate, size in zip(indices, document["size"]):
        index = index * size + coordinate
    return str(index)


def observation(document, **coordinates):
    return document["value"][observation_key(document, **coordinates)]


def set_observation(document, value, **coordinates):
    document["value"][observation_key(document, **coordinates)] = value


def rename_category(document, dimension, old, new):
    category = document["dimension"][dimension]["category"]
    category["index"][new] = category["index"].pop(old)
    category["label"][new] = category["label"].pop(old)


def reorder_categories(document, dimension, new_codes):
    """Re-encode sparse indices after physically moving one source dimension."""
    axis = document["id"].index(dimension)
    size = document["size"][axis]
    stride = 1
    for following_size in document["size"][axis + 1:]:
        stride *= following_size
    category = document["dimension"][dimension]["category"]
    old_positions = category["index"]
    new_positions = {code: position for position, code in enumerate(new_codes)}
    position_map = {old_positions[code]: new_positions[code] for code in new_codes}
    moved = {}
    for key, value in document["value"].items():
        old_index = int(key)
        old_position = (old_index // stride) % size
        new_index = old_index + (position_map[old_position] - old_position) * stride
        moved[str(new_index)] = value
    document["value"] = moved
    category["index"] = new_positions


class FigaroPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(
            (ROOT / "data/metadata/figaro/classification.json").read_text(encoding="utf-8")
        )
        manifest = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))
        cls.updated = manifest["source_updated"]
        cls.documents = {}
        cls.parsed = {}
        cls.results = {}
        for record in manifest["inputs"]:
            key = record["year"], record["role"]
            cls.documents[key] = load_json(ROOT / record["path"])
            cls.parsed[key] = parse_document(
                cls.documents[key], key[0], key[1], cls.contract, cls.updated
            )
        for year in (2022, 2023):
            cls.results[year] = build_year(
                cls.parsed[year, "uses"], cls.parsed[year, "sales"], cls.contract
            )

    def document(self, role="uses", year=2022):
        return copy.deepcopy(self.documents[year, role])

    def parse(self, document, role="uses", year=2022):
        return parse_document(document, year, role, self.contract, self.updated)

    def build(self, *, uses=None, sales=None, year=2022):
        uses = self.parsed[year, "uses"] if uses is None else self.parse(uses, "uses", year)
        sales = self.parsed[year, "sales"] if sales is None else self.parse(sales, "sales", year)
        return build_year(uses, sales, self.contract)

    def test_both_preserved_years_reconcile_and_keep_full_classification(self):
        for year in (2022, 2023):
            with self.subTest(year=year):
                arrays, _ = self.results[year]
                self.assertEqual(arrays["D"].shape, (64, 64))
                self.assertEqual(arrays["M"].shape, (64, 64))
                self.assertEqual(arrays["T0"].shape, (64, 64))
                self.assertEqual(arrays["Z_by_origin"].shape, (64, 64, 50))
                self.assertEqual(arrays["sales_final_by_destination"].shape, (64, 5, 50))
                self.assertEqual(len(arrays["industries"]), 64)
                self.assertEqual(len(arrays["economies"]), 50)
                self.assertIn("WRL_REST", arrays["economies"])
                self.assertNotIn("DOM", arrays["economies"])
                np.testing.assert_allclose(arrays["x"], arrays["x_sales"], rtol=0, atol=1e-6)
                self.assertLess(float(np.max(np.abs(arrays["x_gap"]))), 1e-6)
                self.assertTrue(np.all(arrays["M"] >= arrays["T0"]))
                np.testing.assert_allclose(
                    arrays["china_row_totals"], arrays["T0"].sum(axis=1), rtol=0, atol=1e-9
                )

    def test_asymmetric_published_cells_fix_supplier_by_user_orientation(self):
        arrays, _ = self.results[2022]
        industries = list(arrays["industries"])
        a01, a02 = industries.index("A01"), industries.index("A02")
        self.assertEqual(arrays["D"][a02, a01], 100.268)
        self.assertEqual(arrays["D"][a01, a02], 78.514)
        self.assertEqual(arrays["T0"][a01, a01], 3.644)
        germany = list(arrays["economies"]).index("DE")
        self.assertEqual(arrays["sales_intermediate_by_destination"][a02, a01, germany], 100.268)
        self.assertEqual(arrays["sales_intermediate_by_destination"][a01, a02, germany], 78.514)

    def test_foreign_input_total_includes_rest_of_world_and_excludes_germany(self):
        arrays, _ = self.results[2022]
        raw = self.documents[2022, "uses"]
        foreign = [row["code"] for row in self.contract["economies"] if row["code"] != "DE"]
        expected = sum(observation(raw, use="A01", supplier="A01", country=c) for c in foreign)
        a01 = list(arrays["industries"]).index("A01")
        self.assertAlmostEqual(arrays["M"][a01, a01], expected, places=9)
        rest = observation(raw, use="A01", supplier="A01", country="WRL_REST")
        self.assertEqual(rest, 86.606)
        self.assertNotAlmostEqual(arrays["M"][a01, a01], expected - rest, places=6)

    def test_signed_taxes_and_inventory_observations_are_preserved(self):
        arrays, _ = self.results[2022]
        industry = list(arrays["industries"])
        accounts = list(arrays["accounting_codes"])
        final = list(arrays["final_use_codes"])
        germany = list(arrays["economies"]).index("DE")
        self.assertEqual(arrays["accounting_by_use"][accounts.index("D29X39"), industry.index("A01")], -5475.997)
        self.assertEqual(arrays["final_uses_by_origin"][industry.index("A02"), final.index("P5M"), germany], -612.582)
        self.assertEqual(arrays["sales_final_by_destination"][industry.index("A02"), final.index("P5M"), germany], -612.582)

    def test_output_uses_signed_domestic_cost_factors(self):
        arrays, _ = self.results[2022]
        raw = self.documents[2022, "uses"]
        industry_codes = [row["code"] for row in self.contract["industries"]]
        economies = [row["code"] for row in self.contract["economies"]]
        intermediate = sum(
            observation(raw, use="A01", supplier=supplier, country=country)
            for supplier in industry_codes for country in economies
        )
        factors = sum(
            observation(raw, use="A01", supplier=code, country="DOM")
            for code in self.contract["cost_factor_codes"]
        )
        a01 = list(arrays["industries"]).index("A01")
        self.assertAlmostEqual(arrays["x"][a01], intermediate + factors, places=6)

    def test_inactive_u_is_retained_with_zero_rows_columns_and_output(self):
        for year in (2022, 2023):
            with self.subTest(year=year):
                arrays, _ = self.results[year]
                u = list(arrays["industries"]).index("U")
                self.assertFalse(bool(arrays["active"][u]))
                self.assertEqual(arrays["x"][u], 0)
                self.assertEqual(arrays["x_sales"][u], 0)
                for name in ("D", "M", "T0"):
                    self.assertTrue(np.all(arrays[name][u, :] == 0), name)
                    self.assertTrue(np.all(arrays[name][:, u] == 0), name)
                self.assertEqual(int(np.count_nonzero(arrays["active"])), 63)

    def test_dictionary_insertion_order_does_not_change_output(self):
        uses, sales = self.document(), self.document("sales")
        for document in (uses, sales):
            for dimension in document["id"]:
                category = document["dimension"][dimension]["category"]
                for field in ("index", "label"):
                    category[field] = dict(reversed(list(category[field].items())))
            document["value"] = dict(reversed(list(document["value"].items())))
        arrays, _ = self.build(uses=uses, sales=sales)
        baseline, _ = self.results[2022]
        for name in ("D", "M", "T0", "x", "Z_by_origin", "accounting_by_use"):
            np.testing.assert_array_equal(arrays[name], baseline[name], err_msg=name)

    def test_reencoded_numeric_category_order_is_aligned_by_code(self):
        uses, sales = self.document(), self.document("sales")
        for document, country_dimension in ((uses, "c_orig"), (sales, "c_dest")):
            for dimension in ("ind_use", "ind_ava", country_dimension):
                old = categories(document, dimension)
                new = old[3:] + old[:3] if dimension == "ind_ava" else list(reversed(old))
                reorder_categories(document, dimension, new)
                self.assertNotEqual(categories(document, dimension), old)
        arrays, _ = self.build(uses=uses, sales=sales)
        baseline, _ = self.results[2022]
        for name in (
            "D", "M", "T0", "x", "x_sales", "Z_by_origin", "final_uses_by_origin",
            "sales_intermediate_by_destination", "sales_final_by_destination", "accounting_by_use",
        ):
            np.testing.assert_array_equal(arrays[name], baseline[name], err_msg=name)

    def test_duplicate_category_indices_are_rejected(self):
        document = self.document()
        index = document["dimension"]["ind_use"]["category"]["index"]
        index["A02"] = index["A01"]
        with self.assertRaises(PipelineError):
            categories(document, "ind_use")

    def test_noncontiguous_category_indices_are_rejected(self):
        document = self.document()
        document["dimension"]["ind_use"]["category"]["index"]["A01"] = 100
        with self.assertRaises(PipelineError):
            categories(document, "ind_use")

    def test_duplicate_json_keys_are_rejected_before_decoding_loses_them(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"value":{"0":1,"0":2}}', encoding="utf-8")
            with self.assertRaises(PipelineError):
                load_json(path)

    def test_industry_label_mismatch_is_rejected(self):
        for dimension in ("ind_use", "ind_ava"):
            with self.subTest(dimension=dimension):
                document = self.document()
                document["dimension"][dimension]["category"]["label"]["A01"] = "Unapproved industry label"
                with self.assertRaises(PipelineError):
                    self.parse(document)

    def test_wrong_unit_frequency_year_or_vintage_is_rejected(self):
        for dimension, old, new in (("unit", "MIO_EUR", "THS_EUR"), ("freq", "A", "Q"), ("time", "2022", "2021")):
            with self.subTest(dimension=dimension):
                document = self.document()
                rename_category(document, dimension, old, new)
                with self.assertRaises(PipelineError):
                    self.parse(document)
        document = self.document()
        document["updated"] = "2025-07-20T11:00:00+0200"
        with self.assertRaises(PipelineError):
            self.parse(document)

    def test_wrong_fixed_country_is_rejected(self):
        for role, dimension in (("uses", "c_dest"), ("sales", "c_orig")):
            with self.subTest(role=role):
                document = self.document(role)
                rename_category(document, dimension, "DE", "FR")
                with self.assertRaises(PipelineError):
                    self.parse(document, role)

    def test_rest_of_world_cannot_be_replaced_with_another_country(self):
        for role, dimension in (("uses", "c_orig"), ("sales", "c_dest")):
            with self.subTest(role=role):
                document = self.document(role)
                rename_category(document, dimension, "WRL_REST", "WORLD_TOTAL")
                with self.assertRaises(PipelineError):
                    self.parse(document, role)

    def test_missing_real_intermediate_observation_is_not_zero_filled(self):
        for role in ("uses", "sales"):
            with self.subTest(role=role):
                document = self.document(role)
                key = observation_key(document, use="A01", supplier="A02", country="BE", role=role)
                del document["value"][key]
                with self.assertRaises(PipelineError):
                    self.build(**{role: document})

    def test_missing_final_observation_is_not_zero_filled(self):
        for role in ("uses", "sales"):
            with self.subTest(role=role):
                document = self.document(role)
                key = observation_key(document, use="P3_S13", supplier="A01", country="BE", role=role)
                del document["value"][key]
                with self.assertRaises(PipelineError):
                    self.build(**{role: document})

    def test_missing_domestic_accounting_factor_is_rejected(self):
        document = self.document()
        del document["value"][observation_key(document, use="A01", supplier="D29X39", country="DOM")]
        with self.assertRaises(PipelineError):
            self.build(uses=document)

    def test_dom_is_accounting_only_even_when_fake_intermediate_is_zero(self):
        for value in (0.0, 1.0):
            with self.subTest(value=value):
                document = self.document()
                set_observation(document, value, use="A01", supplier="A01", country="DOM")
                with self.assertRaises(PipelineError):
                    self.build(uses=document)

    def test_accounting_rows_cannot_be_assigned_to_a_real_origin(self):
        document = self.document()
        set_observation(document, 0.0, use="A01", supplier="D1", country="CN")
        with self.assertRaises(PipelineError):
            self.build(uses=document)

    def test_negative_intermediate_observations_are_rejected(self):
        for role in ("uses", "sales"):
            with self.subTest(role=role):
                document = self.document(role)
                set_observation(document, -0.001, use="A01", supplier="A01", country="BE", role=role)
                with self.assertRaises(PipelineError):
                    self.build(**{role: document})

    def test_nonfinite_and_nonnumeric_observations_are_rejected(self):
        for value in (float("nan"), float("inf"), "1.0", True):
            with self.subTest(value=repr(value)):
                document = self.document()
                set_observation(document, value, use="A01", supplier="A01", country="CN")
                with self.assertRaises(PipelineError):
                    self.parse(document)

    def test_domestic_overlap_must_match(self):
        document = self.document("sales")
        coordinates = dict(use="A01", supplier="A02", country="DE", role="sales")
        set_observation(document, observation(document, **coordinates) + 1, **coordinates)
        with self.assertRaises(PipelineError):
            self.build(sales=document)

    def test_foreign_sales_change_must_fail_input_sales_reconciliation(self):
        document = self.document("sales")
        coordinates = dict(use="P3_S13", supplier="A01", country="BE", role="sales")
        set_observation(document, observation(document, **coordinates) + 1, **coordinates)
        with self.assertRaisesRegex(PipelineError, "Input/sales output reconciliation failed"):
            self.build(sales=document)

    def test_active_industry_with_reconciled_nonpositive_output_is_rejected(self):
        uses, sales = self.document(), self.document("sales")
        arrays, _ = self.results[2022]
        delta = float(arrays["x"][list(arrays["industries"]).index("A01")]) + 1
        # Reduce signed domestic taxes and domestic inventories by the same amount:
        # inputs still equal sales, while the active A01 industry has output -1.
        tax = dict(use="A01", supplier="D29X39", country="DOM")
        set_observation(uses, observation(uses, **tax) - delta, **tax)
        for document, role in ((uses, "uses"), (sales, "sales")):
            inventory = dict(use="P5M", supplier="A01", country="DE", role=role)
            set_observation(document, observation(document, **inventory) - delta, **inventory)
        with self.assertRaisesRegex(PipelineError, "Negative industry output"):
            self.build(uses=uses, sales=sales)

    def test_active_non_u_industry_with_zero_input_output_is_rejected(self):
        uses, sales = self.document(), self.document("sales")
        for supplier in [row["code"] for row in self.contract["industries"]]:
            for country in [row["code"] for row in self.contract["economies"]]:
                set_observation(uses, 0.0, use="A01", supplier=supplier, country=country)
            set_observation(sales, 0.0, use="A01", supplier=supplier, country="DE", role="sales")
        for factor in self.contract["cost_factor_codes"]:
            set_observation(uses, 0.0, use="A01", supplier=factor, country="DOM")
        # A01 input-side output is exactly zero, although A01 still supplies A02.
        self.assertEqual(observation(uses, use="A02", supplier="A01", country="DE"), 78.514)
        with self.assertRaisesRegex(PipelineError, "Unexpected zero-output/inactive industry"):
            self.build(uses=uses, sales=sales)

    def test_u_with_cancelling_signed_flows_is_not_silently_dropped(self):
        uses, sales = self.document(), self.document("sales")
        for document, role in ((uses, "uses"), (sales, "sales")):
            set_observation(document, 1.0, use="P3_S13", supplier="U", country="DE", role=role)
            set_observation(document, -1.0, use="P5M", supplier="U", country="DE", role=role)
        # The signed flows cancel in x_sales, so output reconciliation alone cannot
        # distinguish this active U industry from the genuine all-zero source row.
        with self.assertRaisesRegex(PipelineError, "Active flows or accounting entries in zero-output industry U"):
            self.build(uses=uses, sales=sales)


if __name__ == "__main__":
    unittest.main()
