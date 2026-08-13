"""
Download supplementary files for downloaded papers.

Three sequential passes per paper:
  1. PMC      — NCBI efetch + OA packages + Playwright browser fallback.
                Runs for any paper saved as PMC<num>.xml in downloaded_papers/.
  2. EuropePMC — supplementaryFiles endpoint (returns a zip). Tried for any paper
                 that has a PMCID but got nothing in pass 1, AND for PMCID-shaped
                 papers we couldn't pull via PMC.
  3. Elsevier — parses each Elsevier-saved article XML for <ce:e-component> /
                <xocs:attachment> / <ce:object-ref> supplement refs, then fetches
                each one via the Elsevier TDM API (uses elsevier_api_key).

Outputs:
  downloaded_supplements/<PMCID-or-doi>/<filename>     — actual files
  downloaded_supplements/_progress.json                — resume state
  downloaded_supplements/_report.csv                   — per-file outcome incl.
                                                          short-flag for stub files

Short flag: files smaller than supplement_min_useful_bytes are saved but flagged
so you can spot stubs (e.g. publisher wrapper pages) that downloaded but contain
no real metadata.

Usage:
    # activate venv first: source .venv/bin/activate
    python pipeline/05_download_supplements.py
    python pipeline/05_download_supplements.py --skip-elsevier
    python pipeline/05_download_supplements.py --pmcid PMC10843761
    python pipeline/05_download_supplements.py --types xlsx,docx
"""

import argparse
import csv
import html
import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from playwright.sync_api import sync_playwright


def load_local_env(path: str = ".env") -> None:
    """Load simple KEY=VALUE entries without printing or overwriting secrets."""
    if not os.path.exists(path):
        return
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception:
        pass


load_local_env()


# Configuration
papers_dir = "downloaded_papers"
supplement_dir = "downloaded_supplements"
progress_file = os.path.join(supplement_dir, "_progress.json")
report_file = os.path.join(supplement_dir, "_report.csv")
final_audit_file = os.path.join(supplement_dir, "_final_audit.csv")

# File extensions worth downloading (structured/text data + pdfs)
default_types = {".xlsx", ".xls", ".docx", ".doc", ".csv", ".txt", ".pdf"}

# Per-file size threshold below which we suspect the file is empty / wrapper / stub
supplement_min_useful_bytes = 2000

api_delay = 0.35  # NCBI rate limit: ~3 requests/sec

base_url = "https://pmc.ncbi.nlm.nih.gov/articles/instance/{pmcid_num}/bin/{filename}"
efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmcid_num}&rettype=xml"
pmc_oa_api_url = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"
europe_pmc_supp_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC{pmcid_num}/supplementaryFiles"
europe_pmc_timeout_sec = 180

elsevier_api_key = os.environ.get("elsevier_api_key", "").strip()


# Reporting
report_rows: List[Dict] = []


def log_outcome(paper_key: str, source: str, filename: str, status: str,
                bytes_: int, short: bool, reason: str = "") -> None:
    report_rows.append({
        "PaperKey": paper_key,
        "Source": source,
        "Filename": filename,
        "Status": status,
        "Bytes": bytes_,
        "ShortFlag": short,
        "Reason": reason,
    })


def validate_file(path: str, min_bytes: int = supplement_min_useful_bytes) -> Tuple[int, bool]:
    if not os.path.exists(path):
        return 0, True
    size = os.path.getsize(path)
    return size, size < min_bytes


