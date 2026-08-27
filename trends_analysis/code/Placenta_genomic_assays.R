# ------
# WHAT GENOMICS ASSAYS ARE USED IN PLACENTA RESEARCH?
# Goal
#   Plot the genomics assays used in placenta research over time. Violin plots will show the quantity and distribution of assays over the years.
# Contents
#   1) Violin plots of extracted molecules assay types
# ------

# Data sheet last downloaded: June 23, 2026

# Install and load packages
library(readxl)
install.packages("openxlsx")
library(openxlsx)
library(tidyverse)

# Set working directory
setwd("~/Desktop/placenta_db")

# Read in the data freeze file
data <- read_excel("geo_completed_sheet.xlsx") %>% 
  # Only keep relevant columns
  select(`GEO Series ID (GSE___)`, `Data type`, `Extracted molecule`, `Library Strategy`, `Submission date`)

# === 1) Violin plots of extracted molecules assay types ===
# Since each row of the data table can contain multiple entries for Data type, Extracted molecule, and Library strategy, we have to first figure out which combinations are actually real.
# To do this, I will make a table of unique pairs of Data type, Extracted molecule, and Library strategy and manually label what category they should be in. Then I will read the lookup table back in and assign each entry a category based on my manual curration.

# Expand the full dataset into one row per observed combination
expanded <- data %>%
  separate_rows(`Data type`, sep = ",\\s*|\\s*\\|\\s*") %>%
  separate_rows(`Extracted molecule`, sep = ",\\s*|\\s*\\|\\s*") %>%
  separate_rows(`Library Strategy`, sep = ",\\s*|\\s*\\|\\s*") %>%
  transmute(
    GSE = `GEO Series ID (GSE___)`,
    year = as.integer(format(as.Date(`Submission date`, format = "%m/%d/%Y"), "%Y")),
    Data_Type = str_squish(`Data type`),
    Extracted_Molecule = str_squish(`Extracted molecule`),
    Library_Strategy = str_squish(`Library Strategy`)) %>%
  distinct()

# Make the unique lookup table to manually label
lookup <- expanded %>%
  distinct(Data_Type, Extracted_Molecule, Library_Strategy) %>%
  mutate(
    Molecule = NA_character_,
    Category = NA_character_,
    Assay_Type = NA_character_,
    Keep = NA)

# Export as an Excel sheet for manual editing
write.xlsx(lookup, "supplementary/geo_lookup_to_label.xlsx")

# After manually annotating in Excel, re-read the lookup table and join to existing table
lookup_labeled <- read_excel("supplementary/geo_lookup_to_label_filled.xlsx")
plot_data <- expanded %>%
  left_join(lookup_labeled, by = c("Data_Type", "Extracted_Molecule", "Library_Strategy")) %>%
  filter(Keep == TRUE) %>% 
  # Remove any duplicates (keeps duplicate studies that use different assays within the study)
  distinct(GSE, year, Molecule, Category, Assay_Type) %>%
  filter(Molecule %in% c("DNA", "RNA", "Protein")) %>%
  # Label based on Array and Category
  mutate(Panel = case_when(
    Molecule == "DNA" & Category == "Methylation" ~ paste("Methylation", Assay_Type, sep = " — "),
    Molecule == "DNA" & Category == "Variant analysis" ~ paste("Variant analysis", Assay_Type, sep = " — "),
    Molecule == "RNA" & Category == "Coding RNA" ~ paste("Coding RNA", Assay_Type, sep = " — "),
    Molecule == "RNA" & Category == "Non-coding RNA" ~ paste("Non-coding RNA", Assay_Type, sep = " — "),
    Molecule == "Protein" & Category == "Protein" ~ paste("Protein", Assay_Type, sep = " — "),
    TRUE ~ NA_character_),
    Molecule = factor(Molecule, levels = c("DNA", "RNA", "Protein")),
    Assay_Type = factor(Assay_Type, levels = c("Array", "Sequencing"))) %>%
  filter(!is.na(Panel))

# Order panels
plot_data$Panel <- factor(
  plot_data$Panel,
  levels = c(
    "Methylation — Array",
    "Methylation — Sequencing",
    "Variant analysis — Array",
    "Variant analysis — Sequencing",
    "Coding RNA — Array",
    "Coding RNA — Sequencing",
    "Non-coding RNA — Array",
    "Non-coding RNA — Sequencing",
    "Protein — Array", 
    "Protein — Sequencing"))

# Plot -- will re-label the facet labels in Illustrator
violin_plot <- ggplot(plot_data, aes(x = year, y = Panel, fill = Assay_Type)) +
  geom_violin(trim = FALSE, alpha = 0.6, width = 1) +
  geom_jitter(height = 0.15, size = 0.7, alpha = 0.5) +
  facet_grid(rows = vars(Molecule), switch = "y") +
  scale_fill_manual(values = c("Array" = "#e9c46a", "Sequencing" = "#dd1c77")) +
  scale_x_continuous(breaks = seq(2002, 2025, by = 2)) +
  labs(title = "Genomics Assays Used in Placenta Research", x = "Year", y = NULL, fill = "Assay Type") +
  theme_classic() +
  theme(legend.position = "bottom", axis.text.x = element_text(angle = 45, hjust = 1),
        axis.text.y = element_blank(),
        axis.ticks.y = element_blank(),
        axis.line.y = element_blank(),
        strip.placement = "outside",
        strip.background = element_rect(
          fill = "white",
          color = "black"),
        strip.text.y.left = element_text(
          size = 12,
          face = "plain"))
violin_plot
# Save
ggsave("figures/placenta_genomics_assays_raw.pdf", plot = violin_plot, width = 12, height = 8, dpi = 300)

# Count studies for Illustrator labels
count_assays <- plot_data %>%
  # Restrict years to 2002-2025 to match other figures
  filter(year <= 2025) %>% 
  count(Panel)
# Save
write_csv(count_assays, "supplementary/count_assays.csv")

# Label each panel and counts in Illustrator 