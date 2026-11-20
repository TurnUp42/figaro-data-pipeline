"""Acquire the historical FIGARO inputs without changing the frozen thesis pipeline.

Run with the project's existing Python environment. Default: acquire/resume missing
annual extracts. --check: verify all 30 inputs offline, without writing anything.
This script checks transport, classification and observation coverage only. It does
not build economic matrices, reconcile annual accounts or run thesis analyses.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXTENSION = Path(__file__).resolve().parent
ROOT = EXTENSION.parents[1]
MANIFEST = EXTENSION / "data" / "manifest.json"
RAW = EXTENSION / "data" / "raw" / "figaro" / "2026-07-20"
BASE_MANIFEST = ROOT / "data" / "manifest.json"
CONTRACT_PATH = ROOT / "data" / "metadata" / "figaro" / "classification.json"
YEARS = tuple(range(2010, 2025))
API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
PARTITIONS = (
    (2010, 2013, "NAIO_10_FCP_II1", "2026-07-18T23:00:00+0200"),
    (2014, 2017, "NAIO_10_FCP_II2", "2026-07-18T23:00:00+0200"),
    (2018, 2021, "NAIO_10_FCP_II3", "2026-07-18T23:00:00+0200"),
    (2022, 2024, "NAIO_10_FCP_II4", "2026-07-20T11:00:00+0200"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative(path):
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj


def read_json(data):
    def invalid_constant(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")
    return json.loads(data, object_pairs_hook=unique_object,
                      parse_constant=invalid_constant)


def partition(year):
    for first, last, dataset, updated in PARTITIONS:
        if first <= year <= last:
            return dataset, updated
    raise ValueError(f"Unexpected year: {year}")


def source_url(year, role):
    dataset, _ = partition(year)
    selector = "c_dest" if role == "uses" else "c_orig"
    return f"{API}{dataset.lower()}?lang=en&time={year}&{selector}=DE"


def categories(doc, dimension):
    category = doc["dimension"][dimension]["category"]
    positions = category["index"]
    require(isinstance(positions, dict) and positions,
            f"Missing category indices: {dimension}")
    require(all(type(v) is int for v in positions.values()) and
            sorted(positions.values()) == list(range(len(positions))),
            f"Non-contiguous or duplicate category indices: {dimension}")
    require(set(category["label"]) == set(positions),
            f"Incomplete category labels: {dimension}")
    return sorted(positions, key=positions.get)


def validate(data, year, role, contract):
    """Check the untouched JSON snapshot and its entire published-value pattern."""
    doc = read_json(data)
    dataset, updated = partition(year)
    require(doc.get("class") == "dataset" and doc.get("version") == "2.0",
            "Response is not a JSON-stat dataset")
    require(doc.get("source") == "ESTAT" and
            doc.get("extension", {}).get("id") == dataset,
            f"Wrong source or dataset for {year} {role}")
    require(datetime.fromisoformat(doc["updated"]) ==
            datetime.fromisoformat(updated),
            f"Unexpected source vintage for {year} {role}: {doc.get('updated')}")
    require(doc.get("id") == contract["expected_dimension_ids"],
            "Unexpected dimension order")
    codes = {d: categories(doc, d) for d in doc["id"]}
    require(doc["size"] == [len(codes[d]) for d in doc["id"]] ==
            contract["expected_sizes"][role], "Unexpected dimensions")
    for dim, expected in (("time", [str(year)]), ("freq", ["A"]),
                          ("unit", ["MIO_EUR"])):
        require(codes[dim] == expected, f"Unexpected {dim}")

    expected = {
        "ind_use": contract["industries"] + contract["final_uses"],
        "ind_ava": contract["industries"] + contract["accounting_items"],
    }
    economies = contract["economies"]
    de = [item for item in economies if item["code"] == "DE"]
    expected["c_orig"] = (economies + [{"code": "DOM", "label": "Domestic country"}]
                          if role == "uses" else de)
    expected["c_dest"] = de if role == "uses" else economies
    for dim, items in expected.items():
        labels = {item["code"]: item["label"] for item in items}
        require(set(codes[dim]) == set(labels), f"Category coverage differs: {dim}")
        require(doc["dimension"][dim]["category"]["label"] == labels,
                f"Category labels differ: {dim}")

    industries = {item["code"] for item in contract["industries"]}
    supplying_industry = [c in industries for c in codes["ind_ava"]]
    using_industry = [c in industries for c in codes["ind_use"]]
    values = doc.get("value")
    require(isinstance(values, dict), "Expected sparse JSON-stat values")
    country_axis = "c_orig" if role == "uses" else "c_dest"
    countries = codes[country_axis]
    n_country, n_supplier = len(countries), len(codes["ind_ava"])
    expected_count = len(codes["ind_use"]) * len(industries) * len(economies)
    if role == "uses":
        expected_count += len(codes["ind_use"]) * len(contract["accounting_items"])
    require(len(values) == expected_count,
            f"Incomplete observation count: {len(values)} != {expected_count}")
    count = math.prod(doc["size"])
    negatives = 0
    negative_intermediates = 0
    for key, value in values.items():
        require(isinstance(key, str) and key.isascii() and key.isdigit() and
                str(int(key)) == key and int(key) < count,
                f"Invalid observation index: {key}")
        require(type(value) in (int, float) and math.isfinite(value),
                f"Invalid observation value: {key}")
        index = int(key)
        country = index % n_country
        supplier = (index // n_country) % n_supplier
        user = index // (n_country * n_supplier)
        is_dom = countries[country] == "DOM"
        permitted = (supplying_industry[supplier] != is_dom if role == "uses"
                     else supplying_industry[supplier])
        require(permitted, f"Unexpected value in structurally absent cell: {key}")
        negatives += value < 0
        negative_intermediates += (value < 0 and using_industry[user] and
                                   supplying_industry[supplier] and not is_dom)
    statuses = doc.get("status", {})
    require(isinstance(statuses, dict) and
            all(key in values and isinstance(flag, str) for key, flag in statuses.items()),
            "Unexpected status flags")
    return {
        "dataset": dataset,
        "dataset_label": doc.get("label"),
        "source_updated": doc["updated"],
        "dimension_ids": doc["id"],
        "dimension_sizes": doc["size"],
        "observations": len(values),
        "structurally_absent_cells": count - len(values),
        "classification_matches_baseline": True,
        "complete_expected_observation_pattern": True,
        "negative_values_preserved": negatives,
        "negative_intermediate_values": negative_intermediates,
        "status_counts": dict(sorted(Counter(statuses.values()).items())),
    }


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".manifest-",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download(year, role, contract):
    url = source_url(year, role)
    target = RAW / f"de{year}_{role}.json"
    require(not target.exists(), f"Refusing to overwrite an existing raw file: {target}")
    request = Request(url, headers={"User-Agent": "Thesis-FIGARO-history-acquisition/1.0"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                data = response.read()
                final_url = response.url
                headers = {key: response.headers[key] for key in
                           ("Date", "Content-Type", "Content-Length", "ETag", "Last-Modified")
                           if response.headers.get(key) is not None}
            break
        except (HTTPError, URLError, TimeoutError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
    retrieved = utc_now()
    summary = validate(data, year, role, contract)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-",
                                         suffix=".part", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        # Windows rename refuses an existing destination; raw snapshots are immutable.
        require(not target.exists(), f"Destination appeared during download: {target}")
        os.rename(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"year": year, "role": role, "path": relative(target), "url": url,
            "response_url": final_url, "storage": "new_download",
            "retrieved_at_utc": retrieved, "http_headers": headers,
            "bytes": len(data), "sha256": digest(data), **summary}


def verify_record(record, contract):
    path = (ROOT / record["path"]).resolve()
    require(path.is_relative_to(ROOT.resolve()), "Recorded file is outside the project")
    data = path.read_bytes()
    require(len(data) == record["bytes"] and digest(data) == record["sha256"],
            f"Integrity check failed: {record['path']}")
    summary = validate(data, record["year"], record["role"], contract)
    require(all(record.get(key) == value for key, value in summary.items()),
            f"Recorded schema check differs: {record['path']}")


def load_contract():
    baseline = read_json(BASE_MANIFEST.read_bytes())
    raw_contract = CONTRACT_PATH.read_bytes()
    require(digest(raw_contract) == baseline["classification"]["sha256"],
            "Original classification integrity check failed")
    return baseline, read_json(raw_contract)


def verify_all(manifest, contract):
    records = manifest["inputs"]
    pairs = [(r["year"], r["role"]) for r in records]
    require(len(pairs) == len(set(pairs)) == 30 and
            set(pairs) == {(year, role) for year in YEARS for role in ("uses", "sales")},
            "Expected exactly 30 annual extracts")
    for record in records:
        require(record["url"] == source_url(record["year"], record["role"]),
                "Recorded request does not match the extraction scope")
        verify_record(record, contract)
    for reference in manifest["local_references"]:
        data = (ROOT / reference["path"]).read_bytes()
        require(len(data) == reference["bytes"] and digest(data) == reference["sha256"],
                f"Reference integrity check failed: {reference['path']}")
    expected_new = {r["path"] for r in records if r["storage"] == "new_download"}
    actual_new = {relative(p) for p in RAW.iterdir() if p.is_file()}
    require(actual_new == expected_new, "Unexpected or missing raw extension files")
    require(len(expected_new) == 26, "Expected 26 new files and four preserved inputs")


def run(check_only=False):
    baseline, contract = load_contract()
    if MANIFEST.exists():
        manifest = read_json(MANIFEST.read_bytes())
        require(manifest.get("schema_version") == 1 and
                manifest.get("reference_years") == list(YEARS), "Unexpected extension manifest")
        if manifest.get("status") == "complete" or check_only:
            require(manifest.get("status") == "complete", "Acquisition is not complete")
            verify_all(manifest, contract)
            print("Verified all 30 extracts offline: 26 new files, four preserved inputs. No files changed.", flush=True)
            return
    else:
        require(not check_only, "No historical acquisition manifest exists")
        references = []
        for path in (BASE_MANIFEST, CONTRACT_PATH,
                     ROOT / "data" / "metadata" / "figaro" / "figaro-metadata-2026-09-09.html"):
            data = path.read_bytes()
            references.append({"path": relative(path), "bytes": len(data), "sha256": digest(data)})
        manifest = {
            "schema_version": 1, "status": "in_progress", "started_at_utc": utc_now(),
            "project": "German manufacturing Chinese input content: historical extension",
            "scope": "Raw-data acquisition only; no new economic analysis or thesis rewrite",
            "reference_years": list(YEARS), "edition": "FIGARO 2026 edition, July 2026",
            "edition_note": "II1-II3 were updated on 18 July and II4 on 20 July in the same edition; source timestamps are retained per file.",
            "path_base": "Project root containing the canonical thesis plan",
            "unit": "MIO_EUR", "valuation": "Current basic prices",
            "extraction": {"uses": "All inputs and accounting rows used in Germany, all origins; c_dest=DE",
                           "sales": "German supplies to all destinations and uses; c_orig=DE"},
            "official_sources": {
                "database": "https://ec.europa.eu/eurostat/web/esa-supply-use-input-tables/database",
                "metadata": "https://ec.europa.eu/eurostat/cache/metadata/en/naio_10_fcp_esms.htm"},
            "limitations": [
                "Download checks establish integrity, classification consistency and observation coverage, not accounting reconciliation or analytical validity.",
                "China source tables: OECD inter-country IO data in 2010-2019; Eurostat estimates using other-year supply-use tables in 2020-2024 (metadata section18.3).",
                "Current-price changes do not distinguish prices, quantities, sourcing or statistical construction.",
                "Original data/manifest.json and the frozen analysis/rebuild registry remain unchanged."],
            "local_references": references, "inputs": [], "errors": [],
        }
        for old in baseline["inputs"]:
            data = (ROOT / old["path"]).read_bytes()
            require(len(data) == old["bytes"] and digest(data) == old["sha256"],
                    f"Original frozen input changed: {old['path']}")
            summary = validate(data, old["year"], old["role"], contract)
            manifest["inputs"].append({
                "year": old["year"], "role": old["role"], "path": old["path"],
                "url": old["url"], "storage": "reused_frozen_baseline",
                "original_retrieved_on": old["retrieved_on"],
                "retrieval_date_basis": old["retrieval_date_basis"],
                "bytes": old["bytes"], "sha256": old["sha256"], **summary})
        atomic_json(MANIFEST, manifest)

    existing = {(r["year"], r["role"]) for r in manifest["inputs"]}
    require(len(existing) == len(manifest["inputs"]), "Duplicate records in partial manifest")
    for record in manifest["inputs"]:
        verify_record(record, contract)
    tasks = [(year, role) for year in YEARS for role in ("uses", "sales")
             if (year, role) not in existing]
    manifest["errors"] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(download, year, role, contract): (year, role)
                   for year, role in tasks}
        for future in as_completed(futures):
            year, role = futures[future]
            try:
                record = future.result()
                manifest["inputs"].append(record)
                manifest["inputs"].sort(key=lambda r: (r["year"], r["role"]))
                print(f"Saved {year} {role}: {record['bytes']:,} bytes; full expected observation pattern present.", flush=True)
            except Exception as exc:
                manifest["errors"].append({"year": year, "role": role, "error": str(exc)})
                print(f"FAILED {year} {role}: {exc}", flush=True)
            atomic_json(MANIFEST, manifest)
    require(not manifest["errors"], "Some downloads failed; successful raw inputs and their receipts were retained")
    verify_all(manifest, contract)
    manifest["status"] = "complete"
    manifest["completed_at_utc"] = utc_now()
    manifest["summary"] = {
        "years": len(YEARS), "annual_extracts": len(manifest["inputs"]),
        "new_downloads": 26, "reused_frozen_inputs": 4,
        "total_input_bytes": sum(r["bytes"] for r in manifest["inputs"]),
        "new_download_bytes": sum(r["bytes"] for r in manifest["inputs"]
                                  if r["storage"] == "new_download"),
        "all_hashes_schema_and_observation_patterns_verified": True,
        "annual_accounting_reconciliation_performed": False,
        "historical_economic_analysis_performed": False,
    }
    atomic_json(MANIFEST, manifest)
    print(json.dumps(manifest["summary"], indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify preserved downloads offline; do not write files")
    args = parser.parse_args()
    run(args.check)
