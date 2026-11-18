# ------------------------------------------------------------------------------
# Pie chart of studies in the placenta database by the data repository they come 
# from (between 2002 and 2025).
#
# Contents
#   1) Read in & clean up data
#   2) Count entries in each spreadsheet
#   3) Make pie chart of studies per repository
#   4) Pie-donut chart: repositories in the pie, molecule type in the outer donut

# Author: Nora Shefferman
# Last edited: 11-18-2026
# ------------------------------------------------------------------------------

# Data sheets last downloaded:
## geo_completed_sheet.xlsx 11-04-2026
## Final_repository_metadata_combined_dbs.xlsx 11-06-2026

# Install and load packages
library(readxl)
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
sheet_names <- excel_sheets("Final_repository_metadata_combined_dbs.xlsx")
data_protein <- sheet_names %>% 
  set_names() %>% 
  purrr::map(~ read_excel("Final_repository_metadata_combined_dbs.xlsx", sheet = .x, 
                          col_types = "text"), .id = "source_sheet") %>% 
  bind_rows(.id = "source_sheet")
# Combine the GEO and additional repository tables for downstream analysis
data_geo_clean <- data_geo %>% 
  mutate(source_sheet = "geo", across(everything(), as.character))
data <- bind_rows(data_geo_clean, data_protein) %>%
  relocate(source_sheet, .before = everything())

# Clean up dates (same steps as studies_by_year.R)
data <- data %>%
  # Excel dates imported as text can appear as numbers such as "45860"
  # Convert those numbers to dates
  mutate(submission_date = case_when(
    str_detect(`Submission date`, "^[0-9]{5}(\\.[0-9]+)?$") ~
      as.character(as.Date(suppressWarnings(as.numeric(`Submission date`)),
                           origin = "1899-12-30")),
    TRUE ~ `Submission date`)) %>%
  # Handle dates such as 03/27/2021, Feb 23 2012, and 2025-07-22
  mutate(submission_date = as.Date(parse_date_time(
    submission_date, orders = c("mdy", "ymd", "ymd HMS", "mdy HMS"),
    locale = "C", tz = "UTC", quiet = TRUE))) %>%
  mutate(year = year(submission_date))

# ==============================================================================
#  2) Count entries in each spreadsheet
# ==============================================================================
# Check how many entries are dropped by the year cutoff
data %>%
  group_by(source_sheet) %>%
  summarise(total_entries = n(),
            missing_dates = sum(is.na(year)),
            before_2002 = sum(year < 2002, na.rm = TRUE),
            in_2026 = sum(year > 2025, na.rm = TRUE),
            kept = sum(year >= 2002 & year <= 2025, na.rm = TRUE))

# Count entries in each repository (each row is one study)
# Restrict range to 2002-2025 to match the trends analysis (2026 is not complete yet)
# Entries with no submission date are also dropped (1 MassIVE entry)
study_counts <- data %>%
  filter(!is.na(year)) %>%
  filter(year >= 2002, year <= 2025) %>%
  # Use the repository names in the legend
  mutate(Repository = recode(source_sheet, "geo" = "GEO")) %>%
  count(Repository) %>%
  # Order slices from largest to smallest
  arrange(desc(n)) %>%
  mutate(
    Percent = n / sum(n) * 100,
    # Put the counts in the legend since the small slices are too thin to label
    Label = paste0(Repository, " (n = ", n, ")"),
    Label = factor(Label, levels = Label))

# Check counts
study_counts
sum(study_counts$n)

# ==============================================================================
#  3) Pie chart of studies per repository
# ==============================================================================
database_pie <- ggplot(study_counts, aes(x = "", y = n, fill = Label)) +
  geom_col(width = 1, color = "white") +
  coord_polar(theta = "y") +
  theme_void() +
  # Colors go in slice order (largest to smallest):
  # GEO, PRIDE, Metabolomics Workbench, MassIVE, dbGaP, MetaboLights
  scale_fill_manual(values = c("#225ea8", "#2a9d8f", "#e76f51", "#f4a261", "#e9c46a", "#7570b3")) +
  labs(fill = NULL, title = paste0("Studies in the placenta database, 2002-2025 (n = ", sum(study_counts$n), ")"))
database_pie

# Save
ggsave("figures/placenta_omics_database_pie_raw.png", plot = database_pie, width = 8, height = 6, dpi = 300)
ggsave("figures/placenta_omics_database_pie_raw.pdf", plot = database_pie, width = 8, height = 6)


