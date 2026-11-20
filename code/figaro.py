"""Parse the locked FIGARO extracts and construct supplier-row/user-column accounts.

Missing observations remain missing until a complete structural pattern has been
validated. No general missing-value replacement or clipping is used.
"""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np


class PipelineError(ValueError):
    """A source or accounting contract failed; outputs must not be published."""


def require(condition, message):
    if not condition:
        raise PipelineError(message)


def load_json(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique_object)


def categories(document, dimension):
    """Read category positions, independently of JSON dictionary insertion order."""
    try:
        category = document["dimension"][dimension]["category"]
        index, labels = category["index"], category["label"]
    except (KeyError, TypeError) as exc:
        raise PipelineError(f"Missing category metadata: {dimension}") from exc
    require(isinstance(index, dict) and bool(index), f"Invalid category index: {dimension}")
    require(all(isinstance(code, str) and code for code in index), f"Invalid codes: {dimension}")
    require(all(type(i) is int for i in index.values()), f"Noninteger indices: {dimension}")
    require(sorted(index.values()) == list(range(len(index))),
            f"Duplicate or noncontiguous category indices: {dimension}")
    require(set(labels) == set(index), f"Missing or extra category labels: {dimension}")
    require(all(isinstance(label, str) and label for label in labels.values()),
            f"Invalid category labels: {dimension}")
    return sorted(index, key=index.get)


@dataclass
class ParsedSlice:
    document: dict
    values: np.ndarray
    category_codes: dict
    year: int
    role: str


def parse_document(document, year, role, contract, source_updated):
    """Validate source identity and decode JSON-stat without treating absence as zero."""
    require(role in {"uses", "sales"}, f"Unknown slice role: {role}")
    require(document.get("class") == "dataset" and document.get("version") == "2.0",
            "Expected a JSON-stat 2.0 dataset")
    require(document.get("extension", {}).get("id") == contract["dataset"], "Wrong dataset")
    require(document.get("source") == "ESTAT", "Wrong source agency")
    require(document.get("updated") == source_updated == contract["source_updated"],
            "Wrong source vintage/update timestamp")
    dimensions = document.get("id")
    require(dimensions == contract["expected_dimension_ids"], "Unexpected dimension order")
    require(set(document.get("dimension", {})) == set(dimensions), "Unexpected dimension metadata")
    codes = {d: categories(document, d) for d in dimensions}
    sizes = document.get("size")
    require(isinstance(sizes, list) and all(type(n) is int and n > 0 for n in sizes),
            "Invalid dimension sizes")
    require(sizes == [len(codes[d]) for d in dimensions], "Dimension size/index mismatch")
    require(year in contract["reference_years"], "Unapproved reference year")
    require(codes["time"] == [str(year)], "Wrong reference year")
    require(codes["unit"] == [contract["unit"]], "Wrong unit")
    require(codes["freq"] == [contract["frequency"]], "Wrong frequency")

    industries = contract["industries"]
    expected = {"ind_use": industries + contract["final_uses"],
                "ind_ava": industries + contract["accounting_items"]}
    economies = contract["economies"]
    de = next(item for item in economies if item["code"] == contract["domestic_country"])
    dom = {"code": contract["domestic_accounting_code"], "label": "Domestic country"}
    expected["c_orig"] = economies + [dom] if role == "uses" else [de]
    expected["c_dest"] = [de] if role == "uses" else economies
    for dim, items in expected.items():
        expected_labels = {item["code"]: item["label"] for item in items}
        require(set(codes[dim]) == set(expected_labels), f"Category alignment failed: {dim}")
        require(document["dimension"][dim]["category"]["label"] == expected_labels,
                f"Category label alignment failed: {dim}")

    count = int(np.prod(sizes))
    vector = np.full(count, np.nan, dtype=np.float64)
    values = document.get("value")
    require(isinstance(values, dict), "Expected sparse JSON-stat value object")
    for key, value in values.items():
        require(isinstance(key, str) and key.isascii() and key.isdigit()
                and str(int(key)) == key and int(key) < count, f"Invalid observation index: {key}")
        require(type(value) in {int, float} and np.isfinite(value),
                f"Invalid/missing/nonfinite observation at index {key}")
        vector[int(key)] = value
    status = document.get("status", {})
    require(isinstance(status, dict), "Unexpected observation status format")
    require(all(k in values and isinstance(v, str) for k, v in status.items()),
            "Invalid observation status entries")
    # These axes are explicit after checking their names and singleton dimensions.
    full = vector.reshape(sizes)[0, :, :, :, 0, :, 0]
    cube = full[:, :, 0, :] if role == "uses" else full[:, :, :, 0]
    return ParsedSlice(document, cube, codes, year, role)


