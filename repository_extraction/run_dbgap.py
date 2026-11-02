"""Extract public metadata for every input dbGaP study, without AI or pilot overrides.

Run python run_dbgap.py, or add --retry-failed to retry incomplete studies only.
Successful responses are cached. No experimental
files are downloaded. The original 31 columns are preserved in dbgap_metadata.csv.
For dbGaP, the existing Submission date column contains the reported release date.
The raw JSON and details CSV keep its original release_date name. Deposited methods
and paired contacts remain in the detailed outputs.
"""

import argparse
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from extract_pilot import clean, geo_columns, get_publication_ids, join_values
from metadata_io import read_csv, write_csv


output_fields = (
    "dataset_id", "data_type", "superseries", "sample_size_placenta", "title", "organism",
    "characteristics", "extracted_molecule", "extraction_protocol", "library_strategy",
    "library_source", "library_selection", "instrument_model", "assay_description",
    "data_processing", "platform_id", "sra_study_id", "biosample_bioproject_id", "file_types",
    "submission_date", "last_update_date", "organization_name", "contact_name", "email",
    "country", "pmid", "all_pmids", "pmcid", "all_pmcids", "doi", "all_dois",
)
api_url = "https://dbgap.ncbi.nlm.nih.gov/beta/api/"
eutils_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
country_names = {"USA", "United States", "United States of America", "Japan", "France",
                 "Germany", "Canada", "United Kingdom", "Australia", "China", "Sweden"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n")
    temporary.replace(path)


def read_inputs(path, selected=None):
    rows = read_csv(path)
    ids = [row["dataset_id"].strip() for row in rows]
    if not ids or any(not re.fullmatch(r"phs\d{6}\.v\d+\.p\d+", value) for value in ids):
        raise ValueError("Input must contain versioned dbGaP study accessions")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate input study IDs")
    if selected and not set(selected) <= set(ids):
        raise ValueError("Selected study is not in the input list")
    return [dict(row, dataset_id=accession,
                 source_url=f"https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id={accession}")
            for row, accession in zip(rows, ids)
            if not selected or accession in selected]


def xml_document(raw):
    document = ElementTree.fromstring(raw)
    errors = document.findall(".//ERROR")
    if errors:
        raise ValueError("; ".join(node.text or "" for node in errors))
    return document


def api_document(raw):
    document = json.loads(raw)
    if document.get("message") != "OK" or not isinstance(document.get("data"), dict):
        raise ValueError("Expected a successful dbGaP public metadata response")
    return document["data"]


def page_document(raw, accession):
    soup = BeautifulSoup(raw, "html.parser")
    header = soup.select_one("#study-id")
    if header is None or header.get_text(strip=True) != accession:
        raise ValueError("Study page does not match the requested accession/version")
    if not soup.select_one("#study-name"):
        raise ValueError("Study title is missing")
    return soup


def reference_document(raw):
    soup = BeautifulSoup(raw, "html.parser")
    if soup.select_one("#reference-list") is None:
        raise ValueError("Publication list is missing")
    return soup


def reference_page_numbers(soup):
    """Legacy dbGaP uses clickable spans as well as links for pagination."""
    pages = set()
    for tag in soup.find_all(attrs={"onclick": True}):
        pages.update(int(value) for value in re.findall(
            r"updateReferences\([^,]+,[^,]+,\s*['\"]?(\d+)", tag["onclick"]))
    return pages


def molecular_availability(raw, accession):
    """Read the explicit counts used by dbGaP to show or hide the molecular tab."""
    soup = BeautifulSoup(raw, "html.parser")
    scripts = "\n".join(node.get_text() for node in soup.find_all("script"))
    study = re.search(r'window\.accession\s*=\s*("[^"\\]+")\s*;', scripts)
    counts = re.search(r"window\.studyCounts\s*=\s*(\{[^{}]*\})\s*;", scripts)
    if study is None or json.loads(study[1]) != accession or counts is None:
        raise ValueError("Study availability page is missing or belongs to another version")
    # The page embeds a flat JavaScript object with unquoted keys, not JSON.
    data = json.loads(re.sub(r'([{,])\s*([a-z_]+)\s*:', r'\1"\2":', counts[1]))
    if type(data.get("molecular_count")) is not int or data["molecular_count"] < 0:
        raise ValueError("Molecular dataset count is missing or invalid")
    return data


def pending_access(raw):
    soup = BeautifulSoup(raw, "html.parser")
    body = soup.select_one("#restricted-access-body")
    text = clean(body.get_text(" ")) if body else ""
    if text.rstrip(".").casefold() != "individual level data will be coming soon":
        raise ValueError("Classic access page does not explicitly confirm pending data")
    return text


def fetch_response(session, path, url, parser, params=None, offline=False, refresh=False):
    """Validate before saving; never replace a valid response with an error page."""
    requested_url = requests.Request("GET", url, params=params).prepare().url
    provenance = path.with_name(path.name + ".source.json")
    if not refresh and path.exists() and provenance.exists():
        try:
            raw = path.read_bytes()
            info = json.loads(provenance.read_text())
            old, new = urlparse(info["response_url"]), urlparse(requested_url)
            if (old.scheme, old.netloc, old.path, parse_qs(old.query)) == (
                    new.scheme, new.netloc, new.path, parse_qs(new.query)):
                if hashlib.sha256(raw).hexdigest() == info["sha256"]:
                    return parser(raw), info
        except (OSError, ValueError, KeyError, ElementTree.ParseError):
            # A damaged or incompatible cache can be retrieved again online.
            pass
    if offline:
        raise ValueError("No validated cache for " + path.name)
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=(10, 60))
            response.raise_for_status()
            parsed = parser(response.content)
            info = {"response_url": response.url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(response.content).hexdigest(), "bytes": len(response.content)}
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            write_json(provenance, info)
            time.sleep(0.4)
            return parsed, info
        except requests.RequestException as error:
            status = error.response.status_code if error.response is not None else None
            if status == 429 or (status is not None and status < 500) or attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))


