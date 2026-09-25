"""Map cached metabolomics metadata to the GEO categories with source records."""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from extract_pilot import add_publications, clean, extra_columns, geo_columns, join_values, put
from metadata_io import read_csv, source_info, write_csv


metabolomics_columns = ["sample_source", "collection_protocol", "treatment_protocol", "analysis_ids",
                       "sample_metadata_rows", "sample_count_reported", "sample_count_check", "assay_metadata_rows",
                       "sample_types", "sample_source_counts", "placenta_labeled_sample_rows",
                       "publication_titles", "contact_address", "metadata_version", "quality_notes"]
placeholder_values = {"", "na", "n/a", "not available", "not applicable", "-", "none", "null"}
placenta_labels = {"placenta", "mouse placenta"}


def text(value):
    return clean(BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True))


def present(value):
    return clean(value).lower() not in placeholder_values


def api_rows(value, id_key):
    """Workbench returns one record, a list, or a dictionary keyed by record ID."""
    if isinstance(value, list):
        return value
    if id_key in value:
        return [value]
    rows = list(value.values())
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Unexpected metadata response shape")
    return rows


def read_workbench_tables(soup):
    sections = []
    for table in soup.find_all("table"):
        fields = []
        for tr in table.find_all("tr"):
            # Nested tables are read separately, so their rows must not be counted twice.
            if tr.find_parent("table") is not table:
                continue
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) == 2 and not any(cell.find("table") for cell in cells):
                name, value = [clean(cell.get_text(" ", strip=True)) for cell in cells]
                if name:
                    fields.append((name.rstrip(":"), value))
        if fields and fields[0][0] in {"Study ID", "Project ID", "Subject ID", "Collection ID", "Treatment ID",
                                               "Sampleprep ID", "Analysis ID", "MS ID", "NMR ID", "Chromatography ID"}:
            sections.append((fields[0][0].removesuffix(" ID"), fields))
    return sections


def section_fields(sections, names):
    """Read labeled fields without dropping repeated labels or their section names."""
    for section, fields in sections:
        if section in names:
            for label, value in fields:
                yield section, label, value


