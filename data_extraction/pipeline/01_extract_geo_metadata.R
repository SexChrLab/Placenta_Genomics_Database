# Load packages
library(GEOquery)
library(writexl)
library(dplyr)
library(stringr)
library(purrr)
library(lubridate)
library(progressr)
library(tibble)
library(furrr)
library(data.table)
library(rvest)
library(httr)
library(jsonlite)

handlers(global = TRUE)
handlers("progress")
# Keep geo_cache across runs so large batches can resume after interruption.
dir.create("geo_cache", showWarnings = FALSE)
# Utility functions
`%||%` = function(x, y) if (!is.null(x)) x else y

convert_to_gse <- function(ids) {
  ids <- trimws(as.character(ids))
  already_gse <- grepl("^GSE\\d+$", ids, ignore.case = TRUE)
  ids[already_gse] <- toupper(ids[already_gse])
  ids[!already_gse] <- paste0("GSE", gsub("\\D", "", ids[!already_gse]))
  ids
}
fetch_pmc_map <- function(pmids) {
  pmids <- unique(pmids[grepl("^\\d+$", pmids)])
  if (length(pmids) == 0) {
    return(tibble::tibble(pmid = character(0), pmcid = character(0), doi = character(0)))
  }
  # API allows up to ~ 200 IDs per request
  chunks <- split(pmids, ceiling(seq_along(pmids) / 200))
  out <- lapply(chunks, function(ids) {
    resp <- httr::GET(
      url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
      query = list(ids = paste(ids, collapse=","), format = "json")
    )
    txt <- httr::content(resp, as = "text", encoding = "UTF-8")
    j <- jsonlite::fromJSON(txt)
    if (!is.null(j$records)) {
      tibble::tibble(
        pmid  = j$records$pmid %||% NA_character_,
        pmcid = j$records$pmcid %||% NA_character_,
        doi   = j$records$doi %||% NA_character_
      )
    } else {
      tibble::tibble(pmid = character(0), pmcid = character(0), doi = character(0))
    }
  })
  dplyr::bind_rows(out) %>% dplyr::distinct()
}
# GSM fields extractor (multi-line aware)
gsm_cache_dir = file.path("geo_cache", "gsm_pages")
dir.create(gsm_cache_dir, showWarnings = FALSE, recursive = TRUE)

