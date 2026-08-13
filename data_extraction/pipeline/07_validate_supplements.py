#!/usr/bin/env python3
"""Validate that downloaded supplements can be read before running the LLM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.supplements import load_supplements


def unresolved_downloads(progress_file: Path) -> list[str]:
    if not progress_file.exists():
        return []
    with progress_file.open(encoding="utf-8") as source:
        progress = json.load(source)
    return sorted(progress.get("failed", {}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Pipeline root containing downloaded_supplements/",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    supplement_dir = root / "downloaded_supplements"
    progress_file = supplement_dir / "_progress.json"

    failed_downloads = unresolved_downloads(progress_file)
    parse_errors: list[tuple[str, str]] = []
    empty_papers: list[str] = []
    paper_dirs = sorted(
        path for path in supplement_dir.glob("PMC*") if path.is_dir()
    ) if supplement_dir.exists() else []

    for paper_dir in paper_dirs:
        text = load_supplements(
            paper_dir.name,
            base_dir=root,
            char_cap=sys.maxsize,
            verbose=False,
        )
        if text == "(No supplementary files available)":
            empty_papers.append(paper_dir.name)
            continue
        for line in text.splitlines():
            if line.startswith("[Error reading "):
                parse_errors.append((paper_dir.name, line))

    print(f"Supplement folders checked: {len(paper_dirs)}")
    print(f"Unresolved downloads:       {len(failed_downloads)}")
    print(f"Supplement parse errors:    {len(parse_errors)}")
    print(f"Empty supplement folders:   {len(empty_papers)} (informational)")

    if failed_downloads:
        print("\nUnresolved download entries:")
        for key in failed_downloads[:50]:
            print(f"  {key}")
        if len(failed_downloads) > 50:
            print(f"  ... and {len(failed_downloads) - 50} more")

    if parse_errors:
        print("\nSupplement parsing errors:")
        for pmcid, error in parse_errors[:50]:
            print(f"  {pmcid}: {error}")
        if len(parse_errors) > 50:
            print(f"  ... and {len(parse_errors) - 50} more")

    if failed_downloads or parse_errors:
        print("\nSupplement validation failed. Resolve these entries before running Gemini.")
        return 1

    print("Supplement validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
