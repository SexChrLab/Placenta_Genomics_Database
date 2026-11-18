# ------------------------------------------------------------------------------
# Horizontal bar chart summarizing the availability of study information and pregnancy 
# and fetal characteristics only in GEO placenta studies
#
# Contents
#   1) Read in, check, and clean data
#   2) Make tables for information pulled from GEO and information pulled from AI
#     a) GEO information
#     b) AI information
#   3) Bar plots
#     a) Vertical summary stacked bar chart of number of columns filled in by GEO vs. AI
#     b) GEO completeness bars
#     c) AI completeness bars
#   4) Supplementary figure: completeness bars for the other repositories
#   5) Supplementary table: entries with a linked publication (PMID/PMCID/DOI) in each repository

# Author: Nora Shefferman
# Last edited: 11-18-2026
# ------------------------------------------------------------------------------

# Data sheets last downloaded:
## geo_completed_sheet.xlsx 11-04-2026
## Final_repository_metadata_combined_dbs.xlsx 11-06-2026

# Install and load packages
library(readxl)
library(openxlsx)
library(tidyverse)

# Set working directory
setwd("~/Desktop/placenta_db")

# Create  folders if they do not already exist
dir.create("figures", showWarnings = FALSE)
dir.create("supplementary", showWarnings = FALSE)

# ==============================================================================
#  1) Read in, check, and clean data
# ==============================================================================
# Read in the data freeze files
data <- read_excel("geo_completed_sheet.xlsx")

# First, check if all the NAs in the AI columns come from the AI not being able
# to read the paper, or if the AI isn't pulling some columns for some reason.
## Find all columns after the AI paper ID column
start_col <- match("Paper ID used for AI (PMCID or DOI-derived key)", names(data))
post_cols <- names(data)[(start_col + 1):ncol(data)]

is_filled <- function(x) {
  !is.na(x) & str_squish(as.character(x)) != ""
}

row_check <- data %>%
  rowwise() %>%
  mutate(
    n_filled_post = sum(is_filled(c_across(all_of(post_cols)))),
    n_post_cols = length(post_cols),
    post_status = case_when(
      n_filled_post == 0 ~ "all blank",
      n_filled_post == n_post_cols ~ "all filled",
      TRUE ~ "partially filled")) %>%
  ungroup()

# Summarize
row_check %>%
  count(post_status)

# Check to see if the "partially filled" columns are the ones that are "list" and not "yes/no"
## Columns that are allowed to be blank (not yes/no)
allowed_blank <- c(
  "Pregnancy complications in data set (list)",
  "Fetal complications in data set (list)")

## Columns that should always be filled if AI extraction worked
check_cols <- setdiff(post_cols, allowed_blank)

is_filled_v2 <- function(x) {
  !is.na(x) & str_squish(as.character(x)) != ""
}

row_check_v2 <- data %>%
  rowwise() %>%
  mutate(
    n_filled = sum(is_filled_v2(c_across(all_of(check_cols)))),
    n_cols = length(check_cols),
    status = case_when(
      n_filled == 0 ~ "All blank",
      n_filled == n_cols ~ "All filled",
      TRUE ~ "Partially filled")) %>%
  ungroup()

# Check how many rows are filled/not filled
row_check_v2 %>%
  count(status)
# The incomplete filling did come from AI not being able to access entire papers!

# ==============================================================================
#  2) Make tables for information pulled from GEO and information pulled from AI
# ==============================================================================
# Now, split up into two tables: one for information pulled from GEO and one for
# information pulled from AI
# For the AI table, also filter out any rows that are completely blank
is_blank <- function(x) {
  is.na(x) | str_squish(as.character(x)) == ""
}

# ------------------------------------------------------------------------------
# 2a) GEO information
# ------------------------------------------------------------------------------
# Set GEO table to include everything in the datasheet up to PMID
# (this was the last column that was pulled from GEO)
geo_end <- match("PMID", names(data))
geo_cols <- names(data)[1:geo_end]

# Make table of just GEO-pulled columns
data_geo <- data %>%
  select(all_of(geo_cols))

# ------------------------------------------------------------------------------
# 2b) AI information
# ------------------------------------------------------------------------------
# Set AI table to include everything in the datasheet after MatchedPaperKey
# (everything after MatchedPaperKey was pulled by AI)
ai_start <- match("MatchedPaperKey", names(data)) + 1
ai_cols <- names(data)[ai_start:ncol(data)]

data_ai <- data %>%
  # Remove any blank rows (paper was not read by AI)
  filter(!is_blank(MatchedPaperKey)) %>%
  select(
    `GEO Series ID (GSE___)`,
    `Paper ID used for AI (PMCID or DOI-derived key)`,
    all_of(ai_cols))

