# ------
# WHERE ARE PLACENTA SAMPLES COLLECTED GLOBALLY? 
# Goal
#   Plot the global distribution of placenta sample collection.
# Contents
#   1) Prep data
#   2) World map of organizations where placenta studies are conducted
# ------

# Data sheet last downloaded: June 23, 2026

# Install and load packages
library(readxl)
library(tidyverse)
library(maps)
#install.packages("tidygeocoder")
library(tidygeocoder)
#install.packages("countrycode")
library(countrycode)
#install.packages("patchwork")
library(patchwork)

# Set working directory
setwd("~/Desktop/placenta_db")

# Read in the data freeze file
data <- read_excel("geo_completed_sheet.xlsx")

# === 1) Prep data ===
data_map <- data %>% 
  #select columns that are relevant
  select("Organization name", "Country", "Organism", "Sample size (placenta)") %>% 
  # Remove any rows with NA entries for Organization name
  filter(!is.na(`Organization name`))

# First, I want to group together studies from the same organizations and get their coordinates so I can plot them properly on the map
unique(data_map$`Organization name`) 

# Using the unique data list, I used ChatGPT to help me group together repeat names
# Normalize first, then recode with this dictionary
normalize_org <- function(x) {
  x <- tolower(x)
  x <- stringi::stri_trans_general(x, "Latin-ASCII")
  x <- gsub("[^a-z0-9]+", " ", x)
  x <- gsub("\\s+", " ", x)
  trimws(x)
}

