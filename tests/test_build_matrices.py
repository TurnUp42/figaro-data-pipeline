"""Integrity, restoration and publication checks isolated from archived sources."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "code"))

import build_matrices as runner
from figaro import PipelineError


class Download(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url


class BuildMatricesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = self.enterContext(tempfile.TemporaryDirectory(prefix="figaro-runner-test-"))
        self.root = Path(self.temporary) / "project"
        self.root.mkdir()
        self.enterContext(patch.object(runner, "ROOT", self.root))
        self.data = b'{"frozen": "approved bytes"}\n'
        self.record = {
            "path": "data/raw/figaro/snapshot.json",
            "url": "https://ec.europa.eu/eurostat/frozen-example.json",
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "bytes": len(self.data),
        }
        self.source = self.root / self.record["path"]

    def put_source(self, data):
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_bytes(data)

    def mock_download(self, data=None):
        response = Download(self.data if data is None else data, self.record["url"])
        return patch.object(runner.urllib.request, "urlopen", return_value=response)

    def test_present_exact_source_verifies_without_network_or_receipt(self):
        self.put_source(self.data)
        with patch.object(runner.urllib.request, "urlopen") as download:
            self.assertEqual(runner.verify_source(self.record, fetch_missing=True), self.source)
        download.assert_not_called()
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertFalse((self.root / "data/retrievals.json").exists())

    def test_present_corruption_rejects_without_overwriting_or_downloading(self):
        corrupted = b"x" * len(self.data)  # Equal length makes the hash check consequential.
        self.put_source(corrupted)
        with patch.object(runner.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(PipelineError, "checksum/size mismatch"):
                runner.verify_source(self.record, fetch_missing=True)
        download.assert_not_called()
        self.assertEqual(self.source.read_bytes(), corrupted)
        self.assertFalse((self.root / "data/retrievals.json").exists())

    def test_missing_offline_source_rejects_without_creating_files(self):
        with patch.object(runner.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(PipelineError, "Missing frozen source"):
                runner.verify_source(self.record)
        download.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_changed_download_hash_rejects_without_saving_source_or_receipt(self):
        changed = b"x" * len(self.data)
        with self.mock_download(changed) as download:
            with self.assertRaisesRegex(PipelineError, "differs from locked vintage"):
                runner.verify_source(self.record, fetch_missing=True)
        download.assert_called_once()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_changed_download_size_rejects_even_with_matching_hash(self):
        record = dict(self.record, bytes=len(self.data) + 1)
        with self.mock_download():
            with self.assertRaisesRegex(PipelineError, "differs from locked vintage"):
                runner.verify_source(record, fetch_missing=True)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_exact_download_restores_bytes_and_appends_dated_receipt(self):
        receipt_path = self.root / "data/retrievals.json"
        receipt_path.parent.mkdir()
        old_receipt = {"path": "data/raw/earlier.json", "retrieved_at_utc": "2026-09-08T00:00:00+00:00"}
        receipt_path.write_text(json.dumps([old_receipt]), encoding="utf-8")
        before = datetime.now(timezone.utc)
        with self.mock_download() as download:
            restored = runner.verify_source(self.record, fetch_missing=True)
        after = datetime.now(timezone.utc)
        self.assertEqual(restored, self.source)
        self.assertEqual(restored.read_bytes(), self.data)
        download.assert_called_once()
        request = download.call_args.args[0]
        self.assertEqual(request.full_url, self.record["url"])
        receipts = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipts[0], old_receipt)
        self.assertEqual(len(receipts), 2)
        receipt = receipts[1]
        self.assertEqual(receipt["path"], self.record["path"])
        self.assertEqual(receipt["sha256"], self.record["sha256"])
        self.assertEqual(receipt["bytes"], len(self.data))
        self.assertEqual(receipt["requested_url"], self.record["url"])
        self.assertEqual(receipt["response_url"], self.record["url"])
        timestamp = datetime.fromisoformat(receipt["retrieved_at_utc"])
        self.assertEqual(timestamp.utcoffset(), timezone.utc.utcoffset(timestamp))
        self.assertLessEqual(before, timestamp)
        self.assertLessEqual(timestamp, after)

    def test_invalid_receipt_log_rejects_before_publishing_restoration(self):
        receipt_path = self.root / "data/retrievals.json"
        receipt_path.parent.mkdir()
        receipt_path.write_bytes(b"not valid JSON\n")
        with self.mock_download() as download:
            with self.assertRaises(json.JSONDecodeError):
                runner.verify_source(self.record, fetch_missing=True)
        download.assert_not_called()
        self.assertEqual(receipt_path.read_bytes(), b"not valid JSON\n")
        self.assertFalse(self.source.exists(), "A source restored without a receipt is skipped on the next run")

    def test_nonlist_receipt_log_rejects_before_download(self):
        receipt_path = self.root / "data/retrievals.json"
        receipt_path.parent.mkdir()
        receipt_path.write_bytes(b"{}\n")
        with self.mock_download() as download:
            with self.assertRaises(PipelineError):
                runner.verify_source(self.record, fetch_missing=True)
        download.assert_not_called()
        self.assertEqual(receipt_path.read_bytes(), b"{}\n")
        self.assertFalse(self.source.exists())

    def test_receipt_commit_failure_rolls_back_only_new_source(self):
        receipt_path = self.root / "data/retrievals.json"
        receipt_path.parent.mkdir()
        previous = b'[{"path": "data/raw/earlier.json"}]\n'
        receipt_path.write_bytes(previous)
        unrelated = receipt_path.parent / "existing-source.json"
        unrelated.write_bytes(b"unrelated source remains unchanged")
        original_replace = Path.replace

        def fail_receipt_commit(path, target):
            if Path(target) == receipt_path:
                raise OSError("simulated receipt commit failure")
            return original_replace(path, target)

        with self.mock_download():
            with patch.object(Path, "replace", autospec=True, side_effect=fail_receipt_commit):
                with self.assertRaisesRegex(OSError, "simulated receipt commit failure"):
                    runner.verify_source(self.record, fetch_missing=True)
        self.assertFalse(self.source.exists())
        self.assertEqual(receipt_path.read_bytes(), previous)
        self.assertEqual(unrelated.read_bytes(), b"unrelated source remains unchanged")

    def test_path_traversal_and_external_absolute_paths_reject(self):
        outside = self.root.parent / "outside.json"
        outside.write_bytes(b"outside sentinel")
        for relative in ["../outside.json", str(outside), ".", "data/../.."]:
            with self.subTest(path=relative):
                with patch.object(runner.urllib.request, "urlopen") as download:
                    with self.assertRaisesRegex(PipelineError, "Path outside project"):
                        runner.verify_source(dict(self.record, path=relative), fetch_missing=True)
                download.assert_not_called()
        self.assertEqual(outside.read_bytes(), b"outside sentinel")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_download_from_unapproved_host_rejects_before_network(self):
        with patch.object(runner.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(PipelineError, "Unexpected download host"):
                runner.verify_source(dict(self.record, url="https://example.org/source.json"), True)
        download.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_npz_is_byte_deterministic_and_round_trips_without_pickle(self):
        arrays = {
            "x": np.array([3.5, 0.0]),
            "industries": np.array(["C26", "U"]),
            "D": np.array([[0.5, 0.0], [0.0, 0.0]]),
            "active": np.array([True, False]),
            "year": np.asarray(2022),
        }
        first, second = self.root / "first.npz", self.root / "second.npz"
        runner.write_npz(first, arrays)
        runner.write_npz(second, dict(reversed(list(arrays.items()))))
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with np.load(first, allow_pickle=False) as restored:
            self.assertEqual(set(restored.files), set(arrays))
            for key, expected in arrays.items():
                np.testing.assert_array_equal(restored[key], expected)
                self.assertEqual(restored[key].dtype, expected.dtype)
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(archive.namelist(), [key + ".npy" for key in sorted(arrays)])
            self.assertTrue(all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in archive.infolist()))

    def mock_validated_run(self):
        """Bypass source parsing to exercise only runner publication boundaries."""
        stack = ExitStack()
        updated = "2026-07-20T11:00:00+0200"
        manifest = {
            "schema_version": 1, "dataset": "TEST", "source_updated": updated,
            "classification": {"path": "data/metadata/figaro/classification.json"},
            "metadata": [{"path": "data/metadata/source.html"}],
            "inputs": [{"year": year, "role": role, "path": f"data/raw/{year}_{role}.json",
                        "source_updated": updated}
                       for year in [2022, 2023] for role in ["uses", "sales"]],
        }
        contract = {"dataset": "TEST", "source_updated": updated, "reference_years": [2022, 2023]}

        def read(path):
            if Path(path).name == "manifest.json":
                return manifest
            if Path(path).name == "classification.json":
                return contract
            return {}

        arrays = {key: np.array(["aligned"]) for key in
                  ["industries", "industry_labels", "economies", "final_use_codes", "accounting_codes", "active"]}
        stack.enter_context(patch.object(runner, "load_json", side_effect=read))
        stack.enter_context(patch.object(runner, "verify_source", side_effect=lambda r, *args: self.root / r["path"]))
        stack.enter_context(patch.object(runner, "parse_document", return_value=object()))
        stack.enter_context(patch.object(runner, "build_year", return_value=(arrays, {})))
        return stack

    def test_protected_output_directories_reject_before_any_output_write(self):
        for folder in ["", "data", "data/raw", "code", "evidence", "thesis", "tests", ".venv"]:
            with self.subTest(folder=folder), self.mock_validated_run():
                with patch.object(runner, "write_npz") as write:
                    with self.assertRaisesRegex(PipelineError, "separate from source data and code"):
                        runner.run(self.root / folder)
                write.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_staging_failure_keeps_existing_results_and_cleans_temporary_stage(self):
        output = self.root / "outputs/data-pipeline"
        output.mkdir(parents=True)
        existing = output / "validation.json"
        existing.write_bytes(b"prior validated result\n")
        with self.mock_validated_run():
            with patch.object(runner, "write_npz", side_effect=OSError("simulated write failure")):
                with self.assertRaisesRegex(OSError, "simulated write failure"):
                    runner.run(output)
        self.assertEqual(existing.read_bytes(), b"prior validated result\n")
        self.assertEqual(list(output.iterdir()), [existing])
        self.assertEqual(list(output.parent.iterdir()), [output])


if __name__ == "__main__":
    unittest.main()