# ==============================================================================
#  3) Bar plots
# ==============================================================================
# ------------------------------------------------------------------------------
# 3a) Vertical summary stacked bar chart of number of columns filled in by GEO vs. AI
# ------------------------------------------------------------------------------
# Count how many columns are in each table
source_counts <- tibble(
  Source = c("GEO", "AI"),
  n_cols = c(length(geo_cols), length(ai_cols)))

stacked_bar <- ggplot(source_counts, aes(x = "Columns", y = n_cols, fill = Source)) +
  geom_col(width = 0.6, color = "black") +
  geom_text(aes(label = n_cols), position = position_stack(vjust = 0.5), size = 4) +
  scale_fill_manual(values = c("GEO" = "#225ea8", "AI" = "#1d91c0")) +
  labs(x = NULL, y = "Number of columns", fill = NULL, title = "Column source") +
  theme_classic() +
  theme(axis.text.x = element_blank(),
        axis.ticks.x = element_blank(),
        legend.position = "bottom")
stacked_bar

# Save
ggsave("figures/stacked_bar_geo_summary_raw.png", plot = stacked_bar, width = 12, height = 8, dpi = 300)
ggsave("figures/stacked_bar_geo_summary_raw.pdf", plot = stacked_bar, width = 12, height = 8)

# ------------------------------------------------------------------------------
# 3b) GEO completeness bars
# ------------------------------------------------------------------------------
geo_summary <- data_geo %>%
  summarise(across(everything(), ~ sum(!is_blank(.)))) %>%
  pivot_longer(everything(), names_to = "Column", values_to = "Count") %>%
  mutate(Percent = Count / nrow(data_geo) * 100) %>%
  arrange(desc(Percent))

geo_bars <- ggplot(geo_summary, aes(x = reorder(Column, Percent), y = Percent)) +
  geom_col(fill = "#225ea8", color = "black", width = 0.7) +
  geom_text(aes(label = paste0(round(Percent, 1), "%")), hjust = -0.1, size = 3) +
  coord_flip() +
  scale_y_continuous(limits = c(0, 105), expand = c(0, 0)) +
  labs(title = "GEO data completeness", x = NULL, y = "Percent complete") +
  theme_classic()
geo_bars

# Save
ggsave("figures/geo_bar_summary_raw.png", plot = geo_bars, width = 12, height = 8, dpi = 300)
ggsave("figures/geo_bar_summary_raw.pdf", plot = geo_bars, width = 12, height = 8)

# ------------------------------------------------------------------------------
# 3c) AI completeness bars
# ------------------------------------------------------------------------------
ai_summary <- data_ai %>%
  # Remove any columns that are not yes/no (except for GSE, to group studies together)
  select(-`Paper ID used for AI (PMCID or DOI-derived key)`,
         -`Supervisor/Contact/Corresponding author name`,
         -`Supervisor/Contact/Corresponding author email`,
         -`Main topic of the publication`,
         -`Sampling timing during pregnancy`,
         -`Pregnancy complications in data set (list)`,
         -`Fetal complications in data set (list)`,
         -`Hospital/Center where samples were collected`,
         -`Country where samples were collected`) %>%
  pivot_longer(-c(`GEO Series ID (GSE___)`),
               names_to = "Variable",
               values_to = "Value") %>%
  mutate(Value = case_when(
    is.na(Value) | str_trim(as.character(Value)) == "" ~ "NA",
    TRUE ~ as.character(Value))) %>%
  count(Variable, Value) %>%
  group_by(Variable) %>%
  mutate(Percent = n / sum(n) * 100)

ai_bars <- ggplot(ai_summary, aes(x = Percent, y = fct_rev(Variable), fill = Value)) +
  geom_col(position = "fill", color = "black", width = 0.7) +
  scale_x_continuous(labels = scales::percent) +
  scale_fill_manual(values = c("Yes" = "#1d91c0", "No" = "#1d61c0", "NA" = "grey85")) +
  labs(title = "Availability of information pulled by AI", x = "Percent of studies",
       y = NULL, fill = NULL) +
  theme_classic()
ai_bars

# Save
ggsave("figures/ai_bar_summary_raw.png", plot = ai_bars, width = 12, height = 8, dpi = 300)
ggsave("figures/ai_bar_summary_raw.pdf", plot = ai_bars, width = 12, height = 8)

# Combine the three graphs and edit in Illustrator

# ==============================================================================
#  4) Supplementary figure: completeness bars for the other repositories
# ==============================================================================
# The other repositories use the same column names as GEO, but AI was not used to
# read their papers, so only the GEO-style completeness bars (3b) are made here.
# Many columns will be 0% because that field does not exist in the repository
# (e.g., Library strategy for mass spectrometry data)