dict <- c(
  # --- University of California system ---
  "ucla" = "University of California Los Angeles",
  "university of california los angeles" = "University of California Los Angeles",
  "university of california, los angeles" = "University of California Los Angeles",
  "university of california san diego" = "University of California San Diego",
  "university of california, san diego" = "University of California San Diego",
  "ucsd" = "University of California San Diego",
  "university of california san francisco" = "University of California San Francisco",
  "university of california, san francisco" = "University of California San Francisco",
  "ucsf" = "University of California San Francisco",
  "uc san francisco" = "University of California San Francisco",
  "uc san diego" = "University of California San Diego",
  "university of california davis" = "University of California Davis",
  "university of california, davis" = "University of California Davis",
  "uc davis" = "University of California Davis",
  "university of california riverside" = "University of California Riverside",
  "university of california, riverside" = "University of California Riverside",
  
  # --- Stanford / MIT / Harvard ---
  "stanford" = "Stanford University",
  "stanford university" = "Stanford University",
  "stanford univeristy" = "Stanford University",
  "mit" = "Massachusetts Institute of Technology",
  "whitehead institute mit" = "Massachusetts Institute of Technology",
  "whitehead institute" = "Massachusetts Institute of Technology",
  "harvard university" = "Harvard University",
  "harvard medical school" = "Harvard University",
  "broad institute harvard university" = "Harvard University",
  "broad institute" = "Harvard University",
  
  # --- Yale / Columbia / Penn ---
  "yale" = "Yale University",
  "yale university" = "Yale University",
  "yale school of medicine" = "Yale University",
  "yale university school of medicine" = "Yale University",
  "columbia university" = "Columbia University",
  "university of pennsylvania" = "University of Pennsylvania",
  "upenn" = "University of Pennsylvania",
  
  # --- Johns Hopkins ---
  "johns hopkins university" = "Johns Hopkins University",
  "johns hopkins university school of medicine" = "Johns Hopkins University",
  "johns hopkins bloomberg school of public health" = "Johns Hopkins University",
  
  # --- Boston / MGH / Mount Sinai / Cedars ---
  "boston childrens hospital" = "Boston Children's Hospital",
  "boston children's hospital" = "Boston Children's Hospital",
  "boston childrens hospital" = "Boston Children's Hospital",
  "massachusetts general hospital" = "Massachusetts General Hospital",
  "mgh" = "Massachusetts General Hospital",
  "mass general brigham" = "Massachusetts General Hospital",
  "mount sinai hospital" = "Mount Sinai Hospital",
  "mount sinai school of medicine" = "Mount Sinai Hospital",
  "cedars sinai medical center" = "Cedars-Sinai Medical Center",
  "cedars sinai medical center" = "Cedars-Sinai Medical Center",
  "cedars sinai medical center" = "Cedars-Sinai Medical Center",
  "cedars-sinai medical center" = "Cedars-Sinai Medical Center",
  
  # --- California / Washington / Midwest ---
  "university of washington" = "University of Washington",
  "university of michigan" = "University of Michigan",
  "university of wisconsin" = "University of Wisconsin",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin - madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of minnesota" = "University of Minnesota",
  "university of iowa" = "University of Iowa",
  "university of missouri" = "University of Missouri-Columbia",
  "university of missouri columbia" = "University of Missouri-Columbia",
  "university of missouri columbia" = "University of Missouri-Columbia",
  "university of missouri edu" = "University of Missouri-Columbia",
  "univeristy of missouri" = "University of Missouri-Columbia",
  "university of pittsburgh" = "University of Pittsburgh",
  "university of pittburgh" = "University of Pittsburgh",
  "university of pittsburgh magee womens research institute" = "University of Pittsburgh",
  "university of texas at austin" = "University of Texas at Austin",
  "the university of texas at austin" = "University of Texas at Austin",
  "ut southwestern" = "UT Southwestern Medical Center",
  "ut southwestern medical center" = "UT Southwestern Medical Center",
  "ut southwest medical center" = "UT Southwestern Medical Center",
  "utmb" = "University of Texas Medical Branch",
  "utmb ngs core" = "University of Texas Medical Branch",
  "unc chapel hill" = "University of North Carolina at Chapel Hill",
  "university of north carolina" = "University of North Carolina at Chapel Hill",
  "the university of north carolina at chapel hill" = "University of North Carolina at Chapel Hill",
  "unc" = "University of North Carolina at Chapel Hill",
  
  # --- Boston / New England / NY ---
  "tufts university" = "Tufts University",
  "tufts medical center" = "Tufts Medical Center",
  "beth israel deaconess medical center" = "Beth Israel Deaconess Medical Center",
  "brigham and womens hospital" = "Brigham and Women's Hospital",
  "brigham and women s hospital" = "Brigham and Women's Hospital",
  "childrens mercy" = "Children's Mercy Hospital",
  "childrens mercy hospital" = "Children's Mercy Hospital",
  "childrens national hospital" = "Children's National Hospital",
  "childrens hospital of philadelphia" = "Children's Hospital of Philadelphia",
  "yale school of medicine" = "Yale University",
  
  # --- University of California / medical schools with common variants ---
  "university of california san diego" = "University of California San Diego",
  "university of california, san diego" = "University of California San Diego",
  "uc san diego" = "University of California San Diego",
  "ucsd" = "University of California San Diego",
  "university of california san francisco" = "University of California San Francisco",
  "university of california, san francisco" = "University of California San Francisco",
  "ucsf" = "University of California San Francisco",
  "university of california los angeles" = "University of California Los Angeles",
  "university of california, los angeles" = "University of California Los Angeles",
  "ucla" = "University of California Los Angeles",
  "university of california riverside" = "University of California Riverside",
  
  # --- University of Texas / medical centers ---
  "university of texas health science center san antonio" = "University of Texas Health Science Center San Antonio",
  "u t southwestern medical center" = "UT Southwestern Medical Center",
  "u t southwestern medical center" = "UT Southwestern Medical Center",
  
  # --- University of British Columbia / Canada ---
  "university of british columbia" = "University of British Columbia",
  "the university of british columbia" = "University of British Columbia",
  "university of british columbia bc childrens hospital research institute" = "University of British Columbia",
  "mcgill university" = "McGill University",
  "mcgill university health centre" = "McGill University Health Centre",
  "ri muhc" = "McGill University Health Centre",
  "mount sinai hospital university of toronto" = "University of Toronto",
  "university of toronto" = "University of Toronto",
  "the hospital for sick children" = "The Hospital for Sick Children",
  "anatomical pathology" = "University of British Columbia",
  
  # --- UK / Europe ---
  "university of cambridge" = "University of Cambridge",
  "univeristy of cambridge" = "University of Cambridge",
  "cambridge university" = "University of Cambridge",
  "university of oxford" = "University of Oxford",
  "oxford university" = "University of Oxford",
  "university of manchester" = "University of Manchester",
  "university of leeds" = "University of Leeds",
  "university of edinburgh" = "University of Edinburgh",
  "univeristy of edinburgh" = "University of Edinburgh",
  "university of sheffield" = "University of Sheffield",
  "cardiff university" = "Cardiff University",
  "newcastle university" = "Newcastle University",
  "king s college london" = "King's College London",
  "university of warwick" = "University of Warwick",
  "university of birmingham" = "University of Birmingham",
  "imperial college london" = "Imperial College London",
  "university of copenhagen" = "University of Copenhagen",
  "university of helsinki" = "University of Helsinki",
  "universite de montréal" = "Université de Montréal",
  "chu ste justine research center universite de montreal" = "Université de Montréal",
  "universite catholique de louvain" = "Université catholique de Louvain",
  "utrecht university" = "Utrecht University",
  "erasmus medical center" = "Erasmus Medical Center",
  "erasmus mc" = "Erasmus Medical Center",
  "technical university munich" = "Technical University of Munich",
  "technische universitat munchen" = "Technical University of Munich",
  "medical university of graz" = "Medical University of Graz",
  "wuerzburg university" = "University of Wuerzburg",
  "freiburg uniklinik" = "University of Freiburg Medical Center",
  
  # --- China: Shanghai / Beijing / Zhejiang / Nanjing / Wuhan / others ---
  "shanghai jiao tong university" = "Shanghai Jiao Tong University",
  "shanghai jiaotong university" = "Shanghai Jiao Tong University",
  "shanghai jiaotong university" = "Shanghai Jiao Tong University",
  "school of medicine shanghai jiaotong university" = "Shanghai Jiao Tong University",
  "tongji university" = "Tongji University",
  "tongji unversity" = "Tongji University",
  "tongji medical college" = "Tongji University",
  "厦门大学" = "Xiamen University",
  "厦门大学" = "Xiamen University", 
  "xiamen university" = "Xiamen University",
  "zhengzhou university" = "Zhengzhou University",
  "the first affiliated hospital of zhengzhou university" = "Zhengzhou University",
  "zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women's hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "southern medical university" = "Southern Medical University",
  "southern medical univercity" = "Southern Medical University",
  "southern medical university nanfang hospital" = "Southern Medical University",
  "nanfang hospital southern medical university" = "Southern Medical University",
  "fujian medical university" = "Fujian Medical University",
  "fujian maternity and child health hospital" = "Fujian Maternity and Child Health Hospital",
  "fujian provincial maternity and childrens hospital" = "Fujian Maternity and Child Health Hospital",
  "nanjing university" = "Nanjing University",
  "nanjing university medical school" = "Nanjing University",
  "nanjing university of chinese medicine" = "Nanjing University of Chinese Medicine",
  "nanjing agricultural university" = "Nanjing Agricultural University",
  "nanjing agricuture university" = "Nanjing Agricultural University",
  "peking university" = "Peking University",
  "peking university third hospital" = "Peking University",
  "tsinghua university" = "Tsinghua University",
  "fudan university" = "Fudan University",
  "fudan university" = "Fudan University",
  "sun yat sen university" = "Sun Yat-sen University",
  "sun yat sen memorial hospital of the sun yat sen university" = "Sun Yat-sen University",
  "huazhong university of science and technology" = "Huazhong University of Science and Technology",
  "huahzong university of science and technology" = "Huazhong University of Science and Technology",
  "huazhong agricultural university" = "Huazhong Agricultural University",
  "wuhan university" = "Wuhan University",
  "ren ji hospital school of medicine shanghai jiao tong university" = "Shanghai Jiao Tong University",
  "the international peace maternity and child health hospital" = "International Peace Maternity and Child Health Hospital",
  "international peace maternity and child health hospital shanghai jiao tong university" = "International Peace Maternity and Child Health Hospital",
  "international peace maternity and child health hospital school of medicine" = "International Peace Maternity and Child Health Hospital",
  "the international peace maternity and child health hospital school of medicine" = "International Peace Maternity and Child Health Hospital",
  "shanghai first maternity and infant hospital tongji university school of medicine" = "Tongji University",
  "ren ji hospital school of medicine shanghai jiao tong university" = "Shanghai Jiao Tong University",
  "wenzhou medical university" = "Wenzhou Medical University",
  "wenzhou medical university" = "Wenzhou Medical University",
  "jilin university" = "Jilin University",
  "chongqing medical university" = "Chongqing Medical University",
  "guangxi medical university" = "Guangxi Medical University",
  "guangxi academy of medical sciences" = "Guangxi Academy of Medical Sciences",
  "shandong provincial hospital affiliated to shandong university" = "Shandong University",
  "shenzhen institutes of advanced technology chinese academy of sciences" = "Shenzhen Institutes of Advanced Technology, Chinese Academy of Sciences",
  "shenzhen maternity and child healthcare hospital southern medical university" = "Southern Medical University",
  "shenzhen second peoples hospital" = "Shenzhen Second People's Hospital",
  "xiangya hospital central south university" = "Central South University",
  "yichang central peoples hospital" = "Yichang Central People's Hospital",
  "jining medical university" = "Jining Medical University",
  "xiangyang central hospital" = "Xiangyang Central Hospital",
  "linyi peoples hospital" = "Linyi People's Hospital",
  "ningbo first hospital" = "Ningbo First Hospital",
  "wuxi maternity and child health care hospital" = "Wuxi Maternity and Child Health Care Hospital",
  "jinan maternal and child health care hospital" = "Jinan Maternal and Child Health Care Hospital",
  "beijing institute of genomics" = "Beijing Institute of Genomics",
  "beijing chao yang hospital capital medical university" = "Capital Medical University",
  "beijing jishuitan hospital" = "Beijing Jishuitan Hospital",
  "capital institute of pediatrics" = "Capital Institute of Pediatrics",
  "capital institue of pediatrics" = "Capital Institute of Pediatrics",
  
  # --- Chinese Academy of Sciences / institutes ---
  "chinese academy of sciences" = "Chinese Academy of Sciences",
  "chinese academy of science" = "Chinese Academy of Sciences",
  "institute of zoology chinese academy of sciences" = "Chinese Academy of Sciences",
  "institute of zoology" = "Chinese Academy of Sciences",
  "center for excellence in molecular cell science chinese academy of sciences" = "Chinese Academy of Sciences",
  "guangzhou institutes of biomedicine and health chinese academy of sciences" = "Chinese Academy of Sciences",
  "gibh" = "Chinese Academy of Sciences",
  "shanghai institute of biochemistry and cell biology" = "Chinese Academy of Sciences",
  "institute of systems medicine chinese academy of systems medicine" = "Chinese Academy of Sciences",
  
  # --- Japan / Korea / Taiwan ---
  "university of tokyo" = "The University of Tokyo",
  "the university of tokyo" = "The University of Tokyo",
  "the university of tokyo" = "The University of Tokyo",
  "tohoku university" = "Tohoku University",
  "tohoku university graduate school of medicine" = "Tohoku University",
  "tohoku university school of medicine" = "Tohoku University",
  "kyoto university" = "Kyoto University",
  "osaka university" = "Osaka University",
  "kumamoto university" = "Kumamoto University",
  "nagoya university" = "Nagoya University",
  "keio university" = "Keio University",
  "hokkaido university" = "Hokkaido University",
  "chiba university" = "Chiba University",
  "chiba cancer center" = "Chiba Cancer Center",
  "saga university" = "Saga University",
  "shizuoka university" = "Shizuoka University",
  "okayama university of science" = "Okayama University of Science",
  "dokkyo medical university" = "Dokkyo Medical University",
  "nippon medical school" = "Nippon Medical School",
  "tokyo medical university" = "Tokyo Medical University",
  "tokyo medical and dental university" = "Tokyo Medical and Dental University",
  "tokyo university of science" = "Tokyo University of Science",
  "university of tsukuba" = "University of Tsukuba",
  "university of tsukuba graduate school of medicine" = "University of Tsukuba",
  "universi ty of tsukuba" = "University of Tsukuba",
  "university of tsukuba" = "University of Tsukuba",
  "university of tsukuba" = "University of Tsukuba",
  "kaist" = "KAIST",
  "korea institute of science and technology information" = "Korea Institute of Science and Technology Information",
  "korea university" = "Korea University",
  "yonsei university" = "Yonsei University",
  "eulji university" = "Eulji University",
  "national chung cheng university" = "National Chung Cheng University",
  "ming chuan univ" = "Ming Chuan University",
  "nthu" = "National Tsing Hua University",
  
  # --- North Carolina / other common US institutions ---
  "duke university" = "Duke University",
  "emory university" = "Emory University",
  "wake forest school of medicine" = "Wake Forest School of Medicine",
  "ohio state university" = "The Ohio State University",
  "the ohio state university" = "The Ohio State University",
  "north carolina state university" = "North Carolina State University",
  "ncsu" = "North Carolina State University",
  "michigan state university" = "Michigan State University",
  "penn state university" = "Pennsylvania State University",
  
  # --- NIH / US government / public research ---
  "nih" = "National Institutes of Health",
  "national institutes of health" = "National Institutes of Health",
  "national institute of health" = "National Institutes of Health",
  "nih nci" = "National Cancer Institute",
  "nci nih" = "National Cancer Institute",
  "national cancer institute" = "National Cancer Institute",
  "niehs" = "National Institute of Environmental Health Sciences",
  "nichd nih" = "National Institute of Child Health and Human Development",
  "ninds nih" = "National Institute of Neurological Disorders and Stroke",
  "usda ars" = "USDA-ARS",
  "usda ars usmarc" = "USDA-ARS",
  "usda ars arkansas childrens hospital" = "USDA-ARS",
  "usda-ars" = "USDA-ARS",
  
  # --- Canada / Australia / NZ ---
  "university of alberta" = "University of Alberta",
  "university of calgary" = "University of Calgary",
  "mcgill university" = "McGill University",
  "western university" = "Western University",
  "university of toronto" = "University of Toronto",
  "university of technology sydney" = "University of Technology Sydney",
  "university of melbourne" = "University of Melbourne",
  "the university of melbourne" = "University of Melbourne",
  "monash university" = "Monash University",
  "the university of queensland" = "University of Queensland",
  "university of queensland" = "University of Queensland",
  "the university of adelaide" = "University of Adelaide",
  "university of adelaide" = "University of Adelaide",
  "the university of western australia" = "University of Western Australia",
  "university of western australia" = "University of Western Australia",
  "university of otago" = "University of Otago",
  "university of auckland" = "The University of Auckland",
  "the university of auckland" = "The University of Auckland",
  
  # --- Name typos / local duplicates from your list ---
  "university of pittsburgh" = "University of Pittsburgh",
  "university of pittburgh" = "University of Pittsburgh",
  "university of missouri columbia" = "University of Missouri-Columbia",
  "univeristy of missouri" = "University of Missouri-Columbia",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  
  # --- Distinct biomedical institutes / hospitals ---
  "mayo clinic" = "Mayo Clinic",
  "childrens mercy" = "Children's Mercy Hospital",
  "childrens mercy hospital" = "Children's Mercy Hospital",
  "seattle childrens research institute" = "Seattle Children's Research Institute",
  "seattle childrens" = "Seattle Children's Research Institute",
  "cchmc" = "Cincinnati Children's Hospital Medical Center",
  "cincinnati childrens hospital medical center" = "Cincinnati Children's Hospital Medical Center",
  "cincinnati children s hospital medical center" = "Cincinnati Children's Hospital Medical Center",
  "washington university in st louis" = "Washington University in St. Louis",
  "washington university school of medicine" = "Washington University in St. Louis",
  "washington university in st louis" = "Washington University in St. Louis",
  
  # --- Proper names that appear in multiple formats ---
  "weill cornell medicine" = "Weill Cornell Medicine",
  "weill cornell medical college" = "Weill Cornell Medicine",
  "weill cornell medicine" = "Weill Cornell Medicine",
  "weill cornell medical college" = "Weill Cornell Medicine",
  "cornell university" = "Cornell University",
  
  # --- Institutes / consortiums / companies ---
  "encode dcc" = "ENCODE DCC",
  "center for genomic regulation" = "Centre for Genomic Regulation",
  "centre for genomic regulation" = "Centre for Genomic Regulation",
  "crg" = "Centre for Genomic Regulation",
  "universitat pompeu fabra centre for genomic regulation" = "Centre for Genomic Regulation",
  "max planck institute for molecular genetics" = "Max Planck Institute for Molecular Genetics",
  "max delbruck center for molecular medicine" = "Max Delbrück Center for Molecular Medicine",
  "max delbrueck center for molecular medicine" = "Max Delbrück Center for Molecular Medicine",
  "max planck institute of immunobiology and epigenetics" = "Max Planck Institute of Immunobiology and Epigenetics",
  "max planck institute of psychiatry" = "Max Planck Institute of Psychiatry",
  "francis crick institute" = "The Francis Crick Institute",
  "the francis crick institute" = "The Francis Crick Institute",
  "dkfz" = "German Cancer Research Center",
  "german cancer research center" = "German Cancer Research Center",
  "helmholtz center munich" = "Helmholtz Center Munich",
  "ce mm research center for molecular medicine of the austrian academy of sciences" = "CeMM Research Center for Molecular Medicine of the Austrian Academy of Sciences",
  "cemm research center for molecular medicine of the austrian academy of sciences" = "CeMM Research Center for Molecular Medicine of the Austrian Academy of Sciences",
  "imba" = "IMBA - Institute of Molecular Biotechnology",
  "imba institute of molecular biotechnology" = "IMBA - Institute of Molecular Biotechnology",
  "ce mm" = "CeMM Research Center for Molecular Medicine of the Austrian Academy of Sciences",
  "inserm" = "INSERM",
  "inrae" = "INRAE",
  "inrae university paris saclay" = "INRAE",
  "inra" = "INRA",
  "cnrs universite claude bernard lyon 1" = "CNRS",
  "institution pasteur" = "Institute Pasteur",
  "institute pasteur" = "Institute Pasteur",
  "institut pasteur de lille" = "Institut Pasteur de Lille",
  "i n s e r m umrs 1139" = "INSERM UMRS-1139",
  
  # --- Mixed / lab / misc spellings from the list ---
  "cedars sinai medical center" = "Cedars-Sinai Medical Center",
  "cedars-sinai medical center" = "Cedars-Sinai Medical Center",
  "mg h" = "Massachusetts General Hospital",
  "mgh" = "Massachusetts General Hospital",
  "university of california, san francisco" = "University of California San Francisco",
  "university of southern california" = "University of Southern California",
  "university of southern california" = "University of Southern California",
  "university of north carolin" = "University of North Carolina at Chapel Hill",
  "university of pittburgh" = "University of Pittsburgh",
  "stanford univeristy" = "Stanford University",
  "univerisity of cambridge" = "University of Cambridge",
  "university of kalgary" = "University of Calgary"
)

