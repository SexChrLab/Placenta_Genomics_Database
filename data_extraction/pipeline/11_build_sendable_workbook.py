#!/usr/bin/env python3
"""Build a clean workbook for collaborators.

The LLM parser writes the raw analysis workbook. This script turns that into a
sendable workbook with three simple sheets:

- Answers: one row per GEO row, with GEO metadata and AI answer columns.
- Evidence: one row per evidence quote or source note.
- Audit Summary: small counts that explain what was included.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from pathlib import Path
from typing import Iterable

import pandas as pd


geo_id_column = "GEO Series ID (GSE___)"
paper_key_columns = ["MatchedPaperKey", "PaperKey", "PMCID", "PMID", "DOI", "doi (link)"]


def read_excel_sheet(path: Path, sheet_name: str | int = 0) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except ValueError:
        return pd.DataFrame()


def norm(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def unique_join(values: Iterable[str]) -> str:
    seen: OrderedDict[str, None] = OrderedDict()
    for value in values:
        text = norm(value)
        if text:
            seen[text] = None
    return "; ".join(seen.keys())


def build_paper_to_geo_map(answers: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, list[str]] = {}
    if answers.empty or geo_id_column not in answers.columns:
        return {}

    for _, row in answers.iterrows():
        geo_id = norm(row.get(geo_id_column))
        if not geo_id:
            continue
        for col in paper_key_columns:
            if col not in row.index:
                continue
            key = norm(row.get(col))
            if key:
                mapping.setdefault(key, []).append(geo_id)

    return {key: unique_join(values) for key, values in mapping.items()}


def merge_answers(metadata: pd.DataFrame, answers: pd.DataFrame) -> pd.DataFrame:
    if answers.empty:
        return metadata.copy()
    if metadata.empty:
        return answers.copy()
    if geo_id_column not in metadata.columns or geo_id_column not in answers.columns:
        return answers.copy()

    merged = metadata.merge(answers, on=geo_id_column, how="left", suffixes=("", "_ai"))
    duplicate_cols = [c for c in merged.columns if c.endswith("_ai")]
    for dup_col in duplicate_cols:
        base_col = dup_col[:-3]
        if base_col in merged.columns:
            merged[base_col] = merged[dup_col].combine_first(merged[base_col])
            merged.drop(columns=[dup_col], inplace=True)
    return merged


def clean_evidence(evidence: pd.DataFrame, paper_to_geo: dict[str, str]) -> pd.DataFrame:
    if evidence.empty:
        return pd.DataFrame(
            columns=[
                "geo_series_id",
                "question",
                "paper_id_used_for_ai",
                "answer",
                "evidence_quote",
                "evidence_source",
                "confidence",
                "reason",
            ]
        )

    cleaned = evidence.copy()
    paper_id_col = "PMCID" if "PMCID" in cleaned.columns else ""
    if paper_id_col and paper_id_col in cleaned.columns:
        cleaned["paper_id_used_for_ai"] = cleaned[paper_id_col].map(norm)
    elif "PaperKey" in cleaned.columns:
        cleaned["paper_id_used_for_ai"] = cleaned["PaperKey"].map(norm)
    else:
        cleaned["paper_id_used_for_ai"] = ""

    cleaned["geo_series_id"] = cleaned["paper_id_used_for_ai"].map(lambda key: paper_to_geo.get(key, ""))

    rename = {
        "Question": "question",
        "Answer": "answer",
        "Quote": "evidence_quote",
        "Source": "evidence_source",
        "Confidence": "confidence",
        "Reason": "reason",
        "Model": "model",
    }
    cleaned.rename(columns=rename, inplace=True)

    preferred = [
        "geo_series_id",
        "question",
        "paper_id_used_for_ai",
        "answer",
        "evidence_quote",
        "evidence_source",
        "confidence",
        "reason",
        "model",
    ]
    ordered = [col for col in preferred if col in cleaned.columns]
    ordered.extend([col for col in cleaned.columns if col not in ordered and col not in ["PMCID"]])
    return cleaned[ordered]


def audit_rows(metadata: pd.DataFrame, answers: pd.DataFrame, evidence: pd.DataFrame, failures: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, note: str = "") -> None:
        rows.append({"Metric": metric, "Value": value, "Notes": note})

    add("GEO rows", len(metadata) if not metadata.empty else "")
    if not metadata.empty:
        for col in ["PMID", "PMCID", "DOI", "MatchedPaperKey"]:
            if col in metadata.columns:
                add(f"Rows with {col}", int(metadata[col].map(norm).astype(bool).sum()))

    add("Answer rows", len(answers) if not answers.empty else 0)
    if "MatchedPaperKey" in answers.columns:
        add("Answer rows with matched paper key", int(answers["MatchedPaperKey"].map(norm).astype(bool).sum()))
    add("Evidence rows", len(evidence) if not evidence.empty else 0)
    if "geo_series_id" in evidence.columns:
        add("Evidence rows linked to GEO", int(evidence["geo_series_id"].map(norm).astype(bool).sum()))
    add("Raw failure/audit rows", len(failures) if not failures.empty else 0, "Raw rows can include candidate supplement links and diagnostics.")
    return pd.DataFrame(rows)


def build_workbook(metadata_path: Path, ai_path: Path, output_path: Path) -> None:
    metadata = read_excel_sheet(metadata_path)
    answers_raw = read_excel_sheet(ai_path, "Answers")
    evidence_raw = read_excel_sheet(ai_path, "Evidence")
    failures_raw = read_excel_sheet(ai_path, "Failures")

    answers = merge_answers(metadata, answers_raw)
    paper_to_geo = build_paper_to_geo_map(answers)
    evidence = clean_evidence(evidence_raw, paper_to_geo)
    audit = audit_rows(metadata, answers, evidence, failures_raw)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        answers.to_excel(writer, sheet_name="Answers", index=False)
        evidence.to_excel(writer, sheet_name="Evidence", index=False)
        audit.to_excel(writer, sheet_name="Audit Summary", index=False)

    print(f"Saved sendable workbook: {output_path}")
    print(f"  Answers: {len(answers)} rows")
    print(f"  Evidence: {len(evidence)} rows")
    print(f"  Audit Summary: {len(audit)} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a clean collaborator-facing workbook.")
    parser.add_argument(
        "--metadata",
        default="gse_metadata_full_checkpoint_merged.xlsx",
        help="GEO metadata workbook.",
    )
    parser.add_argument(
        "--ai",
        default="ai_annotated.xlsx",
        help="AI annotation workbook from 09_run_gemini_extraction.py.",
    )
    parser.add_argument(
        "--output",
        default="geo_metadata_with_ai_sendable.xlsx",
        help="Output workbook.",
    )
    args = parser.parse_args()
    build_workbook(Path(args.metadata), Path(args.ai), Path(args.output))


if __name__ == "__main__":
    main()
