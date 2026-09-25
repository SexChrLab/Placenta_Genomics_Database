"""Extract and document repository metadata from the cached pilot pages."""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from metadata_io import read_csv, source_info, write_csv


geo_columns = {
    "dataset_id": "GEO Series ID (GSE___)", "source": "",
    "title": "Title", "organism": "Organism", "data_type": "Data type",
    "sample_size_placenta": "Sample size (placenta)", "characteristics": "Characteristics",
    "extracted_molecule": "Extracted molecule", "extraction_protocol": "Extraction protocol",
    "library_strategy": "Library Strategy", "library_source": "Library source",
    "library_selection": "Library selection", "instrument_model": "Instrument model",
    "assay_description": "Assay description", "data_processing": "Data processing",
    "platform_id": "Platform ID (list)", "sra_study_id": "SRA Study ID (raw data)",
    "biosample_bioproject_id": "BioSample/BioProject ID",
    "file_types": "File types/resources provided (list)", "submission_date": "Submission date",
    "last_update_date": "Last update date", "organization_name": "Organization name",
    "contact_name": "Contact name", "email": "E-mail(s)", "country": "Country",
    "pmid": "PMID", "all_pmids": "All PMIDs", "pmcid": "PMCID", "all_pmcids": "All PMCIDs",
    "doi": "DOI", "all_dois": "All DOIs",
    "superseries": "SuperSeries, list GEO Series that are part of the SuperSeries",
}
extra_columns = ["dataset_doi", "px_accession", "related_geo_ids", "repository_data_type", "study_design", "study_focus",
                 "total_subjects", "reported_sample_counts", "keywords", "investigator_details",
                 "molecular_data_table", "release_date", "publication_count", "source_url",
                 "retrieved_at", "extraction_status", "review_status", "review_note"]


def clean(value):
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def join_values(values):
    """Keep distinct, nonblank values in the order the source reported them."""
    cleaned = [clean(value) for value in values]
    return "; ".join(dict.fromkeys(value for value in cleaned if value))


def put(record, evidence, field, value, section, url, method="repository field"):
    """Save a value together with the source that supports it. Keep real zeros."""
    if value is None or value == "":
        return
    record[field] = value
    evidence.append({"source": record["source"], "dataset_id": record["dataset_id"],
                     "field": field, "value": value, "source_section": section,
                     "source_url": url, "method": method})


def heading_block(soup, label):
    heading = next((tag for tag in soup.find_all(["h2", "h3"])
                    if tag.get_text(strip=True) == label), None)
    return heading.parent if heading else None