# Replace original names with the new normalized names
# First, normalize original Organization names
data_map$Org_norm <- normalize_org(data_map$`Organization name`) 
# Replace values using dictionary
data_map$Org_clean <- dict[data_map$Org_norm]
# If a value is not in the dictionary, keep the normalized version and capitalize it properly
data_map$Org_clean <- ifelse(data_map$Org_norm %in% names(dict), 
                             dict[data_map$Org_norm], 
                             tools::toTitleCase(data_map$Org_norm))
# There is only one case of a blank in Org_clean: 厦门大学 (which is Xiamen University). I want to manually fill in that one value.
data_map <- data_map %>% 
  mutate(Org_clean = if_else(Org_clean == "", "Xiamen University", Org_clean))

# Now I want to turn the names of the organizations into coordinates
unique_orgs <- data_map %>% distinct(Org_clean)

# I wanted to check if there were still duplicates in unique_orgs. I put the list into ChatGPT again and it found more duplicates. 
# I asked it to help me merge any duplicates:
dict_extra <- c(
  
  # --- Illinois ---
  "university of illinois at urbana champaign" =
    "University of Illinois Urbana-Champaign",
  "university of illinois urbana champaign" =
    "University of Illinois Urbana-Champaign",
  
  # --- McMaster ---
  "mcmaster universtiy" =
    "McMaster University",
  
  # --- KU Leuven ---
  "k u leuven" =
    "KU Leuven",
  "katholieke universiteit leuven" =
    "KU Leuven",
  
  # --- Kansas Medical Center ---
  "kumc" =
    "University of Kansas Medical Center",
  "the university of kansas medical center" =
    "University of Kansas Medical Center",
  
  # --- Cold Spring Harbor ---
  "cold spring harbor labs" =
    "Cold Spring Harbor Laboratory",
  
  # --- Memorial Sloan Kettering ---
  "memorial sloan kettering" =
    "Memorial Sloan Kettering Cancer Center",
  
  # --- Weizmann ---
  "weizmann" =
    "Weizmann Institute of Science",
  
  # --- Children's hospitals ---
  "cincinnati children s" =
    "Cincinnati Children's Hospital Medical Center",
  "the research institute at nationwide children s hospital" =
    "Nationwide Children's Hospital",
  
  # --- LSU ---
  "lsuhsc no" =
    "LSU Health New Orleans",
  "lsuhsc shreveport" =
    "LSU Health Shreveport",
  
  # --- Bonn ---
  "university medical school bonn" =
    "University of Bonn",
  
  # --- IDIBELL ---
  "idibell" =
    "Institut d'Investigació Biomèdica de Bellvitge (IDIBELL)",
  
  # --- Huazhong ---
  "huazhong agriculture university" =
    "Huazhong Agricultural University",
  
  # --- Jena ---
  "universitatsklinikum jena" =
    "Universitätsklinikum Jena",
  
  # --- Pasteur ---
  "institute pasteur" =
    "Institut Pasteur",
  
  # --- Rosetta ---
  "rosetta inpharmatics merck" =
    "Rosetta Inpharmatics",
  "rosetta inpharmatics merck co" =
    "Rosetta Inpharmatics",
  
  # --- Public health institutes ---
  "natl inst public health environment" =
    "National Institute for Public Health and the Environment",
  
  # --- Paris ---
  "universite paris6" =
    "Sorbonne University"
)
# Merge old and new dictionary
dict_all <- c(dict, dict_extra)

# Keep last definition if a key appears twice
dict_all <- dict_all[!duplicated(names(dict_all), fromLast = TRUE)]

# Apply new dictionary to unique_orgs list
unique_orgs <- unique_orgs %>%
  mutate(
    Org_clean = normalize_org(`Org_clean`),
    Org_canonical = recode(Org_clean, !!!dict_all, .default = Org_clean))

# If a value is not in either dictionary, keep the normalized version and capitalize it properly
unique_orgs$Org_canonical <- ifelse(unique_orgs$Org_canonical %in% names(dict_all), 
                                    dict[unique_orgs$Org_canonical], 
                                    tools::toTitleCase(unique_orgs$Org_canonical))

# Geocode using tidygeocoder
### THIS TAKES ~10 MINS, SKIP THIS IF ORG_COORDS.CSV IS ALREADY DOWNLOADED
#org_coords <- unique_orgs %>% 
  #geocode(Org_canonical, method = "osm", lat = lat, long = long) %>% 
  #select(!Org_clean)

#Save output of org_coords into a csv so that we don't have to run it every time
#write.csv(org_coords, "in_paper/org_coords.csv", row.names = FALSE)

### IF ORG_COORDS.CSV IS ALREADY DOWNLOADED, JUST USE:
org_coords <- read.csv("supplementary/org_coords.csv")

# Check which rows have coordinates with NAs
count(org_coords %>% filter(is.na(lat)))
# 143 are NA, need to figure out how to solve this 

# Filter out NAs for now
org_coords <- org_coords %>% 
  filter(!is.na(lat))

# Rename Org_canonical to Org_clean
org_coords <- org_coords %>% 
  rename(Org_clean = Org_canonical)

