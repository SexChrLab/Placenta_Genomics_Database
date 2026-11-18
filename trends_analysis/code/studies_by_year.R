# ------------------------------------------------------------------------------
# Bar charts of placenta-related studies and number of samples in placenta-related 
# studies submitted to repositories between 2002 and 2025.
#
# Contents
#   1) Read in & clean up data
#   2) Number of placenta-related entries by year
#   3) Number of reported placenta samples by year

# Author: Nora Shefferman
# Last edited: 11-09-2026
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

# Clean up dates and sample counts
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
  # Extract the year and convert sample counts from text to numbers
  # Keep the original sample count column for reference
  mutate(year = year(submission_date),
         placenta_samples = suppressWarnings(as.numeric(str_remove_all(
           `Sample size (placenta)`, ","))))

# Check how many entries from each source can be included in each figure
data_coverage <- data %>%
  group_by(source_sheet) %>%
  summarise(total_entries = n(),
            missing_dates = sum(is.na(year)),
            entries_in_year_figure = sum(year >= 2002 & year <= 2025, na.rm = TRUE),
            entries_in_sample_figure = sum(year >= 2002 & year <= 2025 &
                                             !is.na(placenta_samples) &
                                             placenta_samples >= 0, na.rm = TRUE), 
            .groups = "drop")
data_coverage

# ==============================================================================
#  2) Number of placenta-related entries by year
# ==============================================================================
# Count how many entries were submitted to all repositories each year. 
# Output will be a stacked bar for each year. 
data_studies_repo <- data %>%
  # Remove any empty cells
  filter(!is.na(year)) %>%
  # Restrict range to 2002-2025
  filter(year >= 2002, year <= 2025) %>%
  # Use the repository names in the legend
  mutate(repository = recode(source_sheet, "geo" = "GEO")) %>%
  # Count how many submissions each repository has per year
  count(year, repository) %>%
  # Order the legend/stack from most to fewest entries
  mutate(repository = factor(repository,
                             levels = c("GEO", "PRIDE", "MassIVE",
                                        "Metabolomics Workbench", "dbGaP",
                                        "MetaboLights")))

# Colors for each repository (matches the summary pie chart)
repo_colors <- c("GEO" = "#225ea8",
                 "PRIDE" = "#2a9d8f",
                 "MassIVE" = "#f4a261",
                 "Metabolomics Workbench" = "#e76f51",
                 "dbGaP" = "#e9c46a",
                 "MetaboLights" = "#7570b3")

# Stacked bar plot
placenta_studies_repo <- ggplot(data_studies_repo,
                                aes(x=year, y=n, fill=repository)) +
  # geom_col stacks the repositories within each year by default
  geom_col() +
  # Label the total for each year on top of the stack
  # (data_studies from section 2 already has the per-year totals)
  geom_text(data = data_studies_repo %>% 
              group_by(year) %>% 
              summarise(n = sum(n)),
            aes(x=year, y=n, label=n),
            inherit.aes = FALSE,
            vjust=-0.3,
            size=4) +
  scale_fill_manual(values = repo_colors) +
  labs(x="Year", y="Entries", fill="Repository") +
  theme_classic() +
  scale_x_continuous(breaks = seq(min(data_studies_repo$year),
                                  max(data_studies_repo$year), by = 1)) +
  scale_y_continuous(expand = expansion(mult = c(0,0.05))) +
  coord_cartesian(clip="off") +
  theme(axis.text.x = element_text(angle = 45, hjust = 1),
        axis.title.x = element_text(margin=margin(t=10)))
placenta_studies_repo

# Save
ggsave("figures/placenta_omics_studies_by_repo_raw.png", plot = placenta_studies_repo, width = 10, height = 6, dpi = 300)
ggsave("figures/placenta_omics_studies_by_repo_raw.pdf", plot = placenta_studies_repo, width = 10, height = 6)

# ==============================================================================
#  3) Number of reported placenta samples by year
# ==============================================================================
# Count how many entries were submitted to GEO each year. 
# None of the other repositories have placenta sample numbers consistently available, so this figure will only represent GEO.
data_samples <- data %>%
  # Only GEO reports placenta sample numbers consistently
  filter(source_sheet == "geo") %>% 
  # Both a submission year and placenta sample count are needed
  filter(!is.na(year), !is.na(placenta_samples), placenta_samples >= 0) %>% 
  # Restrict range to 2002-2025
  filter(year >= 2002, year <= 2025) %>% 
  # Count how many placenta samples were submitted by year and calculate average 
  # submission size
  group_by(year) %>%
  summarise(total_samples = sum(placenta_samples),
            # Count how many studies were submitted in a year
            n_studies = n(),
            avg_sample_size = total_samples / n_studies)

# Scale avg_sample_size onto the same range as total_samples (for proper plotting)
scale_factor <- max(data_samples$total_samples) / max(data_samples$avg_sample_size)

# Plot
geo_samples <- ggplot(data_samples, aes(x=year)) +
  geom_col(aes(y = total_samples), fill="#225ea8") +
  geom_text(aes(y = total_samples, label=total_samples),
            vjust=-0.3, size=4) +
  geom_line(aes(y = avg_sample_size * scale_factor), color = "#b2182b", 
            linewidth = 1, group = 1)+
  geom_point(aes(y = avg_sample_size * scale_factor), color = "#b2182b", size = 2) +
  geom_text(aes(y = avg_sample_size * scale_factor, label = round(avg_sample_size, 1)),
            vjust = -1, size = 3.5, color = "#b2182b") +
  scale_y_continuous(name = "Total Samples",
                     expand = expansion(mult = c(0,0.05)),
                     sec.axis = sec_axis(~ . / scale_factor, name = "Average Sample 
                                         Size per Study")) + 
  labs(x="Year") +
  theme_classic() +
  scale_x_continuous(breaks = seq(min(data_samples$year), max(data_samples$year), 
                                  by = 1)) +
  coord_cartesian(clip="off") +
  theme(axis.text.x = element_text(angle = 45, hjust = 1),
        axis.title.x = element_text(margin=margin(t=10)),
        axis.title.y.right = element_text(color="#b2182b"),
        axis.text.y.right = element_text(color="#b2182b"),
        axis.line.y.right = element_line(color="#b2182b"),
        axis.ticks.y.right = element_line(color="#b2182b"))
geo_samples

# Save
ggsave("figures/placenta_geo_samples_raw.png", plot = geo_samples, width =10, height = 6, dpi = 300)
ggsave("figures/placenta_geo_samples_raw.pdf", plot = geo_samples, width =10, height = 6)
