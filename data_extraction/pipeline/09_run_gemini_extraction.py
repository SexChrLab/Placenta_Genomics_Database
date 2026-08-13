#!/usr/bin/env python3
"""
Bulk LLM annotation pipeline for placental papers.

For every PMCID in processed_papers.json, asks an LLM to extract the
metadata listed in json_structure. The model sees:
  - full paper text (with HTML/Elsevier fallbacks)
  - all supplementary files (.docx/.xlsx/.pdf parsed by lib.supplements)
and is asked to back each answer with a quote + source (evidence schema).

The Excel template gets only the final "answer" per question (one cell each).
Full JSON with reason, evidence, and confidence is saved to raw_outputs/ for audit.

Usage:
  source .venv/bin/activate
  export gemini_api_key="<required>"
  export elsevier_api_key="<optional>"
  python pipeline/09_run_gemini_extraction.py
"""

from __future__ import annotations

import json
import os
import pathlib
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import pandas as pd

# project libs
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lib.models import call_model, parse_json  # noqa: E402
from lib.paper_text import paper_text_lookup  # noqa: E402
from lib.supplements import load_supplements  # noqa: E402

# config
input_json_file = "processed_papers.json"
excel_template_file = os.environ.get("pipeline_excel_file", "geo_master_access.xlsx")
output_excel_file = "ai_annotated.xlsx"

# which model(s) to run. one => single-model output (default).
# multiple => one column-suffix per model in the xlsx.
models: List[str] = [os.environ.get("gemini_model", "gemini-3.5-flash")]

# pacing + retry
request_interval_sec = 1.0
llm_workers = max(1, int(os.environ.get("llm_workers", "1")))
backoff_jitter = (0.0, 0.6)
backoff_cap_sec = 60.0

# resume behavior
overwrite = False                # if False, skip PMCID with a complete cache file
resume_requires_all_fields = True  # if a cached result is missing any field, re-do
prompt_version = "paper_only_v3_no_geo_context"

# supplements + paper-text
use_supplements = True
paper_char_cap = int(os.environ.get("paper_char_cap", "0"))  # 0 means no cap
supplement_min_useful_chars = 1000  # below this we suspect the supplement is a stub w/ no real metadata

# output paths
output_raw_dir = "raw_outputs"
save_prompt_per_paper = True

# failures collected during the run (PMCIDs/GEO IDs we couldn't process)
failures_log: List[Dict[str, Any]] = []


def log_failure(pmcid: str, geo_id: str, stage: str, detail: str) -> None:
    failures_log.append({
        "PaperKey": pmcid or "",
        "PMCID": pmcid or "",
        "GEO_ID": geo_id or "",
        "Stage": stage,
        "Detail": detail,
    })


def merge_download_reports(geo_by_key: Dict[str, str]) -> None:
    """Pull short-flagged + failed entries from the download phase CSVs into the
    Failures log so they show up alongside LLM-time issues in one sheet."""
    import csv as csv_reader

    # 1) Per-supplement-file report from 05_download_supplements.py
    suppl_report = pathlib.Path("downloaded_supplements") / "_report.csv"
    if suppl_report.exists():
        try:
            with open(suppl_report, encoding="utf-8") as f:
                for row in csv_reader.DictReader(f):
                    status = (row.get("Status") or "").strip()
                    short = (row.get("ShortFlag") or "").strip().lower() in ("true", "1", "yes")
                    if status == "ok" and not short:
                        continue  # nothing to flag
                    paper_key = (row.get("PaperKey") or "").strip()
                    geo_id = geo_by_key.get(paper_key, "")
                    stage = ("supplement_download_failed" if status == "failed"
                             else "supplement_download_short")
                    detail = (f"{row.get('Source', '?')}: {row.get('Filename', '?')} "
                              f"({row.get('Bytes', '?')} bytes)"
                              + (f" — {row['Reason']}" if row.get('Reason') else ""))
                    log_failure(paper_key, geo_id, stage, detail)
        except Exception as e:
            print(f"  warning: could not read supplements report: {e}")
    else:
        print(f"  (no {suppl_report} found — supplement download report not merged)")

    # 2) Paper-level report from 04_download_papers.py
    paper_report = pathlib.Path("downloaded_papers") / "download_summary.csv"
    if paper_report.exists():
        try:
            with open(paper_report, encoding="utf-8") as f:
                for row in csv_reader.DictReader(f):
                    status = (row.get("status") or "").strip()
                    short = (row.get("short_flag") or "").strip().lower() in ("true", "1", "yes")
                    paper_key = (row.get("pmcid") or "").strip()
                    if not paper_key:
                        doi = (row.get("doi") or "").strip()
                        paper_key = sanitize_paper_key(doi) if doi else ""
                    if status == "ok" and not short:
                        continue
                    if status != "ok":
                        stage = "paper_download_failed"
                    else:
                        stage = "paper_download_short"
                    geo_id = geo_by_key.get(paper_key, "")
                    detail = (f"{row.get('source', '?')} {row.get('format', '?')}; "
                              f"{row.get('bytes', '?')} bytes"
                              + (f"; {row['notes']}" if row.get('notes') else ""))
                    log_failure(paper_key, geo_id, stage, detail)
        except Exception as e:
            print(f"  warning: could not read paper download report: {e}")
    else:
        print(f"  (no {paper_report} found — paper download report not merged)")

