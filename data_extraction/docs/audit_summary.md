# Pipeline Audit Notes

These notes explain the current state of the pipeline outputs and the main caveats to keep in mind when interpreting the workbook.

## Units

A GEO row is one GEO series entry in the final spreadsheet.

A paper is one unique publication downloaded and processed for text.

An evidence row is one quote or source note supporting one AI answer. Evidence rows are not papers. One paper can generate many evidence rows.

## Historical audit from the recovered working run

The current best recovered workbook from the working run was:

`geo_metadata_with_ai_final_simple_sendable_recovered.xlsx`

It contained:

- 1,563 GEO rows
- 1,200 GEO rows with matched paper-level Gemini output
- 363 GEO rows without matched paper-level Gemini output
- 37,408 evidence rows

## Missing paper-level AI answers

The 363 GEO rows without matched paper-level AI output were not all caused by download errors.

They were:

- 341 GEO rows with no PMID, PMCID, or DOI available in the workbook
- 22 GEO rows with some publication identifier but no matched processed paper output

The unresolved paper-input audit is a different unit. It had 26 unresolved paper-key rows, but those rows do not equal 26 GEO rows. Some audit keys do not map to a final GEO row, and some keys overlap.

## Paper download status

The paper download report had:

- 1,222 download summary rows
- 1,212 successful download rows
- 10 failed download rows
- 852 unique processed paper entries in `processed_papers.json`
- 852 Gemini normalized outputs

The Gemini run completed for every paper that reached the processed-paper stage.

## Recovered identifier issue

One important bug was fixed after the first final workbook.

Some GEO rows had only PMIDs. The downloader used those PMIDs to retrieve Elsevier papers, which were saved under DOI-derived keys. The AI output was therefore keyed by DOI, while the GEO row still had PMID.

The recovery joined:

`DOI-derived paper key -> PMID -> GEO row`

This recovered:

- 7 DOI-keyed Elsevier papers
- 10 GEO rows
- 308 evidence rows

After this recovery, there were no remaining unlinked evidence rows from that issue.

## Supplement status

The supplement report is file-level, not paper-level.

It contained:

- 3,145 usable supplement file rows
- 9 usable but short supplement rows
- 2,547 failed candidate-link rows
- 591 rows classified as not actually supplements

The failed candidate-link count should not be read as the number of failed papers. A paper can have several failed candidate links and still have useful supplement files.

## Remaining risk

The main paper pipeline is mostly understood and auditable.

Supplement completeness remains the main scientific risk. Some supplementary materials are very large, and earlier prompt files showed truncation around 80,000 characters. The current code allows this cap to be changed with `supplement_char_cap`, including `0` for no cap, but no cap can increase cost and runtime substantially.

## Recommended collaborator-facing workbook

The clean collaborator workbook should include:

- `Answers`
- `Evidence`
- `Audit Summary`

The raw `Failures` sheet should be replaced by a concise audit summary. The raw failures sheet mixes true unresolved paper problems with candidate supplement-link failures and older diagnostic rows, so it is easy to misread.
