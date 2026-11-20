"""Single entry point: verify frozen inputs, validate accounts, rebuild both years."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import tempfile
import urllib.request
import zipfile

import numpy as np

from figaro import PipelineError, build_year, load_json, parse_document, require


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_path(relative):
    path = (ROOT / relative).resolve()
    require(path.is_relative_to(ROOT) and path != ROOT, f"Path outside project: {relative}")
    return path


def verify_source(record, fetch_missing=False):
    """Never overwrite a present source; accept a download only if its lock matches."""
    path = project_path(record["path"])
    if not path.exists():
        require(fetch_missing and record.get("url"),
                f"Missing frozen source: {record['path']}. Restore the archived file or use --fetch-missing.")
        require(record["url"].startswith("https://ec.europa.eu/"), "Unexpected download host")
        receipt_path = ROOT / "data" / "retrievals.json"
        receipts = load_json(receipt_path) if receipt_path.exists() else []
        require(isinstance(receipts, list) and all(isinstance(r, dict) for r in receipts),
                "Invalid existing retrieval receipt log")
        request = urllib.request.Request(record["url"], headers={"User-Agent": "Thesis-FIGARO-replication/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
            final_url = response.url
        require(len(data) == record["bytes"] and hashlib.sha256(data).hexdigest() == record["sha256"],
                f"Downloaded source differs from locked vintage: {record['path']}; nothing saved. "
                "Restore the archived exact bytes; do not update the lock to today's response.")
        path.parent.mkdir(parents=True, exist_ok=True)
        receipts.append({"path": record["path"], "requested_url": record["url"],
                         "response_url": final_url, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                         "sha256": record["sha256"], "bytes": len(data)})
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".retrieval-", dir=receipt_path.parent) as temporary:
            staged_receipt = Path(temporary) / "retrievals.json"
            write_json(staged_receipt, receipts)
            created = False
            try:
                # Exclusive creation prevents replacing another run's source.
                with path.open("xb") as handle:
                    created = True
                    handle.write(data)
                staged_receipt.replace(receipt_path)
            except OSError:
                if created:
                    path.unlink()  # only the new file owned by this failed restoration
                raise
    require(path.is_file(), f"Source is not a file: {record['path']}")
    require(path.stat().st_size == record["bytes"] and sha256(path) == record["sha256"],
            f"Frozen source checksum/size mismatch: {record['path']}; existing file was not modified")
    return path


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def write_npz(path, arrays):
    """Portable non-pickled NumPy arrays, with fixed ZIP timestamps and member order."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(arrays):
            data = io.BytesIO()
            np.lib.format.write_array(data, np.asarray(arrays[name]), allow_pickle=False)
            info = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, data.getvalue())


def write_matrix(path, codes, matrix):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["supplying_industry / using_industry", *codes])
        for code, row in zip(codes, matrix, strict=True):
            writer.writerow([code, *(format(float(v), ".17g") for v in row)])


def write_accounts(path, arrays, contract):
    factors = contract["cost_factor_codes"]
    factor_indices = [list(arrays["accounting_codes"]).index(code) for code in factors]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["industry", "active", "intermediate_inputs", *factors, "x_inputs",
                         "intermediate_sales", "final_sales", "x_sales", "input_minus_sales"])
        for i, code in enumerate(arrays["industries"]):
            values = [arrays["intermediate_inputs"][i], *arrays["accounting_by_use"][factor_indices, i],
                      arrays["x"][i], arrays["intermediate_sales"][i], arrays["final_sales"][i],
                      arrays["x_sales"][i], arrays["x_gap"][i]]
            writer.writerow([code, int(arrays["active"][i]), *(format(float(v), ".17g") for v in values)])


