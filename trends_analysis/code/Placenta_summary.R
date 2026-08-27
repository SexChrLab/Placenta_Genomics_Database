# ------
# HOW MUCH INFORMATION IS IN THE PLACENTA DATABASE?
# Goal
#   Summarize contents and completeness of placenta database.
# Contents
#   1) Check  data
#   2) Make tables for information pulled from GEO and information pulled from AI
#     a) GEO information
#     b) AI information
#   3) Bar plots
#     a) Vertical summary stacked bar chart of number of columns filled in by GEO vs. AI
# ------

# Data sheet last downloaded: June 23, 2026

# Install and load packages
library(readxl)
library(tidyverse)

# Set working directory
setwd("~/Desktop/placenta_db")

# Read in the data freeze file
data <- read_excel("geo_completed_sheet.xlsx")

# === 1) Check and clean data ===
# First, check if all the NAs in the AI columns come from the AI not being able to read the paper, or if the AI isn't pulling some columns for some reason.
# Find all columns after the AI paper ID column
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
# Columns that are allowed to be blank (not yes/no)
allowed_blank <- c(
  "Pregnancy complications in data set (list)",
  "Fetal complications in data set (list)")

# Columns that should always be filled if AI extraction worked
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
      TRUE ~ "Partially filled"
    )
  ) %>%
  ungroup()

# Check how many rows are filled/not filled
row_check_v2 %>%
  count(status)
# The incomplete filling did come from AI not being able to access entire papers!


# === 2) Make tables for information pulled from GEO and information pulled from AI ===
# Now, split up into two table: one for information pulled from GEO and one for information pulled from AI
# For the AI table, also filter out any rows that are completely blanks

is_blank <- function(x) {
  is.na(x) | str_squish(as.character(x)) == ""
}

# ==== a) GEO information ====
# Set GEO table to include everything in the datasheet up to PMID (this was the last column that was pulled from GEO)
geo_end <- match("PMID", names(data))
geo_cols <- names(data)[1:geo_end]

# Make table of just GEO-pulled columns
data_geo <- data %>%
  select(all_of(geo_cols))

# ==== b) AI information ====
# Set AI table to include everything in the datasheet after MatchedPaperKey (everything after MatchedPaperKey was pulled by AI) 
ai_start <- match("MatchedPaperKey", names(data)) + 1
ai_cols <- names(data)[ai_start:ncol(data)]

data_ai <- data %>%
  # Remove any blank rows (paper was not read by AI)
  filter(!is_blank(MatchedPaperKey)) %>%
  select(
    `GEO Series ID (GSE___)`,
    `Paper ID used for AI (PMCID or DOI-derived key)`,
    all_of(ai_cols))

# === 3) Bar plots ===
# ==== a) Vertical summary stacked bar chart of number of columns filled in by GEO vs. AI ====
# Count how many columns are in each table
source_counts <- tibble(
  Source = c("GEO", "AI"),
  n_cols = c(length(geo_cols), length(ai_cols)))

stacked_bar <- ggplot(source_counts, aes(x = "Columns", y = n_cols, fill = Source)) +
  geom_col(width = 0.6, color = "black") +
  geom_text(aes(label = n_cols), position = position_stack(vjust = 0.5), size = 4) +
  scale_fill_manual(values = c("GEO" = "#b39ddb", "AI" = "#673ab7")) +
  labs(x = NULL, y = "Number of columns", fill = NULL, title = "Column source") +
  theme_classic() +
  theme(
    axis.text.x = element_blank(),
    axis.ticks.x = element_blank(),
    legend.position = "bottom")
stacked_bar
# Save 
ggsave("figures/stacked_bar_summary.pdf", plot = stacked_bar, width = 12, height = 8, dpi = 300)

# ==== b) GEO completeness bars ====
geo_summary <- data_geo %>%
  summarise(across(everything(), ~ sum(!is_blank(.)))) %>%
  pivot_longer(everything(), names_to = "Column", values_to = "Count") %>%
  mutate(Percent = Count / nrow(data_geo) * 100) %>%
  arrange(desc(Percent))

geo_bars <- ggplot(geo_summary, aes(x = reorder(Column, Percent), y = Percent)) +
  geom_col(fill = "#b39ddb", color = "black", width = 0.7) +
  geom_text(aes(label = paste0(round(Percent, 1), "%")), hjust = -0.1, size = 3) +
  coord_flip() +
  scale_y_continuous(limits = c(0, 105), expand = c(0, 0)) +
  labs(title = "GEO data completeness", x = NULL, y = "Percent complete") +
  theme_classic()
geo_bars

# Save 
ggsave("figures/geo_bar_summary.pdf", plot = geo_bars, width = 12, height = 8, dpi = 300)

# ==== c) AI completeness bars ====
ai_summary <- data_ai %>%
  # Remove any columns that are not yes/no (except for GSE, to group studies together)
  select(-`Paper ID used for AI (PMCID or DOI-derived key)`, -`Supervisor/Contact/Corresponding author name`, -`Supervisor/Contact/Corresponding author email`, -`Main topic of the publication`, -`Sampling timing during pregnancy`, -`Pregnancy complications in data set (list)`, -`Fetal complications in data set (list)`, -`Hospital/Center where samples were collected`, -`Country where samples were collected`) %>% 
  pivot_longer(-c(`GEO Series ID (GSE___)`),
    names_to = "Variable",
    values_to = "Value") %>%
  mutate(Value = case_when(is.na(Value) | str_trim(as.character(Value)) == "" ~ "NA", TRUE ~ as.character(Value))) %>% 
  count(Variable, Value) %>%
  group_by(Variable) %>%
  mutate(Percent = n / sum(n) * 100)

ai_bars<- ggplot(ai_summary, aes(x = Percent, y = fct_rev(Variable), fill = Value)) +
  geom_col(position = "fill", color = "black", width = 0.7) +
  scale_x_continuous(labels = scales::percent) +
  scale_fill_manual(values = c("Yes" = "#673ab7", "No" = "#b39ddb", "NA" = "grey85")) +
  labs(title = "Availability of information pulled by AI", x = "Percent of studies", y = NULL, fill = NULL) +
  theme_classic()
ai_bars

# Save
ggsave("figures/ai_bar_summary.pdf", plot = ai_bars, width = 12, height = 8, dpi = 300)

# Combine the three graphs and edit in Illustrator