extract_gsm_fields = function(gsm_id) {
  cache_file = file.path(gsm_cache_dir, paste0(gsm_id, ".rds"))

  if (file.exists(cache_file)) {
    text = readRDS(cache_file)
  } else {
    page = tryCatch(
      read_html(paste0("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=", gsm_id)),
      error = function(e) return(NA)
    )
    if (is.na(page)) return(rep(NA_character_, 7))
    text = html_text2(page)
    saveRDS(text, cache_file)
    Sys.sleep(0.2)
  }

  known_labels <- c(
    "Title","Sample type","Source name","Organism","Characteristics",
    "Molecule","Extracted molecule","Treatment protocol","Growth protocol",
    "Extraction protocol","Library construction protocol","Selection protocol",
    "Library strategy","Library source","Library selection","Instrument model",
    "Description","Data processing","Contact name","Organization","Department",
    "Lab","Address","Email","Phone","Fax","URL"
  )

  grab_block <- function(label) {
    out <- tryCatch({
      next_labels <- setdiff(known_labels, label)
      next_pat <- paste0("(?=\\n(?:", paste0("(?i)", next_labels, collapse="|"), ")\\s*[:\\s])|\\Z")
      pat <- paste0("(?is)", label, "\\s*[:\\s]?\\s*(.+?)", next_pat)
      m <- stringr::str_match(text, pat)
      if (is.null(m) || all(is.na(m))) return(NA_character_)
      val <- stringr::str_squish(m[,2])
      ifelse(is.na(val) | val == "", NA_character_, val)
    }, error = function(e) NA_character_)
    out
  }

  grab_line <- function(label) {
    out <- tryCatch({
      pat <- paste0("(?is)", label, "\\s*[:\\s]?\\s*([^\\n]+)")
      m <- stringr::str_match(text, pat)
      if (is.null(m) || all(is.na(m))) return(NA_character_)
      val <- stringr::str_squish(m[,2])
      ifelse(is.na(val) | val == "", NA_character_, val)
    }, error = function(e) NA_character_)
    out
  }

  library_strategy    <- grab_line("Library strategy")
  library_selection   <- grab_line("Library selection")
  library_source      <- grab_line("Library source")
  instrument_model    <- grab_line("Instrument model")
  extracted_molecule  <- grab_line("Extracted molecule")
  extraction_protocol <- grab_block("Extraction protocol")            # multi-line
  c(library_strategy,
    library_selection,
    library_source,
    instrument_model,
    extracted_molecule,
    extraction_protocol)
}
# Fetch single GSE
get_single_gse_full = function(geo_id) {
  cache_file = file.path("geo_cache", paste0(geo_id, ".rds"))
  if (file.exists(cache_file)) return(readRDS(cache_file))

  out = tryCatch({
    gse = getGEO(geo_id, GSEMatrix = FALSE, AnnotGPL = FALSE)
    meta_data = Meta(gse)
    gsm_list = GSMList(gse)
    gsm_ids = names(gsm_list)

    # placenta sample count
    placenta_keywords = c("placenta","chorionic","decidua","trophoblast","chorion")
    placenta_pattern = paste(placenta_keywords, collapse = "|")
    placenta_samples_count = sum(
      map_lgl(gsm_list, ~ str_detect(tolower(.x@header$title %||% ""), placenta_pattern) |
                str_detect(tolower(.x@header$source_name_ch1 %||% ""), placenta_pattern))
    )

    # GSM characteristics aggregation (defensive)
    gsm_chars <- tryCatch(
      unique(na.omit(unlist(lapply(gsm_list, function(x) x@header$characteristics_ch1 %||% NA)))),
      error = function(e) character(0)
    )
    characteristics <- if (length(gsm_chars) == 0) NA_character_ else paste(unique(str_squish(gsm_chars)), collapse = " | ")

    # Scrape GSMs (6 fields)
    gsm_values = future_map(gsm_ids, extract_gsm_fields)

    collapse_gsm <- function(idx) {
      vals <- tryCatch(vapply(gsm_values, function(x) x[[idx]], character(1)), error = function(e) character(0))
      vals <- vals[!is.na(vals) & vals != ""]
      if (length(vals) == 0) NA_character_ else paste(unique(vals), collapse = if (idx == 6) "\n\n" else ", ")
    }

    library_strategy    <- collapse_gsm(1)
    library_selection   <- collapse_gsm(2)
    library_source      <- collapse_gsm(3)
    instrument_model    <- collapse_gsm(4)
    extracted_molecule  <- collapse_gsm(5)
    extraction_protocol <- collapse_gsm(6)


    # GSE-level parses
    rel_text <- if (!is.null(meta_data$relation)) paste(meta_data$relation, collapse = " | ") else ""

    # SRA Study ID
    sra_ids <- unique(unlist(stringr::str_extract_all(rel_text, "SRP\\d+")))
    sra_study_id <- if (length(sra_ids) == 0) NA_character_ else paste(sra_ids, collapse = ", ")

    # BioSample + BioProject
    biosample_ids  <- unique(unlist(stringr::str_extract_all(rel_text, "(SAMN\\d+|SAMEA\\d+|SAMD\\d+)")))
    bioproject_ids <- unique(unlist(stringr::str_extract_all(rel_text, "PRJ[A-Z]+\\d+")))
    biosample_bioproject <- c(biosample_ids, bioproject_ids)
    biosample_bioproject <- if (length(biosample_bioproject) == 0) NA_character_ else paste(unique(biosample_bioproject), collapse = ", ")

    # File types/resources provided
    supp <- meta_data$supplementary_file
    file_types <- if (!is.null(supp)) {
      exts <- tolower(tools::file_ext(supp))
      exts <- exts[exts != ""]
      if (length(exts) == 0) NA_character_ else paste(unique(exts), collapse = ", ")
    } else NA_character_

    # Organization & contacts
    organization_name <- meta_data$contact_organization %||% meta_data$contact_institute %||% NA

    # Data processing, Data type, Assay description (Overall design)
    data_processing  <- if (!is.null(meta_data$data_processing)) paste(meta_data$data_processing, collapse = "\n\n") else NA
    data_type        <- if (!is.null(meta_data$type)) paste(meta_data$type, collapse = ", ") else NA
    assay_description <- meta_data$overall_design %||% NA

    # Build tibble
    tibble(
      GEO_ID = geo_id,
      contact_country = meta_data$contact_country %||% NA,
      contact_email = meta_data$contact_email %||% NA,
      contact_institute = meta_data$contact_institute %||% NA,
      organization_name = organization_name,
      contact_name = gsub(",+", " ", meta_data$contact_name %||% NA),
      overall_design = meta_data$overall_design %||% NA,
      platform_id = if (!is.null(meta_data$platform_id)) paste(meta_data$platform_id, collapse=", ") else NA,
      pubmed_id = if (!is.null(meta_data$pubmed_id)) paste(meta_data$pubmed_id, collapse=", ") else NA,  # collapsed
      relation = if (!is.null(meta_data$relation)) paste(meta_data$relation, collapse=", ") else NA,
      sample_number = if (!is.null(meta_data$sample_id)) length(meta_data$sample_id) else NA,
      sample_taxid = if (!is.null(meta_data$sample_taxid)) paste(meta_data$sample_taxid, collapse=", ") else NA,
      submission_date = meta_data$submission_date %||% NA,
      last_update_date = meta_data$last_update_date %||% NA,
      main_topic = meta_data$summary %||% NA,
      supplementary_file = if (!is.null(meta_data$supplementary_file)) paste(meta_data$supplementary_file, collapse=", ") else NA,
      title = meta_data$title %||% NA,

      data_type = data_type,
      characteristics = characteristics,
      library_strategy = library_strategy,
      library_source = library_source,
      library_selection = library_selection,
      instrument_model = instrument_model,
      extracted_molecule = extracted_molecule,
      extraction_protocol = extraction_protocol,
      assay_description = assay_description,
      data_processing = data_processing,
      sra_study_id = sra_study_id,
      biosample_bioproject = biosample_bioproject,
      file_types = file_types,
      placenta_samples = placenta_samples_count
    )

  }, error = function(e) {
    tibble(GEO_ID = geo_id, error = as.character(e))
  })
  saveRDS(out, cache_file)
  out
}
# Main workflow
ids_file = Sys.getenv("ids_file", "ids.csv")
gse_df = read.csv(ids_file, header = FALSE, stringsAsFactors = FALSE)
geo_ids = convert_to_gse(as.character(gse_df[[1]]))