# treat these status codes as retryable (kept for old caller; lib.models has its own retry)
retryable_status_codes = {429, 500, 502, 503, 504}

# extraction schema (one entry per question; key = column name in output xlsx)

json_structure: Dict[str, Any] = {
  "Supervisor/Contact/Corresponding author name": "Find the designated corresponding author. If not explicit, use the last author.",
  "Supervisor/Contact/Corresponding author email": "Find the corresponding author's email.",
  "Main topic of the publication": "A brief, 1-2 sentence summary of the paper's main topic.",
  "Sampling timing during pregnancy": (
    "Report when samples were collected during pregnancy using the terminology used by the paper and appropriate for the organism studied. "
    "Do not force all organisms into human trimester categories. Do not convert timing terms across species unless the paper explicitly does so. "
    "If the paper reports multiple species or multiple collection time points, list each clearly using the paper's language."
  ),
  "Samples collected at single pregnancy time point (yes/no)": "Yes if all pregnancy samples were collected at one reported time point; No if multiple time points/stages are studied.",
  "Offspring delivered before sample collection (yes/no/not applicable)": (
    "Return Yes if offspring/neonates were delivered before sample collection. Return No if embryos/fetuses/placentas were collected before delivery or by dissection. "
    "Return Not applicable for non-pregnancy models or if impossible to determine."
  ),
  "Birthweight of offspring provided (yes/no)": "Yes or No.",
  "Weight of offspring/fetus at sample collection provided (yes/no)": "Yes if fetal, embryo, pup, offspring, or conceptus weight at the collection time is provided; otherwise No.",
  "Gestational Age at delivery provided (yes/no)": "Yes or No.",
  "Gestational Age at sample collection provided (yes/no)": "Yes or No.",
  "Sex of Offspring Provided (yes/no)": "Yes or No.",
  "Parity provided (yes/no)": "Yes or No.",
  "Gravidity provided (yes/no)": "Yes or No.",
  "Number of offspring per pregnancy provided (yes/no)": "Yes or No.",
  "Self-reported race/ethnicity of mother provided (yes/no)": "Yes or No.",
  "Genetic ancestry or genetic strain provided (yes/no)": "Yes or No.",
  "Maternal Height provided (yes/no)": "Yes or No.",
  "Maternal Pre-pregnancy Weight provided (yes/no)": "Yes or No.",
  "Maternal pre-pregnancy BMI provided (yes/no)": "Yes or No.",
  "Paternal Height provided (yes/no)": "Yes or No.",
  "Paternal Weight provided (yes/no)": "Yes or No.",
  "Maternal age at sample collection provided (yes/no)": "Yes or No.",
  "Paternal age at sample collection provided (yes/no)": "Yes or No.",
  "Samples from pregnancy complications collected": "Yes or No.",
  "Mode of delivery provided (yes/no)": "Yes or No.",
  "Pregnancy complications in data set (list)": "Return a list of strings.",
  "Fetal complications listed (yes/no)": "Yes or No.",
  "Fetal complications in data set (list)": "Return a list of strings.",
  "Hospital/Center where samples were collected": "The name of the institution.",
  "Country where samples were collected": "The name of the country.",
}