def add_value(result, field, value, section, url):
    if value is None or value == "":
        return
    result["metadata"][field] = value
    result["field_sources"].append({"dataset_id": result["metadata"]["dataset_id"],
        "field": field, "value": value, "source_section": section, "source_url": url})


def parse_contacts(data):
    groups = data.get("study_attribution", {})
    if not isinstance(groups, dict):
        raise ValueError("Unexpected investigator attribution structure")
    contacts = []
    for label, people in groups.items():
        if "principal investigator" not in label.lower():
            continue
        for person in people:
            name, affiliation = clean(person.get("piName")), clean(person.get("piInstitution"))
            tail = affiliation.rstrip(".").rsplit(",", 1)[-1].strip()
            contacts.append({"name": name, "affiliation": affiliation,
                             "country": tail if tail in country_names else ""})
    return contacts


def linked_uid(page, link_name):
    for link in page.find_all("a", href=True):
        query = {key.lower(): value for key, value in parse_qs(urlparse(link["href"]).query).items()}
        if query.get("linkname") == [link_name]:
            uid = query.get("from_uid", [""])[0]
            if uid.isdigit():
                return uid
    return None


def parse_bioproject(raw, ids, accession):
    document = xml_document(raw)
    projects = document.findall("DocumentSummary")
    if document.tag != "RecordSet" or {p.get("uid") for p in projects} != set(ids) or len(projects) != len(ids):
        raise ValueError("Incomplete or mismatched BioProject response")
    records = []
    for project in projects:
        archive = project.find("./Project/ProjectID/ArchiveID")
        if archive is None or not archive.get("accession"):
            raise ValueError("BioProject accession is missing")
        linked = [n.text for n in project.findall("./Project/ProjectDescr/ExternalLink/dbXREF[@db='dbGaP']/ID")]
        centers = [n.text or "" for n in project.findall("./Project/ProjectID/CenterID")]
        study = accession.split(".")[0]
        matches = study in linked or any(re.search(r"(?:^|_)" + study + r"$", value) for value in centers)
        records.append({"accession": archive.get("accession"), "matches_study": matches,
            "organism": join_values(n.text for n in project.findall("./Project/ProjectType/*//OrganismName")),
            "data_type": join_values(n.text for n in project.findall("./Project/ProjectType/*/ProjectDataTypeSet/DataType"))})
    return records