geo_workers = as.integer(Sys.getenv("geo_r_workers", "1"))
if (is.na(geo_workers) || geo_workers < 1) geo_workers = 1
if (geo_workers == 1) {
  plan(sequential)
} else {
  plan(multisession, workers = geo_workers)
}
handlers(global = TRUE)

with_progress({
  p = progressor(along = geo_ids)
  results = future_map(geo_ids, function(id) {
    out = get_single_gse_full(id)
    p()
    out
  }, .options = furrr_options(seed = TRUE))
})
# Combine results + diagnostics (robust)
fail <- purrr::keep(results, ~ "error" %in% names(.x))
ok   <- purrr::keep(results, ~ !"error" %in% names(.x))

if (length(fail) > 0) {
  fail_df <- dplyr::bind_rows(fail)
  try(write.csv(fail_df, "debug_failures.csv", row.names = FALSE), silent = TRUE)
  message("Wrote debug_failures.csv with error messages (if any).")
}

metadata_df <- data.table::rbindlist(ok, fill = TRUE)
failed_ids  <- purrr::map_chr(fail, "GEO_ID")

if (nrow(metadata_df) == 0) {
  writexl::write_xlsx(
    list(
      Metadata = tibble::tibble(),
      Failed   = if (length(fail) > 0) dplyr::bind_rows(fail) else tibble::tibble()
    ),
    "gse_metadata_full.xlsx"
  )
  message("No successful GSE fetches. Saved only the Failed sheet.")
  quit(status = 0)
}

# Ensure expected columns exist
ensure_cols <- function(df, cols) {
  for (nm in cols) if (!nm %in% names(df)) df[[nm]] <- rep(NA_character_, nrow(df))
  df
}
metadata_df <- ensure_cols(
  metadata_df,
  c("relation","sample_taxid","last_update_date","submission_date","pubmed_id")
)

# Superseries list (safe)
metadata_df <- metadata_df %>%
  mutate(
    Superseries = map_chr(
      relation,
      ~ {
        if (is.null(.x) || is.na(.x) || .x == "") return(NA_character_)
        hits <- stringr::str_extract_all(.x, "GSE\\d+")[[1]]
        if (length(hits) == 0) NA_character_ else paste(unique(hits), collapse = ", ")
      }
    )
  )

# Organism mapping from sample_taxid (best-effort). GEO can store multiple taxids
# in one row (e.g. "9606, 10090"); map each taxid instead of treating the whole
# comma-separated string as one key, which caused blank Organism values.
taxonomy <- c(
  "10090"="Mus musculus","9315"="Notamacropus eugenii","9606"="Homo sapiens",
  "9823"="Sus scrofa","10116"="Rattus norvegicus","9913"="Bos taurus",
  "9361"="Dasypus novemcinctus","10092"="Mus musculus domesticus","9544"="Macaca mulatta",
  "9915"="Bos indicus","9545"="Macaca nemestrina","9986"="Oryctolagus cuniculus"
)
map_taxids_to_organisms <- function(x) {
  if (is.null(x) || length(x) == 0 || is.na(x) || x == "") return(NA_character_)
  ids <- unique(unlist(stringr::str_extract_all(as.character(x), "\\d+")))
  if (length(ids) == 0) return(NA_character_)
  mapped <- unname(taxonomy[ids])
  mapped <- mapped[!is.na(mapped) & mapped != ""]
  unknown <- ids[!ids %in% names(taxonomy)]
  vals <- unique(c(mapped, if (length(unknown)) paste0("taxid:", unknown) else character(0)))
  if (length(vals) == 0) NA_character_ else paste(vals, collapse = ", ")
}
metadata_df$organism <- vapply(metadata_df$sample_taxid, map_taxids_to_organisms, character(1))