def workbench(record, evidence, samples, raw_fields, root):
    accession = record["dataset_id"]
    directory = root / "cache/metabolomics_workbench"
    page = directory / (accession + ".html")
    info = source_info(page)
    url = info["response_url"]
    record.update(source_url=url, retrieved_at=info["retrieved_at"])
    soup = BeautifulSoup(page.read_bytes(), "html.parser")
    sections = read_workbench_tables(soup)
    if not any(section == "Study" and ("Study ID", accession) in values for section, values in sections):
        raise ValueError("Workbench study header mismatch")
    for section, fields in sections:
        for index, (field, value) in enumerate(fields, 1):
            raw_fields.append({"source": record["source"], "dataset_id": accession, "section": section,
                               "field_order": index, "field": field, "value": value, "source_url": url})

    def values(section, field):
        return [value for _, label, value in section_fields(sections, {section})
                if label == field and present(value)]

    for section, label, field in [
        ("Study", "Study Title", "title"), ("Study", "Study Summary", "assay_description"),
        ("Study", "Study Type", "study_design"), ("Subject", "Subject Species", "organism"),
        ("Study", "Analysis Type Detail", "data_type"), ("Study", "Institute", "organization_name"),
        ("Study", "Email", "email"), ("Study", "Address", "contact_address"),
        ("Study", "Submit Date", "submission_date"), ("Study", "Release Date", "release_date"),
        ("Study", "Raw Data File Type(s)", "file_types"), ("Study", "Publications", "publication_titles"),
        ("Collection", "Sample Type", "sample_source")]:
        put(record, evidence, field, join_values(values(section, label)), section + " / " + label, url)
    put(record, evidence, "contact_name", join_values(values("Study", "First Name") + values("Study", "Last Name")),
        "Study / First Name and Last Name; as submitted", url)
    contact_labels = {"First Name", "Last Name", "Institute", "Department", "Email", "Address"}
    contact_details = [f"{label}: {value}" for _, label, value in section_fields(sections, {"Study", "Project"})
                       if label in contact_labels]
    put(record, evidence, "investigator_details", "\n".join(contact_details),
        "Study and Project contact fields; roles retained", url)
    for section, field in [("Sampleprep", "extraction_protocol"), ("Collection", "collection_protocol"),
                            ("Treatment", "treatment_protocol")]:
        content = "\n".join(f"{label}: {value}" for _, label, value in section_fields(sections, {section})
                            if not label.endswith(" ID") and present(value))
        put(record, evidence, field, content, section + " / all populated protocol fields", url)
    instruments = [value for _, label, value in section_fields(sections, {"MS", "NMR"})
                   if label == "Instrument Name" and present(value)]
    put(record, evidence, "instrument_model", join_values(instruments), "MS and NMR / Instrument Name", url)
    processing = []
    for section, label, value in section_fields(sections, {"MS", "NMR", "Analysis"}):
        is_processing = any(word in label.lower() for word in ["processing", "software", "baseline", "normalization"])
        if is_processing and present(value):
            processing.append(f"{section} / {label}: {value}")
    put(record, evidence, "data_processing", "\n".join(processing), "MS, NMR and Analysis processing fields", url)
    characteristics = [f"{label}: {value}" for _, label, value in section_fields(sections, {"Subject"})
                       if label != "Subject ID" and present(value)]
    put(record, evidence, "characteristics", "\n".join(characteristics), "Subject / all populated fields", url)
    project_dois = re.findall(r"10\.\d{4,9}/[^\s,]+", join_values(values("Project", "Project DOI")))
    put(record, evidence, "dataset_doi", join_values(project_dois), "Project DOI; not publication DOI", url)
    publication_text = join_values(values("Study", "Publications"))
    dois = re.findall(r"10\.\d{4,9}/[^\s,]+", publication_text)
    pmids = re.findall(r"(?:PMID|pubmed(?:\s+id)?)[\s:]+(\d+)", publication_text, re.I)
    add_publications(record, evidence, pmids, dois, "Study / Publications", url)
    summary = json.loads((directory / (accession + ".summary.json")).read_text())
    if summary["study_id"] != accession:
        raise ValueError("Workbench summary accession mismatch")
    record["repository_data_type"] = summary.get("analysis_type", "")
    record["metadata_version"] = summary.get("version", "")
    if present(summary.get("revision_datetime", "")):
        put(record, evidence, "last_update_date", summary["revision_datetime"], "summary / revision_datetime",
            source_info(directory / (accession + ".summary.json"))["response_url"])
    extract_workbench_samples(record, evidence, samples, directory, summary)
    analysis_path = directory / (accession + ".analysis.json")
    analyses = api_rows(json.loads(analysis_path.read_text()), "analysis_id")
    put(record, evidence, "analysis_ids", join_values(item["analysis_id"] for item in analyses),
        "analysis / all analysis IDs", source_info(analysis_path)["response_url"])
    record["source_details"] = {"summary": summary, "analyses": analyses, "sections": sections}
    record["review_status"] = "needs_review"
    record["review_note"] = "Supplied placenta candidate. Verify cohort, tissue subsets, and independent biological sample counts."


def extract_workbench_samples(record, evidence, samples, directory, summary):
    """Keep every sample row, with tissue counts separate from biological sample size."""
    accession = record["dataset_id"]
    factors_path = directory / (accession + ".factors.json")
    factors = api_rows(json.loads(factors_path.read_text()), "local_sample_id")
    factor_url = source_info(factors_path)["response_url"]
    for index, item in enumerate(factors, 1):
        if item["study_id"] != accession:
            raise ValueError("Workbench factor accession mismatch")
        samples.append({"source": record["source"], "dataset_id": accession, "sample_row": index,
                        "sample_id": item.get("local_sample_id", ""), "organism": record["organism"],
                        "sample_source": item.get("sample_source", ""), "sample_type": "",
                        "metadata_json": json.dumps(item, ensure_ascii=False), "source_url": factor_url})
    tissue_counts = Counter(clean(item.get("sample_source", "")) for item in factors)
    put(record, evidence, "sample_source", join_values(tissue_counts), "factors / all sample_source values", factor_url)
    put(record, evidence, "sample_source_counts", "; ".join(f"{key}: {value}" for key, value in tissue_counts.items()),
        "factors / row counts by original tissue label", factor_url)
    put(record, evidence, "placenta_labeled_sample_rows", sum(n for tissue, n in tissue_counts.items() if tissue.lower() in placenta_labels),
        "factors / rows labeled placenta or mouse placenta", factor_url, "row count only; not independent biological specimens")
    put(record, evidence, "characteristics", record["characteristics"] + "\nSample factors: " +
        join_values(item.get("factors", "") for item in factors), "Subject and factors / complete distinct factors", factor_url)
    put(record, evidence, "sample_metadata_rows", len(factors), "factors / full returned row count", factor_url,
        "count sample metadata rows; not unique placentas or donors")
    reported = int(summary["number_of_samples"]) if summary.get("number_of_samples", "").isdigit() else ""
    put(record, evidence, "sample_count_reported", reported, "summary / number_of_samples",
        source_info(directory / (accession + ".summary.json"))["response_url"])
    record["sample_count_check"] = "matches" if reported == len(factors) else "needs_review"
    record["reported_sample_counts"] = f"{len(factors)} factor rows; summary number_of_samples={reported}; not placenta count"
    # The website calls these total subjects, but the API calls the same number samples.
    record["quality_notes"] = "Website Total Subjects is not treated as a donor or placenta count."


