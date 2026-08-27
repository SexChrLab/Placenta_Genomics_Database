# ------
# WHICH ORGANISMS ARE REPRESENTED IN PLACENTA RESEARCH?
# Goal
#   Plot the distribution of organisms used in placenta research (grouped by human, mouse, rat, and other). For the other category, also make a table of what organisms appear.
# Contents
#   1) Use taxize to standardize organism names that are taxids
#   2) Pie chart of organisms (plots all organisms with 2 or more counts)
#   3) Make table listing "Other" species and counts
# ------

# Data sheet last downloaded: June 23, 2026

# Install and load packages
library(readxl)
library(tidyverse)
#install.packages("taxize")
library(taxize)

# Set working directory
setwd("~/Desktop/placenta_db")

# Read in the data freeze file
data <- read_excel("geo_completed_sheet.xlsx")

# Format table for downstream analysis
data_organism <- data %>% 
  # Only keep relevant columns
  select(`GEO Series ID (GSE___)`, Organism) %>% 
  # Remove any NA rows
  filter(!is.na(Organism)) %>%
  # Break up any entries that are mixed-species (so Homo sapiens, Mus musculus becomes Homo sapiens and Mus musculus)
  separate_rows(Organism, sep = ",\\s*|\\s*\\|\\s*")

# === 1) Use taxize to standardize organism names that are taxids ===
# CAN SKIP ALL OF THE STEPS IN 1 AND JUST READ IN data_organism_clean BELOW. AND THEN SKIP TO 2 OR 3. FOLLOW THE 1) STEPS IF YOU WANT TO MAKE THE TABLE FROM SCRATCH.
data_organism_clean <- read_csv("supplementary/data_organism.csv")

# SKIP THESE STEPS IF YOU ALREADY READ IN THE data_organism_clean TABLE. CAN GO STRAIGHT TO STEP 2. ONLY DO THESE STEPS IF YOU WANT TO MAKE THE TABLE FROM SCRATCH.
## Keep only the taxid rows and get unique taxids
org_taxid <- data_organism %>%
  filter(str_detect(Organism, "^taxid:")) %>%
  mutate(taxid = str_remove(Organism, "^taxid:")) %>%
  # Only list unique taxids
  distinct(taxid)

## Query taxize on the unique taxids only
# Run time: ~ 15 seconds
tax_class <- classification(org_taxid$taxid, db = "ncbi")

## Turn the classification() results into a tidy lookup table
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

## Get common names from scientific names
# Run time: ~ 5 mins (Start 15:02:18, End 15:07:22)
common_raw <- sci2comm(unique(na.omit(tax_lookup$scientific_name)), db = "ncbi")

## Turn the common names list into a lookup table
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

## Join common names back to taxids (in order to join with big organisms list downstream)
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

## Merge back to organism table and format
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
    TRUE ~ scientific_name),
    common_name = case_when(
      scientific_name == "Homo sapiens" ~ "Human",
      scientific_name == "Mus musculus" ~ "Mouse",
      scientific_name == "Bos taurus" ~ "Cow",
      scientific_name == "Rattus norvegicus" ~ "Rat",
      scientific_name == "Macaca nemestrina" ~ "Southern pig-tailed macaque",
      scientific_name == "Sus scrofa" ~ "Wild boar",
      scientific_name == "Macaca mulatta" ~ "Rhesus macaque",
      scientific_name == "Notamacropus eugenii" ~ "Tammar wallaby",
      scientific_name == "Dasypus novemcinctus" ~ "Armadillo",
      scientific_name == "Oryctolagus cuniculus" ~ "Rabbit",
      scientific_name == "Dasypus novemcinctus" ~ "Nine-banded armadillo",
      scientific_name == "Bos indicus" ~ "Zebu",
      scientific_name == "Pan troglodytes" ~ "Chimpanzee",
      TRUE ~ common_name),
    display_name = case_when(
      common_name == "Human" ~ "Human (Homo sapiens)",
      common_name == "Mouse" ~ "Mouse (Mus musculus)",
      common_name == "Cow" ~ "Cow (Bos taurus)",
      common_name == "Rat" ~ "Rat (Rattus norvegicus)",
      common_name == "Southern pig-tailed macaque" ~ "Southern pig-tailed macaque (Macaca nemestrina)",
      common_name == "Wild boar" ~ "Wild boar (Sus scrofa)",
      common_name == "Rhesus macaque" ~ "Rhesus macaque (Macaca mulatta)",
      common_name == "Tammar wallaby" ~ "Tammar wallaby (Notamacropus eugenii)",
      common_name == "Armadillo" ~ "Armadillo (Dasypus novemcinctus)",
      common_name == "Rabbit" ~ "Rabbit (Oryctolagus cuniculus)",
      common_name == "Nine-banded armadillo" ~ "Nine-banded armadillo (Dasypus novemcinctus)",
      common_name == "Zebu" ~ "Zebu (Bos indicus)",
      common_name == "Chimpanzee" ~ "Chimpanzee (Pan troglodytes)",
      TRUE ~ display_name)) %>% 
  # Remove any remaining NAs (these were not organisms -- Betacoronavirus pandemicum and synthetic construct)
  filter(!is.na(scientific_name)) %>% 
  # Rename some columns
  rename(organism_old = Organism, organism = scientific_name)

# Before proceeding with figure making, check which organisms actually have placentas
unique(data_organism$organism) # Outputs list of all unique organisms
## I put this list into ChatGPT and asked it which one of the organisms DO NOT have a placenta (can think of a better way to look at this, but the unique list is still quite long)
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
write_csv(data_organism_clean, "supplementary/data_organism.csv")

# === 2) Pie chart of organisms (plots all organisms with 2 or more counts) ===
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
  arrange(desc(n))

# Uncomment if you do NOT want the "Other" slice
#organism_pie <- organism_pie %>% 
#filter(display_name != "Other")

organism_pie <- organism_pie %>%
  arrange(desc(n)) %>%
  mutate(Organism = factor(display_name, levels = display_name))

# Plot
organisms_pie <- ggplot(organism_pie, aes(x = "", y = n, fill = Organism)) +
  geom_col(width = 0.2, color = NA) +
  coord_polar(theta = "y") +
  #geom_text(aes(label = n), position = position_stack(vjust = 0.5), color = "white", size = 5) +
  theme_void() +
  scale_fill_manual(values = c(
    "Human (Homo sapiens)" = "#a1dab4",
    "Mouse (Mus musculus)" = "#fe9929",
    "Other" = "lightgray",
    "Rat (Rattus norvegicus)" = "#225ea8",
    
    "Cow (Bos taurus)" = "#f768a1",
    "Wild boar (Sus scrofa)" = "#9e9ac8",
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
  labs(fill = "Organism", title = "Distribution of Organisms Used in at least 2 Placenta Research Studies")
organisms_pie

# Save
ggsave("figures/organisms_plot_raw.pdf", plot = organisms_pie, width = 12, height = 8, dpi = 300)

# == 3) Make table listing "Other" species and counts ==
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
write_csv(other_counts, "supplementary/organisms_other_table.csv")

# Edit numbers onto pie chart in Illustrator.