# ==============================================================================
#  4) Pie-donut chart
# ==============================================================================
# In order to represent the molecule types represented in the repositories, I will 
# make a donut pie chart, with repositories in the pie and the molecule type in the
# outer donut. 

# MassIVE entries with a blank Data type were labeled one by one in the assay entry lookup
massive_labels <- read_excel("code/files_used_in_code/assay_entry_lookup_to_label_filled.xlsx",
                             col_types = "text") %>%
  select(Entry_ID, Molecule_entry = Molecule)

# Assign one molecule type to each study
data_molecule <- data %>%
  filter(!is.na(year)) %>%
  filter(year >= 2002, year <= 2025) %>%
  mutate(Repository = recode(source_sheet, "geo" = "GEO")) %>%
  left_join(massive_labels, by = c("GEO Series ID (GSE___)" = "Entry_ID")) %>%
  mutate(Molecule = case_when(
    # GEO has two protein-only studies (mass spec and protein array)
    Repository == "GEO" & str_detect(`Data type`, "^Protein profiling") ~ "Protein",
    Repository %in% c("GEO", "dbGaP") ~ "DNA/RNA",
    Repository == "PRIDE" ~ "Protein",
    Repository == "MassIVE" & `Data type` == "Proteomics" ~ "Protein",
    Repository == "MassIVE" ~ Molecule_entry,
    Repository %in% c("Metabolomics Workbench", "MetaboLights") ~ "Metabolite"))

# Check -- should show no NA molecules
data_molecule %>%
  count(Repository, Molecule)

# Repository order (largest to smallest, same as section 2) and molecule order within each slice
repo_levels <- study_counts$Repository
molecule_levels <- c("DNA/RNA", "Protein", "Metabolite")

# Split each repository slice into molecule pieces, in the same slice order as the pie
slice_molecule <- data_molecule %>%
  count(Repository, Molecule) %>%
  arrange(factor(Repository, levels = repo_levels),
          factor(Molecule, levels = molecule_levels)) %>%
  # Start and end of each piece
  mutate(ymax = cumsum(n),
         ymin = lag(ymax, default = 0))
slice_molecule

# Molecule totals (for the caption/text)
molecule_totals <- slice_molecule %>%
  group_by(Molecule) %>%
  summarise(n = sum(n)) %>%
  mutate(Percent = n / sum(n) * 100)
molecule_totals

# Inner pie: start and end of each repository slice
pie_slices <- study_counts %>%
  mutate(ymax = cumsum(n),
         ymin = lag(ymax, default = 0))

# Donut labels: molecule type and percent within the repository
# Placed just outside the donut -- tidy up the overlapping small ones in Illustrator
donut_labels <- slice_molecule %>%
  group_by(Repository) %>%
  mutate(Percent_in_repo = n / sum(n) * 100) %>%
  ungroup() %>%
  mutate(mid = (ymin + ymax) / 2,
         Label = paste0(Molecule, " ", round(Percent_in_repo, 1), "%"))

# Plot
# x = 0-2 is the pie, x = 2-3 is the donut, labels at x = 3.4
database_pie_donut <- ggplot() +
  geom_rect(data = pie_slices,
            aes(xmin = 0, xmax = 2, ymin = ymin, ymax = ymax, fill = Repository),
            color = "white") +
  geom_rect(data = slice_molecule,
            aes(xmin = 2, xmax = 2.5, ymin = ymin, ymax = ymax, fill = Repository),
            alpha = 0.5, color = "white", linewidth = 0.3) +
  geom_text(data = donut_labels,
            aes(x = 3.4, y = mid, label = Label),
            size = 3) +
  # direction = -1 starts at 12 o'clock with GEO and goes counterclockwise
  coord_polar(theta = "y", direction = -1) +
  xlim(0, 3.6) +
  theme_void() +
  # Same repository colors as section 3 and studies_by_year.R
  scale_fill_manual(
    values = c("GEO" = "#225ea8", "dbGaP" = "#e9c46a", "PRIDE" = "#2a9d8f",
               "MassIVE" = "#f4a261", "Metabolomics Workbench" = "#e76f51",
               "MetaboLights" = "#7570b3"),
    breaks = repo_levels,
    labels = as.character(study_counts$Label)) +
  labs(fill = NULL,
       title = paste0("Studies in the placenta database, 2002-2025 (n = ",
                      sum(study_counts$n), ")"))
database_pie_donut

# Save 
ggsave("figures/placenta_omics_database_pie_donut_raw.png", plot = database_pie_donut, width = 8, height = 6, dpi = 300)
ggsave("figures/placenta_omics_database_pie_donut_raw.pdf", plot = database_pie_donut, width = 8, height = 6)