def parse_sra(document, accession, expected_count):
    packages = document.findall("EXPERIMENT_PACKAGE")
    if document.tag != "EXPERIMENT_PACKAGE_SET" or len(packages) != expected_count:
        raise ValueError("SRA response did not contain the complete requested batch")
    for package in packages:
        linked = [node.text for node in package.findall(
            "./STUDY/IDENTIFIERS/EXTERNAL_ID[@namespace='dbGaP']")]
        if accession.split(".")[0] not in linked:
            raise ValueError("SRA record is not linked to the requested dbGaP study")
        if package.find("EXPERIMENT") is None or package.find("SAMPLE") is None:
            raise ValueError("SRA experiment or sample is missing")
    return packages


def collect_sra(packages, fields, samples, experiments, methods):
    paths = {"organism": "./SAMPLE/SAMPLE_NAME/SCIENTIFIC_NAME",
             "instrument_model": "./EXPERIMENT/PLATFORM/*/INSTRUMENT_MODEL",
             "library_strategy": "./EXPERIMENT/DESIGN/LIBRARY_DESCRIPTOR/LIBRARY_STRATEGY",
             "library_source": "./EXPERIMENT/DESIGN/LIBRARY_DESCRIPTOR/LIBRARY_SOURCE",
             "library_selection": "./EXPERIMENT/DESIGN/LIBRARY_DESCRIPTOR/LIBRARY_SELECTION"}
    for package in packages:
        experiment = package.find("EXPERIMENT").get("accession")
        sample = package.find("SAMPLE").get("accession")
        if not experiment or not sample or experiment in experiments:
            raise ValueError("Missing or repeated SRA accession")
        experiments.add(experiment)
        attributes = defaultdict(list)
        for node in package.findall("./SAMPLE/SAMPLE_ATTRIBUTES/SAMPLE_ATTRIBUTE"):
            attributes[clean(node.findtext("TAG")).lower()].append(clean(node.findtext("VALUE")))
        site = join_values(attributes.get("body site", []) + attributes.get("tissue", []))
        samples.setdefault(sample, set()).add(site)
        for tag in ("body site", "tissue", "histological type", "analyte type", "molecular data type", "is tumor"):
            for value in attributes[tag]:
                if value:
                    fields["characteristics"].add(f"{site or 'Tissue not specified'}: {tag}: {value}")
        fields["extracted_molecule"].update(attributes["analyte type"])
        for field, path in paths.items():
            fields[field].update(clean(node.text) for node in package.findall(path))
        design = clean(package.findtext("./EXPERIMENT/DESIGN/DESIGN_DESCRIPTION"))
        if design:
            methods.add((site, design))
        for node in package.findall("./EXPERIMENT/EXPERIMENT_ATTRIBUTES/EXPERIMENT_ATTRIBUTE"):
            tag, value = clean(node.findtext("TAG")).lower(), clean(node.findtext("VALUE"))
            if value.lower() in {"", "n/a", "none", "not provided"}:
                continue
            if tag in {"data_processing", "data processing", "alignment_software"}:
                fields["data_processing"].add(f"{site or 'Tissue not specified'}: {tag}: {value}")
            elif tag in {"extraction protocol", "extraction_protocol"}:
                fields["extraction_protocol"].add(f"{site or 'Tissue not specified'}: {value}")
            elif tag == "design description":
                methods.add((site, value))
        fields["sra_study_id"].update(n.get("accession", "") for n in package.findall("./STUDY"))
        for namespace, path in (("BioProject", "STUDY"), ("BioSample", "SAMPLE")):
            fields["biosample_bioproject_id"].update(clean(n.text) for n in package.findall(
                f"./{path}/IDENTIFIERS/EXTERNAL_ID[@namespace='{namespace}']"))
        fields["file_types"].update(n.get("filetype", "") for n in package.findall("./RUN_SET/RUN/CloudFiles/CloudFile"))