# Dates
safedate <- function(x) {
  dt <- suppressWarnings(lubridate::parse_date_time(x, orders = c("b d Y","b d, Y","Y-m-d")))
  ifelse(is.na(dt), NA_character_, format(as.Date(dt), "%m/%d/%Y"))
}
metadata_df$last_update_date <- safedate(metadata_df$last_update_date)
metadata_df$submission_date  <- safedate(metadata_df$submission_date)
# PMID -> PMCID / DOI via NIH API, then join
metadata_df <- metadata_df %>%
  mutate(
    pmid_all = pubmed_id %||% NA_character_,
    pmid_list = stringr::str_extract_all(pubmed_id %||% "", "\\d+"),
    pmid_primary = purrr::map_chr(pmid_list, ~ if (length(.x)) .x[[1]] else NA_character_)
  )

all_pmids <- unique(unlist(metadata_df$pmid_list))
all_pmids <- all_pmids[!is.na(all_pmids) & all_pmids != ""]
pmc_map <- tryCatch(fetch_pmc_map(all_pmids), error = function(e) {
  message("NIH ID converter call failed: ", e$message)
  tibble::tibble(pmid = character(0), pmcid = character(0), doi = character(0))
})

# make both keys character, then join
pmc_map$pmid <- as.character(pmc_map$pmid)
metadata_df$pmid_primary <- as.character(metadata_df$pmid_primary)

metadata_df <- metadata_df %>%
  dplyr::left_join(pmc_map, by = c("pmid_primary" = "pmid")) %>%
  dplyr::mutate(
    pmcid_all = purrr::map_chr(pmid_list, function(ids) {
      vals <- unique(na.omit(pmc_map$pmcid[match(ids, pmc_map$pmid)]))
      vals <- vals[vals != ""]
      if (length(vals)) paste(vals, collapse = ", ") else NA_character_
    }),
    doi_all = purrr::map_chr(pmid_list, function(ids) {
      vals <- unique(na.omit(pmc_map$doi[match(ids, pmc_map$pmid)]))
      vals <- vals[vals != ""]
      if (length(vals)) paste(vals, collapse = ", ") else NA_character_
    })
  )
# Final output with exact columns / names requested (+ PMID/PMCID/DOI)
output_df <- metadata_df %>%
  transmute(
    `GEO Series ID (GSE___)` = GEO_ID,
    `Data type` = data_type,
    `SuperSeries, list GEO Series that are part of the SuperSeries` = Superseries,
    `Sample size (placenta)` = placenta_samples,
    `Title` = title,
    `Organism` = organism,
    `Characteristics` = characteristics,
    `Extracted molecule` = extracted_molecule,
    `Extraction protocol` = extraction_protocol,
    `Library Strategy` = library_strategy,
    `Library source` = library_source,
    `Library selection` = library_selection,
    `Instrument model` = instrument_model,
    `Assay description` = assay_description,
    `Data processing` = data_processing,
    `Platform ID (list)` = platform_id,
    `SRA Study ID (raw data)` = sra_study_id,
    `BioSample/BioProject ID` = biosample_bioproject,
    `File types/resources provided (list)` = file_types,
    `Submission date` = submission_date,
    `Last update date` = last_update_date,
    `Organization name` = organization_name,
    `Contact name` = contact_name,
    `E-mail(s)` = contact_email,
    `Country` = contact_country,
    `PMID` = pmid_primary,
    `All PMIDs` = pmid_all,
    `PMCID` = pmcid,
    `All PMCIDs` = pmcid_all,
    `DOI` = doi,
    `All DOIs` = doi_all
  )

# Save.  Keep both the historic full filename and the checkpoint filename
# because 02_repair_geo_metadata.R consumes the checkpoint workbook for its second pass.
failed_df <- if (length(fail) > 0) dplyr::bind_rows(fail) else tibble::tibble(GEO_ID = failed_ids)
out_sheets <- list(Metadata = output_df, Failed = failed_df)

writexl::write_xlsx(out_sheets, "gse_metadata_full.xlsx")
writexl::write_xlsx(out_sheets, "gse_metadata_full_checkpoint.xlsx")

readr::write_csv(output_df, "gse_metadata_full_metadata.csv")
readr::write_csv(failed_df, "gse_metadata_full_failed.csv")
readr::write_csv(output_df, "gse_metadata_full_checkpoint_metadata.csv")
readr::write_csv(failed_df, "gse_metadata_full_checkpoint_failed.csv")

message("Processing complete. Results saved to gse_metadata_full.xlsx and gse_metadata_full_checkpoint.xlsx")
