"""Offline checks for the all-study dbGaP runner."""

import json
import csv
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree

import requests

from run_dbgap import (api_document, collect_sra, extract_study, fetch_response, keep_previous_result,
                       molecular_availability, output_fields, pending_access, run, write_json,
                       page_document, parse_bioproject, parse_contacts, parse_pubmed, parse_sra,
                       read_inputs, reference_document, reference_page_numbers, save_csv, save_results)


def package(experiment="SRX1", sample="SRS1", tissue="Placenta", study="phs001320"):
    return f"""<EXPERIMENT_PACKAGE>
      <STUDY accession="SRP1"><IDENTIFIERS><EXTERNAL_ID namespace="dbGaP">{study}</EXTERNAL_ID>
      <EXTERNAL_ID namespace="BioProject">PRJNA1</EXTERNAL_ID></IDENTIFIERS></STUDY>
      <SAMPLE accession="{sample}"><IDENTIFIERS><EXTERNAL_ID namespace="BioSample">SAMN1</EXTERNAL_ID></IDENTIFIERS>
      <SAMPLE_NAME><SCIENTIFIC_NAME>Homo sapiens</SCIENTIFIC_NAME></SAMPLE_NAME><SAMPLE_ATTRIBUTES>
      <SAMPLE_ATTRIBUTE><TAG>body site</TAG><VALUE>{tissue}</VALUE></SAMPLE_ATTRIBUTE>
      <SAMPLE_ATTRIBUTE><TAG>analyte type</TAG><VALUE>RNA</VALUE></SAMPLE_ATTRIBUTE>
      </SAMPLE_ATTRIBUTES></SAMPLE>
      <EXPERIMENT accession="{experiment}"><DESIGN><DESIGN_DESCRIPTION>General deposited methods.</DESIGN_DESCRIPTION>
      <LIBRARY_DESCRIPTOR><LIBRARY_STRATEGY>RNA-Seq</LIBRARY_STRATEGY><LIBRARY_SOURCE>TRANSCRIPTOMIC</LIBRARY_SOURCE>
      <LIBRARY_SELECTION>other</LIBRARY_SELECTION></LIBRARY_DESCRIPTOR></DESIGN></EXPERIMENT>
    </EXPERIMENT_PACKAGE>"""


def article(pmid, doi="", pmcid=""):
    return f"""<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><AuthorList>
      <Author><ForeName>Jane</ForeName><LastName>Doe</LastName><AffiliationInfo>
      <Affiliation>University. Electronic address: jane@example.edu.</Affiliation>
      </AffiliationInfo></Author></AuthorList></Article></MedlineCitation><PubmedData><ArticleIdList>
      <ArticleId IdType="pubmed">{pmid}</ArticleId><ArticleId IdType="doi">{doi}</ArticleId>
      <ArticleId IdType="pmc">{pmcid}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>"""


def saved_result(accession, status="extracted"):
    return {"metadata": {"dataset_id": accession, "title": "Saved study", "extraction_status": status},
            "components": {}, "details": {}, "field_sources": []}


