"""Small offline tests for the shared file and cache helpers."""

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests

from metadata_io import cached_get, read_csv, source_info, write_csv


class metadata_io_tests(unittest.TestCase):
    def test_csv_quotes_and_empty_values_survive(self):
        rows = [{"dataset_id": "study1", "text": 'A, "quoted" value\nsecond line', "empty": ""}]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "records.csv"
            write_csv(path, rows)
            self.assertEqual(read_csv(path), rows)
            path.write_text("\ufeff" + path.read_text(), encoding="utf-8")
            self.assertEqual(read_csv(path), rows)

    def test_empty_csv_can_still_have_headers(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "records.csv"
            write_csv(path, [], fields=["dataset_id"])
            self.assertEqual(read_csv(path), [])
            self.assertEqual(path.read_text().strip(), "dataset_id")

    def test_cached_response_does_not_make_another_request(self):
        session = Mock()
        session.get.side_effect = AssertionError("The saved response should be reused")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            path.write_bytes(b'{"study": "one"}')
            info = {"response_url": "https://example.test/metadata"}
            path.with_name(path.name + ".source.json").write_text(json.dumps(info))
            self.assertEqual(cached_get(session, info["response_url"], path), (path.read_bytes(), info))
            session.get.assert_not_called()

    @patch("metadata_io.time.sleep")
    def test_refresh_replaces_the_cache_and_records_its_source(self, sleep):
        response = Mock(content=b'{"study": "new"}', url="https://example.test/metadata?id=1")
        session = Mock()
        session.get.return_value = response
        with TemporaryDirectory() as directory:
            path = Path(directory) / "metadata.json"
            path.write_bytes(b'{"study": "old"}')
            path.with_name(path.name + ".source.json").write_text("{}")
            raw, info = cached_get(session, "https://example.test/metadata", path, {"id": 1}, refresh=True)
            self.assertEqual(raw, response.content)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(source_info(path), info)
            self.assertEqual(info["sha256"], hashlib.sha256(raw).hexdigest())
            session.get.assert_called_once_with("https://example.test/metadata", params={"id": 1}, timeout=(15, 60))
            response.json.assert_called_once()

    @patch("metadata_io.time.sleep")
    def test_temporary_errors_are_retried(self, sleep):
        response = Mock(content=b"public page", url="https://example.test")
        session = Mock()
        session.get.side_effect = [requests.Timeout("temporary timeout"), response]
        with TemporaryDirectory() as directory:
            raw, _ = cached_get(session, response.url, Path(directory) / "page.html")
            self.assertEqual(raw, response.content)
            self.assertEqual(session.get.call_count, 2)

    @patch("metadata_io.time.sleep")
    def test_failed_refresh_keeps_the_previous_cache(self, sleep):
        session = Mock()
        session.get.side_effect = requests.Timeout("server unavailable")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "page.html"
            path.write_bytes(b"previous page")
            with self.assertRaises(requests.Timeout):
                cached_get(session, "https://example.test", path, refresh=True)
            self.assertEqual(path.read_bytes(), b"previous page")
            self.assertEqual(session.get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