# Read in the other repositories (one tab per repository) and label the source tab
## .id goes in bind_rows (not map) so the tab names become source_sheet
repo_file <- "Final_repository_metadata_combined_dbs.xlsx"
data_repos <- excel_sheets(repo_file) %>%
  set_names() %>%
  purrr::map(~ read_excel(repo_file, sheet = .x, col_types = "text")) %>%
  bind_rows(.id = "source_sheet")

# Check number of entries per repository
data_repos %>%
  count(source_sheet)

# Percent of entries with each column filled in, per repository
## Use the same columns as the GEO bars (geo_cols from 2a) so the panels match the main figure
repo_summary <- data_repos %>%
  select(source_sheet, all_of(geo_cols)) %>%
  group_by(source_sheet) %>%
  summarise(n_entries = n(),
            across(all_of(geo_cols), ~ sum(!is_blank(.))),
            .groups = "drop") %>%
  pivot_longer(all_of(geo_cols), names_to = "Column", values_to = "Count") %>%
  mutate(Percent = Count / n_entries * 100,
         # Keep the same row order as the GEO bars (most complete in GEO at the top)
         Column = factor(Column, levels = levels(reorder(geo_summary$Column, geo_summary$Percent))),
         # Panel titles with the number of entries, ordered from most to fewest entries
         repository = paste0(source_sheet, " (n = ", n_entries, ")"),
         repository = fct_reorder(repository, n_entries, .desc = TRUE)) %>% 
  arrange(desc(Percent))


# Colors for each repository (matches the summary pie chart and studies by year)
repo_colors <- c("PRIDE" = "#2a9d8f",
                 "MassIVE" = "#f4a261",
                 "Metabolomics Workbench" = "#e76f51",
                 "dbGaP" = "#e9c46a",
                 "MetaboLights" = "#7570b3")

# One panel per repository, side by side so they share the column names on the left
repo_bars <- ggplot(repo_summary, aes(x = Percent, y = Column, fill = source_sheet)) +
  geom_col(color = "black", width = 0.7) +
  geom_text(aes(label = paste0(round(Percent, 1), "%")), hjust = -0.1, size = 3) +
  facet_wrap(~ repository, nrow = 1) +
  
  scale_fill_manual(values = repo_colors, guide = "none") +
  # Extra room past 100% so the percent labels don't run into the next panel
  scale_x_continuous(limits = c(0, 130), breaks = c(0, 50, 100), expand = c(0, 0)) +
  labs(title = "Data completeness in the other repositories", x = "Percent complete", y = NULL) +
  theme_classic()
repo_bars

# Save
ggsave("supplementary/repositories_bar_summary_raw.png", plot = repo_bars, width = 16, height = 8, dpi = 300)
ggsave("supplementary/repositories_bar_summary_raw.pdf", plot = repo_bars, width = 16, height = 8)

# ==============================================================================
#  5) Supplementary table: entries with a linked publication (PMID/PMCID/DOI) in each repository
# ==============================================================================
# Check how many entries in each repository have an associated publication
# (AI could only read papers for entries with a PMID, PMCID, or DOI)
# An entry counts as having an identifier if the main column OR the "All ..." column is filled
pub_ids <- data %>%
  select(PMID, `All PMIDs`, PMCID, `All PMCIDs`, DOI, `All DOIs`) %>%
  # GEO was not read in as text, so convert before combining with the other repositories
  mutate(across(everything(), as.character), source_sheet = "GEO") %>%
  bind_rows(data_repos %>%
              select(source_sheet, PMID, `All PMIDs`, PMCID, `All PMCIDs`, DOI, `All DOIs`)) %>%
  mutate(has_pmid = !is_blank(PMID) | !is_blank(`All PMIDs`),
         has_pmcid = !is_blank(PMCID) | !is_blank(`All PMCIDs`),
         has_doi = !is_blank(DOI) | !is_blank(`All DOIs`),
         has_any = has_pmid | has_pmcid | has_doi)

pub_by_repo <- pub_ids %>%
  group_by(Repository = source_sheet) %>%
  summarise(Entries = n(),
            PMID = sum(has_pmid),
            PMCID = sum(has_pmcid),
            DOI = sum(has_doi),
            Any = sum(has_any),
            .groups = "drop")

pub_table <- bind_rows(pub_by_repo) %>%
  # Order rows: GEO first, then largest to smallest, then the combined row
  mutate(Repository = factor(Repository,
                             levels = c("GEO", "PRIDE", "Metabolomics Workbench", "MassIVE",
                                        "dbGaP", "MetaboLights"))) %>%
  arrange(Repository) %>%
  # Write each count as "n (%)"
  mutate(across(PMID:Any, ~ paste0(.x, " (", round(.x / Entries * 100, 1), "%)")))
pub_table

# Number of GEO papers the AI was able to read (for comparison with GEO "Any")
sum(!is_blank(data$MatchedPaperKey))

# Save
write.xlsx(pub_table, "supplementary/publication_identifiers_by_repository.xlsx")
