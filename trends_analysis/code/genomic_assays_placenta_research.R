# ------------------------------------------------------------------------------
# Violin plots of genomics assays used in placenta research in public data repositories 
# between 2002 and 2025.
#
# Contents
#   1) Read in & clean up data
#   2) Make the lookup tables for manual labeling
#   3) Read in the labeled lookup tables & build the plot data
#   4) Make violin plots of assay types & counts to combine in Illustrator

# Author: Nora Shefferman
# Last edited: 11-18-2026
# ------------------------------------------------------------------------------

# Data sheets last downloaded:
## geo_completed_sheet.xlsx 11-04-2026
## Final_repository_metadata_combined_dbs.xlsx 11-06-2026

# Install and load packages
library(readxl)
#install.packages("openxlsx")
library(openxlsx)
library(tidyverse)

# Set working directory
setwd("~/Desktop/placenta_db")

# Create  folders if they do not already exist
dir.create("figures", showWarnings = FALSE)
dir.create("supplementary", showWarnings = FALSE)
dir.create("code/files_used_in_code", showWarnings = FALSE, recursive = TRUE)

# ==============================================================================
#  1) Read in & clean up data
# ==============================================================================
# Read in the data freeze files
# GEO
## Use only the Answers tab, the Evidence tab does not have data entries
data_geo <- read_excel("geo_completed_sheet.xlsx", sheet = "Answers",
                       col_types = "text")
# Proteomics and other repositories
## Combine the different tabs into one data table and label the source tab
## .id goes in bind_rows (not map) so the tab names become source_sheet
sheet_names <- excel_sheets("Final_repository_metadata_combined_dbs.xlsx")
data_protein <- sheet_names %>%
  set_names() %>%
  purrr::map(~ read_excel("Final_repository_metadata_combined_dbs.xlsx", sheet = .x,
                   col_types = "text")) %>%
  bind_rows(.id = "source_sheet")
# Combine the GEO and additional repository tables for downstream analysis
data_geo_clean <- data_geo %>%
  mutate(source_sheet = "geo", across(everything(), as.character))
data <- bind_rows(data_geo_clean, data_protein) %>%
  relocate(source_sheet, .before = everything())

# Clean up dates
data <- data %>%
  # Excel dates imported as text can appear as numbers such as "45860"
  # Convert those numbers to dates
  # Keep the original Submission date column for reference
  mutate(submission_date = case_when(
    str_detect(`Submission date`, "^[0-9]{5}(\\.[0-9]+)?$") ~
      as.character(as.Date(suppressWarnings(as.numeric(`Submission date`)),
                           origin = "1899-12-30")),
    TRUE ~ `Submission date`)) %>%
  # Handle dates such as 03/27/2021, Feb 23 2012, and 2025-07-22
  # Missing dates and literal ######## values become NA
  mutate(submission_date = as.Date(parse_date_time(
    submission_date, orders = c("mdy", "ymd", "ymd HMS", "mdy HMS"),
    locale = "C", tz = "UTC", quiet = TRUE))) %>%
  mutate(year = year(submission_date))

# ==============================================================================
#  2) Make the lookup tables for manual labeling
# ==============================================================================
# Each entry can list multiple data types, molecules, and library strategies.
# Split these fields to make candidate combinations for manual review.
# This makes all possible combinations within an entry, not confirmed pairs.
# Keep = FALSE should be used for combinations that are not supported.
expanded <- data %>%
  separate_rows(`Data type`, sep = "\\s*[,;|]\\s*") %>%
  separate_rows(`Extracted molecule`, sep = "\\s*[,;|]\\s*") %>%
  separate_rows(`Library Strategy`, sep = "\\s*[,;|]\\s*") %>%
  transmute(source_sheet,
            Entry_ID = `GEO Series ID (GSE___)`,
            year,
            Instrument_Model = `Instrument model`,
            Data_Type = str_squish(`Data type`),
            Extracted_Molecule = str_squish(`Extracted molecule`),
            Library_Strategy = str_squish(`Library Strategy`)) %>%
  # A trailing separator (e.g. "RNA-Seq;") leaves an empty piece, make it NA
  mutate(across(c(Data_Type, Extracted_Molecule, Library_Strategy),
                ~ na_if(.x, ""))) %>%
  distinct()

# Manual labeling guidance (both lookup tables):
# Molecule: DNA, RNA, Protein, or Metabolite
# Category: Methylation, Variant analysis, Coding RNA, Non-coding RNA,
#           Protein, or Metabolite
# Assay_Type: Array or Sequencing/spectral
#             (mass spectrometry and NMR count as Sequencing/spectral)
# If the fields (incl. instrument) do not show the assay, use N/A and Keep = FALSE
# Use N/A for Molecule/Category too if the molecule cannot be determined
# Keep: TRUE for supported combinations, FALSE for unsupported combinations
# Rows sharing a lookup combination must support the same assigned labels

