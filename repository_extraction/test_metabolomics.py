"""Offline regression checks for the two metabolomics repositories."""

import csv
import json
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from extract_metabolomics import field_status, read_workbench_tables, table_rows


root = Path(__file__).resolve().parent


class metabolomics_tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (root / "outputs/four_repository_results.json").is_file():
            raise unittest.SkipTest("Fetch and extract the four-repository pilot first")
        cls.result = json.loads((root / "outputs/four_repository_results.json").read_text())
        cls.rows = {row["dataset_id"]: row for row in cls.result["metadata"]}

    def test_all_selected_records_retained(self):
        self.assertEqual(len(self.result["metadata"]), 25)
        self.assertEqual(self.result["extraction_errors"], [])

    def test_workbench_pagination_not_truncated(self):
        row = self.rows["ST001038"]
        self.assertEqual(row["sample_metadata_rows"], 226)
        self.assertEqual(row["sample_count_reported"], 226)
        self.assertEqual(row["sample_size_placenta"], "")
        self.assertEqual(row["total_subjects"], "")

    def test_mixed_tissues_not_lost_to_summary_label(self):
        row = self.rows["ST000120"]
        self.assertIn("Placenta", row["sample_source"])
        self.assertIn("Adrenal gland", row["sample_source"])
        self.assertEqual(row["sample_metadata_rows"], 270)
        self.assertEqual(row["placenta_labeled_sample_rows"], 30)
        self.assertEqual(row["sample_size_placenta"], "")

    def test_all_analysis_ids_preserved(self):
        self.assertEqual(len(self.rows["ST004226"]["analysis_ids"].split("; ")), 4)
        self.assertEqual(self.rows["ST004226"]["placenta_labeled_sample_rows"], 30)

    def test_publication_and_dataset_doi_separated(self):
        row = self.rows["ST001038"]
        self.assertEqual(row["dataset_doi"], "10.21228/M8V100")
        self.assertEqual(row["all_dois"], "10.3390/metabo8010010")

    @unittest.skipUnless(
        all((root / f"cache/metabolights/{key}.json").is_file() for key in
            ["MTBLS2148", "MTBLS3091", "MTBLS14423", "MTBLS12795", "MTBLS346"]),
        "Fetch the MetaboLights pilot metadata first",
    )
    def test_complete_metabolights_tables(self):
        for key in ["MTBLS2148", "MTBLS3091", "MTBLS14423", "MTBLS12795", "MTBLS346"]:
            source = json.loads((root / f"cache/metabolights/{key}.json").read_text())["content"]
            row = self.rows[key]
            self.assertEqual(row["sample_metadata_rows"], len(source["sampleTable"]["data"]))
            self.assertEqual(row["assay_metadata_rows"], sum(len(a["assayTable"]["data"]) for a in source["assays"]))
            self.assertEqual(row["sample_size_placenta"], "")

    def test_nonplacental_candidates_retained(self):
        self.assertEqual(self.rows["MTBLS12795"]["sample_source"], "feces")
        self.assertEqual(self.rows["MTBLS346"]["organism"], "Vitis vinifera")
        self.assertEqual(self.rows["MTBLS346"]["placenta_labeled_sample_rows"], 0)

    @unittest.skipUnless((root / "outputs/pilot_results.json").is_file(), "Run the pilot extraction first")
    def test_old_results_are_unchanged(self):
        old = json.loads((root / "outputs/pilot_results.json").read_text())
        for original in old["metadata"]:
            for key, value in original.items():
                self.assertEqual(self.rows[original["dataset_id"]][key], value)

    def test_blanks_not_presented_as_extraction_failures(self):
        self.assertEqual(field_status(self.rows["MSV000086385"], "email")[0], "not_assessed")
        self.assertEqual(field_status(self.rows["ST001038"], "sample_size_placenta")[0], "needs_review")
        self.assertEqual(field_status(self.rows["ST001038"], "country")[0], "not_mapped")

    @unittest.skipUnless((root / "outputs/metabolomics_samples.csv").is_file(), "Run the metabolomics extraction first")
    def test_sample_export_count_reconciles(self):
        with (root / "outputs/metabolomics_samples.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), sum(row.get("sample_metadata_rows") or 0 for row in self.result["metadata"]))


class metabolomics_parser_tests(unittest.TestCase):
    """Small parsing checks that do not require downloaded metadata."""

    def test_long_protocol_and_repeated_labels_are_preserved(self):
        long_text = "protocol detail " * 8000
        soup = BeautifulSoup(f'<table><tr><td>MS ID:</td><td>MS1</td></tr>'
            f'<tr><td>MS Comments:</td><td>{long_text}</td></tr>'
            '<tr><td>Instrument Name:</td><td>A</td></tr><tr><td>Instrument Name:</td><td>B</td></tr></table>', "html.parser")
        rows = read_workbench_tables(soup)[0][1]
        self.assertEqual(rows[1][1], long_text.strip())
        self.assertEqual([v for k, v in rows if k == "Instrument Name"], ["A", "B"])

    def test_bad_table_dimensions_raise(self):
        with self.assertRaises(ValueError):
            list(table_rows({"fields": {"x": {"index": 0, "header": "Sample Name", "fieldType": "basic"}}, "data": [["A", "B"]]}))


if __name__ == "__main__":
    unittest.main()
