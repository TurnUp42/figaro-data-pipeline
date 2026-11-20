"""Step 4, task 4.2: the full FIGARO inter-country table, 2010-2024, from the same July 2026 edition.

The history extension holds only Germany's slices (inputs used in Germany from all origins, and
German sales to all destinations). Chinese inputs that reach Germany through third countries also
need every other economy's input structure. This script fetches, for every year and every one of
FIGARO's 50 economies, the slice of inputs used in that economy from all origins (`c_dest=<code>`),
through the same Eurostat API, datasets and vintages as the history extension. Together the 50
slices of a year are the whole industry-by-industry table: all intermediate and final uses, and the
value-added rows.

Each response is checked for the edition, dimensions, classification (against the hash-locked
contract of the 2022-2023 study) and the complete observation pattern before it is stored. Raw
responses are kept byte for byte, gzip-compressed (mtime 0), under data/raw/ (outside Git), and
recorded in data/manifest.json with URL, retrieval time, sizes and SHA-256 of the raw bytes. A rerun
skips files already recorded; --check verifies everything offline.

    python download_figaro_ic.py              fetch what is missing, then verify all
    python download_figaro_ic.py --check      offline verification only
    python download_figaro_ic.py --years 2022 --economies CZ PL     a partial run
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import gzip
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EXTENSION = Path(__file__).resolve().parent
ROOT = EXTENSION.parents[1]
HISTORY = ROOT / "extensions" / "history-2010-2024"
sys.path.insert(0, str(HISTORY))
# Read-only reuse of the history extension's acquisition helpers and classification contract.
from download_data import (API, CONTRACT_PATH, YEARS, atomic_json, categories, digest,  # noqa: E402
                           load_contract, partition, read_json, require, utc_now)

RAW = EXTENSION / "data" / "raw" / "figaro-ic" / "2026-07-20"
MANIFEST = EXTENSION / "data" / "manifest.json"
HISTORY_RAW = (HISTORY / "data" / "raw" / "figaro" / "2026-07-20", ROOT / "data" / "raw" / "figaro" / "2026-07-20")
USER_AGENT = "Thesis-FIGARO-look-through-acquisition/1.0"
PAUSE_SECONDS = 0.3


def relative(path):
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def source_url(year, economy):
    dataset, _ = partition(year)
    return f"{API}{dataset.lower()}?lang=en&time={year}&c_dest={economy}"


def target_path(year, economy):
    return RAW / str(year) / f"{economy}_uses.json.gz"


def validate_slice(data, year, economy, contract):
    """Check one untouched JSON-stat response: edition, dimensions, labels and observation pattern.

    The same checks as the history extension's 'uses' extracts, with the destination economy as a
    parameter instead of Germany.
    """
    doc = read_json(data)
    dataset, updated = partition(year)
    require(doc.get("class") == "dataset" and doc.get("version") == "2.0",
            "Response is not a JSON-stat dataset")
    require(doc.get("source") == "ESTAT" and doc.get("extension", {}).get("id") == dataset,
            f"Wrong source or dataset for {year} {economy}")
    require(datetime.fromisoformat(doc["updated"]) == datetime.fromisoformat(updated),
            f"Unexpected source vintage for {year} {economy}: {doc.get('updated')}")
    require(doc.get("id") == contract["expected_dimension_ids"], "Unexpected dimension order")
    codes = {d: categories(doc, d) for d in doc["id"]}
    require(doc["size"] == [len(codes[d]) for d in doc["id"]] == contract["expected_sizes"]["uses"],
            "Unexpected dimensions")
    for dim, expected in (("time", [str(year)]), ("freq", ["A"]), ("unit", ["MIO_EUR"])):
        require(codes[dim] == expected, f"Unexpected {dim}")

    economies = contract["economies"]
    destination = [item for item in economies if item["code"] == economy]
    require(len(destination) == 1, f"Unknown economy: {economy}")
    expected = {
        "ind_use": contract["industries"] + contract["final_uses"],
        "ind_ava": contract["industries"] + contract["accounting_items"],
        "c_orig": economies + [{"code": contract["domestic_accounting_code"],
                                "label": contract["domestic_accounting_label"]}],
        "c_dest": destination,
    }
    for dim, items in expected.items():
        labels = {item["code"]: item["label"] for item in items}
        require(set(codes[dim]) == set(labels), f"Category coverage differs: {dim}")
        require(doc["dimension"][dim]["category"]["label"] == labels, f"Category labels differ: {dim}")

    industries = {item["code"] for item in contract["industries"]}
    supplying_industry = [c in industries for c in codes["ind_ava"]]
    using_industry = [c in industries for c in codes["ind_use"]]
    values = doc.get("value")
    require(isinstance(values, dict), "Expected sparse JSON-stat values")
    countries = codes["c_orig"]
    n_country, n_supplier = len(countries), len(codes["ind_ava"])
    expected_count = (len(codes["ind_use"]) * len(industries) * len(economies)
                      + len(codes["ind_use"]) * len(contract["accounting_items"]))
    require(len(values) == expected_count,
            f"Incomplete observation count: {len(values)} != {expected_count}")
    count = math.prod(doc["size"])
    negatives = negative_intermediates = 0
    for key, value in values.items():
        require(isinstance(key, str) and key.isascii() and key.isdigit() and str(int(key)) == key
                and int(key) < count, f"Invalid observation index: {key}")
        require(type(value) in (int, float) and math.isfinite(value), f"Invalid observation value: {key}")
        index = int(key)
        country = index % n_country
        supplier = (index // n_country) % n_supplier
        user = index // (n_country * n_supplier)
        is_dom = countries[country] == contract["domestic_accounting_code"]
        require(supplying_industry[supplier] != is_dom,
                f"Unexpected value in structurally absent cell: {key}")
        negatives += value < 0
        negative_intermediates += (value < 0 and using_industry[user] and supplying_industry[supplier]
                                   and not is_dom)
    statuses = doc.get("status", {})
    require(isinstance(statuses, dict) and all(key in values and isinstance(flag, str)
                                               for key, flag in statuses.items()),
            "Unexpected status flags")
    return {
        "dataset": dataset,
        "source_updated": doc["updated"],
        "dimension_sizes": doc["size"],
        "observations": len(values),
        "negative_values_preserved": negatives,
        "negative_intermediate_values": negative_intermediates,
        "status_counts": dict(sorted(Counter(statuses.values()).items())),
    }


def history_extract(year):
    for folder in HISTORY_RAW:
        path = folder / f"de{year}_uses.json"
        if path.exists():
            return path
    raise FileNotFoundError(f"No history extract for Germany {year}")


def fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urlopen(request, timeout=120) as response:
                data = response.read()
                headers = {key: response.headers[key] for key in
                           ("Date", "Content-Type", "Content-Length", "ETag", "Last-Modified")
                           if response.headers.get(key) is not None}
                return data, response.url, headers
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == 4:
                raise
            time.sleep(5 * 3 ** attempt)
    raise AssertionError("unreachable")


def write_once(target, payload):
    require(not target.exists(), f"Refusing to overwrite an existing raw file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".download-", suffix=".part",
                                         delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        require(not target.exists(), f"Destination appeared during download: {target}")
        os.rename(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download(year, economy, contract):
    url = source_url(year, economy)
    data, final_url, headers = fetch(url)
    retrieved = utc_now()
    summary = validate_slice(data, year, economy, contract)
    packed = gzip.compress(data, compresslevel=9, mtime=0)
    target = target_path(year, economy)
    write_once(target, packed)
    record = {"year": year, "economy": economy, "path": relative(target), "url": url,
              "response_url": final_url, "retrieved_at_utc": retrieved, "http_headers": headers,
              "bytes": len(data), "sha256": digest(data),
              "gzip_bytes": len(packed), "gzip_sha256": digest(packed), **summary}
    if economy == "DE":
        reference = history_extract(year)
        old = reference.read_bytes()
        record["history_extract"] = relative(reference)
        record["identical_to_history_extract"] = old == data
        record["values_equal_to_history_extract"] = read_json(old)["value"] == read_json(data)["value"]
    return record


def verify_record(record, contract):
    path = (ROOT / record["path"]).resolve()
    require(path.is_relative_to(ROOT.resolve()), "Recorded file is outside the project")
    packed = path.read_bytes()
    require(len(packed) == record["gzip_bytes"] and digest(packed) == record["gzip_sha256"],
            f"Integrity check failed (compressed): {record['path']}")
    data = gzip.decompress(packed)
    require(len(data) == record["bytes"] and digest(data) == record["sha256"],
            f"Integrity check failed (raw): {record['path']}")
    require(record["url"] == source_url(record["year"], record["economy"]), "Recorded request differs")
    summary = validate_slice(data, record["year"], record["economy"], contract)
    require(all(record.get(key) == value for key, value in summary.items()),
            f"Recorded schema check differs: {record['path']}")


def new_manifest(baseline, contract):
    return {
        "schema_version": 1,
        "status": "in_progress",
        "purpose": ("Step 4 (third-country routes): every FIGARO economy's inputs from all origins, "
                    "the full inter-country industry-by-industry table"),
        "edition": "FIGARO July 2026 edition, as in extensions/history-2010-2024/data/manifest.json",
        "partitions": "NAIO_10_FCP_II1 (2010-2013), II2 (2014-2017), II3 (2018-2021), II4 (2022-2024)",
        "api": API,
        "scope": "One request per year and destination economy: c_dest=<economy>, all origins",
        "storage": "Raw response bytes, gzip-compressed with mtime 0; sha256 and bytes refer to the raw response",
        "classification": {"path": relative(CONTRACT_PATH), "sha256": baseline["classification"]["sha256"]},
        "economies": [item["code"] for item in contract["economies"]],
        "reference_years": list(YEARS),
        "started_at_utc": utc_now(),
        "files": [],
        "errors": [],
    }


def verify_all(manifest, contract, years, economies):
    records = {(r["year"], r["economy"]): r for r in manifest["files"]}
    for key in [(y, e) for y in years for e in economies]:
        require(key in records, f"Missing slice: {key}")
        verify_record(records[key], contract)
    expected = {records[key]["path"] for key in records}
    actual = {relative(p) for p in RAW.rglob("*") if p.is_file()} if RAW.exists() else set()
    require(actual == expected, f"Unexpected or missing raw files: {sorted(actual ^ expected)[:5]}")
    return len(records)


def run(years, economies, check_only=False):
    baseline, contract = load_contract()
    known = [item["code"] for item in contract["economies"]]
    economies = economies or known
    require(set(economies) <= set(known), "Unknown economy requested")
    manifest = read_json(MANIFEST.read_bytes()) if MANIFEST.exists() else None
    if check_only:
        require(manifest is not None, "No manifest yet")
        count = verify_all(manifest, contract, years, economies)
        print(f"Verified {count} recorded slices offline. No files changed.", flush=True)
        return
    if manifest is None:
        manifest = new_manifest(baseline, contract)
        atomic_json(MANIFEST, manifest)
    done = {(r["year"], r["economy"]) for r in manifest["files"]}
    todo = [(y, e) for y in years for e in economies if (y, e) not in done]
    print(f"{len(done)} slices recorded, {len(todo)} to fetch.", flush=True)
    for number, (year, economy) in enumerate(todo, 1):
        try:
            record = download(year, economy, contract)
        except Exception as exc:  # recorded, then the run stops: a failed slice is not skipped silently
            manifest["errors"].append({"year": year, "economy": economy, "at_utc": utc_now(),
                                       "error": f"{type(exc).__name__}: {exc}"})
            atomic_json(MANIFEST, manifest)
            raise
        manifest["files"].append(record)
        manifest["files"].sort(key=lambda r: (r["year"], known.index(r["economy"])))
        atomic_json(MANIFEST, manifest)
        print(f"[{number}/{len(todo)}] {year} {economy}: {record['bytes']:,} bytes", flush=True)
        time.sleep(PAUSE_SECONDS)
    complete = {(r["year"], r["economy"]) for r in manifest["files"]} >= {(y, e) for y in YEARS for e in known}
    count = verify_all(manifest, contract, years, economies)
    if complete:
        manifest["status"] = "complete"
        manifest.setdefault("completed_at_utc", utc_now())
        atomic_json(MANIFEST, manifest)
    print(f"Verified {count} recorded slices; acquisition {'complete' if complete else 'partial'}.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify the recorded slices offline")
    parser.add_argument("--years", type=int, nargs="+", default=list(YEARS))
    parser.add_argument("--economies", nargs="+", default=None)
    args = parser.parse_args()
    run(args.years, args.economies, check_only=args.check)


if __name__ == "__main__":
    main()
