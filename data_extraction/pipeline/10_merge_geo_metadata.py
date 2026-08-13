#!/usr/bin/env python3
"""
Merge GEO metadata with final paper analysis annotations.

Default behavior:
- Join on 'GEO Series ID (GSE___)' (left join on metadata).
- For overlapping columns (e.g. PMID, PMCID) keep a single column,
  preferring non-null values from the final annotations.
- For DOI, if both 'DOI' and 'doi (link)' exist, prefer values from
  'doi (link)' and drop that extra column after merging.
- Print a short summary of how many rows matched and where mismatches
  between metadata and final annotations were found.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def merge_files(
    meta_path: Path,
    final_path: Path,
    output_path: Path,
    id_column: str = "GEO Series ID (GSE___)",
) -> None:
    """Merge metadata and final-paper Excel sheets into a single file."""
    meta_path = Path(meta_path)
    final_path = Path(final_path)
    output_path = Path(output_path)

    meta = pd.read_excel(meta_path)
    final = pd.read_excel(final_path)

    print(f"Loaded metadata: {meta_path} ({len(meta)} rows)")
    print(f"Loaded final annotations: {final_path} ({len(final)} rows)")

    if id_column not in meta.columns:
        raise SystemExit(f"ID column '{id_column}' not found in metadata file.")
    if id_column not in final.columns:
        raise SystemExit(f"ID column '{id_column}' not found in final annotations file.")

    merged = meta.merge(final, on=id_column, how="left", suffixes=("", "_final"))
    print(f"Merged rows (left on metadata): {len(merged)}")

    # Columns present in both inputs (except the ID column) will have a
    # duplicate with suffix '_final' after the merge.
    overlapping = [c for c in meta.columns if c in final.columns and c != id_column]

    mismatch_records: list[tuple[str, int]] = []

    for col in overlapping:
        final_col = f"{col}_final"
        if final_col not in merged.columns:
            continue

        both_mask = merged[col].notna() & merged[final_col].notna()
        mismatch_mask = both_mask & (merged[col] != merged[final_col])
        n_both = int(both_mask.sum())
        n_mismatch = int(mismatch_mask.sum())

        print(f"{col}: {n_both} rows with values in both; {n_mismatch} mismatches.")
        if n_mismatch:
            mismatch_records.append((col, n_mismatch))

        # Prefer annotations from the final-paper sheet wherever present.
        merged[col] = merged[final_col].combine_first(merged[col])
        merged.drop(columns=[final_col], inplace=True)

    # Special handling for DOI vs 'doi (link)' which have different names.
    if "DOI" in merged.columns and "doi (link)" in merged.columns:
        col = "DOI"
        final_col = "doi (link)"
        both_mask = merged[col].notna() & merged[final_col].notna()
        mismatch_mask = both_mask & (merged[col] != merged[final_col])
        n_both = int(both_mask.sum())
        n_mismatch = int(mismatch_mask.sum())

        print(f"{col} vs {final_col}: {n_both} rows with values in both; {n_mismatch} mismatches.")
        if n_mismatch:
            mismatch_records.append((f"{col}/{final_col}", n_mismatch))

        # Prefer DOI from the final-paper sheet where available.
        merged[col] = merged[final_col].combine_first(merged[col])
        merged.drop(columns=[final_col], inplace=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_excel(output_path, index=False)
    print(f"Saved merged file to: {output_path}")

    if mismatch_records:
        print("Warning: some overlapping columns had differing values.")
        for col, n in mismatch_records:
            print(f"  - {col}: {n} rows (kept values from final annotations where present)")
    else:
        print("All overlapping columns matched where both had values.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Merge a GEO metadata Excel file with a final paper-analysis Excel file "
            "using a GEO Series ID column."
        )
    )
    parser.add_argument(
        "metadata",
        help="Path to the GEO metadata Excel file, such as gse_metadata_full_checkpoint_merged.xlsx.",
    )
    parser.add_argument(
        "final",
        help="Path to the final paper-analysis Excel file (e.g. final_paper_analysis_results_2.xlsx).",
    )
    parser.add_argument(
        "output",
        help="Path for the merged output Excel file.",
    )
    parser.add_argument(
        "--id-column",
        default="GEO Series ID (GSE___)",
        help="Column name used as the join key (default: '%(default)s').",
    )

    args = parser.parse_args()
    merge_files(
        meta_path=Path(args.metadata),
        final_path=Path(args.final),
        output_path=Path(args.output),
        id_column=args.id_column,
    )


if __name__ == "__main__":
    main()