def table_rows(table):
    """Use the source column indexes, and stop if a row would lose or mislabel data."""
    columns = sorted(table.get("fields", {}).values(), key=lambda item: item["index"])
    headers = []
    for column in columns:
        header = column["header"]
        if column["fieldType"] != "basic":
            header = f"{column['fieldType']}[{header}]"
        headers.append(header)
    if len(headers) != len(set(headers)):
        raise ValueError("Duplicate ISA table headers require disambiguation")
    for row in table.get("data", []):
        if len(row) != len(headers):
            raise ValueError("ISA sample or assay row length mismatch")
        yield {header: row[column["index"]] for header, column in zip(headers, columns)}


def metabolights(record, evidence, samples, raw_fields, root):
    accession = record["dataset_id"]
    path = root / "cache/metabolights" / (accession + ".json")
    info = source_info(path)
    url = info["response_url"]
    data = json.loads(path.read_text())["content"]
    if data["studyIdentifier"] != accession or data["studyStatus"] != "PUBLIC":
        raise ValueError("MetaboLights public study identity mismatch")
    record.update(source_url="https://www.ebi.ac.uk/metabolights/" + accession, retrieved_at=info["retrieved_at"])
    for field, value, section in [
        ("title", data["title"], "title"), ("assay_description", text(data.get("description")), "description"),
        ("organism", join_values(item["organismName"] for item in data["organism"]), "organism / organismName"),
        ("sample_source", join_values(item["organismPart"] for item in data["organism"]), "organism / organismPart"),
        ("country", data.get("derivedData", {}).get("country", ""), "derivedData / country; submitter location"),
        ("study_design", join_values(item["name"] for item in data.get("factors", [])), "factors"),
        ("metadata_version", data.get("revisionNumber", ""), "revisionNumber")]:
        put(record, evidence, field, value, section, url)
    for field, key in [("submission_date", "studySubmissionDate"), ("release_date", "studyPublicReleaseDate"),
                       ("last_update_date", "updateDate")]:
        if data.get(key):
            put(record, evidence, field, datetime.fromtimestamp(data[key] / 1000, timezone.utc).date().isoformat(), key, url)
    contacts = data.get("contacts", [])
    for field, key in [("organization_name", "affiliation"), ("email", "email"), ("contact_address", "address")]:
        put(record, evidence, field, join_values(item.get(key, "") for item in contacts), "contacts / " + key, url)
    names, contact_details = [], []
    for contact in contacts:
        name_parts = [contact.get("firstName"), contact.get("midInitial"), contact.get("lastName")]
        names.append(" ".join(part for part in name_parts if part))
        contact_details.append("; ".join(f"{key}: {value}" for key, value in contact.items() if present(value)))
    put(record, evidence, "contact_name", join_values(names), "contacts / names", url)
    put(record, evidence, "investigator_details", "\n".join(contact_details), "contacts / complete attribution", url)
    protocols = data.get("protocols", [])
    for index, item in enumerate(protocols, 1):
        raw_fields.append({"source": record["source"], "dataset_id": accession, "section": "protocols",
                           "field_order": index, "field": item["name"], "value": text(item.get("description")), "source_url": url})
    for field, names in [("extraction_protocol", {"extraction"}), ("collection_protocol", {"sample collection"}),
                         ("treatment_protocol", {"treatment"}),
                         ("data_processing", {"data transformation", "metabolite identification", "normalization"})]:
        put(record, evidence, field, "\n".join(item["name"] + ": " + text(item.get("description"))
            for item in protocols if item["name"].lower() in names and present(text(item.get("description")))),
            "protocols / " + ", ".join(sorted(names)), url)
    publications = data.get("publications", [])
    add_publications(record, evidence, [clean(p["pubmedId"]) for p in publications if present(p.get("pubmedId", ""))],
                     [clean(p["doi"]) for p in publications if present(p.get("doi", ""))], "publications", url)
    put(record, evidence, "publication_count", len(publications), "publications / record count", url)
    put(record, evidence, "publication_titles", join_values(p.get("title", "") for p in publications), "publications / titles", url)
    extract_metabolights_samples(record, evidence, samples, data, url)
    record["sample_count_check"] = "not_independently_verified"
    record["quality_notes"] = "Source sample and assay counts are retained without inferring independent placentas."
    record["review_status"] = "needs_review"
    record["review_note"] = "Candidate retrieved by supplied search terms. Review organism, tissue and biological replicate structure."
    record["source_details"] = data


