# GEO Placenta Metadata Pipeline

This project builds a GEO metadata table for placenta-related studies, downloads associated open-access papers and supplementary files, and uses Gemini to extract study-level variables from the paper text.

The goal is to produce a workbook that can be reviewed by researchers. The workbook has a main answer sheet and an evidence sheet. The evidence sheet keeps the quotes and source notes that support the AI answers.

## Project layout

`pipeline/` contains the end-to-end pipeline.

`pipeline/lib/` contains shared helpers for model calls, paper text lookup, and supplement parsing.

`examples/` contains a small input-format example.

Generated data are intentionally not included in this clean project folder. Paper downloads, model outputs, logs, and final workbooks are produced when the pipeline is run.

## Inputs

The pipeline expects a CSV file of GEO series IDs. The default name is `ids.csv`.
This repository includes the full current run list at `ids.csv`.

Use one GEO series ID per row in the first column. A header row is fine. For example, the first column can be named:

`GEO Series ID (GSE___)`

The small format example is:

`examples/ids.example.csv`

## Required keys

Create a `.env` file from `.env.example`.

Required:

`gemini_api_key`

`unpaywall_email`

Optional:

`ncbi_email`

`elsevier_api_key`

If `ncbi_email` is blank or omitted, the pipeline uses `unpaywall_email` as the NCBI contact email.

The Elsevier key is used only for Elsevier full-text and supplement retrieval when those records are available through the Elsevier API.

Do not commit `.env`.

## Setup

Create and activate a Python environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

R is also required for GEO extraction. The R scripts use Bioconductor/GEO-related packages such as `GEOquery`, plus common data packages.

Install the R packages once:

```r
install.packages(c(
  "readxl", "writexl", "dplyr", "stringr", "purrr", "lubridate",
  "progressr", "tibble", "furrr", "data.table", "rvest", "httr",
  "jsonlite", "readr", "future"
))

if (!requireNamespace("BiocManager", quietly = TRUE)) {
  install.packages("BiocManager")
}
BiocManager::install("GEOquery")
```

## Running the pipeline

From the project root:

```bash
bash pipeline/run_pipeline.sh
```

The pipeline runs these stages:

1. Extract GEO metadata for the requested GSE IDs.
2. Retry or repair failed GEO metadata rows.
3. Add paper identifiers and open-access status.
4. Download main papers from PMC, Europe PMC, Unpaywall, and Elsevier when available.
5. Download supplementary files from supported open-access sources.
6. Validate supplement files.
7. Extract and chunk main paper text.
8. Audit paper downloads and chunking.
9. Run Gemini extraction and write the AI workbook.
10. Build a clean sendable workbook.

The raw AI output is:

`ai_annotated.xlsx`

The collaborator-facing output is:

`geo_metadata_with_ai_sendable.xlsx`

## How the pieces fit together

The pipeline has three broad phases.

First, the R scripts create the GEO table. They read `ids.csv`, fetch GEO series and sample metadata, repair rows that failed on the first pass, and write the GEO metadata workbooks.

Second, the paper-download scripts connect each GEO row to publications. They recover PMIDs, PMCIDs, DOIs, open-access status, main-paper text, and supplement files. These steps also write audit files so it is clear which papers downloaded, which supplements were usable, and which files need review.

Third, the Gemini script reads the processed paper text plus available supplement text and answers the study questions. The final workbook builder then turns the raw AI output into a cleaner workbook for collaborators.

The main data flow is:

`ids.csv` -> GEO metadata workbook -> publication access workbook -> downloaded papers/supplements -> processed paper text -> Gemini answers/evidence -> sendable workbook

## Running scripts individually

Run individual scripts from the project root. The full wrapper does this automatically, but running one stage at a time is useful for debugging.

Load `.env` first if the step needs API keys:

```bash
set -a
source .env
set +a
```

`01_extract_geo_metadata.R`

```bash
Rscript pipeline/01_extract_geo_metadata.R
```

Reads `ids.csv`, downloads GEO metadata, and writes `gse_metadata_full.xlsx` and `gse_metadata_full_checkpoint.xlsx`.

`02_repair_geo_metadata.R`

```bash
Rscript pipeline/02_repair_geo_metadata.R
```

Reads the failed GEO rows from the checkpoint workbook, retries them through GEO text/HTML endpoints, and writes `gse_metadata_full_checkpoint_merged.xlsx`.