def parse_pubmed(raw, pmids):
    document = xml_document(raw)
    articles = list(document)
    returned = [article.findtext("./MedlineCitation/PMID") or article.findtext("./BookDocument/PMID")
                for article in articles]
    if document.tag != "PubmedArticleSet" or set(returned) != set(pmids) or len(returned) != len(pmids):
        raise ValueError("PubMed returned an incomplete or mismatched publication set")
    records = {}
    for article in articles:
        is_book = article.tag == "PubmedBookArticle"
        citation_path = "./BookDocument" if is_book else "./MedlineCitation"
        data_path = "./PubmedBookData" if is_book else "./PubmedData"
        author_path = citation_path + ("/AuthorList/Author" if is_book else "/Article/AuthorList/Author")
        pmid = article.findtext(citation_path + "/PMID")
        # Book chapters contain references with their own IDs; use only this record's IDs.
        identifiers = {node.get("IdType"): node.text or "" for node in article.findall(data_path + "/ArticleIdList/ArticleId")}
        if identifiers.get("pubmed", pmid) != pmid:
            raise ValueError("PubMed article identifiers disagree")
        contacts = []
        for author in article.findall(author_path):
            name = clean(" ".join(filter(None, [author.findtext("ForeName"), author.findtext("LastName")])))
            for node in author.findall("./AffiliationInfo/Affiliation"):
                affiliation = "".join(node.itertext())
                for email in re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", affiliation):
                    contacts.append({"name": name, "email": email, "affiliation": affiliation, "pmid": pmid})
        records[pmid] = {"pmid": pmid, "doi": identifiers.get("doi", ""),
                         "pmcid": identifiers.get("pmc", ""), "contacts": contacts}
    return [records[pmid] for pmid in pmids]