def extract_metabolights_samples(record, evidence, samples, data, url):
    """Read the full sample and assay tables, including controls and repeated measurements."""
    accession = record["dataset_id"]
    all_samples = list(table_rows(data.get("sampleTable", {})))
    for index, item in enumerate(all_samples, 1):
        samples.append({"source": record["source"], "dataset_id": accession, "sample_row": index,
                        "sample_id": item.get("Sample Name", ""), "organism": item.get("Characteristics[Organism]", ""),
                        "sample_source": item.get("Characteristics[Organism part]", ""),
                        "sample_type": item.get("Characteristics[Sample type]", ""),
                        "metadata_json": json.dumps(item, ensure_ascii=False), "source_url": url})
    put(record, evidence, "sample_metadata_rows", len(all_samples), "sampleTable / full returned row count", url,
        "count metadata rows; includes controls and repeated measurements where deposited")
    characteristics = {}
    for item in all_samples:
        for field, value in item.items():
            if field.startswith(("Characteristics[", "Factor Value[")) and present(value):
                characteristics.setdefault(field, []).append(value)
    put(record, evidence, "characteristics", "\n".join(f"{key}: {join_values(values)}" for key, values in characteristics.items()),
        "sampleTable / distinct characteristic and factor values", url)
    put(record, evidence, "sample_types", join_values(characteristics.get("Characteristics[Sample type]", [])),
        "sampleTable / sample type", url)
    tissue_counts = Counter(clean(item.get("Characteristics[Organism part]", "")) for item in all_samples)
    put(record, evidence, "sample_source_counts", "; ".join(f"{key}: {value}" for key, value in tissue_counts.items()),
        "sampleTable / row counts by original tissue label", url)
    put(record, evidence, "placenta_labeled_sample_rows", sum(n for tissue, n in tissue_counts.items() if tissue.lower() in placenta_labels),
        "sampleTable / rows labeled placenta or mouse placenta", url, "row count only; not independent biological specimens")
    assays = data.get("assays", [])
    assay_rows = [row for assay in assays for row in table_rows(assay.get("assayTable", {}))]
    put(record, evidence, "assay_metadata_rows", len(assay_rows), "assays / full returned row count", url)
    put(record, evidence, "analysis_ids", join_values(a.get("fileName", "") for a in assays), "assays / fileName", url)
    put(record, evidence, "data_type", join_values(a.get("technology", "") for a in assays), "assays / technology", url)
    record["repository_data_type"] = record["data_type"]
    instruments, files = [], []
    for row in assay_rows:
        for field, value in row.items():
            if field.lower() in {"parameter value[instrument]", "parameter value[nmr instrument]"}:
                instruments.append(value)
            if "file" in field.lower() and present(value):
                files.append(str(value))
    put(record, evidence, "instrument_model", join_values(instruments), "assayTable / instrument", url)
    put(record, evidence, "file_types", join_values("".join(Path(value).suffixes) for value in files), "assayTable / file suffixes", url)
    record["reported_sample_counts"] = f"{len(all_samples)} sample-table rows; {len(assay_rows)} assay rows; not independent placenta count"


