"""Step 5: price data for the diagnostic of memo 5 (pre-registration of 6 October 2026).

Fetches, once, with provenance (URL, retrieval time, size, SHA-256 of the raw response):
- Eurostat Comext DS-045409: German imports by product from China and from all extra-EU origins,
  2010-2024, one request per partner, year and indicator (euros; quantity in 100 kg);
- Eurostat nama_10_a64: the implicit output deflator of German manufacturing (P1, NACE C,
  PD15_NAC; Germany's national currency is the euro);
- ECB: the annual euro-renminbi reference rate (EXR.A.CNY.EUR.SP00.A).
Raw responses are stored gzip-compressed (mtime 0) in data/raw/ (outside Git) and recorded in
data/manifest.json. A rerun skips what is recorded; --check verifies everything offline.

    python download_prices.py
    python download_prices.py --check
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EXTENSION = Path(__file__).resolve().parent
ROOT = EXTENSION.parents[1]
RAW = EXTENSION / "data" / "raw"
MANIFEST = EXTENSION / "data" / "manifest.json"
YEARS = tuple(range(2010, 2025))
PARTNERS = ("CN", "EXT_EU27_2020")
INDICATORS = ("VALUE_IN_EUROS", "QUANTITY_IN_100KG")
COMEXT = "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409"
DEFLATOR = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nama_10_a64"
            "?lang=en&geo=DE&nace_r2=C&na_item=P1&unit=PD15_NAC&sinceTimePeriod=2010")
ECB = "https://data-api.ecb.europa.eu/service/data/EXR/A.CNY.EUR.SP00.A?format=jsondata&startPeriod=2010&endPeriod=2024"
USER_AGENT = "Thesis-prices-acquisition/1.0"


def comext_url(partner, year, indicator):
    return (f"{COMEXT}?format=JSON&lang=EN&freq=A&reporter=DE&partner={partner}&flow=1&time={year}"
            f"&indicators={indicator}")


def sources():
    """Every source as (key, url, file name)."""
    items = [(f"comext/{p}/{y}/{i}", comext_url(p, y, i), f"comext_{p}_{y}_{i}.json.gz")
             for p in PARTNERS for y in YEARS for i in INDICATORS]
    items.append(("eurostat/deflator", DEFLATOR, "nama_10_a64_DE_C_P1_PD15_NAC.json.gz"))
    items.append(("ecb/eur_cny", ECB, "ecb_EXR_A_CNY_EUR.json.gz"))
    return items


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            with urlopen(request, timeout=300) as response:
                return response.read(), {k: response.headers[k] for k in ("Date", "Content-Type")
                                         if response.headers.get(k)}
        except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
            retryable = not isinstance(exc, HTTPError) or exc.code in (429, 500, 502, 503, 504)
            if not retryable or attempt == 4:
                raise
            time.sleep(5 * 3 ** attempt)
    raise AssertionError("unreachable")


def validate(key, data):
    """Structural checks only: the right dataset slice, with observations."""
    doc = json.loads(data)
    if key.startswith("comext/"):
        _, partner, year, indicator = key.split("/")
        codes = {d: list(doc["dimension"][d]["category"]["index"]) for d in doc["id"]}
        expected = {"freq": ["A"], "reporter": ["DE"], "partner": [partner], "flow": ["1"],
                    "indicators": [indicator], "time": [year]}
        for dim, value in expected.items():
            if codes[dim] != value:
                raise ValueError(f"{key}: unexpected {dim} {codes[dim]}")
        if not doc.get("value"):
            raise ValueError(f"{key}: no observations")
        return {"products": len(codes["product"]), "observations": len(doc["value"])}
    if key == "eurostat/deflator":
        times = list(doc["dimension"]["time"]["category"]["index"])
        if len(doc.get("value", {})) < len(YEARS) or not {str(y) for y in YEARS} <= set(times):
            raise ValueError("Deflator series incomplete")
        return {"observations": len(doc["value"]), "updated": doc.get("updated")}
    if key == "ecb/eur_cny":
        observations = doc["dataSets"][0]["series"]["0:0:0:0:0"]["observations"]
        if len(observations) != len(YEARS):
            raise ValueError("Exchange-rate series incomplete")
        return {"observations": len(observations)}
    raise ValueError(f"Unknown source {key}")


def write_once(path, payload):
    if path.exists():
        raise ValueError(f"Refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".part") as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.rename(temporary, path)


def save_manifest(manifest):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=MANIFEST.parent, delete=False, suffix=".tmp",
                                     encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, MANIFEST)


def verify(manifest):
    for record in manifest["files"]:
        packed = (ROOT / record["path"]).read_bytes()
        data = gzip.decompress(packed)
        if digest(packed) != record["gzip_sha256"] or digest(data) != record["sha256"] or len(data) != record["bytes"]:
            raise ValueError(f"Integrity check failed: {record['path']}")
        validate(record["key"], data)
    return len(manifest["files"])


def run(check_only=False):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {
        "purpose": "Step 5 (memo 5): Comext unit values, the manufacturing output deflator, the euro-renminbi rate",
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "files": []}
    if check_only:
        print(f"Verified {verify(manifest)} files offline.")
        return
    done = {r["key"] for r in manifest["files"]}
    todo = [s for s in sources() if s[0] not in done]
    print(f"{len(done)} recorded, {len(todo)} to fetch.", flush=True)
    for number, (key, url, name) in enumerate(todo, 1):
        data, headers = fetch(url)
        summary = validate(key, data)
        packed = gzip.compress(data, compresslevel=9, mtime=0)
        path = RAW / name
        write_once(path, packed)
        manifest["files"].append({"key": key, "url": url, "path": path.relative_to(ROOT).as_posix(),
                                  "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                                  "http_headers": headers, "bytes": len(data), "sha256": digest(data),
                                  "gzip_bytes": len(packed), "gzip_sha256": digest(packed), **summary})
        save_manifest(manifest)
        print(f"[{number}/{len(todo)}] {key}", flush=True)
        time.sleep(0.3)
    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    save_manifest(manifest)
    print(f"Verified {verify(manifest)} files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    run(parser.parse_args().check)