def get_publication_ids(soup):
    pmids, dois = [], []
    for link in soup.find_all("a", href=True):
        parsed = urlparse(link["href"])
        if "pubmed" in parsed.netloc or "/pubmed" in parsed.path:
            term = parse_qs(parsed.query).get("term", [""])[0]
            match = re.fullmatch(r"(\d+)(?:\[PMID\])?", term)
            if match:
                pmids.append(match[1])
            elif re.fullmatch(r"/\d+/?", parsed.path):
                pmids.append(parsed.path.strip("/"))
        if parsed.netloc.lower() in {"doi.org", "dx.doi.org"}:
            dois.append(parsed.path.lstrip("/"))
    dois.extend(re.findall(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", soup.get_text(" ", strip=True)))
    return list(dict.fromkeys(pmids)), list(dict.fromkeys(value.rstrip(".,);") for value in dois))


def add_publications(record, evidence, pmids, dois, section, url):
    for field, values in [("pmid", pmids), ("doi", dois)]:
        if values:
            put(record, evidence, "all_" + field + "s", join_values(values), section, url)
            put(record, evidence, field, values[0], section, url, "first listed identifier; all retained separately")


def extract_massive(record, evidence, soup, root):
    url = record["source_url"]
    header = soup.select_one("#titleHeader")
    if not header or record["dataset_id"] not in header.get_text():
        raise ValueError("MassIVE page header did not match the requested accession")
    put(record, evidence, "title", clean(header.find("h2").get_text()), "Dataset title", url)
    for label, field in [("Species", "organism"), ("Instrument", "instrument_model")]:
        block = heading_block(soup, label)
        if block:
            values = [clean(tag.get_text()) for tag in block.select("ul.metadata-list > li")]
            if field == "organism":
                values = [re.sub(r"\s*\(NCBITaxon:\d+\)", "", value) for value in values]
            put(record, evidence, field, join_values(values), label, url, "normalize whitespace and taxonomy labels")
    block = heading_block(soup, "Description")
    if block:
        text = clean(block.get_text(" ", strip=True))
        description = re.split(r"\[\s*(?:doi:|dataset license:)|Keywords:", text.removeprefix("Description "))[0].strip()
        put(record, evidence, "assay_description", description, "Description", url)
        keyword_match = re.search(r"Keywords:\s*(.*)", text)
        if keyword_match:
            put(record, evidence, "keywords", keyword_match[1], "Keywords", url)
            data_type = re.search(r"DatasetType:([^;]+)", keyword_match[1])
            if data_type:
                put(record, evidence, "data_type", data_type[1].strip(), "Keywords / DatasetType", url)
                put(record, evidence, "repository_data_type", data_type[1].strip(), "Keywords / DatasetType", url)
        dataset_dois = re.findall(r"\[\s*doi:([^\]\s]+)", text)
        put(record, evidence, "dataset_doi", join_values(dataset_dois), "Description / dataset DOI", url)
    px_ids = re.findall(r"\bPXD\d+\b", header.get_text(" ", strip=True))
    put(record, evidence, "px_accession", join_values(px_ids), "Dataset header / ProteomeXchange accession", url)
    contact = heading_block(soup, "Contact")
    if contact:
        row = next((row for row in contact.find_all("tr") if "Principal Investigators:" in row.get_text()), None)
        if row:
            detail = row.select_one("td.value")
            put(record, evidence, "investigator_details", clean(detail.get_text(" ", strip=True)), "Contact / principal investigators", url)
    publications = heading_block(soup, "Publications")
    if publications:
        pmids, dois = get_publication_ids(publications)
        add_publications(record, evidence, pmids, dois, "Publications", url)
    summary_path = root / "cache/massive" / (record["dataset_id"] + ".summary.json")
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        record["source_details"] = summary


def extract_dbgap(record, evidence, soup, search_metadata, root):
    url = record["source_url"]
    accession = soup.select_one("#study-id")
    if not accession or accession.get_text(strip=True) != record["dataset_id"]:
        raise ValueError("dbGaP page header did not match the requested accession")
    put(record, evidence, "title", clean(soup.select_one("#study-name").get_text()), "Study title", url)
    sections = {clean(tag.get_text()): tag.find_next_sibling("dd") for tag in soup.select("dl.report > dt")}
    block = sections.get("Study Description")
    if not block:
        raise ValueError("Study Description section missing")
    block = BeautifulSoup(str(block), "html.parser")
    for element in block.select("#important-links"):
        element.decompose()
    full_text = clean(block.get_text(" ", strip=True))
    subjects = re.search(r"Total number of consented subjects:\s*([\d,]+)", full_text)
    if subjects:
        put(record, evidence, "total_subjects", int(subjects[1].replace(",", "")), "Total number of consented subjects", url)
    study_design = next((item for item in block.find_all("li")
                         if item.get_text(" ", strip=True).startswith("Study Design:")), None)
    if study_design:
        put(record, evidence, "study_design", clean(study_design.get_text(" ", strip=True)).removeprefix("Study Design: "), "Study Design", url)
    for element in list(block.find_all("ul", recursive=True)):
        if element.parent and any(clean(element.get_text()).startswith(prefix)
                                  for prefix in ["Study Weblinks:", "Study Design:", "Study Type:"]):
            element.decompose()
    description = clean(block.get_text(" ", strip=True))
    put(record, evidence, "assay_description", description, "Study Description", url)
    criteria = sections.get('Study Inclusion/Exclusion Criteria')
    if criteria:
        put(record, evidence, 'characteristics', clean(criteria.get_text(' ', strip=True)),
            'Study Inclusion/Exclusion Criteria (study-level eligibility, not individual sample measurements)', url)
    if re.search(r"\bhuman\b", description, re.IGNORECASE):
        put(record, evidence, "organism", "Homo sapiens", "Study Description / explicit human reference", url, "normalize human to Homo sapiens")
    geo_ids = re.findall(r"\bGSE\d+\b", full_text)
    put(record, evidence, "related_geo_ids", join_values(geo_ids), "Study Weblinks", url)
    bioprojects = re.findall(r"\b(?:PRJ[A-Z]+\d+|SAM[NED][A-Z]*\d+)\b", full_text)
    put(record, evidence, "biosample_bioproject_id", join_values(bioprojects), "Study Description / linked identifiers", url)
    molecules = sections.get("Molecular Data")
    if molecules:
        rows = [[clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]
                for row in molecules.select("table tr")]
        put(record, evidence, "molecular_data_table", "\n".join(" | ".join(row) for row in rows), "Molecular Data", url)
        for row in rows[1:]:
            if len(row) >= 3 and row[0] in {"RNA Sequencing", "Whole Genome Sequencing", "Whole Exome Sequencing"}:
                put(record, evidence, "instrument_model", join_values([record["instrument_model"], row[1] + " " + row[2]]), "Molecular Data / sequencing source and platform", url)
    extract_dbgap_investigators(record, evidence, sections.get("Study Attribution"))
    search = search_metadata.get(record["dataset_id"], {})
    search_file = "../inputs/dbgap_search_metadata.json"
    for key, field in [("Study Molecular Data Type", "data_type"), ("Study Disease/Focus", "study_focus"),
                       ("Release Date", "release_date"), ("Study Content", "reported_sample_counts")]:
        value = search.get(key)
        if value and value != "Not Provided":
            put(record, evidence, field, clean(value), "Supplied search export / " + key, search_file, "saved search export; not independently refreshed")
            if field == "data_type":
                put(record, evidence, "repository_data_type", clean(value), "Supplied search export / " + key, search_file, "saved search export; not independently refreshed")
    extract_dbgap_publications(record, evidence, sections["Study Description"], root)
    extract_dbgap_linked(record, evidence, root)


def extract_dbgap_investigators(record, evidence, attribution):
    if not attribution:
        return
    label = next((tag for tag in attribution.find_all("b") if "Principal Investigator" in tag.get_text()), None)
    if not label:
        return

    url = record["source_url"]
    section = "Study Attribution / principal investigators"
    items = label.parent.select("ul > li")
    details = join_values(item.get_text(" ", strip=True) for item in items)
    put(record, evidence, "investigator_details", details, section, url)
    names, organizations, countries = [], [], []
    for item in items:
        lines = [clean(line) for line in item.get_text("\n").splitlines() if clean(line)]
        if len(lines) < 2:
            continue
        names.append(lines[0].rstrip("."))
        affiliation = " ".join(lines[1:]).rstrip(".")
        address = affiliation.rsplit(",", 3)
        # Only separate the country when the address explicitly gives one we recognize.
        if len(address) == 4 and address[-1].strip() in {"USA", "United States", "United States of America"}:
            organizations.append(address[0].strip())
            countries.append(address[-1].strip())
        else:
            organizations.append(affiliation)
    for field, values in [("contact_name", names), ("organization_name", organizations), ("country", countries)]:
        put(record, evidence, field, join_values(values), section, url,
            "Listed principal investigators used for contact fields; country only when explicit in affiliation")


def extract_dbgap_publications(record, evidence, description, root):
    """Combine publications from every cached reference page and the study description."""
    url = record["source_url"]
    references = sorted((root / "cache/dbgap").glob(record["dataset_id"] + ".references_*.html"))
    pmids, dois, count = [], [], None
    for path in references:
        reference = BeautifulSoup(path.read_bytes(), "html.parser")
        source = source_info(path)
        text = reference.get_text(" ", strip=True)
        match = re.search(r"There (?:are|is) (\d+) selected publication", text)
        if match:
            count = int(match[1])
        elif "There are no selected publications" in text:
            count = 0
        page_pmids, page_dois = get_publication_ids(reference)
        pmids.extend(page_pmids)
        dois.extend(page_dois)
        for field, values in [("all_pmids", page_pmids), ("all_dois", page_dois)]:
            put(record, evidence, field, join_values(values), "Selected Publications", source["response_url"])
    description_pmids, description_dois = get_publication_ids(BeautifulSoup(str(description), "html.parser"))
    pmids = list(dict.fromkeys(pmids + description_pmids))
    dois = list(dict.fromkeys(dois + description_dois))
    add_publications(record, evidence, pmids, dois, "Study Description and Selected Publications", url)
    put(record, evidence, "publication_count", count, "Selected Publications / repository count", url)


def extract_dbgap_linked(record, evidence, root):
    directory = root / 'cache/dbgap'
    manifest_path = directory / (record['dataset_id'] + '.linked_metadata.json')
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    if manifest['status'] != 'complete':
        raise ValueError('Linked dbGaP metadata retrieval is incomplete')

    fields, biosamples, experiments = read_sra_metadata(directory, manifest, record['dataset_id'])
    source = record['source_url']
    if experiments:
        query = parse_qs(urlparse(manifest['sra_link_source']['response_url']).query)
        source = 'https://www.ncbi.nlm.nih.gov/sra?LinkName=gap_sra_all&from_uid=' + query['id'][0]
    for field, values in fields.items():
        if field in {'data_processing', 'biosample_bioproject_id', 'characteristics'}:
            values = [record[field], *values]
        put(record, evidence, field, join_values(values), f'Complete linked SRA metadata ({len(experiments)} experiments)', source,
            'Distinct reported values across all linked experiments; protocols retain tissue labels; no specimen count inferred')
    if 'pubmed' in manifest:
        extract_pubmed_identifiers(record, evidence, directory, manifest['pubmed'])
    record['source_details'] = {'linked_metadata_manifest': str(manifest_path.relative_to(root)),
                                'sra_experiments_checked': len(experiments), 'biosample_ids': sorted(biosamples)}


def read_sra_metadata(directory, manifest, dataset_id):
    """Read every linked experiment and reject incomplete or mismatched batches."""
    fields = defaultdict(list)
    biosamples, experiments = set(), set()
    core_attributes = {'body site', 'histological type', 'analyte type', 'molecular data type', 'is tumor'}
    for batch in manifest['sra_batches']:
        packages = ElementTree.parse(directory / batch['file']).getroot().findall('EXPERIMENT_PACKAGE')
        if len(packages) != batch['count']:
            raise ValueError('Cached SRA batch count changed')
        for package in packages:
            experiment = package.find('EXPERIMENT')
            accession = experiment.get('accession')
            if accession in experiments:
                raise ValueError('Duplicate cached SRA experiment')
            experiments.add(accession)
            study_ids = [node.text for node in package.findall('./STUDY/IDENTIFIERS/EXTERNAL_ID[@namespace="dbGaP"]')]
            if dataset_id.split('.')[0] not in study_ids:
                raise ValueError('Linked SRA study does not match dbGaP accession')
            attributes = {clean(node.findtext('TAG')).lower(): clean(node.findtext('VALUE'))
                          for node in package.findall('./SAMPLE/SAMPLE_ATTRIBUTES/SAMPLE_ATTRIBUTE')}
            site = attributes.get('body site', 'Tissue not specified')
            # A study can include placenta and other tissues. Keep that context with the text.
            fields['characteristics'].extend(f'{site}: {tag}: {value}' for tag, value in attributes.items()
                                             if tag in core_attributes and value and tag != 'body site')
            fields['characteristics'].append(f'body site: {site}')
            fields['extracted_molecule'].append(attributes.get('analyte type', ''))
            paths = {'organism': './SAMPLE/SAMPLE_NAME/SCIENTIFIC_NAME',
                     'instrument_model': './EXPERIMENT/PLATFORM/*/INSTRUMENT_MODEL',
                     'library_strategy': './EXPERIMENT/DESIGN/LIBRARY_DESCRIPTOR/LIBRARY_STRATEGY',
                     'library_source': './EXPERIMENT/DESIGN/LIBRARY_DESCRIPTOR/LIBRARY_SOURCE',
                     'library_selection': './EXPERIMENT/DESIGN/LIBRARY_DESCRIPTOR/LIBRARY_SELECTION'}
            for field, path in paths.items():
                fields[field].extend(node.text or '' for node in package.findall(path))
            design = clean(experiment.findtext('./DESIGN/DESIGN_DESCRIPTION'))
            if design:
                fields['extraction_protocol'].append(f'{site}: {design}')
            for attribute in experiment.findall('./EXPERIMENT_ATTRIBUTES/EXPERIMENT_ATTRIBUTE'):
                tag, value = clean(attribute.findtext('TAG')).lower(), clean(attribute.findtext('VALUE'))
                if not value or value.lower() in {'none', 'n/a', 'not provided'}:
                    continue
                if tag == 'design description':
                    fields['extraction_protocol'].append(f'{site}: {value}')
                elif tag in {'alignment_software', 'data processing', 'data_processing'}:
                    fields['data_processing'].append(f'{tag}: {value}')
            fields['sra_study_id'].extend(node.get('accession', '') for node in package.findall('./STUDY'))
            fields['biosample_bioproject_id'].extend(node.text or '' for node in package.findall(
                './STUDY/IDENTIFIERS/EXTERNAL_ID[@namespace="BioProject"]'))
            fields['biosample_bioproject_id'].extend(node.findtext('VALUE', '') for node in package.findall(
                './STUDY/STUDY_ATTRIBUTES/STUDY_ATTRIBUTE') if node.findtext('TAG') == 'parent_bioproject')
            biosamples.update(node.text for node in package.findall('./SAMPLE/IDENTIFIERS/EXTERNAL_ID[@namespace="BioSample"]'))
            fields['file_types'].extend(node.get('filetype', '') for node in package.findall('./RUN_SET/RUN/CloudFiles/CloudFile'))
    if len(experiments) != manifest['sra_count']:
        raise ValueError('Cached SRA metadata is incomplete')
    return fields, biosamples, experiments


def extract_pubmed_identifiers(record, evidence, directory, publication_source):
    original_pmids = set(record['all_pmids'].split('; ')) - {''}
    original_dois = {value.lower() for value in record['all_dois'].split('; ') if value}
    ids = defaultdict(list)
    document = ElementTree.parse(directory / publication_source['file']).getroot()
    for article in document.findall('PubmedArticle'):
        identifiers = {node.get('IdType'): node.text for node in article.findall('./PubmedData/ArticleIdList/ArticleId')}
        pmid = article.findtext('./MedlineCitation/PMID')
        # A lookup result must match an identifier already linked by the study.
        if pmid not in original_pmids and identifiers.get('doi', '').lower() not in original_dois:
            raise ValueError('Publication lookup did not match a listed PMID or DOI')
        for kind, field in [('pubmed', 'all_pmids'), ('doi', 'all_dois'), ('pmc', 'all_pmcids')]:
            if identifiers.get(kind):
                ids[field].append(identifiers[kind])
    singular_fields = {'all_pmids': 'pmid', 'all_dois': 'doi', 'all_pmcids': 'pmcid'}
    for field, values in ids.items():
        combined = join_values([*record[field].split('; '), *values])
        put(record, evidence, field, combined, 'Linked publication identifiers / PubMed ArticleIdList',
            publication_source['response_url'], 'Only PMID/DOI-matched publication metadata; no paper-based answer extraction')
        put(record, evidence, singular_fields[field], combined.split('; ')[0],
            'First listed publication identifier', publication_source['response_url'])


def extract(root, dataset_ids=None):
    records = read_csv(root / "inputs/pilot_ids.csv")
    searches = json.loads((root / "inputs/dbgap_search_metadata.json").read_text())
    reviews = json.loads((root / "pilot_review.json").read_text())
    output, evidence, problems = [], [], []
    selected = set(dataset_ids) if dataset_ids else {item['dataset_id'] for item in records}
    if not selected <= {item['dataset_id'] for item in records}:
        raise ValueError('Requested IDs are not in the pilot list')
    saved = json.loads((root / 'outputs/pilot_results.json').read_text()) if dataset_ids else {}
    saved_rows = {row['dataset_id']: row for row in saved.get('metadata', [])}
    # A targeted update must leave every other record and its evidence untouched.
    evidence.extend(row for row in saved.get('field_sources', []) if row['dataset_id'] not in selected)
    fields = list(geo_columns) + extra_columns
    for item in records:
        if item['dataset_id'] not in selected:
            output.append(saved_rows[item['dataset_id']])
            continue
        record = dict.fromkeys(fields, "")
        record.update({key: item[key] for key in ["dataset_id", "source", "source_url"]})
        record["extraction_status"] = "failed"
        try:
            path = root / "cache" / item["source"] / (item["dataset_id"] + ".html")
            provenance = json.loads(path.with_suffix(".json").read_text())
            manifest_path = path.with_name(item['dataset_id'] + '.linked_metadata.json')
            if item['source'] == 'dbgap' and manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                path = path.with_name(manifest['page'])
                provenance = manifest['page_source']
            record["retrieved_at"] = provenance["retrieved_at"]
            soup = BeautifulSoup(path.read_bytes(), "html.parser")
            if item["source"] == "massive":
                extract_massive(record, evidence, soup, root)
            else:
                extract_dbgap(record, evidence, soup, searches, root)
            record["extraction_status"] = "extracted"
            review = reviews[item["dataset_id"]]
            record.update(review_status=review["status"], review_note=review["note"])
            if review.get('page_categories_checked'):
                record.setdefault('source_details', {})['page_categories_checked'] = True
            for update in review.get("fields", []):
                if clean(update["quote"]) not in clean(soup.get_text(" ", strip=True)):
                    raise ValueError("Reviewed quote not present in cached page: " + update["field"])
                put(record, evidence, update["field"], update["value"], update["quote"], item["source_url"], "reviewed public text")
            evidence[:] = [entry for entry in evidence if not (
                entry["dataset_id"] == record["dataset_id"] and entry["source"] == record["source"]
                and entry["field"] == "data_type" and entry["value"] != record["data_type"])]
        except (OSError, ValueError, KeyError, AttributeError) as error:
            record["extraction_status"] = "failed"
            problems.append({"dataset_id": item["dataset_id"], "error": str(error)})
        output.append(record)
    if dataset_ids and problems:
        # Keep the last saved results if any requested record could not be rebuilt.
        print(json.dumps({'errors': problems, 'saved_outputs_changed': False}, indent=2))
        return False
    directory = root / "outputs"
    directory.mkdir(exist_ok=True)
    write_csv(directory / "pilot_metadata.csv", [{key: row[key] for key in fields} for row in output])
    write_csv(directory / "pilot_field_sources.csv", evidence)
    mapping = []
    for field, heading in geo_columns.items():
        if field == "dataset_id":
            note = "Repository ID replaces GEO-only identifier."
        elif field == "source":
            note = "Repository name."
        else:
            note = "Same category; left blank when the pilot source does not provide a reliable match."
        mapping.append({"output_column": field, "original_geo_column": heading, "note": note})
    write_csv(directory / "field_mapping.csv", mapping)
    coverage = {}
    for source in ["massive", "dbgap"]:
        source_rows = [row for row in output if row["source"] == source]
        coverage[source] = {field: sum(row[field] != "" for row in source_rows) for field in fields}
    summary = {"selected": len(output), "extracted": sum(row["extraction_status"] == "extracted" for row in output),
               "errors": problems, "field_source_rows": len(evidence),
               "review_counts": {status: sum(row["review_status"] == status for row in output)
                                 for status in ["relevant", "needs_review", "likely_irrelevant"]},
               "field_coverage": coverage}
    (directory / "pilot_results.json").write_text(json.dumps({"metadata": output, "field_sources": evidence,
                                                              "mapping": mapping, "summary": summary}, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "field_coverage"}, indent=2))
    return not problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--ids', nargs='+', help='Update only these existing pilot records, preserving the others')
    args = parser.parse_args()
    raise SystemExit(0 if extract(args.root, args.ids) else 1)