def field_status(record, field):
    """Explain a blank only as far as the sources checked for that record allow."""
    if record.get(field, "") != "":
        return "captured", "Value populated; see field_sources and retained metadata."
    if record['source'] == 'dbgap' and record.get('source_details', {}).get('page_categories_checked'):
        if field in {'platform_id', 'superseries'}:
            return 'no_direct_equivalent', 'GEO-specific category. Do not substitute an SRA instrument or a dbGaP version history.'
        if field == 'sample_size_placenta':
            return 'needs_review', 'Subject and public sample-record counts are available but do not explicitly establish independent placenta count.'
        if field in {'pmcid', 'all_pmcids'}:
            return 'not_listed_by_pubmed', 'No PMCID in the matched PubMed identifier records; this is not a claim that full text is unavailable.'
        if field in {'submission_date', 'last_update_date'}:
            return 'not_found_in_checked_sources', 'No matching dbGaP date in the checked page/version history. SRA run publication dates are different dates.'
        return 'not_found_in_checked_sources', 'Not found in the checked dbGaP page, complete linked SRA metadata, or matched publication identifiers; other sources may contain it.'
    if record["source"] in {"massive", "dbgap"}:
        return "not_assessed", "Earlier pilot did not resolve why this field is blank; this is not a missing-data finding."
    if record["extraction_status"] == "failed":
        return "extraction_failed", "Study extraction failed; see extraction errors."
    if field in {"library_strategy", "library_source", "library_selection", "platform_id", "superseries"}:
        return "not_applicable", "GEO sequencing-library/platform/series field has no direct counterpart in this metabolomics record."
    if field in {"sample_size_placenta", "extracted_molecule"}:
        return "needs_review", "Source text or sample metadata require interpretation; do not substitute row counts or infer an analyte."
    if field in {"sra_study_id", "biosample_bioproject_id", "pmcid", "all_pmcids"}:
        return "not_resolved", "Linked identifier lookup not implemented for this pilot."
    if field == "country" and record["source"] == "metabolomics_workbench":
        return "not_mapped", "Contact address retained; country not inferred from address."
    return "not_reported_in_mapped_fields", "No populated value in the specific mapped fields; other text or linked records may contain it."


def extract(root):
    selected = read_csv(root / "inputs/metabolomics_pilot_ids.csv")
    fields = list(geo_columns) + extra_columns + metabolomics_columns
    records, evidence, samples, raw_fields, failures = [], [], [], [], []
    for row in selected:
        record = dict.fromkeys(fields, "")
        record.update(source=row["source"], dataset_id=row["dataset_id"], extraction_status="failed")
        try:
            extractor = workbench if row["source"] == "metabolomics_workbench" else metabolights
            extractor(record, evidence, samples, raw_fields, root)
            record["extraction_status"] = "extracted"
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            failures.append({"source": row["source"], "dataset_id": row["dataset_id"], "error": str(error)})
        records.append(record)
    previous = json.loads((root / "outputs/pilot_results.json").read_text())
    combined = [{**dict.fromkeys(fields, ""), **row} for row in previous["metadata"]] + records
    statuses, coverage = summarize_fields(combined)
    output = root / "outputs"
    write_csv(output / "four_repository_metadata.csv", [{k: row[k] for k in fields} for row in combined])
    write_csv(output / "four_repository_field_sources.csv", previous["field_sources"] + evidence)
    write_csv(output / "four_repository_field_status.csv", statuses)
    write_csv(output / "four_repository_field_coverage.csv", coverage)
    write_csv(output / "metabolomics_samples.csv", samples)
    write_csv(output / "metabolomics_source_fields.csv", raw_fields)
    result = {"metadata": combined, "field_sources": previous["field_sources"] + evidence, "coverage": coverage,
              "sample_rows": len(samples), "source_fields": len(raw_fields), "extraction_errors": failures}
    (output / "four_repository_results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"new_studies": len(records), "combined_studies": len(combined),
                      "sample_metadata_rows": len(samples), "errors": failures}, indent=2))
    return not failures


def summarize_fields(records):
    """Build per-study explanations and repository counts from the same field checks."""
    statuses = []
    for record in records:
        for field in geo_columns:
            if field == "source":
                continue
            status, reason = field_status(record, field)
            statuses.append({"source": record["source"], "dataset_id": record["dataset_id"],
                             "field": field, "status": status, "reason": reason})
    coverage = []
    for source in dict.fromkeys(row["source"] for row in records):
        count = sum(row["source"] == source for row in records)
        for field in geo_columns:
            if field == "source":
                continue
            counts = Counter(row["status"] for row in statuses if row["source"] == source and row["field"] == field)
            coverage.append({"source": source, "field": field, "original_sheet_column": geo_columns[field],
                             "studies_checked": count, "captured": counts.get("captured", 0),
                             "not_populated": count - counts.get("captured", 0),
                             "blank_reasons": "; ".join(f"{key}: {value}" for key, value in counts.items() if key != "captured")})
    return statuses, coverage


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    raise SystemExit(0 if extract(args.root) else 1)
