"""Memo 20: earlier FIGARO editions, from the Wayback Machine's copies of Eurostat's files, each fetched once.

The author approved these 16 files on 5 November 2026 (memo 20): all 13 years of the 2024 edition (E24) and three years
of the 2022 edition (E22). Eurostat's own links now return 404. No login, no contact and no terms step. Each file sits
in its own folder under data/raw/, compressed with gzip (mtime 0) if it came as plain CSV, and is recorded in
data/manifest.json with the URL, the capture time, the access time, the HTTP headers and the size and SHA-256 of both
the original response and the stored file. A saved file is never overwritten; a later run fetches only what the
manifest lacks, and --check verifies everything offline. Downloads are parsed as data and never run.

    python download_editions.py --only e24/2022     one file (the gate)
    python download_editions.py                     everything still missing
    python download_editions.py --check
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.request import Request, urlopen
import zipfile

EXTENSION = Path(__file__).resolve().parent
ROOT = EXTENSION.parents[1]
RAW = EXTENSION / "data" / "raw"
MANIFEST = EXTENSION / "data" / "manifest.json"
USER_AGENT = "Thesis-memo20/1.0"
WAYBACK = "https://web.archive.org/web/{stamp}id_/{url}"
E24 = "https://ec.europa.eu/eurostat/documents/51957/19580762/matrix_eu-ic-io_ind-by-ind_24ed_{year}.csv"
E24_CAPTURES = {2010: "20250520120934", 2011: "20250521001821", 2012: "20250520154152", 2013: "20250521054129",
                2014: "20250520235629", 2015: "20250520125853", 2016: "20250520153017", 2017: "20250520215044",
                2018: "20250520174445", 2019: "20250520120446", 2020: "20250520123302", 2021: "20250520142049",
                2022: "20250520125459"}
E22_FOLDER = "https://ec.europa.eu/eurostat/documents/51957/12789258/"
E22 = {2018: ("20220707102409", "flatfile_eu-ic-io_ind-by-ind_2018.csv.zip/55d85273-1767-89b4-ca8b-f37e0fed75b5?t=1655221287851", 55126111),
       2019: ("20220705151311", "flatfile_eu-ic-io_ind-by-ind_2019.csv.zip/6140e6b3-0b11-4455-f8b8-fb4ad92907ae", 55258572),
       2020: ("20220705030148", "flatfile_eu-ic-io_ind-by-ind_2020.csv.zip/390da49c-d769-afa3-92a1-d9af9b64d2c4", 54866905)}
ATTEMPTS = 4


def sources():
    """(key, stored path relative to data/raw, the original URL, the capture time, the expected size or None)."""
    out = []
    for year, stamp in E24_CAPTURES.items():
        out.append((f"e24/{year}", f"e24-{year}/matrix_eu-ic-io_ind-by-ind_24ed_{year}.csv.gz", E24.format(year=year), stamp,
                    42520150 if year == 2022 else None))
    for year, (stamp, tail, size) in E22.items():
        name = tail.split("/")[0]
        out.append((f"e22/{year}", f"e22-{year}/{name}", E22_FOLDER + tail, stamp, size))
    return out


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked(payload, url, expected):
    """Refuse a page or a wrong size; a CSV must start with its header, a zip must open and hold one CSV."""
    if expected is not None and len(payload) != expected:
        raise SystemExit(f"{url}: {len(payload):,} bytes, expected {expected:,}; nothing stored.")
    if payload.lstrip()[:1] == b"<":
        raise SystemExit(f"{url}: the response is a page, not data; nothing stored.")
    if ".zip" in url:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if len(names) != 1 or not names[0].endswith(".csv") or archive.testzip() is not None:
                raise SystemExit(f"{url}: unexpected archive {names}; nothing stored.")
    else:
        first = payload[:64].split(b"\n")[0]
        if b"rowLabels" not in first:
            raise SystemExit(f"{url}: unexpected first line {first!r}; nothing stored.")


def write_once(path, data):
    if path.exists():
        raise SystemExit(f"{path.relative_to(ROOT)} already exists and is never overwritten.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".part") as handle:
        handle.write(data)
        temporary = Path(handle.name)
    os.rename(temporary, path)


def save_manifest(manifest):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=MANIFEST.parent, delete=False, suffix=".tmp", encoding="utf-8",
                                     newline="\n") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, MANIFEST)


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"purpose": "Memo 20: earlier FIGARO editions, from the Wayback Machine's copies of Eurostat's files", "files": []}


def fetch_one(url, stamp):
    address = WAYBACK.format(stamp=stamp, url=url)
    last = None
    for attempt in range(ATTEMPTS):
        try:
            with urlopen(Request(address, headers={"User-Agent": USER_AGENT}), timeout=600) as response:
                payload = response.read()
                headers = {k: response.headers[k] for k in ("Date", "Content-Type", "Content-Length", "X-Archive-Src")
                           if response.headers.get(k)}
            return address, payload, headers
        except OSError as error:   # the archive is slow at times; a retry changes nothing but the wait
            last = error
            time.sleep(20 * (attempt + 1))
    raise SystemExit(f"{address}: {last}")


def fetch(only=None):
    manifest = load_manifest()
    known = {entry["key"] for entry in manifest["files"]}
    for key, stored, url, stamp, expected in sources():
        if key in known or (only and key != only):
            continue
        address, payload, headers = fetch_one(url, stamp)
        retrieved = datetime.now(timezone.utc).isoformat()
        checked(payload, url, expected)
        packed = gzip.compress(payload, compresslevel=9, mtime=0) if stored.endswith(".gz") else payload
        path = RAW / stored
        write_once(path, packed)
        manifest["files"].append({"key": key, "original_url": url, "wayback_url": address, "capture": stamp,
                                  "path": path.relative_to(ROOT).as_posix(), "retrieved_at_utc": retrieved,
                                  "http_headers": headers,
                                  "storage": "gzip (level 9, mtime 0) of the exact response" if stored.endswith(".gz") else "the exact response",
                                  "bytes": len(payload), "sha256": digest(payload), "stored_bytes": len(packed),
                                  "stored_sha256": digest(packed)})
        save_manifest(manifest)
        print(f"{key}: {len(payload):,} bytes")


def verify(required=True):
    """Every stored file against its record; with `required`, every source must be recorded."""
    records = {entry["key"]: entry for entry in load_manifest()["files"]}
    if required:
        missing = [key for key, *_ in sources() if key not in records]
        if missing:
            raise ValueError(f"Not recorded in the manifest: {missing}")
    for entry in records.values():
        packed = (ROOT / entry["path"]).read_bytes()
        payload = gzip.decompress(packed) if entry["path"].endswith(".gz") else packed
        if (len(packed) != entry["stored_bytes"] or digest(packed) != entry["stored_sha256"]
                or len(payload) != entry["bytes"] or digest(payload) != entry["sha256"]):
            raise ValueError(f"Integrity check failed: {entry['path']}")
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify the saved files offline")
    parser.add_argument("--only", help="fetch one key, such as e24/2022")
    args = parser.parse_args()
    if not args.check:
        fetch(args.only)
    records = verify(required=not args.only)
    print(f"{len(records)} files verified against {MANIFEST.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