# Merge coordinates back to study-level data
# Keep this as the unsplit, one-row-per-study table
studies_coords <- data_map %>%
  mutate(study_id = row_number()) %>%
  left_join(org_coords, by = "Org_clean") %>%
  filter(!is.na(lat), !is.na(long))

# Before plotting, I wanted to make sure that all the coordinates corresponded to the correct institutions.
# I put the studies_coords table into ChatGPT and it caught 9 instances of wrong country labeling. Here I am fixing this:
coord_fixes <- tribble(
  ~Org_clean, ~Country, ~lat_fix, ~long_fix,
  "University of Oxford", "United Kingdom", 51.7548, -1.2544,
  "Mayo Clinic", "USA", 44.0225, -92.4668,
  "Mount Sinai Hospital", "USA", 40.7898, -73.9533,
  "National Cancer Institute", "USA", 39.0000, -77.1040,
  "Children s Mercy", "USA", 39.0844, -94.5775,
  "The Hospital for Sick Children", "Canada", 43.6577, -79.3871,
  "Grafton", "New Zealand", -36.8614, 174.7690,
  "RIKEN", "Japan", 35.7800, 139.6100,
  "INRA", "France", 43.52723, 1.501060)

# Make a corrected study-level table
studies_coords_fixed <- studies_coords %>%
  left_join(coord_fixes, by = c("Org_clean", "Country")) %>%
  mutate(
    lat = coalesce(lat_fix, lat),
    long = coalesce(long_fix, long)) %>%
  select(-lat_fix, -long_fix)

# Group organisms
# Read in the table made in Placenta_organism_type.R that has all the organism groups already
data_organism <- read_csv("supplementary/data_organism.csv") %>% 
  # Rename organism_old to Organism to merge the two tables, rename organism to organism_new to avoid confusion
  rename(Organism = organism_old, organism_new = organism)

# Make sure there is only one row per organism
org_lookup <- data_organism %>%
  distinct(Organism, organism_new, common_name, display_name)

# Join organism table to studies_coords
studies_coords_fixed <- studies_coords_fixed %>%
  separate_rows(Organism, sep = ",\\s*") %>% 
  mutate(Organism = trimws(Organism)) %>% 
  left_join(org_lookup, by = "Organism") %>% 
  # Remove NAs because these organisms do not have placentas
  filter(!is.na(display_name))

# Reorder factor levels to have organisms in proper order for legend
# Make table counting number of studies per continent to label the map
# Label continent each study comes from
studies_coords_continent <- studies_coords_fixed %>%
  mutate(
    continent = countrycode(
      Country,
      origin = "country.name",
      destination = "continent",
      custom_match = c(
        "USA" = "North America",
        "United States" = "North America",
        "Canada" = "North America",
        "Mexico" = "North America",
        "Colombia" = "South America",
        "Brazil" = "South America",
        "Chile" = "South America",
        "UK" = "Europe")))

# Count studies per continent
continent_counts <- studies_coords_continent %>%
  # Make sure it counts once per study, even if the row was split up for multiple organisms in the study
  distinct(study_id, continent) %>%
  count(continent, name = "n") %>%
  # Add row so that African continent is labeled as 0
  add_row(continent = "Africa", n = 0)

# Add approximate positions for labels
continent_pos <- tibble(
  continent = c("North America", "South America", "Europe", "Africa", "Asia", "Oceania"),
  long = c(-100, -60, 15, 20, 95, 140),
  lat  = c(45, -15, 55, 5, 35, -25))
continent_labels <- continent_counts %>%
  left_join(continent_pos, by = "continent")