# ------------------------------------------------------------------------------
# 2a) Combination lookup (one row per source + data type/molecule/strategy)
# ------------------------------------------------------------------------------
# Helper columns are for reference only while labeling:
#   n_entries   = how many entries have this combination
#   Example_IDs = up to 3 accessions to look up on the repository website
#   Instruments = instrument models listed by those entries (use these to decide the assay type)
assays_lookup <- expanded %>%
  group_by(source_sheet, Data_Type, Extracted_Molecule, Library_Strategy) %>%
  summarise(n_entries = n_distinct(Entry_ID),
            Example_IDs = paste(head(unique(Entry_ID), 3), collapse = "; "),
            Instruments = str_trunc(
              paste(sort(unique(na.omit(Instrument_Model))), collapse = "; "),
              250),
            .groups = "drop") %>%
  arrange(source_sheet, Data_Type, Extracted_Molecule, Library_Strategy) %>%
  mutate(Molecule = NA_character_,
         Category = NA_character_,
         Assay_Type = NA_character_,
         Keep = NA_character_)

# Export the lookup table for manual editing (only writes it the first time, so it won't overwrite anything)
# Save a copy with _filled in the filename
if (!file.exists("code/files_used_in_code/combined_assay_lookup_to_label.xlsx")) {
  write.xlsx(assays_lookup, "code/files_used_in_code/combined_assay_lookup_to_label.xlsx")
}

# ------------------------------------------------------------------------------
# 2b) Entry lookup for entries with no data type, molecule, or strategy
# ------------------------------------------------------------------------------
# These entries cannot be labeled by combination (all blanks look the same),
# so label them one by one using the title, instrument, and repository website.
# Currently this is the 52 MassIVE entries with a blank Data type.
entry_lookup <- data %>%
  filter(is.na(`Data type`), is.na(`Extracted molecule`),
         is.na(`Library Strategy`)) %>%
  transmute(source_sheet,
            Entry_ID = `GEO Series ID (GSE___)`,
            year,
            Title,
            Instrument_Model = `Instrument model`,
            Assay_Description = str_trunc(`Assay description`, 300),
            Molecule = NA_character_,
            Category = NA_character_,
            Assay_Type = NA_character_,
            Keep = NA_character_) %>%
  arrange(source_sheet, Entry_ID)

# Export the lookup table for manual editing (only writes it the first time, so it won't overwrite anything)
# Save a copy with _filled in the filename
if (!file.exists("code/files_used_in_code/assay_entry_lookup_to_label.xlsx")) {
  write.xlsx(entry_lookup, "code/files_used_in_code/assay_entry_lookup_to_label.xlsx")
}

# ==============================================================================
#  3) Read in the labeled lookup tables & build the plot data
# ==============================================================================
# Run sections 1-2, fill in both lookup tables in Excel, then run from here.

# Combination lookup
lookup_labeled <- read_excel(
  "code/files_used_in_code/combined_assay_lookup_to_label_filled.xlsx",
  col_types = "text") %>%
  select(source_sheet, Data_Type, Extracted_Molecule, Library_Strategy,
         Molecule, Category, Assay_Type, Keep) %>%
  mutate(across(everything(), ~ na_if(str_squish(.x), ""))) %>%
  distinct()

# Entry lookup
## Rename the label columns so they can override the combination labels below
entry_labeled <- read_excel(
  "code/files_used_in_code/assay_entry_lookup_to_label_filled.xlsx",
  col_types = "text") %>%
  select(source_sheet, Entry_ID, Molecule, Category, Assay_Type, Keep) %>%
  mutate(across(everything(), ~ na_if(str_squish(.x), ""))) %>%
  rename(Molecule_entry = Molecule,
         Category_entry = Category,
         Assay_Type_entry = Assay_Type,
         Keep_entry = Keep)

# Checks before joining -- both should return 0 rows
## Combinations labeled more than once (would duplicate entries in the join)
lookup_labeled %>%
  count(source_sheet, Data_Type, Extracted_Molecule, Library_Strategy) %>%
  filter(n > 1)
## Combinations without a Keep value (not labeled yet)
lookup_labeled %>%
  filter(is.na(Keep))

# Join the labels to every entry
## Entry labels replace the combination labels where they exist
assays <- expanded %>%
  left_join(lookup_labeled,
            by = c("source_sheet", "Data_Type", "Extracted_Molecule",
                   "Library_Strategy")) %>%
  left_join(entry_labeled, by = c("source_sheet", "Entry_ID")) %>%
  mutate(Molecule = coalesce(Molecule_entry, Molecule),
         Category = coalesce(Category_entry, Category),
         Assay_Type = coalesce(Assay_Type_entry, Assay_Type),
         Keep = coalesce(Keep_entry, Keep)) %>%
  select(-ends_with("_entry"))

