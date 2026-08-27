# ------
# HOW DO PLACENTA STUDIES STUDIES SUBMITTED TO GEO VARY BY YEAR?
# Goal
#   Look at distribution of number of placenta-related studies and number of samples in placenta-related studies submitted to GEO across the years
# Contents
#   1) Number of placenta-related GEO entries by year
#   2) Number of placenta samples submitted to GEO by year
# ------

# Data sheet last downloaded: June 23, 2026

# Install and load packages
library(dplyr)
library(readxl)
library(tidyr)
library(stringr)
library(ggplot2)

# Set working directory
setwd("~/Desktop/placenta_db")

# Read in the data freeze file
data <- read_excel("geo_completed_sheet.xlsx")

# === 1) Number of placenta-related GEO entries by year ===
data_studies <- data %>% 
  # Extract the year from the date
  mutate(year=format(as.Date(data$`Submission date`, format="%m/%d/%Y"), "%Y"), .after=1) %>%
  # Convert year from character to numeric
  mutate(year = as.numeric(as.character(year))) %>% 
  # Remove any empty cells
  filter(!is.na(year)) %>%
  # Restrict range to 2002-2025
  filter(year >= 2002, year <= 2025) %>% 
  # Count how many submissions there are per year
  count(year)

# Bar plot
geo_studies <- ggplot(data_studies, aes(x=year, y=n)) +
  geom_col(fill="#225ea8") +
  geom_text(aes(label=n),
            vjust=-0.3,
            size=4) +
  labs(x="Year", y="Entries",
       title="Number of Placenta-Related Entries Submitted to GEO by Year") +
  theme_classic() +
  scale_x_continuous(breaks = seq(min(data_studies$year), max(data_studies$year), by = 1)) +
  scale_y_continuous(expand=c(0,0)) +
  coord_cartesian(clip="off") +
  theme(axis.text.x = element_text(angle = 45, hjust = 1),
        axis.title.x = element_text(margin=margin(t=10)))
geo_studies

# Save
ggsave("figures/placenta_geo_studies.png", plot = geo_studies, width = 10, height = 6, dpi = 300)
ggsave("figures/placenta_geo_studies.pdf", plot = geo_studies, width = 10, height = 6, dpi = 300)

# === 2) Number of placenta samples submitted to GEO by year ===
data_samples <- data %>%
  # Extract the year from the date
  mutate(year=format(as.Date(data$`Submission date`, format="%m/%d/%Y"), "%Y"), .after=1) %>%
  # Convert year from character to numeric
  mutate(year = as.numeric(as.character(year))) %>% 
  # Remove any empty cells
  filter(!is.na(year), !is.na(`Sample size (placenta)`)) %>% 
  # Restrict range to 2002-2025
  filter(year >= 2002, year <= 2025) %>% 
  # Count how many placenta samples were submitted by year and calculate average submission size
  group_by(year) %>%
  summarise(total_samples = sum(`Sample size (placenta)`),
            # Count how many studies were submitted in a year
            n_studies = n(),
            avg_sample_size = total_samples / n_studies)

# Scale avg_sample_size onto the same range as total_samples (for proper plotting)
scale_factor <- max(data_samples$total_samples) / max(data_samples$avg_sample_size)

# Plot
geo_samples <- ggplot(data_samples, aes(x=year)) +
  geom_col(aes(y = total_samples), fill="#a1dab4") +
  geom_text(aes(y = total_samples, label=total_samples),
            vjust=-0.3, size=4) +
  geom_line(aes(y = avg_sample_size * scale_factor), color = "#b2182b", linewidth = 1, group = 1)+
  geom_point(aes(y = avg_sample_size * scale_factor), color = "#b2182b", size = 2) +
  geom_text(aes(y = avg_sample_size * scale_factor, label = round(avg_sample_size, 1)),
            vjust = -1, size = 3.5, color = "#b2182b") +
  scale_y_continuous(name = "Total Samples",
                     expand=c(0,0),
                     sec.axis = sec_axis(~ . / scale_factor, name = "Average Sample Size per Study")) + 
  labs(x="Year", title="Number of Samples in Placenta-Related Entries Submitted to GEO by Year") +
  theme_classic() +
  scale_x_continuous(breaks = seq(min(data_samples$year), max(data_samples$year), by = 1)) +
  coord_cartesian(clip="off") +
  theme(axis.text.x = element_text(angle = 45, hjust = 1),
        axis.title.x = element_text(margin=margin(t=10)),
        axis.title.y.right = element_text(color="#b2182b"),
        axis.text.y.right = element_text(color="#b2182b"),
        axis.line.y.right = element_line(color="#b2182b"),
        axis.ticks.y.right = element_line(color="#b2182b"))
geo_samples

# Save
ggsave("figures/placenta_geo_samples.png", plot = geo_samples, width =10, height = 6, dpi = 300)
ggsave("figures/placenta_geo_samples.pdf", plot = geo_samples, width =10, height = 6, dpi = 300)