# prompt

prompt_template = """You are an expert biomedical data extractor specializing in placental and pregnancy research.

Answer the questions from the main paper text and supplementary material.

Important: Supplementary tables often contain critical metadata (demographics, gestational
ages, birthweights, delivery modes, etc.) that are not in the main paper text. You must
check the supplements carefully. Answer only from the main paper and supplementary material.

Return only a single valid JSON object. No markdown fences, no commentary.

Output format
For each question key below, return an object:
{{
  "<question text>": {{
    "answer": <see answer rules>,
    "confidence": "high" | "medium" | "low",
    "reason": "1-2 sentence explanation",
    "evidence": [
      {{"quote": "exact text from paper or supplement", "source": "where the quote is from"}}
    ]
  }},
  ...
}}

Answer rules
- Yes/No questions: return exactly "Yes" or "No". "Yes" means the paper OR its supplements
  explicitly provides this data. If unclear, return "No".
- Sampling timing during pregnancy: answer using the organism- and paper-specific pregnancy timing language.
  Preserve the terms used by the paper where possible. Avoid forcing a human trimester label onto non-human studies,
  and avoid converting between species-specific timing systems unless the paper explicitly provides that conversion.
  If the study includes multiple species or time points, list each clearly.
- List questions: return an array of strings, [] if none.
- Free text questions: return the most specific value, "Not Provided" if absent.
- Do not invent data.

Evidence rules
- Copy the exact text from the paper or supplement (1-2 sentences max).
- "source": be specific (Methods section, Table 1, Supplemental Table S1, etc.).
- For "No" answers, evidence may be an empty array.

Questions. Use the exact key for each:
{questions}

Main paper text:
{paper_text}

Supplementary material:
{supplement_text}
"""


def build_prompt(paper_text: str, supplement_text: str) -> str:
    questions = "\n".join(f'- "{q}"  ({hint})' for q, hint in json_structure.items())
    return prompt_template.format(
        questions=questions,
        paper_text=paper_text[:paper_char_cap] if paper_char_cap else paper_text,
        supplement_text=supplement_text,
    )


# post-processing

unknown_strings = {"unknown", "not known", "not reported", "n/a", "na", "none stated"}


def coerce_answer(key: str, raw_answer) -> Any:
    """Take whatever the model returned as `answer` and normalize for the xlsx cell."""
    if raw_answer is None:
        return "Not Provided"

    val = raw_answer
    if isinstance(val, str):
        s = val.strip()
        if s.lower() in unknown_strings or s.lower() == "not provided":
            return "Not Provided"
        val = s

    if "(list)" in key or "Return a list" in json_structure.get(key, ""):
        if val == "Not Provided":
            return []
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        if isinstance(val, str):
            parts = [p.strip() for p in val.replace(";", ",").split(",")]
            return [p for p in parts if p]
        return [str(val).strip()]

    if val is None or (isinstance(val, str) and not val.strip()):
        return "Not Provided"
    return val


def normalize_response(model_response: Dict[str, Any]) -> Dict[str, Any]:
    """Pick out the `answer` for each question, coerced to the right type.
    The full evidence/reason structure stays in the cached raw JSON."""
    out: Dict[str, Any] = {}
    for q in json_structure.keys():
        entry = model_response.get(q, {})
        if isinstance(entry, dict):
            raw_ans = entry.get("answer")
        else:
            raw_ans = entry
        out[q] = coerce_answer(q, raw_ans)
    return out


