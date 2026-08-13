import os
import time
import json
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ChunkedEncodingError, RequestException
from urllib3.exceptions import ProtocolError
from urllib3.util.retry import Retry


def first_existing(paths):
    for path in paths:
        if path and os.path.exists(os.path.expanduser(path)):
            return os.path.expanduser(path)
    return os.path.expanduser(paths[-1])


input_xlsx = first_existing([
    os.environ.get("geo_metadata_input", ""),
    "gse_metadata_full_checkpoint_merged.xlsx",
    "gse_metadata_full_checkpoint.xlsx",
    "gse_metadata_full.xlsx",
    "geo_master_access.xlsx",
])
sheet_name = os.environ.get("geo_metadata_sheet", "Metadata")
output_xlsx = os.environ.get("pipeline_excel_file", "geo_master_access.xlsx")
unpaywall_email = os.environ.get("unpaywall_email", "").strip()
if not unpaywall_email:
    raise SystemExit("unpaywall_email is required. Add it to .env before running this step.")
ncbi_tool = "geo_oa_counter"
ncbi_email = unpaywall_email

ncbi_sleep = 0.34
unpaywall_sleep = 0.2
allow_nc = False  # set True only if PI/librarian approves non-commercial use


def make_session():
    retry_kwargs = {
        "total": 6,
        "connect": 6,
        "read": 6,
        "backoff_factor": 0.6,
        "status_forcelist": [429, 500, 502, 503, 504],
    }
    try:
        retry = Retry(allowed_methods=["GET", "HEAD"], **retry_kwargs)
    except TypeError:
        retry = Retry(method_whitelist=["GET", "HEAD"], **retry_kwargs)
    session = requests.Session()
    session.headers.update({
        "User-Agent": f"geo-oa-counter/1.0 (+contact: {unpaywall_email})",
        "Connection": "close",
    })
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


session = make_session()


def safe_get(url, params=None, timeout=30, sleep_after=0.2):
    def send_request():
        return session.get(url, params=params, timeout=timeout,
                           allow_redirects=True, stream=False)

    for attempt in range(1, 5):
        try:
            r = send_request()
            _ = r.content  # force load now to catch chunk errors
            if r.status_code in (429, 500, 502, 503, 504):
                wait = min(5 * attempt, 30)
                print(f"[warn] {r.status_code} {url} – backing off {wait}s (try {attempt})")
                time.sleep(wait)
                continue
            if sleep_after:
                time.sleep(sleep_after)
            return r
        except (ChunkedEncodingError, ProtocolError, RequestException) as exc:
            wait = min(3 * attempt, 15)
            print(f"[warn] network error {url}: {exc} – retry in {wait}s (try {attempt})")
            time.sleep(wait)

    print(f"[error] giving up on {url}")
    return None


def safe_json(response):
    if response is None:
        return {}
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        return {}


def norm_str(x):
    if pd.isna(x): return ""
    s = str(x).strip()
    try:
        if "e+" in s.lower():
            return str(int(float(s)))
    except Exception:
        pass
    return s


def map_pmid_to_pmcid_via_idconv(pmid):
    """
    Preferred: NCBI ID Converter (stable for PMID→PMCID).
    Returns (pmcid, in_pmc)
    """
    if not pmid:
        return ("", False)
    url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    params = {"ids": pmid, "format": "json"}
    r = safe_get(url, params=params, timeout=30, sleep_after=ncbi_sleep)
    if not r or r.status_code != 200:
        return ("", False)
    data = safe_json(r) or {}
    recs = data.get("records", [])
    if not recs:
        return ("", False)
    pmcid = recs[0].get("pmcid", "") or ""
    return (pmcid, bool(pmcid))


