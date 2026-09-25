"""Offline checks for complete, correctly linked dbGaP metadata."""

import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from xml.etree import ElementTree

from extract_pilot import extract, extract_pubmed_identifiers, join_values, put
from fetch_dbgap_metadata import fetch_sra_metadata, fetch_xml


root = Path(__file__).resolve().parent


def linked_ids(count):
    links = "".join(f"<Link><Id>{index}</Id></Link>" for index in range(count))
    return ElementTree.fromstring(f"<LinkSet><LinkSetDb><DbTo>sra</DbTo>{links}</LinkSetDb></LinkSet>")


def experiment_batch(ids, study="phs001320"):
    document = ElementTree.Element("EXPERIMENT_PACKAGE_SET")
    for accession in ids:
        package = ElementTree.SubElement(document, "EXPERIMENT_PACKAGE")
        ElementTree.SubElement(package, "EXPERIMENT", accession=str(accession))
        identifiers = ElementTree.SubElement(ElementTree.SubElement(package, "STUDY"), "IDENTIFIERS")
        ElementTree.SubElement(identifiers, "EXTERNAL_ID", namespace="dbGaP").text = study
    return document


class dbgap_metadata_tests(unittest.TestCase):
    def test_sra_fetch_reads_more_than_one_batch(self):
        manifest = {"sra_batches": []}
        responses = [(linked_ids(201), {}), (experiment_batch(range(200)), {}), (experiment_batch([200]), {})]
        with patch("fetch_dbgap_metadata.fetch_xml", side_effect=responses) as fetch_xml_mock:
            with contextlib.redirect_stdout(io.StringIO()):
                fetch_sra_metadata(Mock(), Path("unused"), "phs001320.v1.p1", "123", manifest)
        self.assertEqual(manifest["sra_count"], 201)
        self.assertEqual([batch["count"] for batch in manifest["sra_batches"]], [200, 1])
        self.assertEqual(fetch_xml_mock.call_count, 3)

    def test_sra_fetch_rejects_incomplete_duplicate_or_unrelated_records(self):
        cases = [
            (experiment_batch([0]), "returned 1 of 2"),
            (experiment_batch([0, 0]), "Duplicate"),
            (experiment_batch([0, 1], study="phs999999"), "not linked"),
        ]
        for document, message in cases:
            with self.subTest(message=message):
                with patch("fetch_dbgap_metadata.fetch_xml", side_effect=[(linked_ids(2), {}), (document, {})]):
                    with self.assertRaisesRegex(ValueError, message):
                        fetch_sra_metadata(Mock(), Path("unused"), "phs001320.v1.p1", "123", {"sra_batches": []})

    def test_missing_sra_link_is_not_a_download_failure(self):
        manifest = {"sra_batches": []}
        with patch("fetch_dbgap_metadata.fetch_xml") as request:
            fetch_sra_metadata(Mock(), Path("unused"), "phs001320.v1.p1", None, manifest)
        request.assert_not_called()
        self.assertEqual(manifest["sra_link_status"], "not_linked_on_page")
        self.assertEqual(manifest["sra_count"], 0)

    def test_changed_request_ids_refresh_the_cached_xml(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sra.xml"
            path.with_name(path.name + ".source.json").write_text(json.dumps({
                "response_url": "https://example.test?db=sra&id=old",
            }))
            with patch("fetch_dbgap_metadata.cached_get", return_value=(b"<response/>", {})) as request:
                fetch_xml(Mock(), "efetch.fcgi", {"db": "sra", "id": "new"}, path)
            self.assertTrue(request.call_args.args[-1])

    def test_unrelated_publication_is_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pubmed.xml"
            path.write_text("<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>999</PMID>"
                            "</MedlineCitation></PubmedArticle></PubmedArticleSet>")
            record = {"all_pmids": "123", "all_dois": "10.1000/listed"}
            with self.assertRaisesRegex(ValueError, "did not match"):
                extract_pubmed_identifiers(record, [], path.parent, {"file": path.name})

    @unittest.skipUnless(
        (root / "outputs/pilot_results.json").is_file() and (root / "cache").is_dir(),
        "Fetch and extract the pilot first",
    )
    def test_failed_targeted_update_preserves_saved_results(self):
        with TemporaryDirectory() as directory:
            temporary = Path(directory)
            for name in ["inputs", "cache", "pilot_review.json"]:
                (temporary / name).symlink_to(root / name)
            (temporary / "outputs").mkdir()
            saved = (root / "outputs/pilot_results.json").read_bytes()
            output = temporary / "outputs/pilot_results.json"
            output.write_bytes(saved)
            with patch("extract_pilot.extract_dbgap", side_effect=ValueError("incomplete source")):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertFalse(extract(temporary, ["phs001320.v1.p1"]))
            self.assertEqual(output.read_bytes(), saved)
            self.assertEqual(list(output.parent.iterdir()), [output])

    def test_blank_values_are_skipped_but_zero_is_retained(self):
        record = {"source": "dbgap", "dataset_id": "study"}
        evidence = []
        put(record, evidence, "count", 0, "reported count", "https://example.test")
        put(record, evidence, "count", "", "blank", "https://example.test")
        self.assertEqual(record["count"], 0)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(join_values([" A ", "B", "A", None, "", 0]), "A; B; 0")


if __name__ == "__main__":
    unittest.main()