def build_evidence_rows(pmcid: str, model: str, model_response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One row per question with answer + quote + source + confidence + reason.
    Multiple evidence quotes for a single question are flattened into separate rows."""
    rows: List[Dict[str, Any]] = []
    for q in json_structure.keys():
        entry = model_response.get(q, {})
        if isinstance(entry, dict):
            raw_ans = entry.get("answer")
            confidence = entry.get("confidence", "")
            reason = entry.get("reason", "")
            evidence = entry.get("evidence", [])
        else:
            raw_ans = entry
            confidence = ""
            reason = ""
            evidence = []
        answer = coerce_answer(q, raw_ans)
        if isinstance(answer, list):
            answer = ", ".join(map(str, answer))

        # one row per evidence item; if none, still emit a single row with empty quote/source
        if isinstance(evidence, list) and evidence:
            for ev in evidence:
                if isinstance(ev, dict):
                    quote = ev.get("quote", "")
                    source = ev.get("source", "")
                else:
                    quote = str(ev)
                    source = ""
                rows.append({
                    "PMCID": pmcid,
                    "Model": model,
                    "Question": q,
                    "Answer": answer,
                    "Quote": quote,
                    "Source": source,
                    "Confidence": confidence,
                    "Reason": reason,
                })
        else:
            rows.append({
                "PMCID": pmcid,
                "Model": model,
                "Question": q,
                "Answer": answer,
                "Quote": "",
                "Source": "",
                "Confidence": confidence,
                "Reason": reason,
            })
    return rows


def load_evidence_from_raw(pmcid: str, model: str) -> List[Dict[str, Any]]:
    """For a resumed run: re-parse the cached .raw.json to rebuild evidence rows."""
    safe_model = model.replace("/", "_")
    raw_path = pathlib.Path(output_raw_dir) / f"{pmcid}__{safe_model}.raw.json"
    if not raw_path.exists():
        return []
    try:
        raw = raw_path.read_text(encoding="utf-8")
        parsed = parse_json(raw)
        if not parsed:
            return []
        return build_evidence_rows(pmcid, model, parsed)
    except Exception:
        return []


# resume + io helpers

def ensure_dir(path: str) -> None:
    pathlib.Path(path).mkdir(parents=True, exist_ok=True)


def cache_path(pmcid: str, model: str) -> pathlib.Path:
    safe_model = model.replace("/", "_")
    return pathlib.Path(output_raw_dir) / f"{pmcid}__{safe_model}.normalized.json"


def is_complete(cached: Dict[str, Any]) -> bool:
    """True if every current question key has a non-empty answer from this prompt version."""
    if cached.get("prompt_version") != prompt_version:
        return False
    for q in json_structure.keys():
        v = cached.get(q)
        if v is None:
            return False
        if isinstance(v, str) and not v.strip():
            return False
        if isinstance(v, list) and v == [] and "(list)" not in q:
            return False
    return True


def load_cache(pmcid: str, model: str) -> Optional[Dict[str, Any]]:
    p = cache_path(pmcid, model)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(pmcid: str, model: str, normalized: Dict[str, Any], raw: str, prompt: str) -> None:
    ensure_dir(output_raw_dir)
    base = pathlib.Path(output_raw_dir) / f"{pmcid}__{model.replace('/', '_')}"
    raw_path = base.parent / f"{base.name}.raw.json"
    normalized_path = base.parent / f"{base.name}.normalized.json"
    raw_path.write_text(raw, encoding="utf-8")
    with open(normalized_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    if save_prompt_per_paper:
        prompt_path = base.parent / f"{base.name}.prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")


def mark_failure(pmcid: str, model: str, err_text: str) -> None:
    ensure_dir(output_raw_dir)
    p = pathlib.Path(output_raw_dir) / f"{pmcid}__{model.replace('/', '_')}.error.txt"
    p.write_text(err_text, encoding="utf-8")


def call_with_retries(model: str, prompt: str) -> Optional[str]:
    """call_model from lib already retries, but we add a top-level pacing cooldown
    after burst failures."""
    try:
        return call_model(model, prompt)
    except Exception as e:
        err = str(e)
        if any(str(c) in err for c in retryable_status_codes):
            time.sleep(backoff_cap_sec)
        print(f"    > {model} failed: {e}")
        return None


# main per-paper flow

def extract_one(
    pmcid: str,
    geo_id: str,
    doi: Optional[str],
    paper_text: str,
    model: str,
) -> Optional[Dict[str, Any]]:
    """Returns a normalized answer dict; also writes raw + normalized caches.
    Evidence rows are attached under the temporary key 'evidence_rows' for the caller."""
    if not paper_text:
        print(f"    > no paper text for {pmcid}; skipping {model}")
        return None

    suppl = load_supplements(pmcid, base_dir=pathlib.Path.cwd(), verbose=True) if use_supplements else ""

    # detect supplement-loading problems (load_supplements embeds "[Error reading ...]" markers)
    if use_supplements:
        if suppl == "(No supplementary files available)":
            log_failure(pmcid, geo_id, "supplements_missing",
                         "No supplementary files found locally for this PMCID")
        elif "[Error reading" in suppl:
            bad = re.findall(r"\[Error reading ([^:]+):", suppl)
            log_failure(pmcid, geo_id, "supplements_partial_error",
                         f"Could not parse: {', '.join(bad) or 'unknown'}")
        else:
            # supplements exist + parsed cleanly, but may still be a useless stub
            # (e.g. one-line table-of-contents file with no real metadata in it)
            stripped_len = len(suppl.strip())
            if stripped_len < supplement_min_useful_chars:
                log_failure(pmcid, geo_id, "supplements_short",
                             f"Supplement text only {stripped_len} chars "
                             f"(< {supplement_min_useful_chars}); likely no real metadata")

    prompt = build_prompt(paper_text, suppl)
    raw = call_with_retries(model, prompt)
    if raw is None:
        mark_failure(pmcid, model, f"call_model returned None for {model}")
        log_failure(pmcid, geo_id, "llm_call_failed", f"call_model returned None ({model})")
        return None
    parsed = parse_json(raw)
    if not parsed:
        mark_failure(pmcid, model, f"unparseable response: {raw[:500]}")
        print(f"    > {model} returned unparseable JSON for {pmcid}")
        log_failure(pmcid, geo_id, "json_unparseable",
                     f"{model} returned text that failed to parse as JSON")
        return None
    normalized = normalize_response(parsed)
    normalized["PaperKey"] = pmcid
    normalized["PMCID"] = pmcid
    normalized["model"] = model
    normalized["prompt_version"] = prompt_version
    normalized["evidence_rows"] = build_evidence_rows(pmcid, model, parsed)
    save_cache(pmcid, model, normalized, raw, prompt)
    return normalized


# paper/template key helpers

def sanitize_paper_key(value: str) -> str:
    value = str(value or "").strip().replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def norm_cell(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def row_lookup(row: pd.Series, *names: str) -> str:
    lower = {str(c).strip().lower(): c for c in row.index}
    for name in names:
        c = lower.get(name.lower())
        if c is not None:
            val = norm_cell(row.get(c))
            if val:
                return val
    return ""


def paper_keys_for_template_row(row: pd.Series) -> List[str]:
    keys: List[str] = []
    pmcid = row_lookup(row, "PMCID", "pmcid")
    doi = row_lookup(row, "DOI", "doi", "doi (link)")
    pmid = row_lookup(row, "PMID", "pmid")
    geo = row_lookup(row, "GEO Series ID (GSE___)", "GEO_ID")
    for key in (pmcid, sanitize_paper_key(doi) if doi else "", pmid, geo):
        if key and key not in keys:
            keys.append(key)
    return keys


def primary_paper_key(row: pd.Series) -> str:
    keys = paper_keys_for_template_row(row)
    return keys[0] if keys else ""


def build_template_maps(template_df: Optional[pd.DataFrame]) -> tuple[Dict[str, str], Dict[str, str], set[str]]:
    doi_by_key: Dict[str, str] = {}
    geo_by_key: Dict[str, str] = {}
    template_keys: set[str] = set()
    if template_df is None:
        return doi_by_key, geo_by_key, template_keys
    for _, row in template_df.iterrows():
        doi = row_lookup(row, "DOI", "doi", "doi (link)")
        geo = row_lookup(row, "GEO Series ID (GSE___)", "GEO_ID")
        keys = paper_keys_for_template_row(row)
        if keys:
            template_keys.add(keys[0])
        for key in keys:
            if doi:
                doi_by_key[key] = doi
            if geo:
                geo_by_key[key] = geo
    return doi_by_key, geo_by_key, template_keys

# excel writer

def stringify_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if df[col].apply(lambda x: isinstance(x, list)).any():
            df[col] = df[col].apply(lambda x: ", ".join(map(str, x)) if isinstance(x, list) else x)
    return df


def merge_with_template(template_df: pd.DataFrame, results_df: pd.DataFrame) -> pd.DataFrame:
    """Merge results into template using any known row key (PMCID, DOI key, PMID, GEO).

    This avoids losing DOI-keyed Elsevier results when the template row also has a PMCID.
    """
    res = results_df.copy()
    if "PaperKey" not in res.columns:
        res["PaperKey"] = res.get("PMCID", "")
    res_by_key = {
        str(row.get("PaperKey") or row.get("PMCID") or "").strip(): row
        for _, row in res.iterrows()
        if str(row.get("PaperKey") or row.get("PMCID") or "").strip()
    }

    rows: List[Dict[str, Any]] = []
    for _, tpl_row in template_df.iterrows():
        out = tpl_row.to_dict()
        keys = paper_keys_for_template_row(tpl_row)
        match = next((res_by_key[k] for k in keys if k in res_by_key), None)
        out["PaperKey"] = keys[0] if keys else ""
        if match is not None:
            out["MatchedPaperKey"] = str(match.get("PaperKey") or match.get("PMCID") or "")
            for col in json_structure.keys():
                val = match.get(col, pd.NA)
                if val is not pd.NA and not (isinstance(val, float) and pd.isna(val)):
                    out[col] = val
                elif col not in out:
                    out[col] = pd.NA
        else:
            out["MatchedPaperKey"] = ""
            for col in json_structure.keys():
                out.setdefault(col, pd.NA)
        rows.append(out)

    final = pd.DataFrame(rows)
    base_cols = [c for c in template_df.columns if c in final.columns]
    cols = base_cols + ["PaperKey", "MatchedPaperKey"] + [c for c in json_structure.keys() if c not in base_cols]
    return final.reindex(columns=cols)


# main

def main() -> None:
    # load processed papers
    try:
        with open(input_json_file, encoding="utf-8") as f:
            all_papers = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Error: {input_json_file} not found")
    except json.JSONDecodeError as e:
        sys.exit(f"Error: failed to parse {input_json_file}: {e}")
    if not isinstance(all_papers, list):
        sys.exit(f"{input_json_file} must be a JSON array")

    # paper-text lookup (with fallbacks)
    lookup = paper_text_lookup(pathlib.Path.cwd())

    # try to read doi/geo_id from the template (only used for fallback fetches)
    template_df: Optional[pd.DataFrame] = None
    try:
        template_df = pd.read_excel(excel_template_file)
    except Exception:
        print(f"Warning: could not read {excel_template_file}; doi fallback unavailable")
    doi_by_key, geo_by_key, template_keys = build_template_maps(template_df)
    template_row_by_key: Dict[str, pd.Series] = {}
    if template_df is not None:
        for _, row in template_df.iterrows():
            for key in paper_keys_for_template_row(row):
                template_row_by_key[key] = row

    total = len(all_papers)
    print(f"Starting annotation of {total} papers x {len(models)} model(s) with {llm_workers} worker(s).")

    # template-tracked papers that never made it into processed_papers.json
    processed_keys = {(p.get("pmcid") or "").strip() for p in all_papers}
    for tpl_key in template_keys:
        if tpl_key and tpl_key not in processed_keys:
            log_failure(tpl_key, geo_by_key.get(tpl_key, ""), "not_in_processed_papers",
                         "Paper is in the template but missing from processed_papers.json "
                         "(paper likely failed download or chunking)")

    results: List[Dict[str, Any]] = []
    evidence_rows_all: List[Dict[str, Any]] = []
    processed = skipped = failures = 0

    def process_paper(idx: int, paper: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, int, int]:
        pmcid = paper.get("pmcid") or "UNKNOWN"  # paper key: PMCID or sanitized DOI
        geo_id = geo_by_key.get(pmcid, "")
        doi = doi_by_key.get(pmcid, "")
        chunks = paper.get("chunks", []) or []
        paper_results: List[Dict[str, Any]] = []
        paper_evidence: List[Dict[str, Any]] = []
        paper_processed = paper_skipped = paper_failures = 0

        print(f"\n[{idx}/{total}] {pmcid}  (GEO={geo_id or '?'})")

        # resolve paper text via the lookup chain (processed_papers first)
        paper_text = " ".join(chunks) if chunks else ""
        if not paper_text or len(paper_text) < 5000:
            paper_text = lookup.get(geo_id, pmcid=pmcid, doi=doi)
        if not paper_text:
            print(f"  > no paper text available; skipping")
            log_failure(pmcid, geo_id, "paper_text_missing",
                         "No usable paper text from chunks or fallback lookups")
            return paper_results, paper_evidence, paper_processed, 1, paper_failures

        # flag papers where the text exists but is suspiciously short
        # (probably an abstract-only stub, not a full paper)
        if len(paper_text) < 5000:
            log_failure(pmcid, geo_id, "paper_text_short",
                         f"Paper text only {len(paper_text)} chars; likely an abstract-only stub")

        # for each configured model
        for model in models:
            cached = load_cache(pmcid, model)
            if not overwrite and cached and (not resume_requires_all_fields or is_complete(cached)):
                print(f"  > {model}: cached + complete; skipping")
                paper_results.append(cached)
                # rebuild evidence rows from the on-disk raw response
                paper_evidence.extend(load_evidence_from_raw(pmcid, model))
                paper_skipped += 1
                continue

            normalized = extract_one(
                pmcid, geo_id, doi, paper_text, model,
            )
            if normalized is None:
                paper_failures += 1
                continue
            ev_rows = normalized.pop("evidence_rows", [])
            paper_evidence.extend(ev_rows)
            paper_results.append(normalized)
            paper_processed += 1
            print(f"  > {model}: OK")

            # base pacing
            time.sleep(request_interval_sec + random.uniform(*backoff_jitter))

        return paper_results, paper_evidence, paper_processed, paper_skipped, paper_failures

    if llm_workers == 1:
        completed = (process_paper(idx, paper) for idx, paper in enumerate(all_papers, start=1))
        for paper_results, paper_evidence, n_processed, n_skipped, n_failures in completed:
            results.extend(paper_results)
            evidence_rows_all.extend(paper_evidence)
            processed += n_processed
            skipped += n_skipped
            failures += n_failures
    else:
        with ThreadPoolExecutor(max_workers=llm_workers) as executor:
            futures = [
                executor.submit(process_paper, idx, paper)
                for idx, paper in enumerate(all_papers, start=1)
            ]
            for future in as_completed(futures):
                paper_results, paper_evidence, n_processed, n_skipped, n_failures = future.result()
                results.extend(paper_results)
                evidence_rows_all.extend(paper_evidence)
                processed += n_processed
                skipped += n_skipped
                failures += n_failures

    print(f"\n--- Summary: processed={processed}, skipped={skipped}, failures={failures} ---")
    print("--- Merging download reports into Failures sheet ---")
    merge_download_reports(geo_by_key)
    print(f"--- Failure rows logged: {len(failures_log)} ---")

    evidence_df = pd.DataFrame(
        evidence_rows_all,
        columns=["PMCID", "Model", "Question", "Answer", "Quote", "Source", "Confidence", "Reason"],
    )
    failures_df = pd.DataFrame(
        failures_log,
        columns=["PaperKey", "PMCID", "GEO_ID", "Stage", "Detail"],
    )

    # build the answers sheet (one row per paper/model when more than one model is used)
    if not results:
        answers_df = pd.DataFrame(columns=["PMCID"] + list(json_structure.keys()))
    else:
        results_df = pd.DataFrame(results)
        results_df = stringify_for_excel(results_df)
        # merge into geo template if it's readable
        try:
            tpl = pd.read_excel(excel_template_file)
            if "PMCID" in tpl.columns:
                answers_df = merge_with_template(tpl, results_df)
            else:
                answers_df = results_df
        except Exception:
            answers_df = results_df
        answers_df.columns = [str(c) for c in answers_df.columns]

    with pd.ExcelWriter(output_excel_file, engine="openpyxl") as writer:
        answers_df.to_excel(writer, sheet_name="Answers", index=False)
        evidence_df.to_excel(writer, sheet_name="Evidence", index=False)
        failures_df.to_excel(writer, sheet_name="Failures", index=False)

    print(f"\nSaved: {output_excel_file}")
    print(f"  - 'Answers' sheet:   {len(answers_df)} rows")
    print(f"  - 'Evidence' sheet:  {len(evidence_df)} rows")
    print(f"  - 'Failures' sheet:  {len(failures_df)} rows")
    print(f"Per-paper raw artifacts in: {output_raw_dir}/")


if __name__ == "__main__":
    main()
