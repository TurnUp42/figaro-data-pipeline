"""Memo 9: UN Comtrade mirror data for the three flagged products, fetched once with provenance.

Pre-registration: memo 9 (thesis-v2/memos/9-lactam-mirror.md, 27 October 2026, approved by the author the same day),
"Mirror data". UN Comtrade's public API (preview endpoint), annual, as reported, 2019-2024, totals over modes of
transport, customs procedures and second partners:
- China (reporter 156) exports to Germany (276): the three flagged products and their HS chapters (29, 32, 38);
- China's exports to the world (0): the three products;
- Germany's imports from China (reporter 276, partner 156): the three products, for comparison only.
Each year uses the HS edition in force: 382219 exists only from HS 2022, so 2019-2021 ask for 382200.
One request per reporter, partner, year and code. Raw responses are stored gzip-compressed (mtime 0) in data/raw/ and
recorded in data/manifest.json (URL, retrieval time, size, SHA-256). A rerun skips what is recorded; --check verifies
the files offline.

    python download_comtrade.py
    python download_comtrade.py --check
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import time

EXTENSION = Path(__file__).resolve().parent
ROOT = EXTENSION.parents[1]
sys.path.insert(0, str(ROOT / "extensions" / "prices"))

from download_prices import digest, fetch, write_once  # noqa: E402

RAW = EXTENSION / "data" / "raw"
MANIFEST = EXTENSION / "data" / "manifest.json"
API = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
YEARS = tuple(range(2019, 2025))
PRODUCTS = ("293379", "382219", "321590")      # other lactams, diagnostic reagents, inks other than printing ink
HS2017 = {"382219": "382200"}                  # the code in force before HS 2022
CHAPTERS = ("29", "38", "32")
CHAPTER_OF = dict(zip(PRODUCTS, CHAPTERS))
CHINA, GERMANY, WORLD = 156, 276, 0
FLOWS = {  # name: (reporter, partner, flow, products, chapters)
    "china_to_germany": (CHINA, GERMANY, "X", True, True),
    "china_to_world": (CHINA, WORLD, "X", True, False),
    "germany_from_china": (GERMANY, CHINA, "M", True, False),
}
PAUSE_SECONDS = 5  # the public endpoint answers 429 to faster requests


def code_in_force(product, year):
    """The HS code a reporter used for `product` in `year`."""
    return HS2017.get(product, product) if year < 2022 else product


def url(reporter, partner, flow, year, code):
    return (f"{API}?reporterCode={reporter}&partnerCode={partner}&flowCode={flow}&period={year}&cmdCode={code}"
            "&partner2Code=0&motCode=0&customsCode=C00")


def sources():
    """Every source as (key, url, file name, expected fields)."""
    items = []
    for name, (reporter, partner, flow, products, chapters) in FLOWS.items():
        for year in YEARS:
            codes = [code_in_force(p, year) for p in PRODUCTS] if products else []
            codes += list(CHAPTERS) if chapters else []
            for code in codes:
                expected = {"reporterCode": reporter, "partnerCode": partner, "flowCode": flow, "refYear": year,
                            "cmdCode": code, "partner2Code": 0, "motCode": 0, "customsCode": "C00"}
                items.append((f"comtrade/{name}/{year}/{code}", url(reporter, partner, flow, year, code),
                              f"comtrade_{reporter}_{partner}_{flow}_{year}_{code}.json.gz", expected))
    return items


def validate(expected, data):
    """Structural checks only: no error, and at most one record, for exactly the requested slice."""
    doc = json.loads(data)
    if doc.get("error"):
        raise ValueError(f"API error: {doc['error']}")
    records = doc.get("data") or []
    if len(records) > 1:
        raise ValueError(f"Expected at most one record, got {len(records)}")
    for record in records:
        for field, value in expected.items():
            if record.get(field) != value:
                raise ValueError(f"Unexpected {field}: {record.get(field)!r} instead of {value!r}")
    return {"records": len(records)}


def save_manifest(manifest):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=MANIFEST.parent, delete=False, suffix=".tmp",
                                     encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, MANIFEST)


def records():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {r["key"]: r for r in manifest["files"]}, manifest


def load(record):
    """The recorded response, after checking both hashes and the structure."""
    packed = (ROOT / record["path"]).read_bytes()
    data = gzip.decompress(packed)
    if digest(packed) != record["gzip_sha256"] or digest(data) != record["sha256"] or len(data) != record["bytes"]:
        raise ValueError(f"Integrity check failed: {record['path']}")
    validate(record["expected"], data)
    return json.loads(data)


def run(check_only=False):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {
        "purpose": "Memo 9: UN Comtrade mirror data for the three flagged products and their chapters",
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "files": []}
    if check_only:
        for record in manifest["files"]:
            load(record)
        print(f"Verified {len(manifest['files'])} files offline.")
        return
    done = {r["key"] for r in manifest["files"]}
    todo = [s for s in sources() if s[0] not in done]
    for n, (key, address, name, expected) in enumerate(todo, 1):
        time.sleep(PAUSE_SECONDS)
        data, headers = fetch(address)
        summary = validate(expected, data)
        packed = gzip.compress(data, compresslevel=9, mtime=0)
        path = RAW / name
        write_once(path, packed)
        manifest["files"].append({"key": key, "url": address, "path": path.relative_to(ROOT).as_posix(),
                                  "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                                  "http_headers": headers, "bytes": len(data), "sha256": digest(data),
                                  "gzip_bytes": len(packed), "gzip_sha256": digest(packed), "expected": expected,
                                  **summary})
        save_manifest(manifest)
        print(f"[{n}/{len(todo)}] recorded {key} ({summary['records']} record)", flush=True)
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_manifest(manifest)
    for record in manifest["files"]:
        load(record)
    print(f"Verified {len(manifest['files'])} files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    run(parser.parse_args().check)
