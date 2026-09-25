"""Cache public study pages for the selected metadata pilot."""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from metadata_io import read_csv

def fetch_detail(session, url, params, path, refresh):
    provenance = path.with_name(path.name + ".source.json")
    if path.exists() and provenance.exists() and not refresh:
        return json.loads(provenance.read_text())
    for attempt in range(3):
        try:
            response = session.get(url, params=params, timeout=(15, 60))
            response.raise_for_status()
            if path.suffix == ".json":
                response.json()
            elif "reference-list" not in response.text:
                raise ValueError("Publication endpoint returned no reference-list element")
            result = {"status": "downloaded", "response_url": response.url,
                      "retrieved_at": datetime.now(timezone.utc).isoformat(),
                      "sha256": hashlib.sha256(response.content).hexdigest(),
                      "bytes": len(response.content)}
            path.write_bytes(response.content)
            provenance.write_text(json.dumps(result, indent=2) + "\n")
            time.sleep(0.5)
            return result
        except (requests.RequestException, ValueError) as error:
            if attempt == 2:
                return {"status": "failed", "url": url, "params": params, "error": str(error)}
            time.sleep(2 ** attempt)


def fetch_details(root, records, session, refresh):
    results = []
    for row in records:
        directory = root / "cache" / row["source"]
        accession = row["dataset_id"]
        page = directory / (accession + ".html")
        if not page.exists():
            continue
        if row["source"] == "massive":
            result = fetch_detail(session, "https://massive.ucsd.edu/ProteoSAFe/MassiveServlet",
                                  {"function": "massivesummary", "massiveid": accession},
                                  directory / (accession + ".summary.json"), refresh)
            results.append({"dataset_id": accession, "component": "summary", **result})
        else:
            match = re.search(r"initializeReferences\('[^']+',\s*'([0-9]+)'", page.read_text())
            if not match:
                results.append({"dataset_id": accession, "component": "publications",
                                "status": "failed", "error": "Publication study key missing"})
                continue
            pending, visited = {1}, set()
            # Publication lists may span several pages; follow every page control.
            while pending:
                page_number = min(pending)
                pending.remove(page_number)
                visited.add(page_number)
                path = directory / f"{accession}.references_{page_number}.html"
                result = fetch_detail(session, "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/GetReference.cgi",
                                      {"study_id": accession, "study_key": match[1], "page_number": page_number},
                                      path, refresh)
                results.append({"dataset_id": accession, "component": "publications",
                                "page_number": page_number, **result})
                if result["status"] != "downloaded":
                    break
                soup = BeautifulSoup(path.read_bytes(), "html.parser")
                for tag in soup.find_all(["a", "input", "button", "option"]):
                    control = " ".join(str(value) for value in tag.attrs.values())
                    for number in re.findall(r"updateReferences\([^,]+,[^,]+,\s*['\"]?(\d+)", control):
                        if int(number) not in visited:
                            pending.add(int(number))
        print(f"Public metadata details: {accession}", flush=True)
    (root / "outputs/detail_fetch_report.json").write_text(json.dumps(results, indent=2) + "\n")
    return all(row["status"] == "downloaded" for row in results)


def fetch(root, refresh=False):
    records = read_csv(root / "inputs/pilot_ids.csv")
    session = requests.Session()
    session.headers["User-Agent"] = "placenta-metadata-pilot/0.1 (public study metadata)"
    results = []
    for index, row in enumerate(records, 1):
        directory = root / "cache" / row["source"]
        directory.mkdir(parents=True, exist_ok=True)
        page = directory / (row["dataset_id"] + ".html")
        provenance = page.with_suffix(".json")
        if page.exists() and provenance.exists() and not refresh:
            result = json.loads(provenance.read_text())
            result["cached"] = True
        else:
            result = {**row, "retrieved_at": datetime.now(timezone.utc).isoformat(), "cached": False}
            for attempt in range(3):
                try:
                    response = session.get(row["source_url"], timeout=(15, 60))
                    response.raise_for_status()
                    if row["dataset_id"] not in response.text:
                        raise ValueError("Returned page does not identify the requested accession")
                    page.write_bytes(response.content)
                    result.update(status="downloaded", http_status=response.status_code,
                                  response_url=response.url, bytes=len(response.content),
                                  sha256=hashlib.sha256(response.content).hexdigest(),
                                  cache_file=str(page.relative_to(root)))
                    result.pop("error", None)
                    provenance.write_text(json.dumps(result, indent=2) + "\n")
                    break
                except (requests.RequestException, ValueError) as error:
                    result.update(status="failed", error=str(error))
                    if attempt < 2:
                        time.sleep(2 ** attempt)
            time.sleep(0.5)
        results.append(result)
        print(f"[{index}/{len(records)}] {row['dataset_id']}: {result['status']}", flush=True)
    output = root / "outputs"
    output.mkdir(exist_ok=True)
    (output / "fetch_report.json").write_text(json.dumps(results, indent=2) + "\n")
    successful_ids = {row["dataset_id"] for row in results if row["status"] == "downloaded"}
    successful = [row for row in records if row["dataset_id"] in successful_ids]
    details_ok = fetch_details(root, successful, session, refresh)
    return all(row["status"] == "downloaded" for row in results) and details_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    raise SystemExit(0 if fetch(args.root, args.refresh) else 1)