def extract_study(session, row, root, offline=False, refresh=False):
    accession = row["dataset_id"]
    directory = root / "cache/dbgap"
    result = {"metadata": dict.fromkeys(output_fields, ""), "components": {}, "field_sources": [], "details": {}}
    result["metadata"].update(dataset_id=accession, extraction_status="partial")
    blocked = False

    def get(name, url, parser, params=None, suffix="xml"):
        nonlocal blocked
        if blocked:
            result["components"][name] = {"status": "not_checked", "reason": "Rate limited; no more requests sent"}
            return None
        path = directory / f"{accession}.{name}.{suffix}"
        try:
            value, info = fetch_response(session, path, url, parser, params, offline, refresh)
            result["components"][name] = {"status": "retrieved", "cache_file": str(path), **info}
            return value
        except (requests.RequestException, ValueError, OSError, KeyError, ElementTree.ParseError) as error:
            response = error.response if isinstance(error, requests.RequestException) else None
            status = response.status_code if response is not None else None
            result["components"][name] = {"status": "failed", "error": str(error), "http_status": status,
                "response_url": response.url if response is not None else requests.Request("GET", url, params=params).prepare().url,
                "retry_after": response.headers.get("Retry-After", "") if response is not None else ""}
            blocked = status == 429
            print(f"  {name}: {error}", flush=True)
            return None

    def source(name):
        return result["components"][name]["response_url"]

    def put(field, value, section, url):
        add_value(result, field, value, section, url)

    page = get("page_review", row["source_url"], lambda raw: page_document(raw, accession), suffix="html")
    if page is None:
        result["metadata"]["extraction_status"] = "failed"
        return result
    sections = {clean(n.get_text()): n.find_next_sibling("dd") for n in page.select("dl.report > dt")}
    put("title", clean(page.select_one("#study-name").get_text()), "Study title", source("page_review"))
    description = sections.get("Study Description")
    if description:
        copy = BeautifulSoup(str(description), "html.parser")
        for node in copy.select("#important-links"):
            node.decompose()
        put("assay_description", clean(copy.get_text(" ", strip=True)), "Full study description, not an assay-specific protocol", source("page_review"))
    molecular = get("molecular", api_url + f"molecular/{accession}/", api_document, suffix="json")
    if molecular is None and (offline or result["components"]["molecular"].get("http_status") == 404):
        availability = get("availability", f"https://dbgap.ncbi.nlm.nih.gov/beta/study/{accession}/",
                           lambda raw: molecular_availability(raw, accession), suffix="html")
        if availability is not None:
            result["details"]["page_dataset_counts"] = availability
            if availability["molecular_count"] == 0:
                result["details"]["molecular_counts"] = []
                result["components"]["molecular"].update(status="not_reported",
                    reason="The study page explicitly lists zero molecular datasets", confirmation_url=source("availability"))
    if molecular is not None:
        result["details"]["molecular_counts"] = molecular.get("datasets", [])
        types = [item.get("sample_use", "") for item in molecular.get("datasets", []) if item.get("study") == accession]
        put("data_type", join_values(types), "Explicit molecular sample-use labels; counts are not summed", source("molecular"))
    table = sections.get("Molecular Data")
    if table:
        rows = [[clean(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])] for tr in table.select("tr")]
        result["details"]["molecular_table"] = rows
        labels = [r[0] for r in rows[1:] if r]
        put("data_type", join_values([result["metadata"]["data_type"], *labels]), "Molecular Data table and molecular sample-use labels", source("page_review"))
    attribution = get("attribution", api_url + f"study/{accession}/attribution/", api_document, suffix="json")
    if attribution is not None:
        contacts = parse_contacts(attribution)
        result["details"]["investigators"] = contacts
        for field, key in (("contact_name", "name"), ("organization_name", "affiliation"), ("country", "country")):
            put(field, join_values(p[key] for p in contacts), "Principal investigators; organization preserves the full listed affiliation", source("attribution"))
    access = get("access", api_url + f"study/{accession}/authorized-access/", api_document, suffix="json")
    file_types = []
    if access is None and (offline or result["components"]["access"].get("http_status") in {404, 500, 502, 503, 504}):
        pending = get("access_notice", "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/GetRestrictedAccess.cgi",
                      pending_access, {"study_id": accession}, "html")
        if pending:
            result["details"]["access_notice"] = pending
            result["components"]["access"].update(status="not_reported", reason=pending,
                confirmation_url=source("access_notice"))
    if access is not None:
        info = access.get("study_info") or {}
        result["details"]["release_date"] = info.get("release_date", "")
        result["details"]["access_contacts"] = info.get("consent_group", [])
        resources = info.get("datasets", []) + info.get("genotype_components", []) + info.get("analyses", [])
        result["details"]["listed_resources"] = resources
        file_types = [r.get("content_type", "") for r in resources]
        file_types.extend("".join(Path(r.get("name", "")).suffixes[-2:]) if r.get("name", "").endswith(".gz")
                          else Path(r.get("name", "")).suffix for r in resources)
        put("file_types", join_values(file_types), "Public resource manifest labels and filename extensions; no files downloaded", source("access"))
        put("release_date", info.get("release_date", ""), "Release date (not submission or update date)", source("access"))

    bioproject_uid = linked_uid(page, "gap_bioproject")
    if bioproject_uid:
        links = get("bioproject_links", eutils_url + "elink.fcgi", xml_document,
                    {"dbfrom": "gap", "db": "bioproject", "id": bioproject_uid, "linkname": "gap_bioproject", "retmode": "xml"})
        ids = [n.text for n in links.findall('.//LinkSetDb[DbTo="bioproject"]/Link/Id')] if links is not None else []
        if ids:
            projects = get("bioproject", eutils_url + "efetch.fcgi", lambda raw: parse_bioproject(raw, ids, accession),
                           {"db": "bioproject", "id": ",".join(ids), "retmode": "xml"})
            if projects is not None:
                result["details"]["linked_bioprojects"] = projects
                matched = [p for p in projects if p["matches_study"]]
                put("biosample_bioproject_id", join_values(p["accession"] for p in matched),
                    "Linked BioProjects with an explicit matching dbGaP study identifier; parent projects excluded", source("bioproject"))
                for field in ("organism", "data_type"):
                    if not result["metadata"][field]:
                        put(field, join_values(p[field] for p in matched), "Explicit field from study-matched BioProjects", source("bioproject"))
    else:
        result["components"]["bioproject_links"] = {"status": "not_linked"}

    uid = linked_uid(page, "gap_sra_all")
    fields, samples, experiments, methods = defaultdict(set), {}, set(), set()
    sra_complete = True

    def read_sra_batches(ids, prefix):
        for start in range(0, len(ids), 200):
            selected = ids[start:start + 200]
            name = f"{prefix}_{start}"
            packages = get(name, eutils_url + "efetch.fcgi",
                           lambda raw: parse_sra(xml_document(raw), accession, len(selected)),
                           {"db": "sra", "id": ",".join(selected), "retmode": "xml"})
            if packages is None:
                return name
            collect_sra(packages, fields, samples, experiments, methods)
            print(f"  SRA metadata: {len(experiments)}/{len(ids)} experiments", flush=True)
        return None

    if uid and uid.isdigit():
        links = get("sra_links", eutils_url + "elink.fcgi", xml_document,
                    {"dbfrom": "gap", "db": "sra", "id": uid, "linkname": "gap_sra_all", "retmode": "xml"})
        sra_complete = links is not None
        ids = [n.text for n in links.findall('.//LinkSetDb[DbTo="sra"]/Link/Id')] if links is not None else []
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate linked SRA UIDs")
        result["details"]["sra_experiments_expected"] = len(ids) if links is not None else None
        sra_url = f"https://www.ncbi.nlm.nih.gov/sra?LinkName=gap_sra_all&from_uid={uid}"
        failed_batch = read_sra_batches(ids, "sra") if links is not None else None
        sra_complete = sra_complete and failed_batch is None
        known_study_search = offline and (directory / f"{accession}.sra_search_0.xml").exists()
        if failed_batch and (known_study_search or result["components"][failed_batch].get("error") == "SRA record is not linked to the requested dbGaP study"):
            # Umbrella projects can link several studies. Search this study explicitly,
            # then require the same identity check on every returned experiment.
            result["details"]["broad_sra_link_count"] = len(ids)
            study_ids, offset, expected = [], 0, None
            query = f'"{accession.split(".")[0]}"[All Fields]'
            while expected is None or offset < expected:
                search = get(f"sra_search_{offset}", eutils_url + "esearch.fcgi", xml_document,
                             {"db": "sra", "term": query, "retstart": offset, "retmax": 1000, "retmode": "xml"})
                if search is None:
                    break
                expected = int(search.findtext("Count", "0"))
                batch = [n.text for n in search.findall("./IdList/Id")]
                study_ids.extend(batch)
                if not batch:
                    break
                offset += len(batch)
            if study_ids and len(study_ids) == expected and len(set(study_ids)) == expected:
                fields, samples, experiments, methods = defaultdict(set), {}, set(), set()
                result["details"]["sra_experiments_expected"] = expected
                sra_complete = read_sra_batches(study_ids, "study_sra") is None
                sra_url = source("sra_search_0")
                if sra_complete:
                    result["components"][failed_batch].update(status="recovered", resolution="All study-specific search results retrieved and study identifiers verified")
            else:
                result["components"]["sra_search_count"] = {"status": "failed", "error": "Study-specific SRA search was empty or incomplete"}
        for field, values in fields.items():
            prior = []
            if field == "file_types" and access is not None:
                prior = file_types
            elif field == "biosample_bioproject_id":
                prior = [p["accession"] for p in result["details"].get("linked_bioprojects", []) if p["matches_study"]]
            put(field, join_values([*prior, *sorted(values)]),
                "Explicit linked SRA fields across all tissues, combined with previously sourced resource/BioProject fields where applicable", sra_url)
    else:
        result["components"]["sra_links"] = {"status": "not_linked"}
    result["details"].update(sra_experiments_read=len(experiments), sra_metadata_complete=sra_complete,
        unique_sample_records=len(samples), tissue_counts=dict(Counter(join_values(sorted(v)) or "Not specified" for v in samples.values())),
        deposited_methods=[{"tissue": tissue, "text": text} for tissue, text in sorted(methods)])
    # Count samples only for a wholly placenta-labelled, fully retrieved sample set.
    # These are distinct sample records, not an inferred count of independent placentas.
    if sra_complete and samples and all({v.casefold() for v in sites} == {"placenta"} for sites in samples.values()):
        put("sample_size_placenta", len(samples), "Distinct sample accessions; every sample explicitly labelled Placenta", sra_url)
    result["details"]["sample_count_rule"] = "Whole linked sample set must be explicitly placenta-labelled and completely retrieved; otherwise blank. No totals across assays or tissues."

    pmids, dois = get_publication_ids(description) if description else ([], [])
    match = re.search(r"initializeReferences\('[^']+',\s*'([0-9]+)'", str(page))
    if match:
        pending, seen, reference_count = {1}, set(), 0
        expected = None
        while pending:
            number = min(pending)
            pending.remove(number)
            seen.add(number)
            references = get(f"references_{number}", "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/GetReference.cgi",
                             reference_document, {"study_id": accession, "study_key": match[1], "page_number": number}, "html")
            if references is None:
                break
            listed = references.select("#reference-list ol > li")
            reference_count += len(listed)
            count = re.search(r"There (?:is|are) (\d+) selected publication", references.get_text(" ", strip=True))
            if count:
                expected = int(count[1])
            found_pmids, found_dois = get_publication_ids(references)
            pmids.extend(found_pmids)
            dois.extend(found_dois)
            pending.update(reference_page_numbers(references) - seen)
        if expected is not None and expected != reference_count:
            result["components"]["reference_count"] = {"status": "failed", "error": f"Retrieved {reference_count} of {expected} publication entries"}
    else:
        result["components"]["references"] = {"status": "not_listed"}
    original_dois = list(dict.fromkeys(dois))
    for index, doi in enumerate(original_dois):
        lookup = get(f"doi_lookup_{index}", eutils_url + "esearch.fcgi", xml_document,
                     {"db": "pubmed", "term": f'"{doi}"[AID]', "retmode": "xml", "retmax": 100})
        if lookup is not None:
            found = [n.text for n in lookup.findall(".//IdList/Id")]
            if len(found) != int(lookup.findtext("Count", "0")):
                raise ValueError("Incomplete DOI lookup")
            pmids.extend(found)
    pmids = list(dict.fromkeys(pmids))
    for field, values in (("all_pmids", pmids), ("all_dois", original_dois)):
        put(field, join_values(values), "Explicitly linked study publications", source("page_review"))
    if pmids:
        put("pmid", pmids[0], "First linked publication", source("page_review"))
        publications = get("pubmed", eutils_url + "efetch.fcgi", lambda raw: parse_pubmed(raw, pmids),
                           {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
        if publications is not None:
            result["details"]["publications"] = publications
            for singular, plural in (("doi", "all_dois"), ("pmcid", "all_pmcids")):
                put(singular, publications[0][singular], "Identifier of the first linked PMID (same paper)", source("pubmed"))
                values = [p[singular] for p in publications]
                if singular == "doi":
                    values = original_dois + values
                put(plural, join_values(values), "Identifiers from linked publications", source("pubmed"))
            contacts = [contact for p in publications for contact in p["contacts"]]
            result["details"]["publication_contacts"] = contacts
            put("email", join_values(f'{c["name"]} <{c["email"]}>' for c in contacts), "Published author email; name and PMID association retained", source("pubmed"))
    else:
        result["components"]["pubmed"] = {"status": "not_linked"}
    statuses = [c["status"] for c in result["components"].values()]
    result["metadata"]["extraction_status"] = "partial" if any(s in {"failed", "not_checked"} for s in statuses) else "extracted"
    return result


def save_results(root, rows, results):
    ordered = [results.get(row["dataset_id"], {"metadata": {"dataset_id": row["dataset_id"], "extraction_status": "not_attempted"},
               "components": {}, "field_sources": [], "details": {}}) for row in rows]
    export_rows = []
    for result in ordered:
        record = {field: result["metadata"].get(field, "") for field in output_fields}
        # Reuse the shared date column without relabelling or changing the raw metadata.
        record["submission_date"] = (result["metadata"].get("release_date")
                                     or result["details"].get("release_date") or "")
        export_rows.append(record)
    states = Counter(r["metadata"]["extraction_status"] for r in ordered)
    summary = {"requested": len(rows), "complete": states["extracted"], "partial": states["partial"],
               "failed": states["failed"], "not_attempted": states["not_attempted"],
               "updated_at": datetime.now(timezone.utc).isoformat(),
               "field_coverage": {field: sum(r.get(field) not in (None, "") for r in export_rows) for field in output_fields}}
    directory = root / "results"
    directory.mkdir(parents=True, exist_ok=True)
    save_csv(directory / "dbgap_metadata.csv", [{geo_columns[f]: r[f] for f in output_fields} for r in export_rows])
    save_csv(directory / "dbgap_status.csv", [{"dataset_id": r["metadata"]["dataset_id"], "status": r["metadata"]["extraction_status"],
              "errors": join_values(f'{k}: {v.get("error", v.get("reason", ""))}' for k, v in r["components"].items() if v["status"] in {"failed", "not_checked"}),
              "notes": join_values(f'{k}: {v.get("reason", v.get("resolution", ""))}' for k, v in r["components"].items() if v["status"] in {"not_reported", "recovered"})} for r in ordered])
    save_csv(directory / "dbgap_details.csv", [{"dataset_id": r["metadata"]["dataset_id"], "release_date": r["details"].get("release_date", ""),
              "molecular_counts": json.dumps(r["details"].get("molecular_counts", [])), "deposited_methods": json.dumps(r["details"].get("deposited_methods", [])),
              "tissue_counts": json.dumps(r["details"].get("tissue_counts", {})), "publication_contacts": json.dumps(r["details"].get("publication_contacts", []))} for r in ordered])
    save_csv(directory / "dbgap_field_sources.csv", [e for r in ordered for e in r["field_sources"]],
              ["dataset_id", "field", "value", "source_section", "source_url"])
    write_json(directory / "dbgap_results.json", {"summary": summary, "results": ordered})
    write_json(root / "progress.json", summary)
    return summary


def save_csv(path, rows, columns=None):
    """An interrupted write must not leave a half-written results table."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    write_csv(temporary, rows, columns)
    temporary.replace(path)


def keep_previous_result(previous, current):
    """Keep a saved row if a later attempt cannot retrieve the study at all."""
    if previous and previous["metadata"].get("title") and current["metadata"]["extraction_status"] == "failed":
        saved = json.loads(json.dumps(previous))
        saved["metadata"]["extraction_status"] = "partial"
        saved["components"].update({"refresh_" + name: error for name, error in current["components"].items()})
        return saved
    return current


def run(root, input_path, selected=None, offline=False, retry_failed=False, refresh=False):
    if offline and refresh:
        raise ValueError("--offline and --refresh cannot be used together")
    rows = read_inputs(input_path)
    selected_rows = read_inputs(input_path, selected)
    results = {}
    for row in rows:
        path = root / "cache/dbgap" / (row["dataset_id"] + ".result.json")
        if path.exists():
            saved = json.loads(path.read_text())
            if saved["metadata"]["dataset_id"] != row["dataset_id"]:
                raise ValueError("Checkpoint study ID does not match its filename")
            results[row["dataset_id"]] = saved
    summary = save_results(root, rows, results)
    targets = [row for row in selected_rows if not retry_failed or
               results.get(row["dataset_id"], {}).get("metadata", {}).get("extraction_status") != "extracted"]
    with requests.Session() as session:
        session.headers["User-Agent"] = "placenta-repository-metadata/1.0 (public metadata only)"
        for index, row in enumerate(targets, 1):
            accession = row["dataset_id"]
            checkpoint = root / "cache/dbgap" / (accession + ".result.json")
            print(f"[{index}/{len(targets)}] {accession}", flush=True)
            try:
                result = extract_study(session, row, root, offline, refresh)
            except (ValueError, KeyError, TypeError, AttributeError, OSError) as error:
                result = {"metadata": {"dataset_id": accession, "extraction_status": "failed"},
                          "components": {"extraction": {"status": "failed", "error": str(error)}}, "field_sources": [], "details": {}}
                print(f"  Extraction error: {error}", flush=True)
            rate_limited = any(c.get("http_status") == 429 for c in result["components"].values())
            previous = results.get(accession)
            if previous:
                write_json(checkpoint.with_suffix(".previous.json"), previous)
            result = keep_previous_result(previous, result)
            results[accession] = result
            write_json(checkpoint, result)
            summary = save_results(root, rows, results)
            print(f'  {result["metadata"]["extraction_status"]}', flush=True)
            for name, component in result["components"].items():
                if component["status"] in {"not_reported", "recovered"}:
                    note = component.get("reason", component.get("resolution", ""))
                    print(f"  {name}: {note}", flush=True)
            if rate_limited:
                print("Rate limited: saved progress and stopped. Rerun later to reuse the cache.", flush=True)
                break
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Results: {root.resolve() / 'results'}", flush=True)
    return summary["complete"] == len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--ids-file", type=Path, default=Path(__file__).resolve().parent / "inputs/dbgap_ids.csv",
                        help="Input CSV with a dataset_id column; source URLs are generated automatically")
    parser.add_argument("--ids", nargs="+", help="Process only these IDs without removing other saved rows")
    parser.add_argument("--retry-failed", action="store_true", help="Process only partial, failed or not-yet-attempted studies")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Use saved responses only; send no network requests")
    mode.add_argument("--refresh", action="store_true", help="Retrieve fresh responses instead of reusing the cache")
    args = parser.parse_args()
    raise SystemExit(0 if run(args.root, args.ids_file, args.ids, args.offline, args.retry_failed, args.refresh) else 1)