def _select(source, using, supplying, countries):
    country_dim = "c_orig" if source.role == "uses" else "c_dest"
    positions = [[source.category_codes[dim].index(code) for code in wanted]
                 for dim, wanted in [("ind_use", using), ("ind_ava", supplying),
                                     (country_dim, countries)]]
    return source.values[np.ix_(*positions)]


def _all_present(values, description):
    require(np.isfinite(values).all(), f"Missing observation in {description}")


def _all_absent(values, description):
    require(np.isnan(values).all(), f"Unexpected observations in structural absence: {description}")


def _sign_summary(values):
    return {"count": int(values.size), "negative_count": int(np.count_nonzero(values < 0)),
            "minimum": float(values.min()), "sum": float(values.sum())}


def build_year(uses, sales, contract):
    """Build D, M, T0 and x, retaining detailed signed accounts for audit/reuse."""
    require(uses.role == "uses" and sales.role == "sales", "Slice roles reversed")
    require(uses.year == sales.year, "Slice years do not match")
    industries = [item["code"] for item in contract["industries"]]
    economies = [item["code"] for item in contract["economies"]]
    final_uses = [item["code"] for item in contract["final_uses"]]
    accounting_codes = [item["code"] for item in contract["accounting_items"]]
    all_uses = industries + final_uses
    de, cn, dom = [contract[key] for key in
                   ["domestic_country", "china_country", "domestic_accounting_code"]]
    require(len(industries) == 64 and len(economies) == 50, "Wrong classification size")
    require("WRL_REST" in economies and dom not in economies, "Invalid economy universe")

    # Check the *entire* presence pattern, including final uses needed for sales.
    real_uses = _select(uses, all_uses, industries, economies)
    real_sales = _select(sales, all_uses, industries, economies)
    accounting = _select(uses, all_uses, accounting_codes, [dom])[:, :, 0].T
    _all_present(real_uses, "real-economy uses (intermediate and final)")
    _all_present(real_sales, "worldwide sales (intermediate and final)")
    _all_present(accounting, "DOM accounting rows")
    _all_absent(_select(uses, all_uses, industries, [dom]), "DOM industry flows")
    _all_absent(_select(uses, all_uses, accounting_codes, economies), "real-origin accounting rows")
    _all_absent(_select(sales, all_uses, accounting_codes, economies), "sales accounting rows")

    n = len(industries)
    # Both raw industry axes are explicitly reordered to the saved code contract
    # before the transpose from (user, supplier, country).
    Z = real_uses[:n].transpose(1, 0, 2).copy()
    F = real_uses[n:].transpose(1, 0, 2).copy()
    S = real_sales[:n].transpose(1, 0, 2).copy()
    SF = real_sales[n:].transpose(1, 0, 2).copy()
    require((Z >= 0).all() and (S >= 0).all(), "Negative intermediate flow")
    d, c = economies.index(de), economies.index(cn)
    require(np.array_equal(Z[:, :, d], S[:, :, d]), "Domestic DE intermediate overlap mismatch")
    require(np.array_equal(F[:, :, d], SF[:, :, d]), "Domestic DE final-use overlap mismatch")
    D = Z[:, :, d].copy()
    foreign = [i for i, code in enumerate(economies) if code != de]
    M = Z[:, :, foreign].sum(axis=2)
    T0 = Z[:, :, c].copy()
    require((T0 <= M).all(), "China flows exceed all-origin import capacity")
    factors = [accounting_codes.index(code) for code in contract["cost_factor_codes"]]
    residence = [accounting_codes.index(code) for code in ["OP_RES", "OP_NRES"]]
    require((accounting[residence, :n] == 0).all(), "Nonzero residence adjustment for industry uses")
    intermediate_inputs = Z.sum(axis=(0, 2))
    x = intermediate_inputs + accounting[factors, :n].sum(axis=0)
    intermediate_sales = S.sum(axis=(1, 2))
    final_sales = SF.sum(axis=(1, 2))
    x_sales = intermediate_sales + final_sales
    require((x >= 0).all() and (x_sales >= 0).all(), "Negative industry output")
    inactive = np.flatnonzero(x == 0)
    require([industries[i] for i in inactive] == ["U"],
            "Unexpected zero-output/inactive industry; locked edition expects only U")
    for i in inactive:
        require((Z[:, i, :] == 0).all() and (Z[i, :, :] == 0).all()
                and (F[i, :, :] == 0).all() and (S[:, i, :] == 0).all()
                and (S[i, :, :] == 0).all() and (SF[i, :, :] == 0).all()
                and (accounting[:, i] == 0).all() and x_sales[i] == 0,
                "Active flows or accounting entries in zero-output industry U")
    gap = x - x_sales
    tolerance = 1e-7  # million EUR, absolute; no relative tolerance hides discrepancies
    require(np.max(np.abs(gap)) <= tolerance,
            f"Input/sales output reconciliation failed: max gap {np.max(np.abs(gap)):.12g} million EUR")

    arrays = {
        "industries": np.asarray(industries),
        "industry_labels": np.asarray([item["label"] for item in contract["industries"]]),
        "economies": np.asarray(economies), "final_use_codes": np.asarray(final_uses),
        "accounting_codes": np.asarray(accounting_codes), "use_codes": np.asarray(all_uses),
        "D": D, "M": M, "T0": T0, "x": x, "x_sales": x_sales, "x_gap": gap,
        "active": x > 0, "china_row_totals": T0.sum(axis=1), "Z_by_origin": Z,
        "final_uses_by_origin": F, "sales_intermediate_by_destination": S,
        "sales_final_by_destination": SF, "accounting_by_use": accounting,
        "intermediate_inputs": intermediate_inputs, "intermediate_sales": intermediate_sales,
        "final_sales": final_sales, "unit": np.asarray(contract["unit"]),
        "year": np.asarray(uses.year), "source_updated": np.asarray(contract["source_updated"]),
    }
    report = {
        "year": uses.year, "status": "passed", "industries": n, "economies": len(economies),
        "active_industries": int(np.count_nonzero(x)), "inactive_industries": ["U"],
        "unit": contract["unit"], "valuation": "current basic prices",
        "matrix_convention": "supplier rows, user columns",
        "source_updated": contract["source_updated"],
        "complete_intermediate_cells_per_slice": int(Z.size),
        "complete_final_use_cells_per_slice": int(F.size),
        "dom_accounting_cells": int(accounting.size),
        "structural_absences_uses": int(np.isnan(uses.values).sum()),
        "structural_absences_sales": int(np.isnan(sales.values).sum()),
        "missing_required_observations": 0, "negative_intermediate_observations": 0,
        "domestic_overlap": "exact equality for intermediate and final uses",
        "domestic_flow_identifier": {"origin": de, "destination": de},
        "tax_and_accounting_rows": {code: _sign_summary(accounting[i, :n])
                                    for i, code in enumerate(accounting_codes)},
        "signed_final_uses_received": _sign_summary(F),
        "signed_final_sales": _sign_summary(SF),
        "output_reconciliation": {
            "absolute_tolerance_million_eur": tolerance,
            "max_absolute_gap_million_eur": float(np.abs(gap).max()),
            "max_relative_gap_active": float((np.abs(gap[x > 0]) / x[x > 0]).max()),
            "exceptions": [],
        },
        "totals_million_eur": {"domestic_intermediate": float(D.sum()),
                               "all_imported_intermediate": float(M.sum()),
                               "china_intermediate": float(T0.sum()),
                               "rest_of_world_intermediate": float(Z[:, :, economies.index("WRL_REST")].sum()),
                               "gross_output": float(x.sum())},
        "observation_status": {role: {"status_object_supplied": "status" in obj.document,
                                      "flagged_observations": len(obj.document.get("status", {}))}
                               for role, obj in [("uses", uses), ("sales", sales)]},
    }
    return arrays, report
