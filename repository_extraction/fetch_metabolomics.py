"""Retrieve public metabolomics metadata, without raw experimental files."""

import argparse
import json
from pathlib import Path

import requests

from metadata_io import cached_get, read_csv, write_csv


def discover(root, session, refresh):
    terms = read_csv(root / "inputs/metabolights_search_terms.csv")
    studies, reports = {}, []
    for item in terms:
        term = item["search_term"]
        query = '"' + term + '"' if " " in term else term
        start, hits, entries = 0, None, []
        # Keep fetching until every reported search hit has been read.
        while hits is None or start < hits:
            path = root / "cache/metabolights_search" / f"{term.replace(' ', '_')}_{start}.json"
            raw, info = cached_get(session, "https://www.ebi.ac.uk/ebisearch/ws/rest/metabolights", path,
                                   {"query": query, "format": "json", "size": 100, "start": start,
                                    "fields": "name,description"}, refresh)
            data = json.loads(raw)
            hits = data["hitCount"]
            page = data.get("entries", [])
            if not page and start < hits:
                raise ValueError(f"Search pagination stopped before all {hits} hits for {term}")
            entries.extend(page)
            start += len(page)
        if len(entries) != hits:
            raise ValueError(f"Search count changed during pagination for {term}")
        reports.append({"search_term": term, "query": query, "original_reported_hits": item["reported_hits"],
                        "current_index_hits": hits, "retrieved_at": info["retrieved_at"],
                        "source_url": info["response_url"]})
        for entry in entries:
            accession = entry["id"]
            if not accession.startswith("MTBLS"):
                continue
            row = studies.setdefault(accession, {"dataset_id": accession, "source": "metabolights",
                "title": "; ".join(entry.get("fields", {}).get("name", [])), "search_terms": [],
                "source_url": "https://www.ebi.ac.uk/metabolights/" + accession})
            row["search_terms"].append(term)
        print(f"MetaboLights search {term}: {hits}", flush=True)
    rows = [{**row, "search_terms": "; ".join(row["search_terms"])} for row in studies.values()]
    rows.sort(key=lambda row: int(row["dataset_id"][5:]))
    write_csv(root / "inputs/metabolights_ids.csv", rows)
    write_csv(root / "outputs/metabolights_search_report.csv", reports)
    print(f"MetaboLights candidate IDs: {len(rows)}", flush=True)


def fetch(root, session, refresh):
    selected = read_csv(root / "inputs/metabolomics_pilot_ids.csv")
    reports = []
    for row in selected:
        accession, source = row["dataset_id"], row["source"]
        directory = root / "cache" / source
        if source == "metabolomics_workbench":
            requests_to_make = [("page", "https://www.metabolomicsworkbench.org/data/DRCCMetadata.php",
                                 {"Mode": "Study", "StudyID": accession}, directory / (accession + ".html"))]
            for part in ["summary", "factors", "analysis"]:
                requests_to_make.append((part, f"https://www.metabolomicsworkbench.org/rest/study/study_id/{accession}/{part}",
                                         None, directory / f"{accession}.{part}.json"))
        else:
            requests_to_make = [("public_study", f"https://www.ebi.ac.uk/metabolights/ws/studies/public/study/{accession}",
                                 None, directory / (accession + ".json"))]
        for component, url, params, path in requests_to_make:
            result = {"source": source, "dataset_id": accession, "component": component}
            try:
                raw, info = cached_get(session, url, path, params, refresh)
                if accession.encode() not in raw:
                    raise ValueError("Response did not identify the requested study")
                result.update(status="downloaded", **info)
            except (requests.RequestException, ValueError) as error:
                result.update(status="failed", error=str(error), source_url=url)
            reports.append(result)
            print(f"{accession} {component}: {result['status']}", flush=True)
        (root / "outputs/metabolomics_fetch_report.json").write_text(json.dumps(reports, indent=2) + "\n")
    return all(row["status"] == "downloaded" for row in reports)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--discover", action="store_true", help="Recover MetaboLights candidates from the supplied terms")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    (args.root / "outputs").mkdir(exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "placenta-metadata-pilot/0.2 (public study metadata)"
    if args.discover:
        discover(args.root, session, args.refresh)
    else:
        raise SystemExit(0 if fetch(args.root, session, args.refresh) else 1)
