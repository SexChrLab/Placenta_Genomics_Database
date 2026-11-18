# Analysis of trends in the placenta database

This directory contains code, figures, and supplementary material for analyzing trends in the placenta database: placenta-related omics studies submitted to public data repositories between 2002 and 2025.

```
.
├── geo_completed_sheet.xlsx                      # input data
├── Final_repository_metadata_combined_dbs.xlsx   # input data
├── code/
│   ├── *.R                                       # one script per figure
│   └── files_used_in_code/                       # lookup tables and cleaned data used by the scripts
├── figures/                                      # figures for the paper (.pdf, .png, .ai)
└── supplementary/                                # supplementary figure and tables for the paper
```

## Input data

The scripts read two spreadsheets from the top level of this directory (all scripts set the working directory to `~/Desktop/placenta_db`, so update the `setwd()` line at the top of each script to match your local path):

* *geo_completed_sheet.xlsx* (GEO entries, "Answers" sheet; last downloaded 11-04-2026)
* *Final_repository_metadata_combined_dbs.xlsx* (entries from the other repositories, one sheet per repository; last downloaded 11-06-2026)

## Code

The `code/` directory contains one R script per figure (or set of related figures). Each script reads and cleans the input spreadsheets, then writes its plots to `figures/` (or `supplementary/` for the supplementary figure and tables). Scripts save "_raw" plots, which were then finalized in Adobe Illustrator.

| Script | What it makes | Main outputs |
|---|---|---|
| `studies_by_year.R` | Bar charts of placenta-related entries by year and repository, and of reported placenta samples by year | `figures/placenta_omics_studies_by_repo_raw`, `figures/placenta_geo_samples_raw` |
| `summary_repositories_pie.R` | Pie chart of studies by repository, and a pie-donut chart with molecule type in the outer ring | `figures/placenta_omics_database_pie_raw`, `figures/placenta_omics_database_pie_donut_raw` |
| `organism_placenta_research.R` | Pie chart of organisms (all organisms with 2 or more entries) and a table of the "Other" organisms | `figures/organisms_plot_raw`, `supplementary/placenta_organisms_2_or_more.csv`, `supplementary/placenta_organisms_other.csv` |
| `geographic_placenta_research_distribution.R` | World map of the organizations where placenta studies are conducted | `figures/placenta_omics_map_raw` |
| `genomic_assays_placenta_research.R` | Violin plots of omics assay types and counts | `figures/placenta_omics_assays_raw`, `supplementary/placenta_omics_assay_counts.csv`, `supplementary/placenta_omics_assay_counts_repositories.csv` |
| `summary_geo_ai_bar.R` | Bar charts of how complete the study, pregnancy, and fetal information is for GEO entries (GEO-derived vs. AI-derived), plus a completeness summary for the other repositories (supplementary figure) | `figures/stacked_bar_geo_summary_raw`, `figures/geo_bar_summary_raw`, `figures/ai_bar_summary_raw`, `supplementary/repositories_bar_summary_raw` |

### files_used_in_code

The `code/files_used_in_code/` directory contains files that are only used by the scripts and are not part of the paper.

* **Lookup tables for manual labeling.** A script writes a table of unique values to be labeled by hand, and then reads back the `_filled` version: *combined_assay_lookup_to_label(_filled).xlsx*, *assay_entry_lookup_to_label(_filled).xlsx*, and *org_lookup_nonGEO(_filled).xlsx*.
* **Cleaned data.** *data_organism.csv* (standardized organism names for each entry) and *org_coords.csv* (coordinates for each organization, used for the map).

### Order of running

Most scripts can be run independently. Exceptions:

* `organism_placenta_research.R` creates *data_organism.csv*, which `geographic_placenta_research_distribution.R` reads, so run the organism script first.
* `genomic_assays_placenta_research.R`, `geographic_placenta_research_distribution.R`, and `summary_repositories_pie.R` use lookup tables that were labeled by hand. The script writes the blank lookup table, and the `_filled` version is read back in.

## Figures

The `figures/` directory contains the main figures for the paper as .pdf and .png files (the "_raw" files written directly by the R scripts) and .ai files (the Illustrator versions), when appropriate. The final Illustrator figures are:

* *placenta_submissions.ai*
* *placenta_omics_database_pie.ai*
* *placenta_organisms_pie.ai*
* *placenta_omics_joint_organisms_map.ai*
* *omics_assays.ai*
* *geo_ai_bar_summary.ai*

## Supplementary

The `supplementary/` directory contains the supplementary figure and tables for the paper.

**Supplementary figure**

* *repositories_bar_summary_raw* (.pdf, .png) is the completeness summary for the non-GEO repositories, made by `summary_geo_ai_bar.R`. *all_repositories_bar_summary.png* is the finalized version.

**Supplementary tables** (each is provided as .csv and .xlsx)

* *placenta_organisms_other* lists the species grouped as "Other" in the organism pie chart and their counts.
* *placenta_organisms_2_or_more* lists the organisms shown in the pie chart and their counts.
* *placenta_omics_assay_counts* and *placenta_omics_assay_counts_repositories* give the number of entries for each assay type (overall and by repository).