def map_pmid_to_pmcid_via_elink(pmid):
    """
    Fallback: eLink PMID -> PMCID.
    Handles both dict links ({"id":"11303482"}) and string links.
    Returns (pmcid, in_pmc)
    """
    if not pmid:
        return ("", False)
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
    params = {
        "dbfrom": "pubmed",
        "db": "pmc",
        "id": pmid,
        "tool": ncbi_tool,
        "email": ncbi_email,
        "retmode": "json",
    }
    r = safe_get(url, params=params, timeout=30, sleep_after=ncbi_sleep)
    if not r or r.status_code != 200:
        return ("", False)
    data = safe_json(r) or {}
    linksets = (data.get("linksets") or [{}])[0].get("linksetdbs", [])
    pmcid = ""
    for db in linksets:
        if db.get("dbto") == "pmc":
            for link in db.get("links", []):
                if isinstance(link, dict) and "id" in link:
                    pmcid = "PMC" + str(link["id"])
                    break
                if isinstance(link, str):
                    pmcid = link if link.upper().startswith("PMC") else "PMC" + link
                    break
        if pmcid:
            break
    return (pmcid, bool(pmcid))


def is_pmc_open_access_subset(pmcid, max_tries=4):
    if not pmcid:
        return False
    oai_url = "https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi"
    params = {
        "verb": "GetRecord",
        "metadataPrefix": "pmc",
        "identifier": f"oai:pubmedcentral.nih.gov:{pmcid.replace('PMC','')}",
    }
    for attempt in range(1, max_tries+1):
        fx = safe_get(oai_url, params=params, timeout=45, sleep_after=ncbi_sleep)
        if fx and fx.status_code == 200:
            txt = fx.text
            if "<setSpec>pmc-open</setSpec>" in txt:
                return True
            return False   # confidently not in OA subset
        time.sleep(1.5 * attempt)
    return None  # unknown (don't mark as False)


def unpaywall_lookup(doi, email):
    if not doi:
        return {"unpaywall_oa_status": "", "best_oa_url": "", "license": ""}
    url = f"https://api.unpaywall.org/v2/{doi}"
    r = safe_get(url, params={"email": email}, timeout=30, sleep_after=unpaywall_sleep)
    if not r or r.status_code != 200:
        return {"unpaywall_oa_status": "", "best_oa_url": "", "license": ""}
    d = safe_json(r)
    best = d.get("best_oa_location") or {}
    return {
        "unpaywall_oa_status": (d.get("oa_status") or ""),
        "best_oa_url": best.get("url_for_pdf") or best.get("url") or "",
        "license": best.get("license") or d.get("license") or "",
    }


def permissive(license_str, allow_nc=False):
    s = (license_str or "").lower()
    allowed = ["cc-by", "cc by", "cc0", "public domain"]
    if allow_nc:
        allowed += ["cc-by-nc", "cc by-nc", "cc by nc"]
    return any(tag in s for tag in allowed)


def decide_ok(pmc_oa_subset, oa_status, license_str, allow_nc=False):
    if pmc_oa_subset is True:
        return True
    if pmc_oa_subset is None:
        return None  # unknown – retry later
    if (oa_status or "").lower() in {"gold", "hybrid", "green"} and permissive(license_str, allow_nc=allow_nc):
        return True
    return False
print(f"Reading GEO/access input workbook: {input_xlsx}")
try:
    df = pd.read_excel(input_xlsx, sheet_name=sheet_name)
except ValueError:
    df = pd.read_excel(input_xlsx, sheet_name=0)

# Try to discover identifier columns by header text. 01_extract_geo_metadata.R writes PMID/PMCID/DOI;
# older hand sheets may use doi (link).
def find_col(exact=None, contains=None):
    for c in df.columns:
        name = str(c).strip().lower()
        if exact and name == exact:
            return c
        if contains and contains in name:
            return c
    return None

col_pmid = find_col(exact="pmid")
col_doi = find_col(exact="doi") or find_col(contains="doi")
col_pmc_existing = find_col(exact="pmcid")

if col_pmid is None:
    df["pmid"] = ""
    col_pmid = "pmid"
if col_doi is None:
    df["doi"] = ""
    col_doi = "doi"