# Plot the map
world_map <- map_data("world")
placenta_map <- ggplot() +
  # Country polygons
  geom_polygon(data = world_map,
               aes(x=long, y = lat, group = group),
               fill = "grey90", color = "white") +
  # Study points
  geom_point(data = studies_coords_fixed,
             aes(x = long, y = lat,
                 size = `Sample size (placenta)`,
                 color = `display_name`), alpha = 0.7) +
  scale_size_continuous(range = c(2, 10),
                        # Manually set lowest Study Size number as 1, not 0
                        breaks = c(1, 200, 400, 600),
                        labels = c("1", "200", "400", "600")) +
  coord_fixed(1.3) +
  scale_color_manual(values = c(
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
  theme_classic() +
  theme(axis.text = element_blank(),
        axis.ticks = element_blank(),
        axis.title = element_blank(),
        axis.line = element_blank()) +
  labs(title = "Global Distribution of Where Placenta Studies are Conducted",
       size = "Study Size",
       color = "Organism Type") +
  geom_text(data = continent_labels, aes(x = long, y = lat, label = n), size = 5, fontface = "bold")
placenta_map
# Save plot
ggsave("figures/placenta_map.png", plot = placenta_map, width = 20, height = 6, dpi = 300)
ggsave("figures/placenta_map.pdf", plot = placenta_map, width = 20, height = 6, dpi = 300)











################################################################################
# PLACENTA MAP
# Goal
#   Plot the global distribution of placenta sample collection.
# Contents
#   1) World map of organizations where placenta studies are conducted
#   2) OLD
######

# Data sheet last downloaded: June 23, 2026

# Install and load packages
library(readxl)
library(dplyr)
library(maps)
#install.packages("tidygeocoder")
library(tidygeocoder)
library(tidyr)
library(viridis)
#install.packages("countrycode")
library(countrycode)
library(ggplot2)
#install.packages("patchwork")
library(patchwork)
library(readr)

# Set working directory
setwd("/data/Wilson_Lab/users/sheffermannm/placenta_database_trends/")

# Read in the data freeze file
data <- read_excel("geo_completed_sheet.xlsx")

# === 1) World map of organizations where placenta studies are conducted ===
data_map <- data %>% 
  #select columns that are relevant
  select("Organization name", "Country", "Organism", "Sample size (placenta)") %>% 
  # Remove any rows with NA entries for Organization name
  filter(!is.na(`Organization name`))

# First, I want to group together studies from the same organizations and get their coordinates so I can plot them properly on the map
unique(data_map$`Organization name`) 

# Using the unique data list, I used ChatGPT to help me group together repeat names
# Normalize first, then recode with this dictionary
normalize_org <- function(x) {
  x <- tolower(x)
  x <- stringi::stri_trans_general(x, "Latin-ASCII")
  x <- gsub("[^a-z0-9]+", " ", x)
  x <- gsub("\\s+", " ", x)
  trimws(x)
}

dict <- c(
  # --- University of California system ---
  "ucla" = "University of California Los Angeles",
  "university of california los angeles" = "University of California Los Angeles",
  "university of california, los angeles" = "University of California Los Angeles",
  "university of california san diego" = "University of California San Diego",
  "university of california, san diego" = "University of California San Diego",
  "ucsd" = "University of California San Diego",
  "university of california san francisco" = "University of California San Francisco",
  "university of california, san francisco" = "University of California San Francisco",
  "ucsf" = "University of California San Francisco",
  "uc san francisco" = "University of California San Francisco",
  "uc san diego" = "University of California San Diego",
  "university of california davis" = "University of California Davis",
  "university of california, davis" = "University of California Davis",
  "uc davis" = "University of California Davis",
  "university of california riverside" = "University of California Riverside",
  "university of california, riverside" = "University of California Riverside",
  
  # --- Stanford / MIT / Harvard ---
  "stanford" = "Stanford University",
  "stanford university" = "Stanford University",
  "stanford univeristy" = "Stanford University",
  "mit" = "Massachusetts Institute of Technology",
  "whitehead institute mit" = "Massachusetts Institute of Technology",
  "whitehead institute" = "Massachusetts Institute of Technology",
  "harvard university" = "Harvard University",
  "harvard medical school" = "Harvard University",
  "broad institute harvard university" = "Harvard University",
  "broad institute" = "Harvard University",
  
  # --- Yale / Columbia / Penn ---
  "yale" = "Yale University",
  "yale university" = "Yale University",
  "yale school of medicine" = "Yale University",
  "yale university school of medicine" = "Yale University",
  "columbia university" = "Columbia University",
  "university of pennsylvania" = "University of Pennsylvania",
  "upenn" = "University of Pennsylvania",
  
  # --- Johns Hopkins ---
  "johns hopkins university" = "Johns Hopkins University",
  "johns hopkins university school of medicine" = "Johns Hopkins University",
  "johns hopkins bloomberg school of public health" = "Johns Hopkins University",
  
  # --- Boston / MGH / Mount Sinai / Cedars ---
  "boston childrens hospital" = "Boston Children's Hospital",
  "boston children's hospital" = "Boston Children's Hospital",
  "boston childrens hospital" = "Boston Children's Hospital",
  "massachusetts general hospital" = "Massachusetts General Hospital",
  "mgh" = "Massachusetts General Hospital",
  "mass general brigham" = "Massachusetts General Hospital",
  "mount sinai hospital" = "Mount Sinai Hospital",
  "mount sinai school of medicine" = "Mount Sinai Hospital",
  "cedars sinai medical center" = "Cedars-Sinai Medical Center",
  "cedars sinai medical center" = "Cedars-Sinai Medical Center",
  "cedars sinai medical center" = "Cedars-Sinai Medical Center",
  "cedars-sinai medical center" = "Cedars-Sinai Medical Center",
  
  # --- California / Washington / Midwest ---
  "university of washington" = "University of Washington",
  "university of michigan" = "University of Michigan",
  "university of wisconsin" = "University of Wisconsin",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin - madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of wisconsin madison" = "University of Wisconsin-Madison",
  "university of minnesota" = "University of Minnesota",
  "university of iowa" = "University of Iowa",
  "university of missouri" = "University of Missouri-Columbia",
  "university of missouri columbia" = "University of Missouri-Columbia",
  "university of missouri columbia" = "University of Missouri-Columbia",
  "university of missouri edu" = "University of Missouri-Columbia",
  "univeristy of missouri" = "University of Missouri-Columbia",
  "university of pittsburgh" = "University of Pittsburgh",
  "university of pittburgh" = "University of Pittsburgh",
  "university of pittsburgh magee womens research institute" = "University of Pittsburgh",
  "university of texas at austin" = "University of Texas at Austin",
  "the university of texas at austin" = "University of Texas at Austin",
  "ut southwestern" = "UT Southwestern Medical Center",
  "ut southwestern medical center" = "UT Southwestern Medical Center",
  "ut southwest medical center" = "UT Southwestern Medical Center",
  "utmb" = "University of Texas Medical Branch",
  "utmb ngs core" = "University of Texas Medical Branch",
  "unc chapel hill" = "University of North Carolina at Chapel Hill",
  "university of north carolina" = "University of North Carolina at Chapel Hill",
  "the university of north carolina at chapel hill" = "University of North Carolina at Chapel Hill",
  "unc" = "University of North Carolina at Chapel Hill",
  
  # --- Boston / New England / NY ---
  "tufts university" = "Tufts University",
  "tufts medical center" = "Tufts Medical Center",
  "beth israel deaconess medical center" = "Beth Israel Deaconess Medical Center",
  "brigham and womens hospital" = "Brigham and Women's Hospital",
  "brigham and women s hospital" = "Brigham and Women's Hospital",
  "childrens mercy" = "Children's Mercy Hospital",
  "childrens mercy hospital" = "Children's Mercy Hospital",
  "childrens national hospital" = "Children's National Hospital",
  "childrens hospital of philadelphia" = "Children's Hospital of Philadelphia",
  "yale school of medicine" = "Yale University",
  
  # --- University of California / medical schools with common variants ---
  "university of california san diego" = "University of California San Diego",
  "university of california, san diego" = "University of California San Diego",
  "uc san diego" = "University of California San Diego",
  "ucsd" = "University of California San Diego",
  "university of california san francisco" = "University of California San Francisco",
  "university of california, san francisco" = "University of California San Francisco",
  "ucsf" = "University of California San Francisco",
  "university of california los angeles" = "University of California Los Angeles",
  "university of california, los angeles" = "University of California Los Angeles",
  "ucla" = "University of California Los Angeles",
  "university of california riverside" = "University of California Riverside",
  
  # --- University of Texas / medical centers ---
  "university of texas health science center san antonio" = "University of Texas Health Science Center San Antonio",
  "u t southwestern medical center" = "UT Southwestern Medical Center",
  "u t southwestern medical center" = "UT Southwestern Medical Center",
  
  # --- University of British Columbia / Canada ---
  "university of british columbia" = "University of British Columbia",
  "the university of british columbia" = "University of British Columbia",
  "university of british columbia bc childrens hospital research institute" = "University of British Columbia",
  "mcgill university" = "McGill University",
  "mcgill university health centre" = "McGill University Health Centre",
  "ri muhc" = "McGill University Health Centre",
  "mount sinai hospital university of toronto" = "University of Toronto",
  "university of toronto" = "University of Toronto",
  "the hospital for sick children" = "The Hospital for Sick Children",
  "anatomical pathology" = "University of British Columbia",
  
  # --- UK / Europe ---
  "university of cambridge" = "University of Cambridge",
  "univeristy of cambridge" = "University of Cambridge",
  "cambridge university" = "University of Cambridge",
  "university of oxford" = "University of Oxford",
  "oxford university" = "University of Oxford",
  "university of manchester" = "University of Manchester",
  "university of leeds" = "University of Leeds",
  "university of edinburgh" = "University of Edinburgh",
  "univeristy of edinburgh" = "University of Edinburgh",
  "university of sheffield" = "University of Sheffield",
  "cardiff university" = "Cardiff University",
  "newcastle university" = "Newcastle University",
  "king s college london" = "King's College London",
  "university of warwick" = "University of Warwick",
  "university of birmingham" = "University of Birmingham",
  "imperial college london" = "Imperial College London",
  "university of copenhagen" = "University of Copenhagen",
  "university of helsinki" = "University of Helsinki",
  "universite de montréal" = "Université de Montréal",
  "chu ste justine research center universite de montreal" = "Université de Montréal",
  "universite catholique de louvain" = "Université catholique de Louvain",
  "utrecht university" = "Utrecht University",
  "erasmus medical center" = "Erasmus Medical Center",
  "erasmus mc" = "Erasmus Medical Center",
  "technical university munich" = "Technical University of Munich",
  "technische universitat munchen" = "Technical University of Munich",
  "medical university of graz" = "Medical University of Graz",
  "wuerzburg university" = "University of Wuerzburg",
  "freiburg uniklinik" = "University of Freiburg Medical Center",
  
  # --- China: Shanghai / Beijing / Zhejiang / Nanjing / Wuhan / others ---
  "shanghai jiao tong university" = "Shanghai Jiao Tong University",
  "shanghai jiaotong university" = "Shanghai Jiao Tong University",
  "shanghai jiaotong university" = "Shanghai Jiao Tong University",
  "school of medicine shanghai jiaotong university" = "Shanghai Jiao Tong University",
  "tongji university" = "Tongji University",
  "tongji unversity" = "Tongji University",
  "tongji medical college" = "Tongji University",
  "厦门大学" = "Xiamen University",
  "厦门大学" = "Xiamen University", 
  "xiamen university" = "Xiamen University",
  "zhengzhou university" = "Zhengzhou University",
  "the first affiliated hospital of zhengzhou university" = "Zhengzhou University",
  "zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "women's hospital school of medicine zhejiang university" = "Zhejiang University",
  "women s hospital school of medicine zhejiang university" = "Zhejiang University",
  "southern medical university" = "Southern Medical University",
  "southern medical univercity" = "Southern Medical University",
  "southern medical university nanfang hospital" = "Southern Medical University",
  "nanfang hospital southern medical university" = "Southern Medical University",
  "fujian medical university" = "Fujian Medical University",
  "fujian maternity and child health hospital" = "Fujian Maternity and Child Health Hospital",
  "fujian provincial maternity and childrens hospital" = "Fujian Maternity and Child Health Hospital",
  "nanjing university" = "Nanjing University",
  "nanjing university medical school" = "Nanjing University",
  "nanjing university of chinese medicine" = "Nanjing University of Chinese Medicine",
  "nanjing agricultural university" = "Nanjing Agricultural University",
  "nanjing agricuture university" = "Nanjing Agricultural University",
  "peking university" = "Peking University",
  "peking university third hospital" = "Peking University",
  "tsinghua university" = "Tsinghua University",
  "fudan university" = "Fudan University",
  "fudan university" = "Fudan University",
  "sun yat sen university" = "Sun Yat-sen University",
  "sun yat sen memorial hospital of the sun yat sen university" = "Sun Yat-sen University",
  "huazhong university of science and technology" = "Huazhong University of Science and Technology",
  "huahzong university of science and technology" = "Huazhong University of Science and Technology",
  "huazhong agricultural university" = "Huazhong Agricultural University",
  "wuhan university" = "Wuhan University",
  "ren ji hospital school of medicine shanghai jiao tong university" = "Shanghai Jiao Tong University",
  "the international peace maternity and child health hospital" = "International Peace Maternity and Child Health Hospital",
  "international peace maternity and child health hospital shanghai jiao tong university" = "International Peace Maternity and Child Health Hospital",
  "international peace maternity and child health hospital school of medicine" = "International Peace Maternity and Child Health Hospital",
  "the international peace maternity and child health hospital school of medicine" = "International Peace Maternity and Child Health Hospital",
  "shanghai first maternity and infant hospital tongji university school of medicine" = "Tongji University",
  "ren ji hospital school of medicine shanghai jiao tong university" = "Shanghai Jiao Tong University",
  "wenzhou medical university" = "Wenzhou Medical University",
  "wenzhou medical university" = "Wenzhou Medical University",
  "jilin university" = "Jilin University",
  "chongqing medical university" = "Chongqing Medical University",
  "guangxi medical university" = "Guangxi Medical University",
  "guangxi academy of medical sciences" = "Guangxi Academy of Medical Sciences",
  "shandong provincial hospital affiliated to shandong university" = "Shandong University",
  "shenzhen institutes of advanced technology chinese academy of sciences" = "Shenzhen Institutes of Advanced Technology, Chinese Academy of Sciences",
  "shenzhen maternity and child healthcare hospital southern medical university" = "Southern Medical University",
  "shenzhen second peoples hospital" = "Shenzhen Second People's Hospital",
  "xiangya hospital central south university" = "Central South University",
  "yichang central peoples hospital" = "Yichang Central People's Hospital",
  "jining medical university" = "Jining Medical University",
  "xiangyang central hospital" = "Xiangyang Central Hospital",
  "linyi peoples hospital" = "Linyi People's Hospital",
  "ningbo first hospital" = "Ningbo First Hospital",
  "wuxi maternity and child health care hospital" = "Wuxi Maternity and Child Health Care Hospital",
  "jinan maternal and child health care hospital" = "Jinan Maternal and Child Health Care Hospital",
  "beijing institute of genomics" = "Beijing Institute of Genomics",
  "beijing chao yang hospital capital medical university" = "Capital Medical University",
  "beijing jishuitan hospital" = "Beijing Jishuitan Hospital",
  "capital institute of pediatrics" = "Capital Institute of Pediatrics",
  "capital institue of pediatrics" = "Capital Institute of Pediatrics",
  
  # --- Chinese Academy of Sciences / institutes ---
  "chinese academy of sciences" = "Chinese Academy of Sciences",
  "chinese academy of science" = "Chinese Academy of Sciences",
  "institute of zoology chinese academy of sciences" = "Chinese Academy of Sciences",
  "institute of zoology" = "Chinese Academy of Sciences",
  "center for excellence in molecular cell science chinese academy of sciences" = "Chinese Academy of Sciences",
  "guangzhou institutes of biomedicine and health chinese academy of sciences" = "Chinese Academy of Sciences",
  "gibh" = "Chinese Academy of Sciences",
  "shanghai institute of biochemistry and cell biology" = "Chinese Academy of Sciences",
  "institute of systems medicine chinese academy of systems medicine" = "Chinese Academy of Sciences",
  
  # --- Japan / Korea / Taiwan ---
  "university of tokyo" = "The University of Tokyo",
  "the university of tokyo" = "The University of Tokyo",
  "the university of tokyo" = "The University of Tokyo",
  "tohoku university" = "Tohoku University",
  "tohoku university graduate school of medicine" = "Tohoku University",
  "tohoku university school of medicine" = "Tohoku University",
  "kyoto university" = "Kyoto University",
  "osaka university" = "Osaka University",
  "kumamoto university" = "Kumamoto University",
  "nagoya university" = "Nagoya University",
  "keio university" = "Keio University",
  "hokkaido university" = "Hokkaido University",
  "chiba university" = "Chiba University",
  "chiba cancer center" = "Chiba Cancer Center",
  "saga university" = "Saga University",
  "shizuoka university" = "Shizuoka University",
  "okayama university of science" = "Okayama University of Science",
  "dokkyo medical university" = "Dokkyo Medical University",
  "nippon medical school" = "Nippon Medical School",
  "tokyo medical university" = "Tokyo Medical University",
  "tokyo medical and dental university" = "Tokyo Medical and Dental University",
  "tokyo university of science" = "Tokyo University of Science",
  "university of tsukuba" = "University of Tsukuba",
  "university of tsukuba graduate school of medicine" = "University of Tsukuba",
  "universi ty of tsukuba" = "University of Tsukuba",
  "university of tsukuba" = "University of Tsukuba",
  "university of tsukuba" = "University of Tsukuba",
  "kaist" = "KAIST",
  "korea institute of science and technology information" = "Korea Institute of Science and Technology Information",
  "korea university" = "Korea University",
  "yonsei university" = "Yonsei University",
  "eulji university" = "Eulji University",
  "national chung cheng university" = "National Chung Cheng University",
  "ming chuan univ" = "Ming Chuan University",
  "nthu" = "National Tsing Hua University",
  
  # --- North Carolina / other common US institutions ---
  "duke university" = "Duke University",
  "emory university" = "Emory University",
  "wake forest school of medicine" = "Wake Forest School of Medicine",
  "ohio state university" = "The Ohio State University",
  "the ohio state university" = "The Ohio State University",
  "north carolina state university" = "North Carolina State University",
  "ncsu" = "North Carolina State University",
  "michigan state university" = "Michigan State University",
  "penn state university" = "Pennsylvania State University",
  
  # --- NIH / US government / public research ---
  "nih" = "National Institutes of Health",
  "national institutes of health" = "National Institutes of Health",
  "national institute of health" = "National Institutes of Health",
  "nih nci" = "National Cancer Institute",
  "nci nih" = "National Cancer Institute",
  "national cancer institute" = "National Cancer Institute",
  "niehs" = "National Institute of Environmental Health Sciences",
  "nichd nih" = "National Institute of Child Health and Human Development",
  "ninds nih" = "National Institute of Neurological Disorders and Stroke",
  "usda ars" = "USDA-ARS",
  "usda ars usmarc" = "USDA-ARS",
  "usda ars arkansas childrens hospital" = "USDA-ARS",
  "usda-ars" = "USDA-ARS",
  
  # --- Canada / Australia / NZ ---
  "university of alberta" = "University of Alberta",
  "university of calgary" = "University of Calgary",
  "mcgill university" = "McGill University",
  "western university" = "Western University",
  "university of toronto" = "University of Toronto",
  "university of technology sydney" = "University of Technology Sydney",
  "university of melbourne" = "University of Melbourne",
  "the university of melbourne" = "University of Melbourne",
  "monash university" = "Monash University",
  "the university of queensland" = "University of Queensland",
  "university of queensland" = "University of Queensland",
  "the university of adelaide" = "University of Adelaide",
  "university of adelaide" = "University of Adelaide",
  "the university of western australia" = "University of Western Australia",
  "university of western australia" = "University of Western Australia",
  "university of otago" = "University of Otago",
  "university of auckland" = "The University of Auckland",
  "the university of auckland" = "The University of Auckland",
  
  # --- Name typos / local duplicates from your list ---
  "university of pittsburgh" = "University of Pittsburgh",
  "university of pittburgh" = "University of Pittsburgh",
  "university of missouri columbia" = "University of Missouri-Columbia",
  "univeristy of missouri" = "University of Missouri-Columbia",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  "university of kansas medical center" = "University of Kansas Medical Center",
  
  # --- Distinct biomedical institutes / hospitals ---
  "mayo clinic" = "Mayo Clinic",
  "childrens mercy" = "Children's Mercy Hospital",
  "childrens mercy hospital" = "Children's Mercy Hospital",
  "seattle childrens research institute" = "Seattle Children's Research Institute",
  "seattle childrens" = "Seattle Children's Research Institute",
  "cchmc" = "Cincinnati Children's Hospital Medical Center",
  "cincinnati childrens hospital medical center" = "Cincinnati Children's Hospital Medical Center",
  "cincinnati children s hospital medical center" = "Cincinnati Children's Hospital Medical Center",
  "washington university in st louis" = "Washington University in St. Louis",
  "washington university school of medicine" = "Washington University in St. Louis",
  "washington university in st louis" = "Washington University in St. Louis",
  
  # --- Proper names that appear in multiple formats ---
  "weill cornell medicine" = "Weill Cornell Medicine",
  "weill cornell medical college" = "Weill Cornell Medicine",
  "weill cornell medicine" = "Weill Cornell Medicine",
  "weill cornell medical college" = "Weill Cornell Medicine",
  "cornell university" = "Cornell University",
  
  # --- Institutes / consortiums / companies ---
  "encode dcc" = "ENCODE DCC",
  "center for genomic regulation" = "Centre for Genomic Regulation",
  "centre for genomic regulation" = "Centre for Genomic Regulation",
  "crg" = "Centre for Genomic Regulation",
  "universitat pompeu fabra centre for genomic regulation" = "Centre for Genomic Regulation",
  "max planck institute for molecular genetics" = "Max Planck Institute for Molecular Genetics",
  "max delbruck center for molecular medicine" = "Max Delbrück Center for Molecular Medicine",
  "max delbrueck center for molecular medicine" = "Max Delbrück Center for Molecular Medicine",
  "max planck institute of immunobiology and epigenetics" = "Max Planck Institute of Immunobiology and Epigenetics",
  "max planck institute of psychiatry" = "Max Planck Institute of Psychiatry",
  "francis crick institute" = "The Francis Crick Institute",
  "the francis crick institute" = "The Francis Crick Institute",
  "dkfz" = "German Cancer Research Center",
  "german cancer research center" = "German Cancer Research Center",
  "helmholtz center munich" = "Helmholtz Center Munich",
  "ce mm research center for molecular medicine of the austrian academy of sciences" = "CeMM Research Center for Molecular Medicine of the Austrian Academy of Sciences",
  "cemm research center for molecular medicine of the austrian academy of sciences" = "CeMM Research Center for Molecular Medicine of the Austrian Academy of Sciences",
  "imba" = "IMBA - Institute of Molecular Biotechnology",
  "imba institute of molecular biotechnology" = "IMBA - Institute of Molecular Biotechnology",
  "ce mm" = "CeMM Research Center for Molecular Medicine of the Austrian Academy of Sciences",
  "inserm" = "INSERM",
  "inrae" = "INRAE",
  "inrae university paris saclay" = "INRAE",
  "inra" = "INRA",
  "cnrs universite claude bernard lyon 1" = "CNRS",
  "institution pasteur" = "Institute Pasteur",
  "institute pasteur" = "Institute Pasteur",
  "institut pasteur de lille" = "Institut Pasteur de Lille",
  "i n s e r m umrs 1139" = "INSERM UMRS-1139",
  
  # --- Mixed / lab / misc spellings from the list ---
  "cedars sinai medical center" = "Cedars-Sinai Medical Center",
  "cedars-sinai medical center" = "Cedars-Sinai Medical Center",
  "mg h" = "Massachusetts General Hospital",
  "mgh" = "Massachusetts General Hospital",
  "university of california, san francisco" = "University of California San Francisco",
  "university of southern california" = "University of Southern California",
  "university of southern california" = "University of Southern California",
  "university of north carolin" = "University of North Carolina at Chapel Hill",
  "university of pittburgh" = "University of Pittsburgh",
  "stanford univeristy" = "Stanford University",
  "univerisity of cambridge" = "University of Cambridge",
  "university of kalgary" = "University of Calgary"
)

# Replace original names with the new normalized names
# First, normalize original Organization names
data_map$Org_norm <- normalize_org(data_map$`Organization name`) 
# Replace values using dictionary
data_map$Org_clean <- dict[data_map$Org_norm]
# If a value is not in the dictionary, keep the normalized version and capitalize it properly
data_map$Org_clean <- ifelse(data_map$Org_norm %in% names(dict), 
                             dict[data_map$Org_norm], 
                             tools::toTitleCase(data_map$Org_norm))
# There is only one case of a blank in Org_clean: 厦门大学 (which is Xiamen University). I want to manually fill in that one value.
data_map <- data_map %>% 
  mutate(Org_clean = if_else(Org_clean == "", "Xiamen University", Org_clean))

# Now I want to turn the names of the organizations into coordinates
unique_orgs <- data_map %>% distinct(Org_clean)

# I wanted to check if there were still duplicates in unique_orgs. I put the list into ChatGPT again and it found more duplicates. 
# I asked it to help me merge any duplicates:
dict_extra <- c(
  
  # --- Illinois ---
  "university of illinois at urbana champaign" =
    "University of Illinois Urbana-Champaign",
  "university of illinois urbana champaign" =
    "University of Illinois Urbana-Champaign",
  
  # --- McMaster ---
  "mcmaster universtiy" =
    "McMaster University",
  
  # --- KU Leuven ---
  "k u leuven" =
    "KU Leuven",
  "katholieke universiteit leuven" =
    "KU Leuven",
  
  # --- Kansas Medical Center ---
  "kumc" =
    "University of Kansas Medical Center",
  "the university of kansas medical center" =
    "University of Kansas Medical Center",
  
  # --- Cold Spring Harbor ---
  "cold spring harbor labs" =
    "Cold Spring Harbor Laboratory",
  
  # --- Memorial Sloan Kettering ---
  "memorial sloan kettering" =
    "Memorial Sloan Kettering Cancer Center",
  
  # --- Weizmann ---
  "weizmann" =
    "Weizmann Institute of Science",
  
  # --- Children's hospitals ---
  "cincinnati children s" =
    "Cincinnati Children's Hospital Medical Center",
  "the research institute at nationwide children s hospital" =
    "Nationwide Children's Hospital",
  
  # --- LSU ---
  "lsuhsc no" =
    "LSU Health New Orleans",
  "lsuhsc shreveport" =
    "LSU Health Shreveport",
  
  # --- Bonn ---
  "university medical school bonn" =
    "University of Bonn",
  
  # --- IDIBELL ---
  "idibell" =
    "Institut d'Investigació Biomèdica de Bellvitge (IDIBELL)",
  
  # --- Huazhong ---
  "huazhong agriculture university" =
    "Huazhong Agricultural University",
  
  # --- Jena ---
  "universitatsklinikum jena" =
    "Universitätsklinikum Jena",
  
  # --- Pasteur ---
  "institute pasteur" =
    "Institut Pasteur",
  
  # --- Rosetta ---
  "rosetta inpharmatics merck" =
    "Rosetta Inpharmatics",
  "rosetta inpharmatics merck co" =
    "Rosetta Inpharmatics",
  
  # --- Public health institutes ---
  "natl inst public health environment" =
    "National Institute for Public Health and the Environment",
  
  # --- Paris ---
  "universite paris6" =
    "Sorbonne University"
)
# Merge old and new dictionary
dict_all <- c(dict, dict_extra)

# Keep last definition if a key appears twice
dict_all <- dict_all[!duplicated(names(dict_all), fromLast = TRUE)]

# Apply new dictionary to unique_orgs list
unique_orgs <- unique_orgs %>%
  mutate(
    Org_clean = normalize_org(`Org_clean`),
    Org_canonical = recode(Org_clean, !!!dict_all, .default = Org_clean))

# If a value is not in either dictionary, keep the normalized version and capitalize it properly
unique_orgs$Org_canonical <- ifelse(unique_orgs$Org_canonical %in% names(dict_all), 
                                    dict[unique_orgs$Org_canonical], 
                                    tools::toTitleCase(unique_orgs$Org_canonical))

# Geocode using OpenStreetMap
### THIS TAKES ~10 MINS, SKIP THIS IF ORG_COORDS.CSV IS ALREADY DOWNLOADED
#org_coords <- unique_orgs %>% 
#geocode(Org_canonical, method = "osm", lat = lat, long = long) %>% 
#select(!Org_clean)

#Save output of org_coords into a csv so that we don't have to run it every time
#write.csv(org_coords, "in_paper/org_coords.csv", row.names = FALSE)

### IF ORG_COORDS.CSV IS ALREADY DOWNLOADED, JUST USE:
org_coords <- read.csv("in_paper/org_coords.csv")

# Check which rows have coordinates with NAs
count(org_coords %>% filter(is.na(lat)))
# 145 are NA, need to figure out how to solve this 

# Filter out NAs for now
org_coords <- org_coords %>% 
  filter(!is.na(lat))

# Rename Org_canonical to Org_clean
org_coords <- org_coords %>% 
  rename(Org_clean = Org_canonical)

# Merge coordinates back to study-level data
# Keep this as the unsplit, one-row-per-study table
studies_coords <- data_map %>%
  mutate(study_id = row_number()) %>%
  left_join(org_coords, by = "Org_clean") %>%
  filter(!is.na(lat), !is.na(long))

# Before plotting, I wanted to make sure that all the coordinates corresponded to the correct institutions.
# I put the studies_coords table into ChatGPT and it caught 9 instances of wrong country labeling. Here I am fixing this:
coord_fixes <- tribble(
  ~Org_clean, ~Country, ~lat_fix, ~long_fix,
  "University of Oxford", "United Kingdom", 51.7548, -1.2544,
  "Mayo Clinic", "USA", 44.0225, -92.4668,
  "Mount Sinai Hospital", "USA", 40.7898, -73.9533,
  "National Cancer Institute", "USA", 39.0000, -77.1040,
  "Children s Mercy", "USA", 39.0844, -94.5775,
  "The Hospital for Sick Children", "Canada", 43.6577, -79.3871,
  "Grafton", "New Zealand", -36.8614, 174.7690,
  "RIKEN", "Japan", 35.7800, 139.6100,
  "INRA", "France", 43.52723, 1.501060)

# Make a corrected study-level table
studies_coords_fixed <- studies_coords %>%
  left_join(coord_fixes, by = c("Org_clean", "Country")) %>%
  mutate(
    lat = coalesce(lat_fix, lat),
    long = coalesce(long_fix, long)) %>%
  select(-lat_fix, -long_fix)

# Group organisms
# Read in the table made in Placenta_organism_type.R that has all the organism groups already
data_organism <- read_csv("in_paper/data_organism.csv") %>% 
  # Rename organism_old to Organism to merge the two tables, rename organism to organism_new to avoid confusion
  rename(Organism = organism_old, organism_new = organism)

# Make sure there is only one row per organism
org_lookup <- data_organism %>%
  distinct(Organism, organism_new, common_name, display_name)

# Join organism table to studies_coords
studies_coords_fixed <- studies_coords_fixed %>%
  separate_rows(Organism, sep = ",\\s*") %>% 
  mutate(Organism = trimws(Organism)) %>% 
  left_join(org_lookup, by = "Organism") %>% 
  # Remove NAs because these organisms do not have placentas
  filter(!is.na(display_name))

# Group into Human, Mouse, Rat, or Other
studies_coords_fixed <- studies_coords_fixed %>%
  # Group organisms
  mutate(organism_group = case_when(
    organism_new == "Homo sapiens" ~ "Human (Homo sapiens)",
    organism_new == "Mus musculus" ~ "Mouse (Mus musculus)",
    organism_new == "Rattus norvegicus" ~ "Rat (Rattus norvegicus)",
    TRUE ~ "Other"))

# Reorder factor levels to have organisms in proper order for legend
studies_coords_fixed$organism_group <- factor(
  studies_coords_fixed$organism_group, levels = c("Human (Homo sapiens)", "Mouse (Mus musculus)", "Rat (Rattus norvegicus)", "Other"))

# Make table counting number of studies per continent to label the map
# Label continent each study comes from
studies_coords_continent <- studies_coords_fixed %>%
  mutate(
    continent = countrycode(
      Country,
      origin = "country.name",
      destination = "continent",
      custom_match = c(
        "USA" = "North America",
        "United States" = "North America",
        "Canada" = "North America",
        "Mexico" = "North America",
        "Colombia" = "South America",
        "Brazil" = "South America",
        "Chile" = "South America",
        "UK" = "Europe")))

# Count studies per continent
continent_counts <- studies_coords_continent %>%
  count(continent, name = "n") %>% 
  add_row(continent = "Africa", n = 0)

# Add approximate positions for labels
continent_pos <- tibble(
  continent = c("North America", "South America", "Europe", "Africa", "Asia", "Oceania"),
  long = c(-100, -60, 15, 20, 95, 140),
  lat  = c(45, -15, 55, 5, 35, -25))
continent_labels <- continent_counts %>%
  left_join(continent_pos, by = "continent")

# Plot the map
world_map <- map_data("world")
placenta_map <- ggplot() +
  # Country polygons
  geom_polygon(data = world_map,
               aes(x=long, y = lat, group = group),
               fill = "grey90", color = "white") +
  # Study points
  geom_point(data = studies_coords_fixed,
             aes(x = long, y = lat,
                 size = `Sample size (placenta)`,
                 color = `organism_group`), alpha = 0.7) +
  scale_size_continuous(range = c(2, 10),
                        # Manually set lowest Study Size number as 1, not 0
                        breaks = c(1, 200, 400, 600),
                        labels = c("1", "200", "400", "600")) +
  coord_fixed(1.3) +
  scale_color_manual(values = c(
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
  theme_classic() +
  theme(axis.text = element_blank(),
        axis.ticks = element_blank(),
        axis.title = element_blank(),
        axis.line = element_blank()) +
  labs(title = "Global Distribution of Where Placenta Studies are Conducted",
       size = "Study Size",
       color = "Organism Type") +
  geom_text(data = continent_labels, aes(x = long, y = lat, label = n), size = 5, fontface = "bold")
placenta_map
# Save plot
ggsave("in_paper/figures/placenta_map.pdf", plot = placenta_map, width = 8, height = 6, dpi = 300)

# === 2) OLD === ######
# ==== a) Map with organism list of organisms with 5 or studies ===
# Group into Human, Mouse, Rat, or Other
studies_coords_fixed_v2 <- studies_coords_fixed %>%
  # Group organisms
  mutate(organism_group = case_when(
    organism_new == "Homo sapiens" ~ "Human (Homo sapiens)",
    organism_new == "Mus musculus" ~ "Mouse (Mus musculus)",
    organism_new == "Rattus norvegicus" ~ "Rat (Rattus norvegicus)",
    organism_new == "Bos taurus" ~ "Cow (Bos taurus)",
    organism_new == "Sus scrofa" ~ "Wild boar (Sus scrofa)",
    organism_new == "Macaca mulatta" ~ "Rhesus macaque (Macaca mulatta)",
    organism_new == "Equus caballus" ~ "Horse (Equus caballus)",
    organism_new == "Macaca fascicularis" ~ "Crab-eating macaque (Macaca fascicularis)",
    organism_new == "Cavia porcellus" ~ "Guinea pig (Cavia porcellus)",
    organism_new == "Monodelphis domestica" ~ "Gray short-tailed opossum (Monodelphis domestica)",
    TRUE ~ "Other"))

# Reorder factor levels to have organisms in proper order for legend
studies_coords_fixed_v2$organism_group <- factor(
  studies_coords_fixed$organism_group, levels = c("Human (Homo sapiens)", "Mouse (Mus musculus)", "Rat (Rattus norvegicus)", "Other"))

# Plot the map
world_map <- map_data("world")
placenta_map_v2 <- ggplot() +
  # Country polygons
  geom_polygon(data = world_map,
               aes(x=long, y = lat, group = group),
               fill = "grey90", color = "white") +
  # Study points
  geom_point(data = studies_coords_fixed_v2,
             aes(x = long, y = lat,
                 size = `Sample size (placenta)`,
                 color = `organism_group`), alpha = 0.7) +
  scale_size_continuous(range = c(2, 10),
                        # Manually set lowest Study Size number as 1, not 0
                        breaks = c(1, 200, 400, 600),
                        labels = c("1", "200", "400", "600")) +
  coord_fixed(1.3) +
  scale_color_manual(values = c(
    "Other" = "grey",
    "Human (Homo sapiens)" = "#a1dab4",
    "Mouse (Mus musculus)" = "#fe9929",
    "Rat (Rattus norvegicus)" = "#225ea8",
    "Cow (Bos taurus)" = "#f768a1",
    "Wild boar (Sus scrofa)" = "#9e9ac8",
    "Rhesus macaque (Macaca mulatta)" = "#2ca25f",
    "Horse (Equus caballus)" = "#fec44f",
    "Crab-Eating Macaque (Macaca fascicularis)" = "#41b6c4",
    "Domestic Guinea Pig (Cavia porcellus)" = "#756bb1",
    "Gray Short-Tailed Opossum (Monodelphis domestica)" = "#dd1c77")) +
  theme_classic() +
  theme(axis.text = element_blank(),
        axis.ticks = element_blank(),
        axis.title = element_blank(),
        axis.line = element_blank()) +
  labs(title = "Global Distribution of Where Placenta Studies are Conducted",
       size = "Study Size",
       color = "Organism Type") +
  geom_text(data = continent_labels, aes(x = long, y = lat, label = n), size = 5, fontface = "bold")
placenta_map_v2

# Save
ggsave("in_paper/figures/placenta_map_v2.png", plot = placenta_map_v2, width = 8, height = 6, dpi = 300)


# === b) Map of locations of just studies using human placentas ===
# Filter for just human
human_coords <- studies_coords %>% 
  filter(organism_group == "Human")
# Plot
placenta_map_human <- ggplot() +
  # Country polygons
  geom_polygon(data = world_map,
               aes(x=long, y = lat, group = group),
               fill = "grey90", color = "white") +
  # Study points
  geom_point(data = human_coords,
             aes(x = long, y = lat,
                 size = `Sample size (placenta)`),
             alpha = 0.7, color = "steelblue") +
  scale_size_continuous(range = c(2, 10)) +
  coord_fixed(1.3) +
  theme_classic() +
  theme(axis.text = element_blank(),
        axis.ticks = element_blank(),
        axis.title = element_blank(),
        axis.line = element_blank()) +
  labs(title = "Global Distribution of Human Placenta Studies",
       size = "Study Size")
placenta_map_human
# Save plot
ggsave("figures/placenta_map_human.png", plot = placenta_map_human, width = 8, height = 6, dpi = 300)

# === c) Map of locations of studies using non-human placentas ===
# Filter for everything non-human
nonhuman_coords <- studies_coords %>% 
  filter(organism_group != "Human")
# Plot
placenta_map_nonhuman <- ggplot() +
  # Country polygons
  geom_polygon(data = world_map,
               aes(x=long, y = lat, group = group),
               fill = "grey90", color = "white") +
  # Study points
  geom_point(data = nonhuman_coords,
             aes(x = long, y = lat,
                 size = `Sample size (placenta)`),
             alpha = 0.4, color = "lightblue") +
  scale_size_continuous(range = c(2, 10)) +
  coord_fixed(1.3) +
  theme_classic() +
  theme(axis.text = element_blank(),
        axis.ticks = element_blank(),
        axis.title = element_blank(),
        axis.line = element_blank()) +
  labs(title = "Global Distribution of Non-Human Placenta Studies",
       size = "Study Size")
placenta_map_nonhuman
# Save plot
ggsave("figures/placenta_map_nonhuman.png", plot = placenta_map_nonhuman, width = 8, height = 6, dpi = 300)

# === d) Map of locations of studies not using human or mouse placentas ===
# Filter for just human
other_coords <- studies_coords %>% 
  filter(organism_group != "Human") %>% 
  filter(organism_group != "Mouse")
# Plot
placenta_map_other <- ggplot() +
  # Country polygons
  geom_polygon(data = world_map,
               aes(x=long, y = lat, group = group),
               fill = "grey90", color = "white") +
  # Study points
  geom_point(data = other_coords,
             aes(x = long, y = lat,
                 size = `Sample size (placenta)`),
             alpha = 0.7, color = "blue") +
  scale_size_continuous(range = c(2, 10)) +
  coord_fixed(1.3) +
  theme_classic() +
  theme(axis.text = element_blank(),
        axis.ticks = element_blank(),
        axis.title = element_blank(),
        axis.line = element_blank()) +
  labs(title = "Global Distribution of Non-Human or Mouse Placenta Studies",
       size = "Study Size")
placenta_map_other
# Save plot
ggsave("figures/placenta_map_other.png", plot = placenta_map_other, width = 8, height = 6, dpi = 300)

# === e) Map of placenta study locations, broken up by continents ===
# Zoom into each continent
placenta_map_na <- placenta_map +
  coord_fixed(1.3, xlim = c(-170, -50), ylim = c(10, 85)) +
  labs(title = "North America")
placenta_map_sa <- placenta_map +
  coord_fixed(1.3, xlim = c(-90, -30), ylim = c(-60, 15)) +
  labs(title = "South America") +
  theme(legend.position = "none")
placenta_map_europe <- placenta_map +
  coord_fixed(1.3, xlim = c(-25, 60), ylim = c(35, 75)) +
  labs(title = "Europe") +
  theme(legend.position = "none")
placenta_map_africa <- placenta_map +
  coord_fixed(1.3, xlim = c(-20, 55), ylim = c(-35, 40)) +
  labs(title = "Africa") +
  theme(legend.position = "none")
placenta_map_asia <- placenta_map +
  coord_fixed(1.3, xlim = c(25, 180), ylim = c(-10, 80)) +
  labs(title = "Asia") +
  theme(legend.position = "none")
placenta_map_oceania <- placenta_map +
  coord_fixed(1.3, xlim = c(110, 180), ylim = c(-50, 0)) +
  labs(title = "Australia & Oceania") +
  theme(legend.position = "none")
# Combine
combined_map <- (placenta_map_na | placenta_map_sa | placenta_map_europe) /
  (placenta_map_africa | placenta_map_asia | placenta_map_oceania) +
  plot_layout(guides = "collect") + 
  plot_annotation(
    title = "Continental Distribution of Placenta Studies",
    theme = theme(
      plot.title = element_text(size = 18, face = "bold", hjust = 0.5))) &
  theme(legend.position = "bottom")
combined_map
# Save plot
ggsave("figures/placenta_continental_map.png", plot = combined_map, width = 8, height = 6, dpi = 300)
