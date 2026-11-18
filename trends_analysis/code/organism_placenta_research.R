# ------------------------------------------------------------------------------
# Pie chart of organisms used in placenta research studies submitted to public data 
# repositories between 2002 and 2025.
#
# Contents
#   1) Read in & clean up data
#   2) Use taxize to standardize organism names that are taxids
#   3) Pie chart of organisms (plots all organisms with 2 or more counts)
#   4) Make table listing "Other" species and counts

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
#install.packages("taxize")
library(taxize)

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
  # Missing dates become NA
  mutate(submission_date = as.Date(parse_date_time(
    submission_date, orders = c("mdy", "ymd", "ymd HMS", "mdy HMS"),
    locale = "C", tz = "UTC", quiet = TRUE))) %>%
  mutate(year = year(submission_date))

# List of studies submitted between 2002 and 2025 (filter also removes studies with no date)
# Used in 3) to restrict the pie chart and Other table to 2002-2025
studies_in_window <- data %>%
  filter(year >= 2002, year <= 2025) %>%
  distinct(source_sheet, `GEO Series ID (GSE___)`)

# Format table for downstream analysis
data_organism <- data %>% 
  # Only keep relevant columns
  select(source_sheet, `GEO Series ID (GSE___)`, Organism) %>% 
  # Remove any NA rows
  filter(!is.na(Organism)) %>%
  # Break up any entries that are mixed-species (so Homo sapiens, Mus musculus becomes Homo sapiens and Mus musculus)
  # PRIDE separates species with ";" instead of ","
  separate_rows(Organism, sep = ",\\s*|\\s*\\|\\s*|;\\s*") %>%
  # PRIDE adds the common name in parentheses, e.g. "Homo sapiens (human)", remove it
  mutate(Organism = str_trim(str_remove(Organism, "\\s*\\(.*\\)$"))) %>%
  # Fix names in the non-GEO repositories that are not written as a species name
  mutate(Organism = case_when(
    Organism == "Sus scrofa domesticus" ~ "Sus scrofa",          # PRIDE
    Organism == "Parturient sow" ~ "Sus scrofa",                 # MetaboLights
    Organism == "9823" ~ "Sus scrofa",                           # MassIVE (NCBI taxid for pig)
    Organism == "dairy cow" ~ "Bos taurus",                      # MetaboLights
    str_detect(Organism, "^Oryctolagus cuniculus") ~ "Oryctolagus cuniculus",  # PRIDE subspecies
    TRUE ~ Organism))

# ==============================================================================
#  2) Use taxize to standardize organism names that are taxids
# ==============================================================================
# !!!!!!!!!!
# Can skip all of the steps in 2) and just read in data_organism.xlsx. 
# Once data_organism.xlsx is read in, you can skip to steps 3) and 4). 
data_organism_clean <- read_xlsx("code/files_used_in_code/data_organism.xlsx")

# Only follow the steps in 2) if you want to make the table from scratch.
# !!!!!!!!!!

# Keep only the taxid rows and get unique taxids
org_taxid <- data_organism %>%
  filter(str_detect(Organism, "^taxid:")) %>%
  mutate(taxid = str_remove(Organism, "^taxid:")) %>%
  # Only list unique taxids
  distinct(taxid)

# Query taxize on the unique taxids only
# Run time: ~ 15 seconds
tax_class <- classification(org_taxid$taxid, db = "ncbi")

# Turn the classification() results into a tidy lookup table
tax_lookup <- imap_dfr(tax_class, function(x, taxid) {
  if (is.null(x) || all(is.na(x))) {
    tibble(
      taxid = taxid,
      scientific_name = NA_character_)} else {
        species_name <- x$name[x$rank == "species"]
        species_name <- species_name[!is.na(species_name)]
        # Make table of taxid and scientific name
        tibble(taxid = taxid,
               scientific_name = if (length(species_name) == 0) NA_character_ else species_name[1])
      }
})

# Get common names from scientific names
## Run time: ~ 6 mins
common_raw <- sci2comm(unique(na.omit(tax_lookup$scientific_name)), db = "ncbi")