# Order of the panels (top to bottom)
panel_levels <- c(
  "Methylation — Array",
  "Methylation — Sequencing/spectral",
  "Variant analysis — Array",
  "Variant analysis — Sequencing/spectral",
  "Coding RNA — Array",
  "Coding RNA — Sequencing/spectral",
  "Non-coding RNA — Array",
  "Non-coding RNA — Sequencing/spectral",
  "Protein — Array",
  "Protein — Sequencing/spectral",
  "Metabolite — Array",
  "Metabolite — Sequencing/spectral")

plot_data <- assays %>%
  # Keep only supported combinations (Excel TRUE is read in as "TRUE")
  filter(toupper(Keep) == "TRUE") %>%
  # Restrict years to 2002-2025 to match other figures
  # Entries without a date (e.g. PRIDE ########) are dropped here
  filter(year >= 2002, year <= 2025) %>%
  # Remove any duplicates
  # (keeps studies that use different assays within the study)
  distinct(source_sheet, Entry_ID, year, Molecule, Category, Assay_Type) %>%
  mutate(Panel = paste(Category, Assay_Type, sep = " — "))

# Check which TRUE labels do not fit a panel (e.g. Category "Other")
# These are dropped from the plot, so fix them in the lookup if needed
plot_data %>%
  filter(!Panel %in% panel_levels) %>%
  count(Molecule, Panel)

plot_data <- plot_data %>%
  filter(Panel %in% panel_levels) %>%
  mutate(Panel = factor(Panel, levels = panel_levels),
         Molecule = factor(Molecule,
                           levels = c("RNA", "DNA", "Protein", "Metabolite")),
         Assay_Type = factor(Assay_Type,
                             levels = c("Array", "Sequencing/spectral")))

# ==============================================================================
#  4) Make violin plots of assay types & counts to combine in Illustrator
# ==============================================================================
# Plot -- I will re-label the facet labels in Illustrator
## fct_rev puts the first panel level at the top
## scales/space = "free_y" so each molecule only shows its own panels
violin_plot <- ggplot(plot_data,
                      aes(x = year, y = fct_rev(Panel), fill = Assay_Type)) +
  geom_violin(trim = FALSE, alpha = 0.6, width = 1) +
  geom_jitter(height = 0.15, size = 0.7, alpha = 0.5) +
  facet_grid(rows = vars(Molecule), scales = "free_y", space = "free_y",
             switch = "y") +
  scale_fill_manual(values = c("Array" = "#e9c46a",
                               "Sequencing/spectral" = "#dd1c77")) +
  scale_x_continuous(breaks = seq(2002, 2025, by = 2)) +
  labs(title = "Genomics Assays Used in Placenta Research",
       x = "Year", y = NULL, fill = "Assay Type") +
  theme_classic() +
  theme(legend.position = "bottom",
        axis.text.x = element_text(angle = 45, hjust = 1),
        axis.text.y = element_blank(),
        axis.ticks.y = element_blank(),
        axis.line.y = element_blank(),
        strip.placement = "outside",
        strip.background = element_rect(fill = "white", color = "black"),
        strip.text.y.left = element_text(size = 12, face = "plain"))
violin_plot

# Save
ggsave("figures/placenta_omics_assays_raw.png", plot = violin_plot, width = 12, height = 10, dpi = 300)
ggsave("figures/placenta_omics_assays_raw.pdf", plot = violin_plot, width = 12, height = 10)

# Calculate how many protein and metabolite datasets were submitted after 2016 (when most
# datasets started to be submitted based on the violin)
data %>%
  filter(source_sheet %in% c("PRIDE", "MassIVE", "MetaboLights", "Metabolomics Workbench"),
         year >= 2002, year <= 2025) %>%
  summarise(total_entries = n(),
            entries_2016_or_later = sum(year >= 2016),
            percent_2016_or_later = round(entries_2016_or_later / total_entries * 100, 1),
            earliest_year = min(year))

# Count studies for Illustrator labels
count_assays <- plot_data %>%
  count(Molecule, Panel)

# Save
if (!file.exists("supplementary/placenta_omics_assay_counts.xlsx")) {
  write.xlsx(count_assays, "supplementary/placenta_omics_assay_counts.xlsx")
}
  
# Count how many studies come from each repository for each category
count_categories <- plot_data %>% 
  count(source_sheet, Category)
count_categories

# Save
if (!file.exists("supplementary/placenta_omics_assay_counts_repositories.xlsx")) {
  write.xlsx(count_categories, "supplementary/placenta_omics_assay_counts_repositories.xlsx")
}