class dbgap_run_tests(unittest.TestCase):
    def test_ids_validate_and_do_not_deduplicate_silently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ids.csv"
            path.write_text("dataset_id,source_url\nphs001320.v1.p1,https://example.org\n")
            self.assertEqual(len(read_inputs(path)), 1)
            self.assertIn("study_id=phs001320.v1.p1", read_inputs(path)[0]["source_url"])
            with self.assertRaises(ValueError):
                read_inputs(path, ["phs999999.v1.p1"])
            path.write_text(path.read_text() + "phs001320.v1.p1,https://example.org\n")
            with self.assertRaises(ValueError):
                read_inputs(path)

    def test_page_must_match_version(self):
        raw = '<span id="study-id">phs001320.v2.p1</span><h1 id="study-name">A</h1>'
        with self.assertRaises(ValueError):
            page_document(raw, "phs001320.v1.p1")

    def test_api_errors_are_not_absent_metadata(self):
        with self.assertRaises(ValueError):
            api_document(b'{"message":"error","data":{}}')

    def test_molecular_availability_requires_explicit_count_and_same_version(self):
        raw = b'''<script>window.accession = "phs001320.v1.p1";
            window.studyCounts = {num_datasets: 4, molecular_count: 0};</script>'''
        self.assertEqual(molecular_availability(raw, "phs001320.v1.p1")["molecular_count"], 0)
        for invalid in [raw.replace(b"molecular_count: 0", b"num_documents: 0"),
                        raw.replace(b"molecular_count: 0", b"molecular_count: -1"),
                        raw.replace(b"molecular_count: 0", b"molecular_count: null")]:
            with self.assertRaises(ValueError):
                molecular_availability(invalid, "phs001320.v1.p1")
        with self.assertRaises(ValueError):
            molecular_availability(raw, "phs001320.v2.p1")

    def test_access_notice_is_not_an_arbitrary_error_page(self):
        self.assertEqual(pending_access(b'<div id="restricted-access-body">Individual level data will be coming soon</div>'),
                         "Individual level data will be coming soon")
        for raw in [b'<html>Internal Server Error</html>', b'<div id="restricted-access-body"></div>',
                    b'<div id="restricted-access-body">Resources available</div>']:
            with self.assertRaises(ValueError):
                pending_access(raw)

    def test_unavailable_fields_need_positive_confirmation(self):
        def response(session, path, url, parser, params=None, offline=False, refresh=False):
            if path.name.endswith("page_review.html"):
                raw = b'<span id="study-id">phs001320.v1.p1</span><h1 id="study-name">Study</h1>'
            elif path.name.endswith("molecular.json") or path.name.endswith("access.json"):
                failure = requests.Response()
                failure.status_code = 404 if path.name.endswith("molecular.json") else 500
                failure.url = url
                failure.raise_for_status()
            elif path.name.endswith("availability.html"):
                raw = b'<script>window.accession = "phs001320.v1.p1"; window.studyCounts = {molecular_count: 0};</script>'
            elif path.name.endswith("access_notice.html"):
                raw = b'<div id="restricted-access-body">Individual level data will be coming soon</div>'
            else:
                raw = b'{"message":"OK","data":{}}'
            return parser(raw), {"response_url": url}
        with tempfile.TemporaryDirectory() as directory, patch("run_dbgap.fetch_response", side_effect=response):
            row = {"dataset_id": "phs001320.v1.p1", "source_url": "https://example.org/study"}
            result = extract_study(Mock(), row, Path(directory))
        self.assertEqual(result["metadata"]["extraction_status"], "extracted")
        self.assertEqual(result["components"]["molecular"]["status"], "not_reported")
        self.assertEqual(result["components"]["access"]["status"], "not_reported")
        self.assertEqual(result["components"]["access"]["http_status"], 500)
        self.assertFalse(result["metadata"]["sample_size_placenta"])
        self.assertNotIn("release_date", result["details"])

        def unconfirmed(*args, **kwargs):
            if args[1].name.endswith("availability.html"):
                return {"molecular_count": 1}, {"response_url": args[2]}
            return response(*args, **kwargs)
        with tempfile.TemporaryDirectory() as directory, patch("run_dbgap.fetch_response", side_effect=unconfirmed):
            result = extract_study(Mock(), row, Path(directory))
        self.assertEqual(result["metadata"]["extraction_status"], "partial")
        self.assertEqual(result["components"]["molecular"]["status"], "failed")

    def test_publication_pagination_uses_spans(self):
        soup = reference_document("""<div id="reference-list">There are 14 selected publications.
            <span onclick="updateReferences('phs001320.v1.p1','1234','2')">Next</span>
            <a onclick="updateReferences('phs001320.v1.p1','1234','1')">1</a></div>""")
        self.assertEqual(reference_page_numbers(soup), {1, 2})

    def test_contacts_exclude_funders_and_do_not_guess_countries(self):
        contacts = parse_contacts({"study_attribution": {
            "Principal Investigators": [{"piName": "A", "piInstitution": "Institute, France"},
                {"piName": "B", "piInstitution": "Institute, Unknown"}],
            "Funding Source": [{"piName": "Funder", "piInstitution": "Company, USA"}]}})
        self.assertEqual([p["country"] for p in contacts], ["France", ""])
        self.assertEqual([p["name"] for p in contacts], ["A", "B"])

    def test_sra_rejects_wrong_study_and_incomplete_batch(self):
        document = ElementTree.fromstring("<EXPERIMENT_PACKAGE_SET>" + package() + "</EXPERIMENT_PACKAGE_SET>")
        with self.assertRaises(ValueError):
            parse_sra(document, "phs999999.v1.p1", 1)
        with self.assertRaises(ValueError):
            parse_sra(document, "phs001320.v1.p1", 2)

    def test_bioproject_separates_parent_project_and_validates_requested_ids(self):
        raw = b'''<RecordSet><DocumentSummary uid="1"><Project><ProjectID>
            <ArchiveID accession="PRJNA1"/><CenterID>bp_data_submission_phs001320</CenterID>
            </ProjectID></Project></DocumentSummary><DocumentSummary uid="2"><Project><ProjectID>
            <ArchiveID accession="PRJNA2"/><CenterID>bp_data_submission_phs999999</CenterID>
            </ProjectID></Project></DocumentSummary></RecordSet>'''
        records = parse_bioproject(raw, ["1", "2"], "phs001320.v1.p1")
        self.assertEqual([r["matches_study"] for r in records], [True, False])
        with self.assertRaises(ValueError):
            parse_bioproject(raw, ["1"], "phs001320.v1.p1")

    def test_sra_preserves_tissue_context_and_general_methods(self):
        document = ElementTree.fromstring("<EXPERIMENT_PACKAGE_SET>" + package() +
            package("SRX2", "SRS1") + package("SRX3", "SRS2", "Saliva") + "</EXPERIMENT_PACKAGE_SET>")
        fields, samples, experiments, methods = defaultdict(set), {}, set(), set()
        collect_sra(parse_sra(document, "phs001320.v1.p1", 3), fields, samples, experiments, methods)
        self.assertEqual(len(samples), 2)
        self.assertEqual(len(experiments), 3)
        self.assertEqual(fields["extraction_protocol"], set())
        self.assertIn(("Placenta", "General deposited methods."), methods)
        self.assertIn("SAMN1", fields["biosample_bioproject_id"])
        self.assertIn("Saliva: body site: Saliva", fields["characteristics"])
        self.assertNotIn("sample_size_placenta", fields)

    def test_duplicate_experiments_are_rejected(self):
        document = ElementTree.fromstring("<EXPERIMENT_PACKAGE_SET>" + package() * 2 + "</EXPERIMENT_PACKAGE_SET>")
        with self.assertRaises(ValueError):
            collect_sra(parse_sra(document, "phs001320.v1.p1", 2), defaultdict(set), {}, set(), set())

    def test_broad_sra_link_is_recovered_only_with_matching_study_records(self):
        def response(session, path, url, parser, params=None, offline=False, refresh=False):
            if path.name.endswith("page_review.html"):
                raw = b'''<span id="study-id">phs001320.v1.p1</span><h1 id="study-name">Study</h1>
                    <a href="https://www.ncbi.nlm.nih.gov/sra?LinkName=gap_sra_all&amp;from_uid=123">SRA</a>'''
            elif url.endswith("elink.fcgi"):
                raw = b'<eLinkResult><LinkSetDb><DbTo>sra</DbTo><Link><Id>1</Id></Link></LinkSetDb></eLinkResult>'
            elif url.endswith("esearch.fcgi"):
                raw = b'<eSearchResult><Count>2</Count><IdList><Id>2</Id><Id>3</Id></IdList></eSearchResult>'
            elif url.endswith("efetch.fcgi"):
                packages = package(study="phs999999") if params["id"] == "1" else package() + package("SRX2", "SRS2")
                raw = ("<EXPERIMENT_PACKAGE_SET>" + packages + "</EXPERIMENT_PACKAGE_SET>").encode()
            else:
                raw = b'{"message":"OK","data":{}}'
            return parser(raw), {"response_url": url}
        with tempfile.TemporaryDirectory() as directory, patch("run_dbgap.fetch_response", side_effect=response):
            result = extract_study(Mock(), {"dataset_id": "phs001320.v1.p1", "source_url": "https://example.org/study"}, Path(directory))
        self.assertEqual(result["metadata"]["extraction_status"], "extracted")
        self.assertEqual(result["components"]["sra_0"]["status"], "recovered")
        self.assertEqual(result["metadata"]["sample_size_placenta"], 2)
        self.assertEqual(result["details"]["sra_experiments_read"], 2)
        self.assertEqual(result["details"]["broad_sra_link_count"], 1)

    def test_pubmed_preserves_pairing_and_author_email(self):
        raw = ("<PubmedArticleSet>" + article("2", "10.123/second", "PMC2") + article("1") + "</PubmedArticleSet>").encode()
        records = parse_pubmed(raw, ["1", "2"])
        self.assertEqual(records[0]["pmid"], "1")
        self.assertFalse(records[0]["doi"])
        self.assertFalse(records[0]["pmcid"])
        self.assertEqual(records[1]["doi"], "10.123/second")
        self.assertEqual(records[0]["contacts"][0]["email"], "jane@example.edu")
        with self.assertRaises(ValueError):
            parse_pubmed(raw, ["1", "3"])

    def test_rate_limit_is_not_retried(self):
        response = requests.Response()
        response.status_code = 429
        response.url = "https://example.org/data"
        session = Mock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "response.json"
            with self.assertRaises(requests.HTTPError):
                fetch_response(session, path, response.url, api_document)
            self.assertFalse(path.exists())
        self.assertEqual(session.get.call_count, 1)

    def test_book_chapter_does_not_borrow_identifiers_from_references(self):
        raw = b'''<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>3</PMID>
            <ReferenceList><Reference><ArticleIdList>
            <ArticleId IdType="pubmed">9</ArticleId><ArticleId IdType="pmc">PMC9</ArticleId>
            </ArticleIdList></Reference></ReferenceList></BookDocument>
            <PubmedBookData><ArticleIdList><ArticleId IdType="pubmed">3</ArticleId>
            </ArticleIdList></PubmedBookData></PubmedBookArticle></PubmedArticleSet>'''
        records = parse_pubmed(raw, ["3"])
        self.assertEqual(records[0]["pmid"], "3")
        self.assertEqual(records[0]["pmcid"], "")
        self.assertEqual(records[0]["doi"], "")

    def test_invalid_response_is_not_cached(self):
        response = requests.Response()
        response.status_code = 200
        response.url = "https://example.org/data"
        response._content = b'{"message":"not found","data":{}}'
        session = Mock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "response.json"
            with self.assertRaises(ValueError):
                fetch_response(session, path, response.url, api_document)
            self.assertFalse(path.exists())

    def test_offline_mode_never_sends_a_request(self):
        session = Mock()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                fetch_response(session, Path(directory) / "missing.json", "https://example.org", api_document, offline=True)
        session.get.assert_not_called()

    def test_cached_response_is_reused_and_refresh_is_explicit(self):
        response = requests.Response()
        response.status_code = 200
        response.url = "https://example.org/data"
        response._content = b'{"message":"OK","data":{"value":1}}'
        session = Mock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as directory, patch("run_dbgap.time.sleep"):
            path = Path(directory) / "response.json"
            fetch_response(session, path, response.url, api_document)
            fetch_response(session, path, response.url, api_document)
            self.assertEqual(session.get.call_count, 1)
            fetch_response(session, path, response.url, api_document, refresh=True)
            self.assertEqual(session.get.call_count, 2)
            path.with_name(path.name + ".source.json").write_text("broken json")
            fetch_response(session, path, response.url, api_document)
            self.assertEqual(session.get.call_count, 3)

    def test_failed_refresh_does_not_replace_a_valid_response(self):
        valid = requests.Response()
        valid.status_code = 200
        valid.url = "https://example.org/data"
        valid._content = b'{"message":"OK","data":{"value":1}}'
        failed = requests.Response()
        failed.status_code = 500
        failed.url = valid.url
        session = Mock()
        session.get.side_effect = [valid, failed, failed, failed]
        with tempfile.TemporaryDirectory() as directory, patch("run_dbgap.time.sleep"):
            path = Path(directory) / "response.json"
            fetch_response(session, path, valid.url, api_document)
            with self.assertRaises(requests.HTTPError):
                fetch_response(session, path, valid.url, api_document, refresh=True)
            self.assertEqual(path.read_bytes(), valid.content)
            self.assertEqual(fetch_response(session, path, valid.url, api_document, offline=True)[0], {"value": 1})
        self.assertEqual(session.get.call_count, 4)

    def test_interrupted_csv_write_keeps_previous_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            path.write_text("previous results\n")
            with patch("run_dbgap.write_csv", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    save_csv(path, [{"dataset_id": "phs001320.v1.p1"}])
            self.assertEqual(path.read_text(), "previous results\n")

    def test_selected_retry_keeps_all_input_rows(self):
        ids = ["phs001320.v1.p1", "phs001782.v2.p1", "phs001886.v6.p1"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "ids.csv"
            path.write_text("dataset_id\n" + "\n".join(ids) + "\n")
            for accession in ids:
                write_json(root / "cache/dbgap" / (accession + ".result.json"), saved_result(accession, "partial"))
            with patch("run_dbgap.extract_study", return_value=saved_result(ids[1])) as extract:
                run(root, path, [ids[1]], retry_failed=True)
            self.assertEqual(extract.call_count, 1)
            with (root / "results/dbgap_metadata.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r["GEO Series ID (GSE___)"] for r in rows], ids)
            with (root / "results/dbgap_status.csv").open() as stream:
                statuses = list(csv.DictReader(stream))
            self.assertEqual([r["status"] for r in statuses], ["partial", "extracted", "partial"])

    def test_retry_failed_skips_successes_and_includes_unattempted_studies(self):
        ids = ["phs001320.v1.p1", "phs001782.v2.p1", "phs001886.v6.p1"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "ids.csv"
            path.write_text("dataset_id\n" + "\n".join(ids) + "\n")
            write_json(root / "cache/dbgap" / (ids[0] + ".result.json"), saved_result(ids[0]))
            write_json(root / "cache/dbgap" / (ids[1] + ".result.json"), saved_result(ids[1], "partial"))
            with patch("run_dbgap.extract_study", side_effect=lambda session, row, *args: saved_result(row["dataset_id"])) as extract:
                self.assertTrue(run(root, path, retry_failed=True))
            self.assertEqual([call.args[1]["dataset_id"] for call in extract.call_args_list], ids[1:])

    def test_failed_refresh_retains_even_a_partial_saved_row(self):
        previous = saved_result("phs001320.v1.p1", "partial")
        current = {"metadata": {"dataset_id": "phs001320.v1.p1", "extraction_status": "failed"},
                   "components": {"page": {"status": "failed", "http_status": 500}}, "field_sources": [], "details": {}}
        result = keep_previous_result(previous, current)
        self.assertEqual(result["metadata"]["title"], "Saved study")
        self.assertEqual(result["metadata"]["extraction_status"], "partial")
        self.assertEqual(result["components"]["refresh_page"]["http_status"], 500)
        self.assertFalse(previous["components"])

    def test_rate_limit_stops_queue_and_keeps_unattempted_rows(self):
        ids = ["phs001320.v1.p1", "phs001782.v2.p1"]
        limited = saved_result(ids[0], "partial")
        limited["components"]["page"] = {"status": "failed", "http_status": 429, "error": "Rate limited"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "ids.csv"
            path.write_text("dataset_id\n" + "\n".join(ids) + "\n")
            with patch("run_dbgap.extract_study", return_value=limited) as extract:
                self.assertFalse(run(root, path))
            self.assertEqual(extract.call_count, 1)
            summary = json.loads((root / "progress.json").read_text())
            self.assertEqual(summary["partial"], 1)
            self.assertEqual(summary["not_attempted"], 1)

    def test_complete_ids_and_blank_fields_in_export(self):
        rows = [{"dataset_id": "phs001320.v1.p1"}, {"dataset_id": "phs001782.v2.p1"}]
        result = {"metadata": {"dataset_id": rows[0]["dataset_id"], "extraction_status": "partial", "title": "Test"},
                  "components": {"sra": {"status": "failed", "error": "test"}}, "details": {"release_date": "2017-05-24"}, "field_sources": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = save_results(root, rows, {rows[0]["dataset_id"]: result})
            self.assertEqual((summary["complete"], summary["partial"], summary["not_attempted"]), (0, 1, 1))
            saved = json.loads((root / "results/dbgap_results.json").read_text())
            self.assertEqual([r["metadata"]["dataset_id"] for r in saved["results"]], [r["dataset_id"] for r in rows])
            self.assertEqual(len(output_fields), 31)
            self.assertNotIn("release_date", output_fields)
            with (root / "results/dbgap_metadata.csv").open() as stream:
                exported = list(csv.DictReader(stream))
            self.assertEqual(exported[0]["Submission date"], "2017-05-24")
            self.assertEqual(exported[1]["Submission date"], "")
            self.assertEqual(exported[0]["Last update date"], "")
            self.assertEqual(summary["field_coverage"]["submission_date"], 1)
            self.assertNotIn("submission_date", result["metadata"])
            self.assertEqual(saved["results"][0], result)

    def test_release_date_export_preserves_raw_metadata_and_sources(self):
        accession = "phs001320.v1.p1"
        result = saved_result(accession)
        result["metadata"].update(release_date="2017-05-24", submission_date="")
        result["details"]["release_date"] = "2017-05-24"
        result["field_sources"] = [{"dataset_id": accession, "field": "release_date",
            "value": "2017-05-24", "source_section": "Release date (not submission or update date)",
            "source_url": "https://dbgap.ncbi.nlm.nih.gov/beta/api/study/phs001320.v1.p1/authorized-access/"}]
        original = json.loads(json.dumps(result))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save_results(root, [{"dataset_id": accession}], {accession: result})
            with (root / "results/dbgap_metadata.csv").open() as stream:
                reader = csv.DictReader(stream)
                exported = list(reader)
                self.assertEqual(len(reader.fieldnames), 31)
                self.assertEqual(reader.fieldnames[19], "Submission date")
            self.assertEqual(exported[0]["Submission date"], "2017-05-24")
            saved = json.loads((root / "results/dbgap_results.json").read_text())
            self.assertEqual(saved["results"][0], original)
            with (root / "results/dbgap_field_sources.csv").open() as stream:
                self.assertEqual(list(csv.DictReader(stream)), original["field_sources"])
            with (root / "results/dbgap_details.csv").open() as stream:
                self.assertEqual(next(csv.DictReader(stream))["release_date"], "2017-05-24")
        self.assertEqual(result, original)

    def test_missing_release_dates_stay_blank(self):
        for value in (None, ""):
            with self.subTest(release_date=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result = saved_result("phs001320.v1.p1")
                result["metadata"].update(release_date=value, last_update_date="2026-11-02")
                result["details"]["release_date"] = value
                rows = [{"dataset_id": result["metadata"]["dataset_id"]}]
                summary = save_results(root, rows, {rows[0]["dataset_id"]: result})
                with (root / "results/dbgap_metadata.csv").open() as stream:
                    exported = next(csv.DictReader(stream))
                self.assertEqual(exported["Submission date"], "")
                self.assertEqual(exported["Last update date"], "2026-11-02")
                self.assertEqual(summary["field_coverage"]["submission_date"], 0)

    def test_study_release_date_reaches_main_export(self):
        accession = "phs001320.v1.p1"

        def response(session, path, url, parser, params=None, offline=False, refresh=False):
            if path.name.endswith("page_review.html"):
                raw = f'<span id="study-id">{accession}</span><h1 id="study-name">Study</h1>'.encode()
            elif path.name.endswith("access.json"):
                raw = json.dumps({"message": "OK", "data": {"study_info": {
                    "release_date": "2017-05-24",
                    "datasets": [{"name": "data.txt", "release_date": "2016-01-01"}]}}}).encode()
            else:
                raw = b'{"message":"OK","data":{}}'
            return parser(raw), {"response_url": url}

        with tempfile.TemporaryDirectory() as directory, patch("run_dbgap.fetch_response", side_effect=response):
            root = Path(directory)
            row = {"dataset_id": accession, "source_url": "https://example.org/study"}
            result = extract_study(Mock(), row, root)
            save_results(root, [row], {accession: result})
            with (root / "results/dbgap_metadata.csv").open() as stream:
                exported = next(csv.DictReader(stream))
        self.assertEqual(exported["Submission date"], "2017-05-24")
        self.assertEqual(result["metadata"]["release_date"], "2017-05-24")
        self.assertEqual(result["metadata"]["submission_date"], "")


if __name__ == "__main__":
    unittest.main()