# Turn the common names list into a lookup table
common_lookup <- tibble(
  scientific_name = names(common_raw),
  common_name = map_chr(common_raw, function(x) {
    x <- x[!is.na(x) & nzchar(x)]
    if (length(x) == 0) NA_character_ else x[1]})) %>%
  # Manually fill in common names of species taxize did not recognize
  mutate(common_name = case_when(
    scientific_name == "Toxoplasma gondii" ~ "Parasitic alveolate",
    scientific_name == "Muntiacus vaginalis" ~ "Northern red muntjac",
    scientific_name == "Myotis myotis" ~ "Greater mouse-eared bat",
    scientific_name == "Addax nasomaculatus" ~ "Addax",
    scientific_name == "Equus quagga" ~ "Plains zebra",
    scientific_name == "Myotis thysanodes" ~ "Fringed myotis",
    scientific_name == "Myotis yumanensis" ~ "Yuma myotis",
    scientific_name == "Pteropus pumilus" ~ "Little golden-mantled flying fox",
    scientific_name == "Zapus princeps" ~ "Western jumping mouse",
    scientific_name == "Scapanus orarius" ~ "Coast mole",
    scientific_name == "Neurotrichus gibbsii" ~ "American shrew mole",
    scientific_name == "Tolypeutes matacus" ~ "Souther three-banded armadillo",
    scientific_name == "Microtus guentheri" ~ "Günther's vole",
    scientific_name == "Mirza zaza" ~ "Northern giant mouse lemur",
    scientific_name == "Alticola semicanus" ~ "Mongolian silver vole",
    TRUE ~ common_name)) %>% 
  # Remove any remaining NAs (these were not organisms -- Betacoronavirus pandemicum and synthetic construct)
  filter(!is.na(common_name)) %>% 
  mutate(common_name = str_to_title(common_name),
         display_name = case_when(is.na(common_name) ~ scientific_name,
                                  TRUE ~ paste0(common_name, " (", scientific_name, ")")))

# Join common names back to taxids (in order to join with big organisms list downstream)
tax_lookup <- tax_lookup %>%
  left_join(common_lookup, by = "scientific_name") %>%
  # There were two taxids not picked up before: for mouse and rat
  mutate(scientific_name = case_when(
    taxid == "10114" ~ "Rattus norvegicus",
    taxid == "10088" ~ "Mus musculus",
    TRUE ~ scientific_name),
    common_name = case_when(
      scientific_name == "Rattus norvegicus" ~ "Rat",
      scientific_name == "Mus musculus" ~ "Mouse",
      TRUE ~ common_name),
    display_name = case_when(
      common_name == "Rat" ~ "Rat (Rattus norvegicus)",
      common_name == "Mouse" ~ "Mouse (Mus musculus)",
      TRUE ~ display_name)) %>% 
  # Remove any remaining NAs (these were not organisms -- Betacoronavirus pandemicum and synthetic construct)
  filter(!is.na(common_name)) %>% 
  # Make taxid column have the taxid: prefix to join back to original organisms table
  mutate(taxid = paste0("taxid:", taxid))