`03_annotate_open_access.py`

```bash
python pipeline/03_annotate_open_access.py
```

Reads the GEO metadata workbook and adds publication identifiers and open-access status. The main output is `geo_master_access.xlsx`.

`04_download_papers.py`

```bash
python pipeline/04_download_papers.py
```

Uses `geo_master_access.xlsx` to download main papers from supported open-access sources. Outputs go into `downloaded_papers/`.

`05_download_supplements.py`

```bash
python pipeline/05_download_supplements.py
```

Downloads supplementary files for the paper set. Outputs go into `downloaded_supplements/`, with a supplement report CSV for auditing.

`07_validate_supplements.py`

```bash
python pipeline/07_validate_supplements.py --root "$PWD"
```

Checks whether supplement folders and files are readable and flags unresolved supplement problems before the AI step.

`06_chunk_papers.py`

```bash
python pipeline/06_chunk_papers.py
```

Extracts usable text from downloaded papers and writes `processed_papers.json`, which is the main input to Gemini.

`08_validate_papers.py`

```bash
python pipeline/08_validate_papers.py --root "$PWD"
```

Audits paper downloads and chunking. This is where download failures, not-chunked papers, and suspiciously short files are summarized.

`09_run_gemini_extraction.py`

```bash
python pipeline/09_run_gemini_extraction.py
```

Reads `processed_papers.json`, loads available supplement text, sends the combined context to Gemini, and writes `ai_annotated.xlsx`. The workbook includes raw `Answers`, `Evidence`, and `Failures` sheets.

`11_build_sendable_workbook.py`

```bash
python pipeline/11_build_sendable_workbook.py \
  --metadata gse_metadata_full_checkpoint_merged.xlsx \
  --ai ai_annotated.xlsx \
  --output geo_metadata_with_ai_sendable.xlsx
```

Builds the clean collaborator workbook with `Answers`, `Evidence`, and `Audit Summary`. This is the workbook to review or share.

`10_merge_geo_metadata.py`

```bash
python pipeline/10_merge_geo_metadata.py \
  gse_metadata_full_checkpoint_merged.xlsx \
  ai_annotated.xlsx \
  geo_metadata_with_ai_merged.xlsx
```

This is a general merge utility kept for debugging or custom exports. For normal handoff, use `11_build_sendable_workbook.py`.

## Output sheets

The final sendable workbook keeps these sheets:

`Answers`

One row per GEO series. This is the main table.

`Evidence`

One row per supporting quote or source note. Evidence rows are not papers. One paper can create many evidence rows because the model answers many questions.

`Audit Summary`

A concise summary of what worked, what failed, and what should be interpreted cautiously.

Raw failure logs are useful for debugging, but they are not included in the sendable workbook. They include failed supplement candidate links and diagnostic rows, so they are easy to misread as a clean list of failed GEO entries.

## Important interpretation notes

GEO rows and papers are different units.

One paper can map to multiple GEO series. This means the number of processed papers can be smaller than the number of GEO rows covered by AI answers.

PMID, PMCID, and DOI are also different identifiers. PMCID is best for direct PMC full text. PMID is still important because GEO often provides only a PMID, and the pipeline can use that PMID to find a PMCID or DOI.

Supplement reports are file-level reports. A paper can have failed supplement candidate links and still have usable downloaded supplements.

## Current known limitations

Some GEO rows do not have a linked publication identifier. Those rows can still have GEO metadata, but the paper-level AI extraction cannot run unless a paper can be identified.

Some papers download but do not produce usable full text. These need manual review or another full-text source.

Very large supplementary materials may exceed practical prompt limits. The current code allows supplement truncation to be controlled with `supplement_char_cap`, but sending very large supplements in full may increase cost and latency.

## Environment settings

`gemini_model` controls the Gemini model. The default is `gemini-3.5-flash`.

`llm_workers` controls parallel Gemini calls. Use low values if rate limits or cost are a concern.

`paper_char_cap=0` means no main-paper character cap.

`supplement_char_cap=80000` keeps supplements capped by default. Use `0` only if you intentionally want no supplement cap and understand the cost.

`geo_r_workers=1` is the safest setting on macOS.

`max_gsms_per_gse` controls whether the repair script limits sample-level GSM parsing. Leave it blank for a full run. Set it to a small number only for testing.

`ids_file` can point to a different input ID file. If blank, the pipeline uses `ids.csv` in the project root.
