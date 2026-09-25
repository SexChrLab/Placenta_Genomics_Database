"""Fetch linked public metadata for explicitly selected dbGaP pilot studies."""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from extract_pilot import get_publication_ids
from metadata_io import cached_get, read_csv


eutils = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'


def sra_study_uid(soup):
    for anchor in soup.find_all('a', href=True):
        query = {key.lower(): value for key, value in parse_qs(urlparse(anchor['href']).query).items()}
        if query.get('linkname') == ['gap_sra_all']:
            uid = query.get('from_uid', [''])[0]
            if not uid.isdigit():
                raise ValueError('Public SRA link has no valid dbGaP UID')
            return uid
    return None


def fetch_xml(session, endpoint, params, path):
    provenance = path.with_name(path.name + '.source.json')
    refresh = False
    if provenance.exists():
        # A batch filename can be reused, but its requested IDs may have changed.
        query = parse_qs(urlparse(json.loads(provenance.read_text())['response_url']).query)
        refresh = any(query.get(key) != [str(value)] for key, value in params.items())
    raw, info = cached_get(session, eutils + endpoint, path, params, refresh)
    document = ElementTree.fromstring(raw)
    errors = document.findall('.//ERROR')
    if errors:
        raise ValueError('; '.join(node.text or '' for node in errors))
    return document, info


def fetch_sra_metadata(session, directory, accession, uid, manifest):
    """Fetch all linked experiment metadata in batches, without downloading raw data."""
    ids = []
    manifest['sra_link_status'] = 'not_linked_on_page'
    if uid:
        ids_xml, info = fetch_xml(session, 'elink.fcgi', {'dbfrom': 'gap', 'db': 'sra', 'id': uid,
            'linkname': 'gap_sra_all', 'retmode': 'xml'}, directory / f'{accession}.sra_links.xml')
        ids = [node.text for node in ids_xml.findall('.//LinkSetDb[DbTo="sra"]/Link/Id')]
        manifest.update(sra_link_status='retrieved', sra_link_source=info)
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate SRA UIDs in linked result')
    manifest['sra_count'] = len(ids)
    experiments = set()
    for start in range(0, len(ids), 200):
        selected = ids[start:start + 200]
        filename = f'{accession}.sra_{start}.xml'
        document, info = fetch_xml(session, 'efetch.fcgi', {'db': 'sra', 'id': ','.join(selected),
            'retmode': 'xml'}, directory / filename)
        packages = document.findall('EXPERIMENT_PACKAGE')
        if len(packages) != len(selected):
            raise ValueError(f'SRA returned {len(packages)} of {len(selected)} requested records')
        for package in packages:
            study_ids = [node.text for node in package.findall('.//STUDY/IDENTIFIERS/EXTERNAL_ID[@namespace="dbGaP"]')]
            if accession.split('.')[0] not in study_ids:
                raise ValueError('SRA experiment is not linked to the selected dbGaP study')
            experiment = package.find('EXPERIMENT').get('accession')
            if experiment in experiments:
                raise ValueError('Duplicate SRA experiment across batches')
            experiments.add(experiment)
        manifest['sra_batches'].append({'file': filename, 'count': len(packages), **info})
        print(f'{accession}: public SRA metadata {len(experiments)}/{len(ids)}', flush=True)


def fetch_publication_metadata(session, directory, accession, soup, manifest):
    pmids, dois = get_publication_ids(soup.select_one('dl.report > dd'))
    for path in directory.glob(f'{accession}.references_*.html'):
        found_pmids, found_dois = get_publication_ids(BeautifulSoup(path.read_bytes(), 'html.parser'))
        pmids.extend(found_pmids)
        dois.extend(found_dois)
    # Resolve listed DOIs as well as PMIDs, then fetch each publication only once.
    for index, doi in enumerate(dict.fromkeys(dois)):
        document, info = fetch_xml(session, 'esearch.fcgi', {'db': 'pubmed', 'term': f'"{doi}"[AID]',
            'retmode': 'xml', 'retmax': 100}, directory / f'{accession}.doi_lookup_{index}.xml')
        found = [node.text for node in document.findall('.//IdList/Id')]
        if len(found) != int(document.findtext('Count', '0')):
            raise ValueError('Incomplete publication lookup')
        pmids.extend(found)
        manifest['doi_queries'].append({'doi': doi, 'pmids': found, **info})
    pmids = list(dict.fromkeys(pmids))
    if pmids:
        filename = f'{accession}.pubmed.xml'
        document, info = fetch_xml(session, 'efetch.fcgi', {'db': 'pubmed', 'id': ','.join(pmids),
            'retmode': 'xml'}, directory / filename)
        returned = {node.text for node in document.findall('./PubmedArticle/MedlineCitation/PMID')}
        if returned != set(pmids):
            raise ValueError('Incomplete PubMed metadata response')
        manifest['pubmed'] = {'file': filename, 'pmids': pmids, **info}
    return pmids


def fetch(root, dataset_ids):
    candidates = {row['dataset_id']: row for row in read_csv(root / 'inputs/dbgap_ids.csv')}
    if not dataset_ids or not set(dataset_ids) <= candidates.keys():
        raise ValueError('Select existing dbGaP IDs explicitly.')
    session = requests.Session()
    session.headers['User-Agent'] = 'placenta-metadata-pilot/0.3 (public repository metadata only)'
    for accession in dataset_ids:
        directory = root / 'cache/dbgap'
        manifest_path = directory / f'{accession}.linked_metadata.json'
        manifest = {'dataset_id': accession, 'status': 'in_progress', 'sra_batches': [], 'doi_queries': []}
        # Extraction must not treat a partially completed download as complete.
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        page, page_info = cached_get(session, candidates[accession]['source_url'], directory / f'{accession}.page_review.html', refresh=True)
        soup = BeautifulSoup(page, 'html.parser')
        study_id = soup.select_one('#study-id')
        if not study_id or study_id.get_text(strip=True) != accession:
            raise ValueError(f'Unexpected study page for {accession}')
        manifest['page'] = f'{accession}.page_review.html'
        manifest['page_source'] = page_info
        fetch_sra_metadata(session, directory, accession, sra_study_uid(soup), manifest)
        pmids = fetch_publication_metadata(session, directory, accession, soup, manifest)
        manifest['status'] = 'complete'
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        print(f'{accession}: linked metadata complete; {len(pmids)} publication records', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--ids', nargs='+', required=True)
    args = parser.parse_args()
    fetch(args.root, args.ids)