# Merge back to organism table and format
data_organism <- data_organism %>% 
  left_join(tax_lookup, by = c("Organism" = "taxid")) %>% 
  # Fill in columns for organisms that already had names (mostly human, mouse, and rat)
  mutate(scientific_name = case_when(
    Organism == "Homo sapiens" ~ "Homo sapiens",
    Organism == "Mus musculus" ~ "Mus musculus",
    Organism == "Bos taurus" ~ "Bos taurus",
    Organism == "Rattus norvegicus" ~ "Rattus norvegicus",
    Organism == "Macaca nemestrina" ~ "Macaca nemestrina",
    Organism == "Sus scrofa" ~ "Sus scrofa",
    Organism == "Macaca mulatta" ~ "Macaca mulatta",
    Organism == "Notamacropus eugenii" ~ "Notamacropus eugenii",
    Organism == "Dasypus novemcinctus" ~ "Dasypus novemcinctus",
    Organism == "Oryctolagus cuniculus" ~ "Oryctolagus cuniculus",
    Organism == "Dasypus novemcinctus" ~ "Dasypus novemcinctus",
    Organism == "Mus musculus domesticus" ~ "Mus musculus",
    Organism == "Bos indicus" ~ "Bos indicus",
    Organism == "Pan troglodytes" ~ "Pan troglodytes",
    # Species that only come from the non-GEO repositories as names (not taxids)
    Organism == "Ovis aries" ~ "Ovis aries",
    Organism == "Equus caballus" ~ "Equus caballus",
    Organism == "Cavia porcellus" ~ "Cavia porcellus",
    Organism == "Papio anubis" ~ "Papio anubis",
    TRUE ~ scientific_name),
    common_name = case_when(
      scientific_name == "Homo sapiens" ~ "Human",
      scientific_name == "Mus musculus" ~ "Mouse",
      scientific_name == "Bos taurus" ~ "Cow",
      scientific_name == "Rattus norvegicus" ~ "Rat",
      scientific_name == "Macaca nemestrina" ~ "Southern pig-tailed macaque",
      scientific_name == "Sus scrofa" ~ "Pig",
      scientific_name == "Macaca mulatta" ~ "Rhesus macaque",
      scientific_name == "Notamacropus eugenii" ~ "Tammar wallaby",
      scientific_name == "Dasypus novemcinctus" ~ "Armadillo",
      scientific_name == "Oryctolagus cuniculus" ~ "Rabbit",
      scientific_name == "Dasypus novemcinctus" ~ "Nine-banded armadillo",
      scientific_name == "Bos indicus" ~ "Zebu",
      scientific_name == "Pan troglodytes" ~ "Chimpanzee",
      # Match the common names taxize gives these species so they join the same pie slice
      scientific_name == "Ovis aries" ~ "Sheep",
      scientific_name == "Equus caballus" ~ "Horse",
      scientific_name == "Cavia porcellus" ~ "Domestic Guinea Pig",
      scientific_name == "Papio anubis" ~ "Olive Baboon",
      TRUE ~ common_name),
    display_name = case_when(
      common_name == "Human" ~ "Human (Homo sapiens)",
      common_name == "Mouse" ~ "Mouse (Mus musculus)",
      common_name == "Cow" ~ "Cow (Bos taurus)",
      common_name == "Rat" ~ "Rat (Rattus norvegicus)",
      common_name == "Southern pig-tailed macaque" ~ "Southern pig-tailed macaque (Macaca nemestrina)",
      common_name == "Pig" ~ "Pig (Sus scrofa)",
      common_name == "Rhesus macaque" ~ "Rhesus macaque (Macaca mulatta)",
      common_name == "Tammar wallaby" ~ "Tammar wallaby (Notamacropus eugenii)",
      common_name == "Armadillo" ~ "Armadillo (Dasypus novemcinctus)",
      common_name == "Rabbit" ~ "Rabbit (Oryctolagus cuniculus)",
      common_name == "Nine-banded armadillo" ~ "Nine-banded armadillo (Dasypus novemcinctus)",
      common_name == "Zebu" ~ "Zebu (Bos indicus)",
      common_name == "Chimpanzee" ~ "Chimpanzee (Pan troglodytes)",
      common_name == "Sheep" ~ "Sheep (Ovis aries)",
      common_name == "Horse" ~ "Horse (Equus caballus)",
      common_name == "Domestic Guinea Pig" ~ "Domestic Guinea Pig (Cavia porcellus)",
      common_name == "Olive Baboon" ~ "Olive Baboon (Papio anubis)",
      TRUE ~ display_name)) %>%
  # Remove any remaining NAs (these were not organisms -- Betacoronavirus pandemicum and synthetic construct)
  filter(!is.na(scientific_name)) %>%
  # Count each organism only once per study (some entries list the same species twice,
  # e.g. two subspecies or a species name and its taxid)
  distinct(source_sheet, `GEO Series ID (GSE___)`, scientific_name, .keep_all = TRUE) %>%
  # Rename some columns
  rename(organism_old = Organism, organism = scientific_name)

# Before proceeding with figure making, check which organisms actually have placentas
unique(data_organism$organism) # Outputs list of all unique organisms
# I put this list into ChatGPT and asked it which one of the organisms DO NOT have a placenta (can think of a better way to look at this, but the unique list is still quite long)
## It said: Ornithorhynchus anatinus, Tachyglossus aculeatus, Xenopus tropicalis, Gallus gallus, Saccharomyces cerevisiae, Toxoplasma gondii

## Remove organisms that DO NOT have a placenta (according to ChatGPT)
data_organism_clean <- data_organism %>% 
  filter(organism != "Ornithorhynchus anatinus",
         organism != "Tachyglossus aculeatus",
         organism != "Xenopus tropicalis",
         organism != "Gallus gallus",
         organism != "Saccharomyces cerevisiae",
         organism != "Toxoplasma gondii")

# Save this table to save time making it in the future
write.xlsx(data_organism_clean, "code/files_used_in_code/data_organism.xlsx")

# ==============================================================================
# 3) Pie chart of organisms (plots all organisms with 2 or more counts)
# ==============================================================================
# Only keep studies submitted between 2002 and 2025
# (done here so it works whether data_organism.xlsx was read in or made from scratch;
# data_organism.xlsx itself keeps all years because the map script filters on its own)
data_organism_clean <- data_organism_clean %>%
  semi_join(studies_in_window, by = c("source_sheet", "GEO Series ID (GSE___)"))

# Count organisms
organism_counts <- data_organism_clean %>%
  count(display_name, sort = TRUE)

# Only keep slices for organisms with 2 or more studies
organism_pie <- organism_counts %>%
  mutate(display_name = if_else(
    n >= 2,
    display_name,
    "Other")) %>% 
  group_by(display_name) %>%
  summarise(n = sum(n), .groups = "drop") %>%
  arrange(desc(n)) %>%
  # Order slices from most to fewest studies, with "Other" always last
  # (ggplot uses factor levels for the slice order, not the row order)
  mutate(display_name = fct_relevel(fct_reorder(display_name, n, .desc = TRUE)))