if col_pmc_existing is None:
    df["pmcid"] = ""
    col_pmc_existing = "pmcid"

# Canonical lowercase columns used by later Python steps.
df["pmid"] = df[col_pmid].map(norm_str)
df["doi"] = df[col_doi].map(norm_str)
df["pmcid"] = df[col_pmc_existing].map(norm_str)

# Normalize IDs ahead of lookups
df["PMID_norm"] = df["pmid"]
df["DOI_norm"] = df["doi"]

df["has_pmid"] = df["PMID_norm"].ne("")
df["has_doi"] = df["DOI_norm"].ne("")

# Initialize output columns
df["in_pmc"] = False

# Tri-state column (True / False / None) so we can represent "unknown"
df["pmc_oa_subset"] = pd.Series([None] * len(df), dtype="object")

df["unpaywall_oa_status"] = ""
df["best_oa_url"] = ""
df["license"] = ""

# Also tri-state for OK (True/False/None) so unknowns don't get counted as False
df["ok_to_text_mine"] = pd.Series([None] * len(df), dtype="object")

# Look up PMC for PMIDs
for ctr, (i, row) in enumerate(df[df["has_pmid"]].iterrows(), start=1):
    # Check if we already have a PMCID value
    pmcid_existing = norm_str(row[col_pmc_existing]) if col_pmc_existing else ""
    if pmcid_existing:
        pmcid, in_pmc = pmcid_existing, True
    else:
        pmcid, in_pmc = map_pmid_to_pmcid_via_idconv(row["PMID_norm"])
        if not in_pmc:
            pmcid, in_pmc = map_pmid_to_pmcid_via_elink(row["PMID_norm"])

    df.loc[i, "pmcid"] = pmcid
    df.loc[i, "in_pmc"] = in_pmc
    df.loc[i, "pmc_oa_subset"] = is_pmc_open_access_subset(pmcid) if in_pmc else False

    if ctr % 200 == 0:
        df.to_excel(os.path.splitext(output_xlsx)[0] + "_checkpoint.xlsx", index=False)

# Look up OA/license for DOIs
for ctr, (i, row) in enumerate(df[df["has_doi"]].iterrows(), start=1):
    info = unpaywall_lookup(row["DOI_norm"], unpaywall_email)
    for k, v in info.items():
        df.loc[i, k] = v
    if ctr % 200 == 0:
        df.to_excel(os.path.splitext(output_xlsx)[0] + "_checkpoint.xlsx", index=False)

# Determine mining eligibility with the new metadata
df["ok_to_text_mine"] = df.apply(
    lambda r: decide_ok(r["pmc_oa_subset"], r["unpaywall_oa_status"], r["license"], allow_nc=allow_nc),
    axis=1
)

total = len(df)
with_pmid = int(df["has_pmid"].sum())
with_doi = int(df["has_doi"].sum())
with_both = int((df["has_pmid"] & df["has_doi"]).sum())
in_pmc_any = int(df["in_pmc"].sum())
in_pmc_oa = int((df["pmc_oa_subset"] == True).sum())  # count only True values
ok_total = int((df["ok_to_text_mine"] == True).sum())  # count only True values
unknown_oa = int(df["pmc_oa_subset"].isna().sum())    # count None/unknown values
unknown_ok = int(df["ok_to_text_mine"].isna().sum())  # count None/unknown values

print(f"Total rows: {total}")
print(f"Has PMID: {with_pmid}")
print(f"Has DOI: {with_doi}")
print(f"Has PMID + DOI: {with_both}")
print("--- Access summary ---")
print(f"In PMC (any): {in_pmc_any}")
print(f"In PMC Open Access subset: {in_pmc_oa}")
print(f"PMC OA status unknown: {unknown_oa}")
print(f"Accessible for LLM (final OK): {ok_total}")
print(f"Mining status unknown: {unknown_ok}")

df.to_excel(output_xlsx, index=False)
print(f"Wrote: {output_xlsx}")
