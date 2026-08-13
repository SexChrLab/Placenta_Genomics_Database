#!/usr/bin/env python3
"""Write a final audit of paper downloads and chunking before the LLM step."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def sanitize_paper_key(value: str) -> str:
    value = value.strip().replace("https://doi.org/", "").replace("http://doi.org/", "")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as source:
        return list(csv.DictReader(source))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Pipeline root containing downloaded_papers/ and processed_papers.json",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    papers_dir = root / "downloaded_papers"
    processed_file = root / "processed_papers.json"
    audit_file = papers_dir / "_final_input_audit.csv"

    with processed_file.open(encoding="utf-8") as source:
        processed_rows = json.load(source)
    processed = {
        row.get("pmcid", ""): sum(len(chunk) for chunk in row.get("chunks", []))
        for row in processed_rows
        if row.get("pmcid")
    }

    candidate_keys = set()
    for path in papers_dir.iterdir():
        if path.suffix.lower() not in {".xml", ".html", ".pdf"}:
            continue
        key = path.stem[:-5] if path.stem.endswith(".full") else path.stem
        candidate_keys.add(key)

    audit: list[dict[str, str | int]] = []
    for key in sorted(candidate_keys - set(processed)):
        audit.append({
            "PaperKey": key,
            "Category": "not_chunked",
            "Status": "unresolved",
            "ProcessedChars": 0,
            "Detail": "Downloaded candidate file did not produce usable full text.",
        })

    seen_failures = set()
    for row in read_csv(papers_dir / "download_failures.csv"):
        key = (
            (row.get("pmcid") or "").strip()
            or sanitize_paper_key(row.get("doi") or "")
            or (row.get("pmid") or "").split(".")[0]
        )
        if not key or key in seen_failures:
            continue
        seen_failures.add(key)
        audit.append({
            "PaperKey": key,
            "Category": "download_failed",
            "Status": "unresolved",
            "ProcessedChars": processed.get(key, 0),
            "Detail": row.get("notes") or "No usable full text downloaded.",
        })

    seen_short = set()
    for row in read_csv(papers_dir / "download_successes.csv"):
        if (row.get("short_flag") or "").lower() != "true":
            continue
        key = (row.get("pmcid") or "").strip() or sanitize_paper_key(row.get("doi") or "")
        if not key or key in seen_short:
            continue
        seen_short.add(key)
        chars = processed.get(key, 0)
        audit.append({
            "PaperKey": key,
            "Category": "short_download_flag",
            "Status": "resolved_fulltext" if chars >= 5_000 else "unresolved",
            "ProcessedChars": chars,
            "Detail": row.get("notes") or "Downloaded file was below the size threshold.",
        })

    for key, chars in sorted(processed.items()):
        if chars < 5_000:
            audit.append({
                "PaperKey": key,
                "Category": "processed_text_short",
                "Status": "unresolved",
                "ProcessedChars": chars,
                "Detail": "Processed paper text is below 5,000 characters.",
            })

    fieldnames = ["PaperKey", "Category", "Status", "ProcessedChars", "Detail"]
    with audit_file.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(audit)

    counts: dict[tuple[str, str], int] = {}
    for row in audit:
        pair = (str(row["Category"]), str(row["Status"]))
        counts[pair] = counts.get(pair, 0) + 1

    print(f"Processed papers: {len(processed)}")
    for (category, status), count in sorted(counts.items()):
        print(f"{category}: {status} = {count}")
    print(f"Paper input audit: {audit_file}")


if __name__ == "__main__":
    main()
