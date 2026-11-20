"""Audit and combine the frozen historical FIGARO inputs, without changing them.

Uses the established accounting parser with per-year source identifiers. Writes a
compressed all-year array archive, two compact CSV panels and their audit record.
No imputations, deflation, exposure estimates or ranking calculations are made.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import tempfile
import zipfile
import zlib

import numpy as np


EXTENSION = Path(__file__).resolve().parent
ROOT = EXTENSION.parents[1]
DEFAULT_OUTPUT = EXTENSION / "data" / "processed"
sys.path.insert(0, str(ROOT / "code"))

from figaro import build_year, load_json, parse_document, require
import download_data


YEARS = download_data.YEARS
MONEY_TOL = 1e-7  # Million euros; the unchanged baseline absolute tolerance.
STATIC = {"industries", "industry_labels", "economies", "final_use_codes",
          "accounting_codes", "use_codes", "unit"}
ARTIFACTS = ("history_2010_2024.npz", "intermediate_panel.csv", "industry_accounts.csv")
OUTPUT_NAMES = {*ARTIFACTS, "validation.json", "data-audit.md"}
PANEL_HEADER = ["year", "supplying_industry", "using_industry",
                "domestic_intermediate_million_eur", "imported_intermediate_million_eur",
                "china_intermediate_million_eur"]


def fingerprint(path):
    path = Path(path)
    with path.open("rb") as handle:
        return {"bytes": path.stat().st_size,
                "sha256": hashlib.file_digest(handle, "sha256").hexdigest()}


def relative(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False)
                          + "\n", encoding="utf-8", newline="\n")


def write_archive(path, arrays):
    """Lossless float64 compression with fixed ZIP dates and no pickled objects."""
    with zipfile.ZipFile(path, "w") as archive:
        for name in sorted(arrays):
            data = io.BytesIO()
            np.lib.format.write_array(data, arrays[name], allow_pickle=False)
            info = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data.getvalue(), compresslevel=6)


def csv_number(value):
    return format(float(value), ".17g")


def audit_year(arrays, report, contract):
    """Check readiness and record signs/support without estimating exposure."""
    industries = list(arrays["industries"])
    active = arrays["active"]
    economies = list(arrays["economies"])
    foreign = [i for i, code in enumerate(economies) if code != "DE"]
    delivered = arrays["x"] - arrays["D"].sum(axis=1)
    observed = arrays["sales_intermediate_by_destination"][:, :, foreign].sum(axis=(1, 2))
    observed += arrays["sales_final_by_destination"].sum(axis=(1, 2))
    delivery_gap = float(np.abs(delivered - observed).max())
    require(delivery_gap <= MONEY_TOL, "External-delivery reconciliation failed")
    require((delivered[active] > 0).all() and (delivered[~active] == 0).all(),
            "Nonpositive delivery in active industry or nonzero inactive delivery")
    A = arrays["D"][np.ix_(active, active)] / arrays["x"][active][None, :]
    radius = float(np.max(np.abs(np.linalg.eigvals(A))))
    require(np.isfinite(radius) and radius < 1, "Unproductive domestic system")
    condition = float(np.linalg.cond(np.eye(active.sum()) - A))
    require(np.isfinite(condition), "Nonfinite domestic-system condition diagnostic")
    arrays["external_deliveries"] = delivered
    report["readiness"] = {
        "external_delivery_max_gap_million_eur": delivery_gap,
        "minimum_active_external_delivery_million_eur": float(delivered[active].min()),
        "domestic_coefficient_spectral_radius": radius,
        "condition_number_2_estimate": condition,
        "note": "Ordinary floating-point readiness diagnostics, not error bounds or empirical results.",
    }
    report["support"] = {
        "zero_domestic_intermediate_cells": int(np.count_nonzero(arrays["D"] == 0)),
        "zero_imported_intermediate_cells": int(np.count_nonzero(arrays["M"] == 0)),
        "zero_china_intermediate_cells": int(np.count_nonzero(arrays["T0"] == 0)),
        "zero_import_using_industries": [industries[j] for j in
                                         np.flatnonzero((arrays["M"] == 0).all(axis=0))],
    }
    report["negative_final_values_by_category"] = {
        name: {str(code): int(np.count_nonzero(arrays[key][:, j, :] < 0))
               for j, code in enumerate(arrays["final_use_codes"])}
        for name, key in [("received", "final_uses_by_origin"),
                          ("sold", "sales_final_by_destination")]
    }
    report["negative_accounting_values_by_item"] = {
        str(code): int(np.count_nonzero(arrays["accounting_by_use"][j] < 0))
        for j, code in enumerate(arrays["accounting_codes"])
    }
    report["china_source_sut_status"] = "OECD_ICIO" if report["year"] <= 2019 else "EE"
    report["source_dataset"] = contract["dataset"]


def compare_baseline(year, arrays, validation):
    """Require exact agreement with every preserved annual array, including detail."""
    path = ROOT / "outputs" / "data-pipeline" / f"matrices_{year}.npz"
    require(fingerprint(path) == validation["artifacts"][path.name],
            f"Preserved baseline artifact integrity failed: {year}")
    with np.load(path, allow_pickle=False) as old:
        for name in old.files:
            require(name in arrays and arrays[name].dtype == old[name].dtype and
                    np.array_equal(arrays[name], old[name]),
                    f"Historical preparation differs from baseline {year}: {name}")
        return {"path": relative(path), **fingerprint(path),
                "arrays_compared": len(old.files), "exact_agreement": True}


def stack_years(built, reports):
    require(set(built) == set(YEARS), "Exactly 2010-2024 must be present")
    reference = built[YEARS[0]]
    for year in YEARS:
        require(set(built[year]) == set(reference), f"Array fields differ in {year}")
        require(int(built[year]["year"]) == year, "Annual array year mismatch")
        for name in STATIC | {"active"}:
            require(np.array_equal(built[year][name], reference[name]),
                    f"Cross-year alignment failed: {name}, {year}")
    combined = {name: reference[name] for name in STATIC}
    combined["years"] = np.asarray(YEARS)
    for name in sorted(set(reference) - STATIC - {"year"}):
        combined[name] = np.stack([built[year][name] for year in YEARS])
    combined["source_dataset"] = np.asarray([reports[year]["source_dataset"] for year in YEARS])
    combined["china_source_sut_status"] = np.asarray(
        [reports[year]["china_source_sut_status"] for year in YEARS])
    return combined


def write_panels(stage, built, contract):
    with (stage / "intermediate_panel.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(PANEL_HEADER)
        for year in YEARS:
            arr = built[year]
            for i, supplier in enumerate(arr["industries"]):
                for j, user in enumerate(arr["industries"]):
                    writer.writerow([year, supplier, user,
                                     *(csv_number(arr[name][i, j]) for name in ("D", "M", "T0"))])
    factors = contract["cost_factor_codes"]
    values = ["intermediate_inputs", *factors, "x", "intermediate_sales", "final_sales",
              "x_sales", "x_gap", "external_deliveries"]
    with (stage / "industry_accounts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["year", "industry", "active", *(name + "_million_eur" for name in values)])
        for year in YEARS:
            arr = built[year]
            for j, industry in enumerate(arr["industries"]):
                data = [arr["accounting_by_use"][list(arr["accounting_codes"]).index(name), j]
                        if name in factors else arr[name][j] for name in values]
                writer.writerow([year, industry, int(arr["active"][j]), *(csv_number(v) for v in data)])


def verify_round_trip(stage, combined, built, contract):
    with np.load(stage / "history_2010_2024.npz", allow_pickle=False) as restored:
        require(set(restored.files) == set(combined), "Archive fields differ")
        for name, expected in combined.items():
            require(restored[name].dtype == expected.dtype and
                    np.array_equal(restored[name], expected), f"Archive round trip differs: {name}")
    codes = [str(c) for c in combined["industries"]]
    position = {code: i for i, code in enumerate(codes)}
    with (stage / "intermediate_panel.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames == PANEL_HEADER, "Panel header differs")
        seen = set()
        for row in reader:
            year, supplier, user = int(row["year"]), row["supplying_industry"], row["using_industry"]
            key = (year, supplier, user)
            require(key not in seen, "Duplicate industry-pair/year key")
            seen.add(key)
            i, j = position[supplier], position[user]
            for name, column in zip(("D", "M", "T0"), PANEL_HEADER[3:], strict=True):
                require(float(row[column]) == built[year][name][i, j], "Panel value round trip differs")
    require(seen == {(y, i, j) for y in YEARS for i in codes for j in codes},
            "Industry-pair panel coverage differs")
    factors = contract["cost_factor_codes"]
    with (stage / "industry_accounts.csv").open(encoding="utf-8", newline="") as handle:
        seen_accounts = set()
        for row in csv.DictReader(handle):
            year, industry = int(row["year"]), row["industry"]
            require((year, industry) not in seen_accounts, "Duplicate industry-year key")
            seen_accounts.add((year, industry))
            arr, j = built[year], position[industry]
            require(int(row["active"]) == int(arr["active"][j]), "Activity flag differs")
            for column in set(row) - {"year", "industry", "active"}:
                name = column.removesuffix("_million_eur")
                expected = (arr["accounting_by_use"][list(arr["accounting_codes"]).index(name), j]
                            if name in factors else arr[name][j])
                require(float(row[column]) == expected, "Accounting panel round trip differs")
    require(seen_accounts == {(y, i) for y in YEARS for i in codes}, "Industry-year panel coverage differs")
    return {"archive_all_fields_exact": True, "intermediate_panel_unique_rows": len(seen),
            "industry_accounts_unique_rows": len(seen_accounts), "all_csv_values_exact": True}


def audit_markdown(report):
    years = report["years"]
    worst = max(r["output_reconciliation"]["max_absolute_gap_million_eur"] for r in years.values())
    negative_final_codes = sorted({code for row in years.values()
                                   for counts in row["negative_final_values_by_category"].values()
                                   for code, count in counts.items() if count})
    archive = report["artifacts"][ARTIFACTS[0]]["bytes"] / 1e6
    panel = report["artifacts"][ARTIFACTS[1]]["bytes"] / 1e6
    lines = ["# Historical FIGARO data audit, 2010-2024", "",
        "All fifteen annual accounts pass the declared data and accounting checks. No source values needed correction, imputation, clipping, rebalancing or deletion. This is data preparation; no exposure, ranking, decomposition or causal result is estimated.", "",
        f"The largest cost-side versus sales-side output discrepancy is {worst:.12g} million euros ({worst * 1e6:.6g} euros), below the unchanged absolute tolerance of 1e-7 million euros. This reconciles the published accounts; it does not independently validate their underlying sources.", "",
        "## Handling required before analysis", "",
        "- Preserve signed inventory/final-use, operating-surplus/mixed-income, tax/subsidy and residence-adjustment entries. Nonnegativity applies to intermediate flows, not every account. "
        f"Observed negative final-use categories: {', '.join(negative_final_codes) or 'none'}. The annual audit also records negative accounting entries by item.",
        "- Keep the 64-category universe. U has zero output and flows in every year; retain it with active=false and exclude it from per-unit-output denominators. The other 63 industries have positive output and external deliveries.",
        "- Distinguish DE domestic flows from DOM accounting entries. Keep WRL_REST in foreign-origin totals. Structurally absent source positions are not imputed zeros.",
        "- Uses and sales are overlapping views: DE-to-DE intermediate and final flows agree exactly. Keep the named archive arrays separate; do not add the two views as disjoint transactions. The intermediate panel has one row per year/supplier/user. China inputs are a subset of all imported inputs, so its three value columns must not all be added together.",
        "- Retain current-basic-price units. Ratios are not deflators, and a temporal movement cannot by itself identify physical sourcing or a policy effect.",
        "- China's source SUT status is OECD_ICIO for 2010-2019 and EE (Eurostat estimates using other-year SUTs) for 2020-2024. This source-construction distinction is recorded per year; it does not mean every Chinese bilateral cell has the same estimation method. Missing observation-status flags do not mean every cell was directly observed. See the preserved official metadata, section 18.3, referenced and hashed in validation.json.", "",
        "## Combined files", "",
        f"- [history_2010_2024.npz](history_2010_2024.npz): {archive:.2f} MB, losslessly compressed float64 arrays covering all fifteen years, all origins/destinations, final uses and signed accounts. Named arrays follow the existing baseline schema, with a leading year axis; classifications are stored once.",
        f"- [intermediate_panel.csv](intermediate_panel.csv): {panel:.2f} MB and 61,440 unique year/supplying-industry/using-industry rows containing D, M and T0. CSV values retain round-trip numeric precision.",
        "- [industry_accounts.csv](industry_accounts.csv): 960 unique year/industry rows, including output, cost factors, sales, external deliveries and the activity mask. Join output for an input coefficient on year and using industry; joining on year alone would duplicate observations.",
        "- [validation.json](validation.json): annual checks, signs, source and code hashes, file sizes, exact 2022-2023 baseline comparisons, archive schema and output checksums.", "",
        "The raw downloads, acquisition manifest and original research pipeline are unchanged. The original 2022 and 2023 arrays agree exactly with the preserved baseline. All saved numerical values were read back and compared; no precision reduction was used.", "",
        "## Annual checks", "",
        "Negative final-use counts describe the two overlapping source views separately; they must not be summed as unique transactions.", "",
        "| Year | Active industries | Maximum output gap (million EUR) | Negative final uses received | Negative final sales | China source SUT status |",
        "|---|---:|---:|---:|---:|---|"]
    for year in YEARS:
        r = years[str(year)]
        lines.append(f"| {year} | {r['active_industries']} | {r['output_reconciliation']['max_absolute_gap_million_eur']:.3g} | {r['signed_final_uses_received']['negative_count']} | {r['signed_final_sales']['negative_count']} | {r['china_source_sut_status']} |")
    lines += ["", "## Reproduce", "", "From the project root, using the existing pinned environment:", "", "```powershell",
              ".\\.venv\\Scripts\\python.exe -B extensions\\history-2010-2024\\prepare_data.py",
              ".\\.venv\\Scripts\\python.exe -B extensions\\history-2010-2024\\prepare_data.py --check", "```", "",
              "The first command rebuilds and validates the prepared data. The second checks stored input, code and output fingerprints offline without writing. The full archive additionally preserves the signed values beyond the compact CSVs. See the canonical data codebook for definitions and axis conventions.", ""]
    return "\n".join(lines)


def check_output(output):
    report = load_json(output / "validation.json")
    require(report["status"] == "passed" and report["reference_years"] == list(YEARS),
            "Invalid preparation audit")
    require({p.name for p in output.iterdir()} == OUTPUT_NAMES, "Missing or unexpected prepared files")
    for section in ("sources", "code_and_environment", "baseline_comparisons"):
        for path, expected in report[section].items():
            current = fingerprint(ROOT / path)
            require(all(current[k] == expected[k] for k in ("bytes", "sha256")),
                    f"Preparation dependency changed: {path}")
    for name, expected in report["artifacts"].items():
        require(fingerprint(output / name) == expected, f"Prepared artifact changed: {name}")
    require((output / "data-audit.md").read_text(encoding="utf-8") == audit_markdown(report),
            "Human-readable audit differs from validation record")
    print("PASS: all prepared files and their raw-input, code and baseline dependencies verified offline.", flush=True)
    return report


def run(output, check_only=False):
    output = Path(output).resolve()
    require(not output.is_relative_to(ROOT) or output == DEFAULT_OUTPUT,
            "Within the project, prepared data may only be written to the extension's data/processed folder")
    if check_only:
        return check_output(output)
    if output.exists():
        require(all(p.is_file() and p.name in OUTPUT_NAMES for p in output.iterdir()),
                "Output folder contains unrelated files; nothing overwritten")
    _, contract = download_data.load_contract()
    manifest = load_json(download_data.MANIFEST)
    require(manifest["status"] == "complete", "Historical acquisition is incomplete")
    download_data.verify_all(manifest, contract)
    require(not any(r["status_counts"] for r in manifest["inputs"]),
            "Flagged observations require explicit cell-level treatment before preparing this archive")
    records = {(r["year"], r["role"]): r for r in manifest["inputs"]}
    baseline_validation = load_json(ROOT / "outputs/data-pipeline/validation.json")
    built, reports, baseline = {}, {}, {}
    for year in YEARS:
        rec = records[year, "uses"]
        annual_contract = dict(contract, dataset=rec["dataset"], source_updated=rec["source_updated"],
                               reference_years=[year])
        parsed = {}
        for role in ("uses", "sales"):
            record = records[year, role]
            parsed[role] = parse_document(load_json(ROOT / record["path"]), year, role,
                                          annual_contract, record["source_updated"])
        arrays, report = build_year(parsed["uses"], parsed["sales"], annual_contract)
        if year in (2022, 2023):
            comparison = compare_baseline(year, arrays, baseline_validation)
            baseline[comparison.pop("path")] = comparison
        audit_year(arrays, report, annual_contract)
        built[year], reports[year] = arrays, report
        print(f"{year}: accounts, source overlap, activity and delivery checks passed.", flush=True)
    combined = stack_years(built, reports)
    source_paths = [ROOT / r["path"] for r in manifest["inputs"]]
    source_paths += [ROOT / r["path"] for r in manifest["local_references"]]
    source_paths += [download_data.MANIFEST, ROOT / "outputs/data-pipeline/validation.json"]
    code_paths = [Path(__file__).resolve(), EXTENSION / "download_data.py", ROOT / "code/figaro.py",
                  ROOT / ".python-version", ROOT / "requirements.txt"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".history-prepare-", dir=output.parent) as temporary:
        stage = Path(temporary)
        write_archive(stage / ARTIFACTS[0], combined)
        write_panels(stage, built, contract)
        round_trip = verify_round_trip(stage, combined, built, contract)
        report = {
            "schema_version": 1, "status": "passed", "reference_years": list(YEARS),
            "scope": "Data audit and preparation only; no exposure or ranking analysis",
            "unit": "MIO_EUR", "valuation": "current basic prices",
            "cleaning": {"imputed_values": 0, "clipped_values": 0, "rebalanced_values": 0,
                         "dropped_published_observations": 0, "raw_files_modified": 0,
                         "action": "Canonical code alignment, explicit axis transposition, documented sums and stacking by year"},
            "coverage": {"annual_extracts": 30,
                         "published_observations_in_two_views": sum(r["observations"] for r in manifest["inputs"]),
                         "domestic_overlap_per_year": 64 * 69,
                         "unique_source_observations": sum(r["observations"] for r in manifest["inputs"]) - len(YEARS) * 64 * 69,
                         "overlap_handling": "DE-to-DE flows compared exactly and retained in distinct named uses/sales arrays; never summed as disjoint flows"},
            "cross_year_alignment": "Exact codes, labels and 63-active/one-inactive classification in all 15 years",
            "sources": {relative(p): fingerprint(p) for p in source_paths},
            "code_and_environment": {relative(p): fingerprint(p) for p in code_paths},
            "baseline_comparisons": baseline,
            "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                        "zlib": zlib.ZLIB_RUNTIME_VERSION, "randomness": "None"},
            "round_trip_checks": round_trip,
            "years": {str(year): reports[year] for year in YEARS},
            "array_schema": {name: {"shape": list(arr.shape), "dtype": str(arr.dtype),
                                    "year_axis": 0 if name not in STATIC else None}
                             for name, arr in sorted(combined.items())},
            "artifacts": {name: fingerprint(stage / name) for name in ARTIFACTS},
        }
        (stage / "data-audit.md").write_text(audit_markdown(report), encoding="utf-8", newline="\n")
        write_json(stage / "validation.json", report)
        check_output(stage)
        output.mkdir(parents=True, exist_ok=True)
        for name in (*ARTIFACTS, "data-audit.md", "validation.json"):
            (stage / name).replace(output / name)
    print(json.dumps({"output": str(output), "artifacts": report["artifacts"],
                      "round_trip_checks": round_trip}, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Verify saved fingerprints offline without writing")
    args = parser.parse_args()
    run(args.output_dir, args.check)