def write_report(progress: Optional[dict] = None) -> None:
    rows = list(report_rows)
    seen = {
        (str(r.get("PaperKey")), str(r.get("Source")), str(r.get("Filename")))
        for r in rows
    }

    if os.path.exists(report_file):
        try:
            with open(report_file, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    key = (row.get("PaperKey", ""), row.get("Source", ""), row.get("Filename", ""))
                    if key not in seen:
                        rows.append(row)
                        seen.add(key)
        except Exception as e:
            print(f"  warning: could not merge existing supplement report: {e}")

    # If this is a resumed run, previously downloaded/skipped files would not be
    # present in report_rows. Preserve auditability by seeding report rows from
    # the resume checkpoint when no more specific report row exists.
    if progress:
        for key, info in (progress.get("downloaded") or {}).items():
            paper_key, filename = key.split("/", 1) if "/" in key else (key, "")
            report_key = (paper_key, "resume_progress", filename)
            if report_key in seen:
                continue
            path = (info or {}).get("path", "")
            size = int((info or {}).get("size") or (os.path.getsize(path) if path and os.path.exists(path) else 0))
            short = size < supplement_min_useful_bytes
            rows.append({
                "PaperKey": paper_key,
                "Source": "resume_progress",
                "Filename": filename,
                "Status": "ok_short" if short else "ok",
                "Bytes": size,
                "ShortFlag": short,
                "Reason": "from existing progress checkpoint",
            })
            seen.add(report_key)
        for key, info in (progress.get("failed") or {}).items():
            paper_key, filename = key.split("/", 1) if "/" in key else (key, "")
            report_key = (paper_key, "resume_progress", filename)
            if report_key in seen:
                continue
            rows.append({
                "PaperKey": paper_key,
                "Source": "resume_progress",
                "Filename": filename,
                "Status": "failed",
                "Bytes": 0,
                "ShortFlag": True,
                "Reason": f"from existing progress checkpoint; attempts={(info or {}).get('attempts', '')}",
            })
            seen.add(report_key)
        for key, info in (progress.get("not_supplement") or {}).items():
            paper_key, filename = key.split("/", 1) if "/" in key else (key, "")
            report_key = (paper_key, "resume_progress", filename)
            if report_key in seen:
                continue
            rows.append({
                "PaperKey": paper_key,
                "Source": "resume_progress",
                "Filename": filename,
                "Status": "not_supplement",
                "Bytes": 0,
                "ShortFlag": False,
                "Reason": (info or {}).get("reason", "classified as not supplementary material"),
            })
            seen.add(report_key)
        for key, info in (progress.get("publisher_recovered") or {}).items():
            paper_key, filename = key.split("/", 1) if "/" in key else (key, "")
            report_key = (paper_key, "resume_progress", filename)
            if report_key in seen:
                continue
            rows.append({
                "PaperKey": paper_key,
                "Source": "resume_progress",
                "Filename": filename,
                "Status": "publisher_recovered",
                "Bytes": 0,
                "ShortFlag": False,
                "Reason": (info or {}).get("reason", "recovered under publisher filename"),
            })
            seen.add(report_key)

    os.makedirs(supplement_dir, exist_ok=True)
    with open(report_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["PaperKey", "Source", "Filename", "Status", "Bytes", "ShortFlag", "Reason"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Report written: {report_file} ({len(rows)} rows)")


def audit_validation(path: str) -> str:
    if not path or not os.path.exists(path):
        return "missing"
    size = os.path.getsize(path)
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        head = f.read(256).lstrip().lower()
    if head.startswith((b"<!doctype", b"<html")):
        return "html_placeholder"
    if ext in (".xlsx", ".docx"):
        try:
            with zipfile.ZipFile(path) as zf:
                if zf.testzip():
                    return "corrupt_office_archive"
        except Exception:
            return "invalid_office_archive"
    if ext == ".pdf" and not head.startswith(b"%pdf-"):
        return "invalid_pdf"
    if size < supplement_min_useful_bytes:
        if ext in (".csv", ".txt"):
            try:
                lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) >= 2:
                    return "valid_small_text"
            except Exception:
                pass
        return "short_review"
    return "valid"


def write_final_audit(progress: dict) -> None:
    rows: List[Dict] = []
    for key, info in sorted((progress.get("downloaded") or {}).items()):
        paper_key, filename = key.split("/", 1) if "/" in key else (key, "")
        path = (info or {}).get("path", "") or os.path.join(supplement_dir, key)
        rows.append({
            "PaperKey": paper_key,
            "Filename": filename,
            "FinalStatus": "downloaded",
            "Path": path,
            "Bytes": os.path.getsize(path) if os.path.exists(path) else 0,
            "Validation": audit_validation(path),
            "Reason": "",
        })
    for bucket, status in (
        ("publisher_recovered", "publisher_recovered_under_different_filename"),
        ("not_supplement", "not_supplement"),
        ("failed", "failed"),
    ):
        for key, info in sorted((progress.get(bucket) or {}).items()):
            paper_key, filename = key.split("/", 1) if "/" in key else (key, "")
            rows.append({
                "PaperKey": paper_key,
                "Filename": filename,
                "FinalStatus": status,
                "Path": "",
                "Bytes": 0,
                "Validation": "not_applicable" if status != "failed" else "unresolved",
                "Reason": (info or {}).get("reason", ""),
            })
    with open(final_audit_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["PaperKey", "Filename", "FinalStatus", "Path", "Bytes", "Validation", "Reason"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Final audit written: {final_audit_file} ({len(rows)} rows)")


# Progress state
def load_progress() -> dict:
    if os.path.exists(progress_file):
        with open(progress_file) as f:
            progress = json.load(f)
            progress.setdefault("downloaded", {})
            progress.setdefault("failed", {})
            progress.setdefault("not_supplement", {})
            progress.setdefault("publisher_recovered", {})
            return progress
    return {"downloaded": {}, "failed": {}, "not_supplement": {}, "publisher_recovered": {}}


def save_progress(progress: dict) -> None:
    os.makedirs(supplement_dir, exist_ok=True)
    with open(progress_file, "w") as f:
        json.dump(progress, f, indent=2)


def get_pmcid_number(pmcid: str) -> str:
    return pmcid.replace("PMC", "").strip()


def sanitize_paper_key(value: str) -> str:
    value = str(value or "").strip().replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def load_download_summary() -> Dict[str, Dict[str, str]]:
    """Map downloaded file stems / PMCID / sanitized DOI to download-summary rows."""
    path = os.path.join(papers_dir, "download_summary.csv")
    out: Dict[str, Dict[str, str]] = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                keys = []
                saved = row.get("saved_path") or ""
                if saved:
                    keys.append(os.path.splitext(os.path.basename(saved))[0])
                pmcid = (row.get("pmcid") or "").strip()
                doi = (row.get("doi") or "").strip()
                pmid = (row.get("pmid") or "").strip()
                if pmcid:
                    keys.append(pmcid)
                if doi:
                    keys.append(sanitize_paper_key(doi))
                if pmid:
                    keys.append(pmid)
                for key in keys:
                    out[key] = row
    except Exception as e:
        print(f"  warning: could not read paper download summary: {e}")
    return out


def europepmc_search_record(meta: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Find a Europe PMC record from DOI/PMID/PMCID metadata."""
    queries = []
    doi = (meta.get("doi") or "").strip()
    pmid = (meta.get("pmid") or "").strip()
    pmcid = (meta.get("pmcid") or "").strip()
    if doi:
        queries.append(f'DOI:"{doi}"')
    if pmid:
        queries.append(f"EXT_ID:{pmid}")
    if pmcid:
        queries.append(f"EXT_ID:{pmcid}")
    for q in queries:
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode({
            "query": q,
            "format": "json",
            "pageSize": 1,
        })
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            results = (data.get("resultList") or {}).get("result") or []
            if results:
                return results[0]
        except Exception:
            continue
    return None


# Pass 1: PMC through NCBI efetch and Playwright fallback
def fetch_supplement_list_efetch(pmcid_num: str) -> List[dict]:
    """Fetch supplement file list from NCBI efetch API."""
    url = efetch_url.format(pmcid_num=pmcid_num)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            xml_str = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    efetch failed: {e}")
        return []
    return parse_supplements_from_xml_str(xml_str)


def parse_supplements_from_xml_str(xml_str: str) -> List[dict]:
    """Parse actual supplementary-material filenames from PMC XML.

    Do not collect every xlink:href in the article. In particular, <self-uri>
    points at the main article PDF and was previously inflating supplement
    failures by hundreds of files.
    """
    supplements = []
    seen = set()
    try:
        root = ET.fromstring(xml_str)
        for elem in root.iter():
            if elem.tag.split("}")[-1] != "supplementary-material":
                continue
            for child in elem.iter():
                href = (
                    child.attrib.get("{http://www.w3.org/1999/xlink}href")
                    or child.attrib.get("href")
                    or ""
                ).strip()
                if not href:
                    continue
                filename = os.path.basename(urllib.parse.urlparse(href).path)
                if not filename or filename in seen:
                    continue
                ext = os.path.splitext(filename)[1].lower()
                if ext:
                    seen.add(filename)
                    supplements.append({"filename": filename, "ext": ext})
    except ET.ParseError:
        # Conservative fallback: only inspect supplementary-material blocks.
        for block in re.findall(r"<supplementary-material[\s\S]*?</supplementary-material>", xml_str):
            for match in re.finditer(r'href="([^"]+\.\w{2,5})"', block):
                filename = os.path.basename(urllib.parse.urlparse(match.group(1)).path)
                if not filename or filename in seen:
                    continue
                ext = os.path.splitext(filename)[1].lower()
                if ext:
                    seen.add(filename)
                    supplements.append({"filename": filename, "ext": ext})
    return supplements


def classify_existing_main_article_pdfs(progress: dict) -> int:
    """Move main-article PDF entries out of the supplement failure bucket."""
    moved = 0
    for key in list(progress.get("failed", {})):
        if "/" not in key:
            continue
        pmcid, filename = key.split("/", 1)
        xml_path = os.path.join(papers_dir, f"{pmcid}.xml")
        if not os.path.exists(xml_path):
            continue
        try:
            xml_str = Path(xml_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        escaped = re.escape(filename)
        if not re.search(r'<self-uri[^>]+xlink:href="' + escaped + r'"', xml_str, re.IGNORECASE):
            continue
        progress["not_supplement"][key] = {
            "reason": "main article PDF referenced by self-uri; not supplementary material"
        }
        progress["failed"].pop(key, None)
        log_outcome(
            pmcid,
            "pmc_xml_classification",
            filename,
            "not_supplement",
            0,
            False,
            "main article PDF referenced by self-uri",
        )
        moved += 1
    return moved


def reconcile_exact_downloads(progress: dict) -> int:
    """Remove stale failures when the exact file was later downloaded."""
    resolved = 0
    for key in list(progress.get("failed", {})):
        info = progress.get("downloaded", {}).get(key)
        if not info:
            continue
        path = info.get("path", "") or os.path.join(supplement_dir, key)
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            continue
        with open(path, "rb") as f:
            head = f.read(256).lstrip().lower()
        if head.startswith((b"<!doctype", b"<html")):
            continue
        progress["failed"].pop(key, None)
        resolved += 1
    return resolved


def reconcile_html_placeholders(progress: dict) -> Tuple[int, int]:
    """Remove HTML pages mistakenly recorded as downloaded files.

    Main article PDF placeholders are classified as not supplements. Actual
    supplementary-material placeholders are returned to the failure queue.
    """
    main_articles = 0
    supplements = 0
    for key, info in list(progress.get("downloaded", {}).items()):
        path = (info or {}).get("path", "") or os.path.join(supplement_dir, key)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as f:
                head = f.read(256).lstrip().lower()
        except Exception:
            continue
        if not head.startswith((b"<!doctype", b"<html")):
            continue
        progress["downloaded"].pop(key, None)
        if "/" not in key:
            continue
        pmcid, filename = key.split("/", 1)
        xml_path = os.path.join(papers_dir, f"{pmcid}.xml")
        xml_str = Path(xml_path).read_text(encoding="utf-8", errors="replace") if os.path.exists(xml_path) else ""
        if re.search(r'<self-uri[^>]+xlink:href="' + re.escape(filename) + r'"', xml_str, re.IGNORECASE):
            progress["not_supplement"][key] = {
                "reason": "main article PDF placeholder; not supplementary material"
            }
            main_articles += 1
        else:
            progress["failed"][key] = {
                "attempts": progress.get("failed", {}).get(key, {}).get("attempts", 0),
                "reason": "HTML placeholder recorded instead of supplement",
            }
            supplements += 1

    # Also catch placeholder files removed from the downloaded checkpoint by an
    # earlier cleanup attempt.
    for path in Path(supplement_dir).glob("PMC*/*"):
        if not path.is_file():
            continue
        key = f"{path.parent.name}/{path.name}"
        if key in progress.get("downloaded", {}) or key in progress.get("not_supplement", {}):
            continue
        try:
            with open(path, "rb") as f:
                head = f.read(256).lstrip().lower()
        except Exception:
            continue
        if not head.startswith((b"<!doctype", b"<html")):
            continue
        xml_path = os.path.join(papers_dir, f"{path.parent.name}.xml")
        xml_str = Path(xml_path).read_text(encoding="utf-8", errors="replace") if os.path.exists(xml_path) else ""
        if re.search(r'<self-uri[^>]+xlink:href="' + re.escape(path.name) + r'"', xml_str, re.IGNORECASE):
            progress["not_supplement"][key] = {
                "reason": "main article PDF placeholder; not supplementary material"
            }
            main_articles += 1
        elif re.search(
            r'<supplementary-material[\s\S]{0,2000}?xlink:href="' + re.escape(path.name) + r'"',
            xml_str,
            re.IGNORECASE,
        ):
            progress["failed"][key] = {
                "attempts": progress.get("failed", {}).get(key, {}).get("attempts", 0),
                "reason": "HTML placeholder recorded instead of supplement",
            }
            supplements += 1
    return main_articles, supplements


def pmc_oa_package_urls(pmcid: str) -> List[str]:
    """Return possible HTTPS URLs for the official PMC OA package archive.

    The OA API still returns ftp:// paths for some older packages. NCBI moved
    many of those archives under /pub/pmc/deprecated/ in April 2026, so try both
    the direct HTTPS mirror path and the deprecated mirror path.
    """
    url = pmc_oa_api_url.format(pmcid=pmcid)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        print(f"    OA package lookup failed for {pmcid}: {e}")
        return []

    urls: List[str] = []
    for link in root.findall(".//link"):
        if link.attrib.get("format") != "tgz":
            continue
        href = (link.attrib.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/"):
            rel = href.removeprefix("ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/")
            urls.append(f"https://ftp.ncbi.nlm.nih.gov/pub/pmc/{rel}")
            urls.append(f"https://ftp.ncbi.nlm.nih.gov/pub/pmc/deprecated/{rel}")
        elif href.startswith("https://ftp.ncbi.nlm.nih.gov/pub/pmc/"):
            rel = href.removeprefix("https://ftp.ncbi.nlm.nih.gov/pub/pmc/")
            urls.append(href)
            urls.append(f"https://ftp.ncbi.nlm.nih.gov/pub/pmc/deprecated/{rel}")
        elif href.startswith("http"):
            urls.append(href)

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(urls))


def fetch_pmc_oa_package(pmcid: str) -> Optional[bytes]:
    urls = pmc_oa_package_urls(pmcid)
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if data:
                return data
        except Exception as e:
            print(f"    OA package URL failed for {pmcid}: {url} ({e})")
            continue
    return None


def extract_from_pmc_oa_package(
    pmcid: str,
    planned: List[Tuple[str, str]],
    progress: dict,
) -> set:
    """Extract planned supplement filenames from a PMC OA tarball.

    planned is [(filename, ext), ...]. Returns the set of filenames saved.
    """
    if not planned:
        return set()

    data = fetch_pmc_oa_package(pmcid)
    if not data:
        return set()

    wanted = {filename.lower(): filename for filename, _ in planned}
    saved: set = set()
    paper_dir = os.path.join(supplement_dir, pmcid)
    os.makedirs(paper_dir, exist_ok=True)

    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            members = [m for m in tf.getmembers() if m.isfile()]
            by_basename = {os.path.basename(m.name).lower(): m for m in members}
            for wanted_lower, original_filename in wanted.items():
                member = by_basename.get(wanted_lower)
                if member is None:
                    continue
                extracted = tf.extractfile(member)
                if extracted is None:
                    continue
                out_path = os.path.join(paper_dir, original_filename)
                with open(out_path, "wb") as f:
                    f.write(extracted.read())
                size, short = validate_file(out_path)
                status = "ok_short" if short else "ok"
                reason = "below threshold; recovered from PMC OA package" if short else "recovered from PMC OA package"
                flag_str = " — flagged short" if short else ""
                print(f"    OA package: {original_filename}: {size:,} bytes{flag_str}")
                log_outcome(pmcid, "pmc_oa_package", original_filename, status, size, short, reason)
                progress["downloaded"][f"{pmcid}/{original_filename}"] = {"size": size, "path": out_path}
                progress.get("failed", {}).pop(f"{pmcid}/{original_filename}", None)
                saved.add(original_filename)
    except Exception as e:
        print(f"    OA package extract failed for {pmcid}: {e}")
        return saved

    return saved


def is_browser_verification_page(page) -> bool:
    try:
        title = (page.title() or "").lower()
        body = (page.locator("body").inner_text(timeout=2000) or "").lower()
        return any(
            marker in f"{title}\n{body}"
            for marker in (
                "checking your browser",
                "recaptcha",
                "preparing to download",
                "verify you are human",
            )
        )
    except Exception:
        return False


def wait_for_interactive_verification(page, interactive: bool) -> bool:
    if not is_browser_verification_page(page):
        return True
    if not interactive:
        print("      PMC browser verification required")
        return False
    print("\n      PMC browser verification required.")
    print("      Complete the verification in the Chromium window, then press Enter here.")
    try:
        input()
        return not is_browser_verification_page(page)
    except EOFError:
        print("      Interactive input unavailable")
        return False


def save_browser_download(page, url: str, out_path: str, timeout: int = 60000) -> bool:
    """Navigate to a download URL and save it.

    Chromium sometimes raises "Page.goto: Download is starting" even though
    Playwright has correctly emitted the download event. Treat that navigation
    exception as success and consume the pending download.
    """
    with page.expect_download(timeout=timeout) as dl_info:
        try:
            page.goto(url, wait_until="commit", timeout=min(timeout, 30000))
        except Exception as e:
            if "Download is starting" not in str(e):
                raise
    download = dl_info.value
    download.save_as(out_path)
    with open(out_path, "rb") as f:
        header = f.read(200).lstrip().lower()
    if header.startswith((b"<!doctype", b"<html")):
        os.remove(out_path)
        return False
    return True


def download_file_playwright(
    page,
    context,
    pmcid_num: str,
    filename: str,
    out_path: str,
    interactive_verification: bool = False,
) -> bool:
    """Download a single PMC supplement. PDFs render inline so we fetch them via
    the browser context's request API (reusing PoW cookies)."""
    url = base_url.format(pmcid_num=pmcid_num, filename=filename)
    ext = os.path.splitext(filename)[1].lower()

    # PDFs are served inline by chromium — use request API instead of download event
    if ext == ".pdf":
        try:
            resp = context.request.get(url, timeout=60000)
            if not resp.ok:
                print(f"      HTTP {resp.status}")
                return False
            body = resp.body()
            if body[:20].startswith(b"<!DOCTYPE") or body[:20].startswith(b"<html"):
                return False
            with open(out_path, "wb") as f:
                f.write(body)
            return True
        except Exception as e:
            print(f"      Error: {e}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if not wait_for_interactive_verification(page, interactive_verification):
                return False
            resp = context.request.get(url, timeout=60000)
            if not resp.ok:
                print(f"      HTTP {resp.status}")
                return False
            body = resp.body()
            if body[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                return False
            with open(out_path, "wb") as f:
                f.write(body)
            return True
        except Exception as e:
            print(f"      Error: {e}")
            return False

    try:
        return save_browser_download(page, url, out_path, timeout=60000)
    except Exception as e:
        if is_browser_verification_page(page) and interactive_verification:
            if wait_for_interactive_verification(page, True):
                try:
                    return save_browser_download(page, url, out_path, timeout=60000)
                except Exception as retry_error:
                    print(f"      Error after verification: {retry_error}")
        print(f"      Error: {e}")
        return False


def run_pmc_pass(
    papers: List[str],
    progress: dict,
    allowed_types: Optional[set],
    skip_playwright: bool = False,
    unresolved_only: bool = False,
    headed: bool = False,
    interactive_verification: bool = False,
    playwright_profile: str = "",
) -> None:
    print("\n" + "=" * 70)
    print("Pass 1: PMC supplementary files through OA package and Playwright fallback")
    print("=" * 70)

    plan = []
    if unresolved_only:
        paper_set = set(papers)
        for key in sorted(progress.get("failed", {})):
            if "/" not in key:
                continue
            pmcid, filename = key.split("/", 1)
            if not pmcid.startswith("PMC") or pmcid not in paper_set:
                continue
            ext = os.path.splitext(filename)[1].lower()
            if allowed_types and ext not in allowed_types:
                continue
            plan.append((pmcid, get_pmcid_number(pmcid), filename, ext))
    else:
        for pmcid in papers:
            if not pmcid.startswith("PMC"):
                continue
            pmcid_num = get_pmcid_number(pmcid)
            supplements = fetch_supplement_list_efetch(pmcid_num)
            time.sleep(api_delay)
            if not supplements:
                continue
            for supp in supplements:
                if allowed_types and supp["ext"] not in allowed_types:
                    continue
                key = f"{pmcid}/{supp['filename']}"
                if key in progress["downloaded"]:
                    continue
                plan.append((pmcid, pmcid_num, supp["filename"], supp["ext"]))

    print(f"  {len(plan)} PMC supplement files queued")
    if not plan:
        return

    by_pmcid: Dict[str, List[Tuple[str, str]]] = {}
    for pmcid, pmcid_num_unused, filename, ext in plan:
        by_pmcid.setdefault(pmcid, []).append((filename, ext))

    recovered = set()
    print(f"  Trying official PMC OA packages for {len(by_pmcid)} paper(s)")
    for i, (pmcid, planned) in enumerate(sorted(by_pmcid.items()), 1):
        print(f"  [{i}/{len(by_pmcid)}] {pmcid}: OA package recovery")
        saved = extract_from_pmc_oa_package(pmcid, planned, progress)
        recovered.update(f"{pmcid}/{filename}" for filename in saved)
        save_progress(progress)
        time.sleep(api_delay)

    plan = [
        item for item in plan
        if f"{item[0]}/{item[2]}" not in recovered
        and f"{item[0]}/{item[2]}" not in progress["downloaded"]
    ]
    print(f"  {len(plan)} PMC supplement files still queued for Playwright fallback")
    if not plan:
        return
    if skip_playwright:
        print("  Playwright fallback skipped.")
        return

    with sync_playwright() as p:
        browser = None
        if playwright_profile:
            os.makedirs(playwright_profile, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                playwright_profile,
                headless=not headed,
                accept_downloads=True,
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            browser = p.chromium.launch(headless=not headed)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

        # Solve PoW once — cookies carry over
        first_pmcid_num = plan[0][1]
        try:
            page.goto(f"https://pmc.ncbi.nlm.nih.gov/articles/PMC{first_pmcid_num}/",
                      wait_until="networkidle", timeout=45000)
        except Exception:
            pass
        wait_for_interactive_verification(page, interactive_verification)

        for i, (pmcid, pmcid_num, filename, ext) in enumerate(plan):
            key = f"{pmcid}/{filename}"
            paper_dir = os.path.join(supplement_dir, pmcid)
            os.makedirs(paper_dir, exist_ok=True)
            out_path = os.path.join(paper_dir, filename)

            print(f"  [{i+1}/{len(plan)}] {pmcid} / {filename} ...", end=" ", flush=True)
            ok = download_file_playwright(
                page,
                context,
                pmcid_num,
                filename,
                out_path,
                interactive_verification=interactive_verification,
            )

            if ok:
                size, short = validate_file(out_path)
                if short:
                    print(f"ok ({size:,} bytes) — flagged short")
                    log_outcome(pmcid, "PMC", filename, "ok_short", size, True, "below threshold")
                else:
                    print(f"OK ({size:,} bytes)")
                    log_outcome(pmcid, "PMC", filename, "ok", size, False)
                progress["downloaded"][key] = {"size": size, "path": out_path}
                progress.get("failed", {}).pop(key, None)
            else:
                print("failed")
                log_outcome(pmcid, "PMC", filename, "failed", 0, True, "download error")
                progress["failed"][key] = {
                    "attempts": progress.get("failed", {}).get(key, {}).get("attempts", 0) + 1
                }

            if (i + 1) % 10 == 0:
                save_progress(progress)
            time.sleep(1)

        if browser is not None:
            browser.close()
        else:
            context.close()


# Pass 2: Europe PMC supplementary files endpoint
def run_europepmc_pass(papers: List[str], progress: dict, allowed_types: Optional[set]) -> None:
    print("\n" + "=" * 70)
    print("Pass 2: Europe PMC supplementary files")
    print("=" * 70)

    metadata = load_download_summary()
    fetched_for = 0
    for paper_key in papers:
        # Still try Europe PMC even if PMC found files; it can expose additional supplements.
        url = None
        request_key = paper_key
        if paper_key.startswith("PMC"):
            pmcid_num = get_pmcid_number(paper_key)
            url = europe_pmc_supp_url.format(pmcid_num=pmcid_num)
        else:
            meta = metadata.get(paper_key, {})
            record = europepmc_search_record(meta)
            if record:
                source = (record.get("source") or "").strip()
                ext_id = (record.get("id") or record.get("pmid") or "").strip()
                pmcid = (record.get("pmcid") or "").strip()
                if pmcid:
                    url = europe_pmc_supp_url.format(pmcid_num=get_pmcid_number(pmcid))
                elif source and ext_id:
                    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{urllib.parse.quote(source)}/{urllib.parse.quote(ext_id)}/supplementaryFiles"
            if not url:
                continue

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=europe_pmc_timeout_sec) as r:
                data = r.read()
        except Exception as e:
            print(f"  {request_key}: EPMC fetch failed: {e}")
            log_outcome(request_key, "EuropePMC", "(zip)", "failed", 0, True, str(e))
            time.sleep(api_delay)
            continue

        if not data or len(data) < 200:
            time.sleep(api_delay)
            continue

        paper_dir = os.path.join(supplement_dir, request_key)
        os.makedirs(paper_dir, exist_ok=True)
        saved = 0
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    if allowed_types and ext and ext not in allowed_types:
                        continue
                    filename = os.path.basename(name)
                    out_path = os.path.join(paper_dir, filename)
                    with open(out_path, "wb") as f:
                        f.write(zf.read(name))
                    size, short = validate_file(out_path)
                    status = "ok_short" if short else "ok"
                    reason = "below threshold" if short else ""
                    log_outcome(request_key, "EuropePMC", filename, status, size, short, reason)
                    progress["downloaded"][f"{request_key}/{filename}"] = {"size": size, "path": out_path}
                    saved += 1
            if saved > 0:
                fetched_for += 1
                print(f"  {request_key}: saved {saved} EPMC supplements")
        except zipfile.BadZipFile:
            print(f"  {request_key}: EPMC response not a valid zip ({len(data)} bytes)")
            log_outcome(request_key, "EuropePMC", "(zip)", "failed", len(data), True, "not a zip")

        time.sleep(api_delay)

    print(f"  EPMC pass: supplements fetched for {fetched_for} paper(s)")


# Pass 3: Elsevier by parsing downloaded article XMLs
def parse_elsevier_supplement_refs(xml_path: str) -> List[Dict[str, str]]:
    """Find supplement file references in an Elsevier article XML.

    Defensive parse — Elsevier puts supplement refs in several places depending on
    journal:
      - <ce:e-component> with @xlink:href or child <ce:link>
      - <xocs:attachment> with @filename, @ref-type
      - <ce:object-ref> with @xlink:href
    Returns [{href, filename}] (either or both may be empty).
    """
    refs: List[Dict[str, str]] = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception:
        return refs

    seen = set()
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag not in ("e-component", "attachment", "object-ref", "object"):
            continue

        attrs = elem.attrib
        # Elsevier's API exposes downloadable supplement objects directly as
        # element text. Keep APPLICATION objects, but exclude the accepted
        # manuscript/main article PDF.
        object_type = (attrs.get("type") or "").upper()
        object_text = (elem.text or "").strip()
        if tag == "object" and object_type == "APPLICATION" and object_text.startswith("http"):
            filename = os.path.basename(urllib.parse.urlparse(object_text).path)
            key = (object_text, filename)
            if key not in seen:
                seen.add(key)
                refs.append({"href": object_text, "filename": filename})
            continue

        href = (
            attrs.get("{http://www.w3.org/1999/xlink}href")
            or attrs.get("href")
            or attrs.get("eid")
            or attrs.get("refid")
            or ""
        )
        filename = attrs.get("filename") or attrs.get("name") or ""

        # Look through children for filename / link tags
        for child in elem.iter():
            ctag = child.tag.split("}")[-1]
            if ctag in ("filename", "label", "caption") and child.text:
                t = child.text.strip()
                if not filename and "." in t and len(t) < 200:
                    filename = t
            if ctag == "link":
                lh = child.attrib.get("{http://www.w3.org/1999/xlink}href")
                if lh and not href:
                    href = lh

        if not href and not filename:
            continue
        key = (href, filename)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"href": href, "filename": filename})

    return refs


def fetch_elsevier_article_xml(doi: str) -> Optional[str]:
    url = f"https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi, safe='')}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "X-ELS-APIKey": elsevier_api_key,
                "Accept": "application/xml",
                "User-Agent": "Mozilla/5.0",
            },
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Elsevier article XML fetch failed for {doi}: {e}")
        return None


def reconcile_publisher_attachments(paper_key: str, downloaded_filenames: List[str], progress: dict) -> int:
    """Clear old PMC-name failures when publisher attachments cover them by type.

    Publisher APIs often rename NIHMS supplement files to mmc1/mmc2/etc. Match
    conservatively by extension and only clear as many failures as were actually
    downloaded from the publisher.
    """
    available: Dict[str, int] = {}
    for filename in downloaded_filenames:
        ext = os.path.splitext(filename)[1].lower()
        available[ext] = available.get(ext, 0) + 1

    moved = 0
    prefix = f"{paper_key}/"
    for key in list(progress.get("failed", {})):
        if not key.startswith(prefix):
            continue
        original_filename = key.split("/", 1)[1]
        ext = os.path.splitext(original_filename)[1].lower()
        if available.get(ext, 0) <= 0:
            continue
        progress["failed"].pop(key, None)
        progress["publisher_recovered"][key] = {
            "reason": f"publisher attachment recovered under a different {ext or 'file'} filename"
        }
        available[ext] -= 1
        moved += 1
    return moved


def publisher_supplement_links(doi: str, allowed_types: Optional[set]) -> List[str]:
    """Return clearly supplementary direct-file links from a publisher page."""
    try:
        req = urllib.request.Request(
            f"https://doi.org/{urllib.parse.quote(doi, safe='/')}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            final_url = r.geturl()
            page = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Publisher page fetch failed for {doi}: {e}")
        return []

    links: List[str] = []
    for match in re.finditer(r'href=["\']([^"\']+)["\']', page, re.IGNORECASE):
        href = html.unescape(match.group(1))
        url = urllib.parse.urljoin(final_url, href)
        lower = url.lower()
        path = urllib.parse.urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        if not ext or (allowed_types and ext not in allowed_types):
            continue
        clearly_supplementary = (
            "static-content.springer.com/esm/" in lower
            or any(token in lower for token in ("supplement", "supp-", "suppl", "/esm/", "moesm", "/mmc", "additional"))
        )
        if clearly_supplementary:
            links.append(url)
    return list(dict.fromkeys(links))


def run_publisher_pass(papers: List[str], progress: dict, allowed_types: Optional[set]) -> None:
    print("\n" + "=" * 70)
    print("Pass 3: publisher-page supplementary files")
    print("=" * 70)

    metadata = load_download_summary()
    for index, paper_key in enumerate(papers, 1):
        meta = metadata.get(paper_key, {})
        doi = (meta.get("doi") or "").strip()
        if not doi:
            continue
        links = publisher_supplement_links(doi, allowed_types)
        if not links:
            continue
        print(f"  [{index}/{len(papers)}] {paper_key}: {len(links)} publisher supplement link(s)")
        paper_dir = os.path.join(supplement_dir, paper_key)
        os.makedirs(paper_dir, exist_ok=True)
        downloaded_filenames: List[str] = []
        for url in links:
            filename = os.path.basename(urllib.parse.urlparse(url).path)
            key = f"{paper_key}/{filename}"
            if key in progress["downloaded"]:
                downloaded_filenames.append(filename)
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                if not data or data[:20].lstrip().lower().startswith((b"<!doctype", b"<html")):
                    continue
                out_path = os.path.join(paper_dir, filename)
                with open(out_path, "wb") as f:
                    f.write(data)
                size, short = validate_file(out_path)
                status = "ok_short" if short else "ok"
                reason = "below threshold; publisher page" if short else "publisher page"
                print(f"    {filename}: {size:,} bytes")
                log_outcome(paper_key, "PublisherPage", filename, status, size, short, reason)
                progress["downloaded"][key] = {"size": size, "path": out_path}
                downloaded_filenames.append(filename)
            except Exception as e:
                print(f"    {filename}: publisher fetch failed: {e}")
            time.sleep(api_delay)

        reconciled = reconcile_publisher_attachments(paper_key, downloaded_filenames, progress)
        if reconciled:
            print(f"  {paper_key}: reconciled {reconciled} prior PMC-name failure(s)")
        save_progress(progress)


def parse_elsevier_supplement_refs_text(xml_text: str) -> List[Dict[str, str]]:
    cache_dir = os.path.join(supplement_dir, "_elsevier_xml_cache")
    os.makedirs(cache_dir, exist_ok=True)
    temp_path = os.path.join(cache_dir, f"article_{abs(hash(xml_text))}.xml")
    try:
        Path(temp_path).write_text(xml_text, encoding="utf-8")
        return parse_elsevier_supplement_refs(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def run_elsevier_pass(papers: List[str], progress: dict, allowed_types: Optional[set]) -> None:
    print("\n" + "=" * 70)
    print("Pass 3: Elsevier supplementary files through the TDM API")
    print("=" * 70)

    if not elsevier_api_key:
        print("  elsevier_api_key not set in environment; skipping pass.")
        return

    # Identify Elsevier-saved XMLs and PMC papers with Elsevier DOIs.
    if not os.path.isdir(papers_dir):
        print(f"  {papers_dir}/ not found; nothing to scan.")
        return
    metadata = load_download_summary()
    targets: List[Tuple[str, List[Dict[str, str]]]] = []
    for fname in sorted(os.listdir(papers_dir)):
        if not fname.endswith(".xml"):
            continue
        base = fname[:-4]
        if base.startswith("PMC"):
            continue
        meta = metadata.get(base, {})
        if metadata and (meta.get("source") or "").lower() != "elsevier":
            continue
        refs = parse_elsevier_supplement_refs(os.path.join(papers_dir, fname))
        targets.append((base, refs))

    for paper_key in papers:
        if not paper_key.startswith("PMC"):
            continue
        meta = metadata.get(paper_key, {})
        doi = (meta.get("doi") or "").strip()
        if not doi.startswith("10.1016/"):
            continue
        xml_text = fetch_elsevier_article_xml(doi)
        if not xml_text:
            continue
        refs = parse_elsevier_supplement_refs_text(xml_text)
        targets.append((paper_key, refs))
        time.sleep(api_delay)

    if not targets:
        print("  No Elsevier supplement targets detected.")
        return

    print(f"  Scanning {len(targets)} Elsevier article(s) for supplement refs...")

    for doi_key, refs in targets:
        if not refs:
            print(f"  {doi_key}: no supplement refs in XML")
            continue

        paper_dir = os.path.join(supplement_dir, doi_key)
        os.makedirs(paper_dir, exist_ok=True)
        print(f"  {doi_key}: {len(refs)} supplement ref(s)")
        downloaded_filenames: List[str] = []

        for ref in refs:
            href = (ref.get("href") or "").strip()
            if href.startswith("pii:"):
                # Elsevier also supplies a direct downloadable object URL for
                # these internal references. The internal form returns HTTP 400.
                continue
            filename = (ref.get("filename") or "").strip()
            if not filename and href:
                filename = href.rsplit("/", 1)[-1]
            if not filename:
                filename = f"elsevier_supp_{abs(hash(href)) % 10**8}.bin"
            ext = os.path.splitext(filename)[1].lower()
            if allowed_types and ext and ext not in allowed_types:
                continue
            progress_key = f"{doi_key}/{filename}"
            if progress_key in progress["downloaded"]:
                downloaded_filenames.append(filename)
                continue

            # Resolve URL
            if href.startswith("http"):
                url = href
            elif href:
                url = f"https://api.elsevier.com/content/object/eid/{urllib.parse.quote(href)}"
            else:
                log_outcome(doi_key, "Elsevier", filename, "failed", 0, True, "no href / eid")
                continue

            out_path = os.path.join(paper_dir, filename)
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "X-ELS-APIKey": elsevier_api_key,
                        "Accept": "*/*",
                        "User-Agent": "Mozilla/5.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
            except Exception as e:
                print(f"    {filename}: Elsevier fetch failed: {e}")
                log_outcome(doi_key, "Elsevier", filename, "failed", 0, True, str(e))
                time.sleep(api_delay)
                continue

            if not data:
                log_outcome(doi_key, "Elsevier", filename, "failed", 0, True, "empty response")
                continue

            with open(out_path, "wb") as f:
                f.write(data)
            size, short = validate_file(out_path)
            status = "ok_short" if short else "ok"
            reason = "below threshold" if short else ""
            flag_str = " — flagged short" if short else ""
            print(f"    {filename}: {size:,} bytes{flag_str}")
            log_outcome(doi_key, "Elsevier", filename, status, size, short, reason)
            progress["downloaded"][f"{doi_key}/{filename}"] = {"size": size, "path": out_path}
            downloaded_filenames.append(filename)
            time.sleep(api_delay)

        reconciled = reconcile_publisher_attachments(doi_key, downloaded_filenames, progress)
        if reconciled:
            print(f"  {doi_key}: reconciled {reconciled} prior PMC-name failure(s)")
        save_progress(progress)


# Main
def main():
    parser = argparse.ArgumentParser(description="Download supplements (PMC + EPMC + Elsevier)")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of papers")
    parser.add_argument("--pmcid", type=str, default="", help="Single PMCID to process")
    parser.add_argument(
        "--types", type=str, default="",
        help="Comma-separated extensions (e.g., xlsx,docx). Default: xlsx,xls,docx,doc,csv,txt,pdf",
    )
    parser.add_argument("--all-types", action="store_true", help="Download all file types")
    parser.add_argument("--skip-pmc", action="store_true", help="Skip PMC pass")
    parser.add_argument("--skip-playwright", action="store_true", help="Use PMC OA packages only; skip browser fallback")
    parser.add_argument("--headed", action="store_true", help="Show the Playwright Chromium window")
    parser.add_argument(
        "--interactive-verification",
        action="store_true",
        help="Pause so browser verification can be completed manually",
    )
    parser.add_argument(
        "--playwright-profile",
        default="playwright_pmc_profile",
        help="Persistent Chromium profile directory for PMC verification cookies",
    )
    parser.add_argument("--skip-europepmc", action="store_true", help="Skip Europe PMC pass")
    parser.add_argument("--skip-elsevier", action="store_true", help="Skip Elsevier pass")
    parser.add_argument("--skip-publisher", action="store_true", help="Skip publisher-page supplement links")
    parser.add_argument(
        "--unresolved-only",
        action="store_true",
        help="Process only file/paper keys currently listed in _progress.json failed entries",
    )
    args = parser.parse_args()

    allowed_types: Optional[set]
    if args.all_types:
        allowed_types = None
    elif args.types:
        allowed_types = {"." + t.strip(".") for t in args.types.split(",")}
    else:
        allowed_types = default_types

    os.makedirs(supplement_dir, exist_ok=True)
    progress = load_progress()
    placeholder_main, placeholder_supp = reconcile_html_placeholders(progress)
    if placeholder_main or placeholder_supp:
        print(
            f"Reconciled HTML placeholders: {placeholder_main} main article PDF(s), "
            f"{placeholder_supp} supplement(s) re-queued."
        )
        save_progress(progress)
    exact_reconciled = reconcile_exact_downloads(progress)
    if exact_reconciled:
        print(f"Reconciled {exact_reconciled} stale failure(s) with exact downloaded files.")
        save_progress(progress)
    reclassified = classify_existing_main_article_pdfs(progress)
    if reclassified:
        print(f"Reclassified {reclassified} main article PDF(s) as not supplements.")
        save_progress(progress)

    if not os.path.isdir(papers_dir):
        sys.exit(f"Papers directory not found: {papers_dir}. Run 04_download_papers.py first.")

    # Discover papers: file stems of XML/HTML/PDF in downloaded_papers/
    if args.pmcid:
        papers = [args.pmcid]
    elif args.unresolved_only:
        papers = sorted({
            key.split("/", 1)[0]
            for key in progress.get("failed", {})
            if "/" in key
        })
    else:
        stems = set()
        for f in os.listdir(papers_dir):
            if f.endswith((".xml", ".html", ".pdf")):
                stems.add(os.path.splitext(f)[0])
        papers = sorted(stems)

    if args.limit:
        papers = papers[: args.limit]

    print(f"Papers to scan: {len(papers)}")
    print(f"Allowed types: {sorted(allowed_types) if allowed_types else 'ALL'}")
    print(f"Elsevier API key set: {bool(elsevier_api_key)}")

    if not args.skip_pmc:
        run_pmc_pass(
            papers,
            progress,
            allowed_types,
            skip_playwright=args.skip_playwright,
            unresolved_only=args.unresolved_only,
            headed=args.headed,
            interactive_verification=args.interactive_verification,
            playwright_profile=args.playwright_profile,
        )
        save_progress(progress)

    if not args.skip_europepmc:
        run_europepmc_pass(papers, progress, allowed_types)
        save_progress(progress)

    if not args.skip_publisher:
        run_publisher_pass(papers, progress, allowed_types)
        save_progress(progress)

    if not args.skip_elsevier:
        run_elsevier_pass(papers, progress, allowed_types)
        save_progress(progress)

    save_progress(progress)
    write_report(progress)
    write_final_audit(progress)

    dl_count = len(progress["downloaded"])
    fail_count = len(progress["failed"])
    short_count = sum(1 for r in report_rows if r["ShortFlag"] and r["Status"].startswith("ok"))
    print("\n" + "=" * 70)
    print("Final summary")
    print("=" * 70)
    print(f"  Files downloaded:     {dl_count}")
    print(f"  Files failed:         {fail_count}")
    print(f"  Files flagged short:  {short_count}  (saved but suspiciously small)")
    print(f"  Report:               {report_file}")


if __name__ == "__main__":
    main()