def run(output_dir, fetch_missing=False):
    manifest_path = ROOT / "data" / "manifest.json"
    manifest = load_json(manifest_path)
    contract_path = ROOT / "data" / "metadata" / "figaro" / "classification.json"
    require(manifest.get("schema_version") == 1, "Unsupported manifest schema")
    require(bool(manifest.get("metadata")), "Official metadata provenance is missing")
    require(manifest.get("classification", {}).get("path") == "data/metadata/figaro/classification.json",
            "Missing classification integrity lock")
    verify_source(manifest["classification"])
    contract = load_json(contract_path)
    require(manifest["dataset"] == contract["dataset"]
            and manifest["source_updated"] == contract["source_updated"], "Manifest/contract vintage mismatch")
    require(len(manifest["inputs"]) == 4 and
            {(r["year"], r["role"]) for r in manifest["inputs"]} ==
            {(year, role) for year in contract["reference_years"] for role in ["uses", "sales"]},
            "Expected exactly one uses/sales pair for each of 2022 and 2023")
    records = manifest["inputs"] + manifest["metadata"]
    require(len({r["path"] for r in records}) == len(records), "Duplicate provenance paths")
    paths = {r["path"]: verify_source(r, fetch_missing) for r in records}
    for record in manifest["inputs"]:
        require(record["source_updated"] == manifest["source_updated"], "Input vintage mismatch")
    parsed = {(r["year"], r["role"]): parse_document(load_json(paths[r["path"]]), r["year"],
              r["role"], contract, manifest["source_updated"]) for r in manifest["inputs"]}
    built = {year: build_year(parsed[year, "uses"], parsed[year, "sales"], contract)
             for year in contract["reference_years"]}
    left, right = [built[year][0] for year in contract["reference_years"]]
    for key in ["industries", "industry_labels", "economies", "final_use_codes", "accounting_codes", "active"]:
        require(np.array_equal(left[key], right[key]), f"Cross-year alignment failed: {key}")

    output = Path(output_dir).resolve()
    require(output != ROOT and not any(output.is_relative_to(ROOT / folder) for folder in
            ["data", "code", "evidence", "thesis", "tests", ".venv"]),
            "Generated results must be separate from source data and code")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Every year validates before any existing result is touched. The report is
    # published last and includes hashes of every numerical artifact.
    with tempfile.TemporaryDirectory(prefix=".figaro-build-", dir=output.parent) as temporary:
        stage = Path(temporary)
        for year, (arrays, report) in built.items():
            write_npz(stage / f"matrices_{year}.npz", arrays)
            for name in ["D", "M", "T0"]:
                write_matrix(stage / f"{name}_{year}.csv", arrays["industries"], arrays[name])
            write_accounts(stage / f"accounting_{year}.csv", arrays, contract)
        artifacts = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
                     for p in sorted(stage.iterdir())}
        validation = {
            "status": "passed", "schema_version": 1,
            "input_integrity": "All four raw extracts and all official source references verified by SHA-256 and size",
            "cross_year_alignment": "Exact code/label/universe and active-mask agreement",
            "years": {str(year): report for year, (_, report) in built.items()},
            "reproducibility": {
                "python": platform.python_version(), "numpy": np.__version__,
                "reference_python": (ROOT / ".python-version").read_text(encoding="utf-8").strip(),
                "randomness": "None; no random seed required",
                "source_hashes": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in
                                  [manifest_path, contract_path, ROOT / "requirements.txt",
                                   ROOT / ".python-version", ROOT / "code" / "figaro.py", Path(__file__).resolve()]},
            },
            "artifacts": artifacts,
        }
        write_json(stage / "validation.json", validation)
        output.mkdir(parents=True, exist_ok=True)
        for name in [*artifacts, "validation.json"]:
            (stage / name).replace(output / name)
    for year, (_, report) in built.items():
        error = report["output_reconciliation"]["max_absolute_gap_million_eur"]
        print(f"{year}: PASS; 64 industries (63 active), 50 economies; max output gap {error:.3g} million EUR")
    print(f"Results: {output}")
    return validation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "data-pipeline",
                        help="Generated results directory (default: outputs/data-pipeline)")
    parser.add_argument("--fetch-missing", action="store_true",
                        help="Fetch absent frozen sources only; accept exactly the locked hash/size")
    args = parser.parse_args()
    try:
        run(args.output_dir, args.fetch_missing)
    except (PipelineError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
