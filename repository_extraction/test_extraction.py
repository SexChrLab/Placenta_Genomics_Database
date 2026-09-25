"""Offline checks for the scientific distinctions exercised by the pilot."""

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from extract_pilot import extract_dbgap_linked, extract_massive, geo_columns, get_publication_ids
from fetch_dbgap_metadata import sra_study_uid


root = Path(__file__).resolve().parent


class extraction_tests(unittest.TestCase):
    @unittest.skipUnless((root / "outputs/pilot_results.json").is_file(), "Run the pilot extraction first")
    def test_dataset_doi_is_not_a_publication(self):
        result = json.loads((root / "outputs/pilot_results.json").read_text())
        rows = {row["dataset_id"]: row for row in result["metadata"]}
        self.assertEqual(rows["MSV000085995"]["dataset_doi"], "10.25345/C5XX87")
        self.assertEqual(rows["MSV000085995"]["all_dois"], "")
        self.assertEqual(rows["MSV000085995"]["all_pmids"], "")

    @unittest.skipUnless((root / "outputs/pilot_results.json").is_file(), "Run the pilot extraction first")
    def test_population_counts_are_not_placenta_counts(self):
        result = json.loads((root / "outputs/pilot_results.json").read_text())
        rows = {row["dataset_id"]: row for row in result["metadata"]}
        self.assertEqual(rows["phs001782.v2.p1"]["total_subjects"], 802)
        self.assertEqual(rows["phs001782.v2.p1"]["sample_size_placenta"],
                         "Whole-transcriptome dataset: 59 placentas (111 biopsies); "
                         "targeted RNA-seq dataset: 251 placentas (262 samples). "
                         "Overlap between datasets is not stated.")
        self.assertEqual(rows["phs001320.v1.p1"]["sample_size_placenta"], "")
        self.assertEqual(rows["MSV000095456"]["sample_size_placenta"], 1)
        self.assertEqual(rows["MSV000094962"]["sample_size_placenta"], "")

    @unittest.skipUnless((root / "outputs/pilot_results.json").is_file(), "Run the pilot extraction first")
    def test_all_selected_publications_survive(self):
        result = json.loads((root / "outputs/pilot_results.json").read_text())
        row = next(row for row in result["metadata"] if row["dataset_id"] == "phs001886.v6.p1")
        self.assertEqual(row["publication_count"], 6)
        self.assertEqual(len(row["all_pmids"].split("; ")), 6)

    def test_reconcile_versions_without_losing_candidates(self):
        with (root / "inputs/dbgap_ids.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 33)
        self.assertEqual(len({row["study_id"] for row in rows}), 33)
        changed = next(row for row in rows if row["study_id"] == "phs001886")
        self.assertEqual(changed["workbook_accession"], "phs001886.v5.p1")
        self.assertEqual(changed["dataset_id"], "phs001886.v6.p1")
        self.assertIn("phs003122.v1.p1", {row["dataset_id"] for row in rows})

    @unittest.skipUnless((root / "outputs/pilot_results.json").is_file(), "Run the pilot extraction first")
    def test_search_hits_are_retained_for_review(self):
        result = json.loads((root / "outputs/pilot_results.json").read_text())
        row = next(row for row in result["metadata"] if row["dataset_id"] == "phs003002.v2.p1")
        self.assertEqual(row["review_status"], "likely_irrelevant")
        self.assertEqual(row["extraction_status"], "extracted")

    @unittest.skipUnless((root / "outputs/pilot_results.json").is_file(), "Run the pilot extraction first")
    def test_original_labels_are_preserved(self):
        result = json.loads((root / "outputs/pilot_results.json").read_text())
        row = next(row for row in result["metadata"] if row["dataset_id"] == "phs003122.v1.p1")
        self.assertEqual(row["repository_data_type"], "OTHER")
        self.assertEqual(row["data_type"], "Single-cell RNA sequencing")
        self.assertEqual(row["study_design"], "Metagenomics")

    def test_generic_ncbi_link_is_not_a_pmid(self):
        soup = BeautifulSoup('<a href="https://www.ncbi.nlm.nih.gov/pubmed?from_uid=1684408">PubMed</a>', "html.parser")
        self.assertEqual(get_publication_ids(soup), ([], []))

    @unittest.skipUnless((root / "cache/massive/MSV000086385.html").is_file(), "Fetch the MassIVE pilot pages first")
    def test_description_has_no_character_cap(self):
        original = (root / "cache/massive/MSV000086385.html").read_bytes()
        soup = BeautifulSoup(original, "html.parser")
        heading = next(tag for tag in soup.find_all("h2") if tag.get_text(strip=True) == "Description")
        paragraph = heading.parent.find("p")
        paragraph.clear()
        description = "complete metadata text " * 6000 + "final_marker"
        paragraph.append(description)
        record = dict.fromkeys(geo_columns, "")
        record.update(dataset_id="MSV000086385", source="massive", source_url="https://example.test")
        extract_massive(record, [], soup, root)
        self.assertEqual(record["assay_description"], description)

    @unittest.skipUnless(
        all((root / "cache/dbgap" / f"{accession}.html").is_file() for accession in
            ["phs001320.v1.p1", "phs001782.v2.p1", "phs001886.v6.p1", "phs003122.v1.p1"]),
        "Fetch the dbGaP pilot pages first",
    )
    def test_link_detection_on_four_page_layouts(self):
        for accession in ['phs001320.v1.p1', 'phs001782.v2.p1', 'phs001886.v6.p1', 'phs003122.v1.p1']:
            with self.subTest(accession=accession):
                soup = BeautifulSoup((root / 'cache/dbgap' / f'{accession}.html').read_bytes(), 'html.parser')
                self.assertTrue(sra_study_uid(soup).isdigit())
        self.assertIsNone(sra_study_uid(BeautifulSoup('<p>No link here</p>', 'html.parser')))
        with self.assertRaisesRegex(ValueError, 'valid dbGaP UID'):
            sra_study_uid(BeautifulSoup('<a href="?LinkName=gap_sra_all">SRA</a>', 'html.parser'))

    @unittest.skipUnless(
        (root / "outputs/pilot_results.json").is_file()
        and all((root / "cache/dbgap" / f"{accession}.linked_metadata.json").is_file()
                for accession in ["phs001320.v1.p1", "phs001782.v2.p1"]),
        "Fetch linked metadata for the two reviewed dbGaP studies and rerun the pilot extraction",
    )
    def test_complete_linked_metadata_is_preserved(self):
        rows = {row['dataset_id']: row for row in json.loads((root / 'outputs/pilot_results.json').read_text())['metadata']}
        first, second = rows['phs001320.v1.p1'], rows['phs001782.v2.p1']
        self.assertEqual(first['source_details']['sra_experiments_checked'], 59)
        self.assertEqual(second['source_details']['sra_experiments_checked'], 1217)
        self.assertEqual(set(first['instrument_model'].split('; ')), {'Illumina HiSeq 2000', 'Illumina HiSeq 2500'})
        self.assertEqual(first['library_selection'], 'other')
        self.assertIn('TRIzol', first['extraction_protocol'])
        self.assertEqual(set(second['library_source'].split('; ')), {'GENOMIC', 'TRANSCRIPTOMIC'})
        for tissue in ['placenta', 'saliva', 'umbilical_cord']:
            self.assertIn(tissue, second['characteristics'])
        self.assertIn('SMARTer', second['extraction_protocol'])
        self.assertNotIn('alignment_software: None', second['data_processing'])
        self.assertEqual(set(second['all_pmcids'].split('; ')), {'PMC6993844', 'PMC8496276'})
        self.assertEqual(first['all_pmcids'], '')

    @unittest.skipUnless((root / "cache/dbgap/phs001320.v1.p1.sra_0.xml").is_file(), "Fetch linked dbGaP metadata first")
    def test_linked_validation_and_no_link_case(self):
        accession = 'phs001320.v1.p1'
        package = ElementTree.parse(root / 'cache/dbgap' / f'{accession}.sra_0.xml').getroot().find('EXPERIMENT_PACKAGE')
        with TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            directory = temp_root / 'cache/dbgap'
            directory.mkdir(parents=True)
            manifest_path = directory / f'{accession}.linked_metadata.json'
            manifest = {'status': 'complete', 'sra_count': 0, 'sra_batches': []}
            record = dict.fromkeys(geo_columns, '')
            record.update(dataset_id=accession, source='dbgap', source_url='https://example.test')
            manifest_path.write_text(json.dumps(manifest))
            extract_dbgap_linked(record, [], temp_root)
            self.assertEqual(record['source_details']['sra_experiments_checked'], 0)

            document = ElementTree.Element('EXPERIMENT_PACKAGE_SET')
            document.append(package)
            path = directory / 'sra.xml'
            ElementTree.ElementTree(document).write(path)
            manifest.update(sra_count=1, sra_batches=[{'file': 'sra.xml', 'count': 1}],
                            sra_link_source={'response_url': 'https://example.test?id=1684408'})
            manifest_path.write_text(json.dumps(manifest))
            extract_dbgap_linked(record, [], temp_root)
            self.assertEqual(record['source_details']['sra_experiments_checked'], 1)

            manifest['sra_count'] = 2
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                extract_dbgap_linked(record, [], temp_root)
            document.append(package)
            ElementTree.ElementTree(document).write(path)
            manifest['sra_batches'][0]['count'] = 2
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                extract_dbgap_linked(record, [], temp_root)

            document.remove(package)
            package.find('./STUDY/IDENTIFIERS/EXTERNAL_ID[@namespace="dbGaP"]').text = 'phs999999'
            ElementTree.ElementTree(document).write(path)
            manifest.update(sra_count=1, sra_batches=[{'file': 'sra.xml', 'count': 1}])
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'does not match'):
                extract_dbgap_linked(record, [], temp_root)


if __name__ == "__main__":
    unittest.main()