# Save table of organisms in the pie chart
if (!file.exists("supplementary/placenta_organisms_2_or_more.xlsx")) {
  write.xlsx(organism_pie, "supplementary/placenta_organisms_2_or_more.xlsx")
}

  # Uncomment if you do NOT want the "Other" slice
##organism_pie <- organism_pie %>% 
##filter(display_name != "Other")

# Plot
organisms_pie <- ggplot(organism_pie, aes(x = "", y = n, fill = display_name)) +
  # reverse = TRUE starts the largest slice at 12 o'clock and goes clockwise
  geom_col(width = 0.2, color = NA, position = position_stack(reverse = TRUE)) +
  coord_polar(theta = "y") +
  theme_void() +
  scale_fill_manual(values = c(
    "Human (Homo sapiens)" = "#a1dab4",
    "Mouse (Mus musculus)" = "#fe9929",
    "Other" = "lightgray",
    "Rat (Rattus norvegicus)" = "#225ea8",
    
    "Cow (Bos taurus)" = "#f768a1",
    "Pig (Sus scrofa)" = "#9e9ac8",
    "Horse (Equus caballus)" = "#fec44f",
    "Sheep (Ovis aries)" = "#fd8d3c",
    
    "Rhesus macaque (Macaca mulatta)" = "#2ca25f",
    "Crab-Eating Macaque (Macaca fascicularis)" = "#41b6c4",
    "Brown Lemur (Eulemur fulvus)" = "#807dba",
    "Chimpanzee (Pan troglodytes)" = "#6a51a3",
    "Hamadryas Baboon (Papio hamadryas)" = "#88419d",
    "Southern pig-tailed macaque (Macaca nemestrina)" = "#bc80bd",
    "Western Gorilla (Gorilla gorilla)" = "#8c6bb1",
    "White-Tufted-Ear Marmoset (Callithrix jacchus)" = "#756bb1",
    
    "Domestic Guinea Pig (Cavia porcellus)" = "#3182bd",
    "Chinese Hamster (Cricetulus griseus)" = "#6baed6",
    "Shrew Mouse (Mus pahari)" = "#9ecae1",
    "Western Wild Mouse (Mus spretus)" = "#c6dbef",
    "Upper Galilee Mountains Blind Mole Rat (Nannospalax galili)" = "#2171b5",
    "Cuis (Galea musteloides)" = "#4292c6",
    
    "Gray Short-Tailed Opossum (Monodelphis domestica)" = "#dd1c77",
    
    "Rabbit (Oryctolagus cuniculus)" = "#74c476",
    "Wolf (Canis lupus)" = "#636363",
    "African Savanna Elephant (Loxodonta africana)" = "#bdb76b",
    "Armadillo (Dasypus novemcinctus)" = "#8c6d31",
    "Hector's Dolphin (Cephalorhynchus hectori)" = "#3690c0",
    "Tailess Tenrec (Tenrec ecaudatus)" = "#31a354"))+
  labs(fill = "Organism", title = "Organisms Used in at least 2 Placenta Research Studies")
organisms_pie

# Save
ggsave("figures/organisms_plot_raw.png", plot = organisms_pie, width = 12, height = 8, dpi = 300)
ggsave("figures/organisms_plot_raw.pdf", plot = organisms_pie, width = 12, height = 8)

# ==============================================================================
# 4) Make table listing "Other" species and counts
# ==============================================================================
other_counts <- organism_counts %>% 
  filter(n < 2) %>% 
  rename(Organism = display_name, Counts = n) %>% 
  # Label which organisms are marsupials and which are eutherian mammals
  mutate(placenta_type = case_when(
    # Marsupials
    Organism %in% c(
      "Gray Short-Tailed Opossum (Monodelphis domestica)",
      "North American Opossum (Didelphis virginiana)",
      "Southern Opossum (Didelphis marsupialis)",
      "Agile Wallaby (Notamacropus agilis)",
      "Tammar Wallaby (Notamacropus eugenii)",
      "Red-Necked Wallaby (Notamacropus rufogriseus)",
      "Eastern Gray Kangaroo (Macropus giganteus)",
      "Western Gray Kangaroo (Macropus fuliginosus)",
      "Common Wallaroo (Osphranter robustus)",
      "Red Kangaroo (Osphranter rufus)",
      "Koala (Phascolarctos cinereus)",
      "Common Wombat (Vombatus ursinus)",
      "Tasmanian Devil (Sarcophilus harrisii)",
      "Monito Del Monte (Dromiciops gliroides)",
      "Silky Shrew Opossum (Caenolestes fuliginosus)") ~ "Marsupial",
    TRUE ~ "Eutherian mammal"))

# Save
if (!file.exists("supplementary/placenta_organisms_other.xlsx")) {
  write.xlsx(other_counts, "supplementary/placenta_organisms_other.xlsx")
}

# Edit numbers onto pie chart in Illustrator.