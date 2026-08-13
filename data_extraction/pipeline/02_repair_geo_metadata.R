# Parallel patch of Failed GSEs with visible progress (+ optional 404 HTTP salvage)
# Fills: Sample size (placenta), Organism, Characteristics, Extracted molecule,
#        Extraction protocol, Library Strategy/Source/Selection, Instrument model,
#        Data processing, SuperSeries, Platform IDs, SRA/BioProject/BioSample,
#        contacts/dates, PMID -> PMCID/DOI. Merges back in ids.csv order.

options(stringsAsFactors = FALSE)
base_dir <- Sys.getenv("project_root", getwd())
keep_only_ids_in_csv   <- TRUE
max_gsms_env <- Sys.getenv("max_gsms_per_gse", "")
max_gsms_per_gse <- if (nzchar(max_gsms_env)) as.numeric(max_gsms_env) else Inf

# Networking / performance
gse_workers_env <- as.integer(Sys.getenv("geo_r_workers", "1"))
gse_workers     <- if (is.na(gse_workers_env) || gse_workers_env < 1) 1 else gse_workers_env
series_tries    <- 3
gsm_tries       <- 3
series_timeout  <- 12
gsm_timeout     <- 10
polite_delay_gsm <- c(0.02, 0.06)  # short delay per GSM request
suppressPackageStartupMessages({
  library(httr); library(jsonlite); library(readxl); library(writexl); library(readr)
  library(dplyr); library(stringr); library(tibble); library(purrr); library(tools)
  library(future); library(furrr)
  library(progressr)
})

# progress bars visible from furrr
progressr::handlers(global = TRUE)
dir.create(file.path(base_dir, "geo_cache"), showWarnings = FALSE, recursive = TRUE)
series_cache <- file.path(base_dir, "geo_cache", "gse_text")
gsm_cache    <- file.path(base_dir, "geo_cache", "gsm_text")
html_cache   <- file.path(base_dir, "geo_cache", "gse_html")
log_dir      <- file.path(base_dir, "geo_cache", "logs")
dir.create(series_cache, showWarnings = FALSE, recursive = TRUE)
dir.create(gsm_cache,    showWarnings = FALSE, recursive = TRUE)
dir.create(html_cache,   showWarnings = FALSE, recursive = TRUE)
dir.create(log_dir,      showWarnings = FALSE, recursive = TRUE)

`%||%` <- function(x, y) if (!is.null(x)) x else y
excel_char_limit <- 32767L
truncate_vec <- function(v) {
  if (is.null(v)) return(v)
  if (!is.character(v)) { if (is.factor(v)) v <- as.character(v) else return(v) }
  idx <- !is.na(v) & nchar(v, type = "chars", allowNA = TRUE) > excel_char_limit
  v[idx] <- substr(v[idx], 1L, excel_char_limit)
  v
}
sanitize_for_excel <- function(df) {
  if (is.null(df) || !nrow(df)) return(df)
  for (nm in names(df)) df[[nm]] <- truncate_vec(df[[nm]])
  df
}
extract_all_gse <- function(x) {
  x <- toupper(trimws(as.character(x)))
  toks <- stringr::str_extract_all(x, "GSE\\d+")[[1]]
  if (!length(toks)) return(character(0))
  norm <- paste0("GSE", sub("^0+", "", substring(toks, 4)))
  unique(norm[nzchar(norm)])
}
collapse_uniq <- function(x, sep = " | ", max_items = Inf) {
  x <- unique(x[!is.na(x) & nzchar(x)])
  if (!length(x)) return(NA_character_)
  if (is.finite(max_items)) x <- head(x, max_items)
  paste(x, collapse = sep)
}

series_text_url <- function(gse) sprintf(
  "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=%s&targ=gse&form=text&view=full", gse)
gsm_text_url <- function(gsm) sprintf(
  "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=%s&targ=gsm&form=text&view=full", gsm)
series_html_url <- function(gse) sprintf("https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=%s", gse)

read_resp_text <- function(resp) {
  if (inherits(resp, "response")) return(httr::content(resp, as = "text", encoding = "UTF-8"))
  if (!is.null(resp$content)) { txt <- rawToChar(resp$content); Encoding(txt) <- "UTF-8"; return(txt) }
  stop("Unsupported response object in read_resp_text()")
}

# Compact retry using httr::RETRY
http_get_text_cached <- function(url, cache_file, tries = 3, timeout_secs = 10) {
  if (file.exists(cache_file)) return(readRDS(cache_file))
  resp <- try(httr::RETRY(
    verb = "GET", url = url,
    times = tries, pause_base = 1, pause_cap = 8, pause_min = 0.3,
    httr::timeout(timeout_secs), httr::user_agent("geo-text-patch/1.5")
  ), silent = TRUE)
  if (inherits(resp, "try-error") || httr::status_code(resp) != 200)
    stop(sprintf("GET failed: %s", url))
  txt <- read_resp_text(resp)
  saveRDS(txt, cache_file)
  txt
}
first_val <- function(lines, pat) {
  m <- str_match(lines, pat); m <- m[!is.na(m[, 2]), , drop = FALSE]
  if (nrow(m)) str_squish(m[1, 2]) else NA_character_
}
all_vals <- function(lines, pat) {
  m <- str_match(lines, pat); vals <- m[, 2]
  str_squish(vals[!is.na(vals)])
}
parse_series_block <- function(lines) {
  list(
    series_type       = first_val(lines, "^!Series_type\\s*=\\s*(.+)$"),
    series_title      = first_val(lines, "^!Series_title\\s*=\\s*(.+)$"),
    series_summary    = first_val(lines, "^!Series_summary\\s*=\\s*(.+)$"),
    overall_design    = first_val(lines, "^!Series_overall_design\\s*=\\s*(.+)$"),
    data_processing   = collapse_uniq(all_vals(lines, "^!Series_data_processing\\s*=\\s*(.+)$"), sep = "\n\n"),
    platform_ids      = all_vals(lines, "^!Series_platform_id\\s*=\\s*(GPL\\d+)"),
    sample_ids        = all_vals(lines, "^!Series_sample_id\\s*=\\s*(GSM\\d+)"),
    series_organisms  = all_vals(lines, "^!Series_organism\\s*=\\s*(.+)$"),
    sub_date          = first_val(lines, "^!Series_submission_date\\s*=\\s*(.+)$"),
    last_update       = first_val(lines, "^!Series_last_update_date\\s*=\\s*(.+)$"),
    pmids             = all_vals(lines, "^!Series_pubmed_id\\s*=\\s*(\\d+)"),
    contact_name      = first_val(lines, "^!Series_contact_name\\s*=\\s*(.+)$"),
    contact_email     = first_val(lines, "^!Series_contact_email\\s*=\\s*(.+)$"),
    contact_country   = first_val(lines, "^!Series_contact_country\\s*=\\s*(.+)$"),
    contact_org       = first_val(lines, "^!Series_contact_organization\\s*=\\s*(.+)$") %||%
      first_val(lines, "^!Series_contact_institute\\s*=\\s*(.+)$"),
    series_rel        = all_vals(lines, "^!Series_relation\\s*=\\s*(.+)$"),
    supp_files        = all_vals(lines, "^!Series_supplementary_file\\s*=\\s*(.+)$")
  )
}
parse_series_html_fallbacks <- function(html_txt) {
  org  <- str_match(html_txt, "(?is)\\bOrganism\\s+([^\\r\\n<]+)")[,2] %||% NA_character_
  contact_org <- str_match(html_txt, "(?is)\\bOrganization name\\s+([^\\r\\n<]+)")[,2] %||% NA_character_
  contact_dep <- str_match(html_txt, "(?is)\\bDepartment\\s+([^\\r\\n<]+)")[,2]
  list(
    organism_html    = if (!is.na(org)) str_squish(org) else NA_character_,
    contact_org_html = collapse_uniq(na.omit(c(
      if (!is.na(contact_org)) str_squish(contact_org),
      if (!is.na(contact_dep)) str_squish(contact_dep)
    )), sep = " / ")
  )
}
parse_gsm_text_to_row <- function(gsm, txt) {
  lines <- unlist(strsplit(txt, "\n", fixed = TRUE), use.names = FALSE)
  title        <- first_val(lines, "^!Sample_title\\s*=\\s*(.+)$")
  source_name  <- first_val(lines, "^!Sample_source_name(?:_ch1)?\\s*=\\s*(.+)$")
  organisms    <- all_vals(lines, "^!Sample_organism(?:_ch1)?\\s*=\\s*(.+)$")
  molecule     <- all_vals(lines, "^!Sample_molecule(?:_ch1)?\\s*=\\s*(.+)$")
  lib_strategy <- all_vals(lines, "^!Sample_library_strategy\\s*=\\s*(.+)$")
  lib_selection<- all_vals(lines, "^!Sample_library_selection\\s*=\\s*(.+)$")
  lib_source   <- all_vals(lines, "^!Sample_library_source\\s*=\\s*(.+)$")
  instrument   <- all_vals(lines, "^!Sample_instrument_model\\s*=\\s*(.+)$")
  char_lines   <- all_vals(lines, "^!Sample_characteristics(?:_ch1)?\\s*=\\s*(.+)$")
  extract_prot <- all_vals(lines, "^!Sample_extract_protocol(?:_ch1)?\\s*=\\s*(.+)$")
  sample_rel   <- all_vals(lines, "^!Sample_relation\\s*=\\s*(.+)$")
  tibble(
    gsm = gsm,
    title = title %||% NA_character_,
    source_name = source_name %||% NA_character_,
    organisms = collapse_uniq(organisms, sep = " | "),
    molecule  = collapse_uniq(molecule,  sep = " | "),
    lib_strategy = collapse_uniq(lib_strategy, sep = " | "),
    lib_selection= collapse_uniq(lib_selection,sep = " | "),
    lib_source   = collapse_uniq(lib_source,   sep = " | "),
    instrument   = collapse_uniq(instrument,   sep = " | "),
    characteristics = collapse_uniq(char_lines, sep = " | ", max_items = 999),
    extract_protocol = collapse_uniq(extract_prot, sep = "\n\n", max_items = 999),
    rel_text = collapse_uniq(sample_rel, sep = " | ")
  )
}
placenta_keywords <- c("placenta","placental","chorion","chorionic","decidua","trophoblast",
                       "trophoblastic","villous","villi","syncytiotrophoblast","cytotrophoblast")
is_placenta_record <- function(title, source_name, characteristics) {
  txt <- tolower(paste(title %||% "", source_name %||% "", characteristics %||% "", sep = " | "))
  any(stringr::str_detect(txt, stringr::regex(paste(placenta_keywords, collapse="|"), ignore_case = TRUE)))
}
find_gsm_ids_html <- function(gse) {
  txt <- try(http_get_text_cached(series_html_url(gse),
                                  file.path(html_cache, paste0(gse, ".rds")),
                                  tries = series_tries, timeout_secs = series_timeout), silent = TRUE)
  if (inherits(txt, "try-error")) return(character(0))
  gsms <- unique(stringr::str_extract_all(txt, "GSM\\d+")[[1]])
  gsms[!is.na(gsms)]
}
fetch_pmc_map <- function(pmids) {
  pmids <- unique(pmids[grepl("^\\d+$", pmids)])
  if (!length(pmids)) return(tibble(pmid = character(0), pmcid = character(0), doi = character(0)))
  chunks <- split(pmids, ceiling(seq_along(pmids) / 200))
  out <- lapply(chunks, function(ids) {
    resp <- httr::GET("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                      query = list(ids = paste(ids, collapse=","), format = "json"),
                      user_agent("geo-text-patch/1.5"))
    txt <- httr::content(resp, as = "text", encoding = "UTF-8")
    j <- jsonlite::fromJSON(txt)
    if (!is.null(j$records)) {
      tibble(
        pmid  = as.character(j$records$pmid %||% NA_character_),
        pmcid = as.character(j$records$pmcid %||% NA_character_),
        doi   = as.character(j$records$doi   %||% NA_character_)
      )
    } else tibble(pmid = character(0), pmcid = character(0), doi = character(0))
  })
  dplyr::bind_rows(out) |> dplyr::distinct()
}
build_gse_row <- function(gse) {
  logf <- file.path(log_dir, paste0(gse, ".log"))
  cat(sprintf("[%s] start\n", gse), file = logf, append = TRUE)

  s_txt <- http_get_text_cached(series_text_url(gse),
                                file.path(series_cache, paste0(gse, ".rds")),
                                tries = series_tries, timeout_secs = series_timeout)
  s_lines <- unlist(strsplit(s_txt, "\n", fixed = TRUE), use.names = FALSE)
  ser <- parse_series_block(s_lines)

  html_txt <- try(http_get_text_cached(series_html_url(gse),
                                       file.path(html_cache, paste0(gse, ".rds")),
                                       tries = series_tries, timeout_secs = series_timeout), silent = TRUE)
  html_fb <- list(organism_html = NA_character_, contact_org_html = NA_character_)
  if (!inherits(html_txt, "try-error")) html_fb <- parse_series_html_fallbacks(html_txt)

  gsm_ids <- unique(ser$sample_ids)
  if (!length(gsm_ids) || is.na(gsm_ids[1])) gsm_ids <- find_gsm_ids_html(gse)
  if (is.finite(max_gsms_per_gse) && length(gsm_ids) > max_gsms_per_gse)
    gsm_ids <- head(gsm_ids, max_gsms_per_gse)
  sample_total <- length(gsm_ids)
  cat(sprintf("[%s] GSMs: %d\n", gse, sample_total), file = logf, append = TRUE)

  gsm_rows <- list()
  if (length(gsm_ids)) {
    for (gsm in gsm_ids) {
      g_txt <- try(http_get_text_cached(gsm_text_url(gsm),
                                        file.path(gsm_cache, paste0(gsm, ".rds")),
                                        tries = gsm_tries, timeout_secs = gsm_timeout), silent = TRUE)
      if (!inherits(g_txt, "try-error")) gsm_rows[[length(gsm_rows) + 1]] <- parse_gsm_text_to_row(gsm, g_txt)
      if ((length(gsm_rows) %% 10L) == 0L) cat(sprintf("[%s] parsed %d GSM\n", gse, length(gsm_rows)), file = logf, append = TRUE)
      Sys.sleep(runif(1, polite_delay_gsm[1], polite_delay_gsm[2]))
    }
  }

  gsm_df <- if (length(gsm_rows)) bind_rows(gsm_rows) else tibble()

  organisms_gsm       <- if (nrow(gsm_df)) collapse_uniq(gsm_df$organisms, sep = " | ") else NA_character_
  characteristics     <- if (nrow(gsm_df)) collapse_uniq(gsm_df$characteristics, sep = " | ", max_items = 999) else NA_character_
  molecule            <- if (nrow(gsm_df)) collapse_uniq(gsm_df$molecule,  sep = " | ") else NA_character_
  lib_strategy        <- if (nrow(gsm_df)) collapse_uniq(gsm_df$lib_strategy, sep = " | ") else NA_character_
  lib_selection       <- if (nrow(gsm_df)) collapse_uniq(gsm_df$lib_selection,sep = " | ") else NA_character_
  lib_source          <- if (nrow(gsm_df)) collapse_uniq(gsm_df$lib_source,   sep = " | ") else NA_character_
  instrument          <- if (nrow(gsm_df)) collapse_uniq(gsm_df$instrument,   sep = " | ") else NA_character_
  extract_protocol    <- if (nrow(gsm_df)) collapse_uniq(gsm_df$extract_protocol, sep = "\n\n", max_items = 999) else NA_character_

  placenta_n <- if (nrow(gsm_df)) sum(mapply(is_placenta_record, gsm_df$title, gsm_df$source_name, gsm_df$characteristics)) else NA_integer_
  placenta_n <- if (is.na(placenta_n)) sample_total else placenta_n

  ser_rel_text <- collapse_uniq(ser$series_rel, sep = " | ")
  gsm_rel_text <- if (nrow(gsm_df)) collapse_uniq(gsm_df$rel_text, sep = " | ") else NA_character_
  combined_rel <- paste(ser_rel_text %||% "", gsm_rel_text %||% "", sep = " | ")

  sra_srp <- unique(na.omit(stringr::str_extract_all(combined_rel, "SRP\\d+")[[1]]))
  sra_srx <- unique(na.omit(stringr::str_extract_all(combined_rel, "SRX\\d+")[[1]]))
  sra_srr <- unique(na.omit(stringr::str_extract_all(combined_rel, "SRR\\d+")[[1]]))
  prj_ids <- unique(na.omit(stringr::str_extract_all(combined_rel, "PRJ[A-Z]+\\d+")[[1]]))
  bio_ids <- unique(na.omit(stringr::str_extract_all(combined_rel, "(SAMN\\d+|SAMEA\\d+|SAMD\\d+)")[[1]]))
  super_gse <- unique(na.omit(stringr::str_extract_all(ser_rel_text %||% "", "GSE\\d+")[[1]]))

  sra_study_id <- if (length(sra_srp)) paste(sra_srp, collapse = ", ")
  else if (length(sra_srx)) paste(sra_srx, collapse = ", ")
  else if (length(sra_srr)) paste(sra_srr, collapse = ", ")
  else NA_character_
  biosample_biop  <- collapse_uniq(unique(c(bio_ids, prj_ids)), sep = ", ")
  superseries_val <- if (length(super_gse)) paste(super_gse, collapse = ", ") else NA_character_

  file_types <- if (length(ser$supp_files)) {
    exts <- tolower(tools::file_ext(ser$supp_files)); exts <- exts[exts != ""]
    if (length(exts)) paste(unique(exts), collapse = ", ") else NA_character_
  } else NA_character_

  organisms_final    <- organisms_gsm %||% collapse_uniq(ser$series_organisms, sep = " | ") %||% html_fb$organism_html
  contact_org_final  <- ser$contact_org %||% html_fb$contact_org_html
  pmid_primary       <- if (length(ser$pmids)) ser$pmids[1] else NA_character_
  pmids_all          <- if (length(ser$pmids)) paste(unique(ser$pmids), collapse = ", ") else NA_character_

  out <- tibble(
    `GEO Series ID (GSE___)` = gse,
    `Data type` = ser$series_type,
    `SuperSeries, list GEO Series that are part of the SuperSeries` = superseries_val,
    `Sample size (placenta)` = placenta_n,
    `PlTitle` = ser$series_title,
    `Organism` = organisms_final,
    `Characteristics` = characteristics,
    `Extracted molecule` = molecule,
    `Extraction protocol` = extract_protocol,
    `Library Strategy` = lib_strategy,
    `Library source` = lib_source,
    `Library selection` = lib_selection,
    `Instrument model` = instrument,
    `Assay description` = ser$overall_design,
    `Data processing` = ser$data_processing,
    `Platform ID (list)` = collapse_uniq(ser$platform_ids, sep = ", "),
    `SRA Study ID (raw data)` = sra_study_id,
    `BioSample/BioProject ID` = biosample_biop,
    `File types/resources provided (list)` = file_types,
    `Submission date` = ser$sub_date,
    `Last update date` = ser$last_update,
    `Organization name` = contact_org_final,
    `Contact name` = ser$contact_name,
    `E-mail(s)` = ser$contact_email,
    `Country` = ser$contact_country,
    `PMID` = pmid_primary,
    `All PMIDs` = pmids_all,
    `PMCID` = NA_character_,
    `All PMCIDs` = NA_character_,
    `DOI` = NA_character_,
    `All DOIs` = NA_character_
  )
  cat(sprintf("[%s] done\n", gse), file = logf, append = TRUE)
  out
}
chk_xlsx <- file.path(base_dir, "gse_metadata_full_checkpoint.xlsx")
chk_csv  <- file.path(base_dir, "gse_metadata_full_checkpoint_failed.csv")
if (!file.exists(chk_xlsx) && file.exists(file.path(base_dir, "gse_metadata_full.xlsx"))) {
  chk_xlsx <- file.path(base_dir, "gse_metadata_full.xlsx")
}
if (!file.exists(chk_csv) && file.exists(file.path(base_dir, "gse_metadata_full_failed.csv"))) {
  chk_csv <- file.path(base_dir, "gse_metadata_full_failed.csv")
}

if (file.exists(chk_xlsx)) {
  message("Reading Failed sheet from Excel: ", chk_xlsx); flush.console()
  failed <- readxl::read_xlsx(chk_xlsx, sheet = "Failed") |>
    dplyr::filter(!is.na(GEO_ID)) |>
    dplyr::distinct(GEO_ID, .keep_all = TRUE)
} else if (file.exists(chk_csv)) {
  message("Reading failed rows from CSV: ", chk_csv); flush.console()
  failed <- readr::read_csv(chk_csv, show_col_types = FALSE) |>
    dplyr::filter(!is.na(GEO_ID)) |>
    dplyr::distinct(GEO_ID, .keep_all = TRUE)
} else stop("Couldn't find failed list.")

if (!("error" %in% names(failed)) && "Error" %in% names(failed)) {
  failed <- dplyr::rename(failed, error = Error)
}

failed <- failed |>
  dplyr::mutate(was_404 = stringr::str_detect(tolower(coalesce(error, "")), "\\b404\\b"))

failed_non404 <- dplyr::filter(failed, !was_404)
failed_404    <- dplyr::filter(failed,  was_404)

gse_ids <- unique(c(
  failed_non404$GEO_ID,
  failed_404$GEO_ID
))

message("Failed IDs to patch (including 404 salvage if enabled): ", length(gse_ids)); flush.console()
if (!length(gse_ids)) { message("Nothing to patch. Exiting."); flush.console(); quit(save = "no") }
ids_csv_path <- file.path(base_dir, "ids.csv")
ids_csv_env <- Sys.getenv("ids_file", "")
if (nzchar(ids_csv_env)) ids_csv_path <- ids_csv_env
if (!file.exists(ids_csv_path)) stop("ids.csv not found for ordering/filtering.")
ids_df <- read.csv(ids_csv_path, header = FALSE, stringsAsFactors = FALSE)
id_order <- unique(unlist(lapply(ids_df[[1]], extract_all_gse)))
if (!length(id_order)) stop("No GSE IDs found in ids.csv")
probe_ok <- try({
  resp <- httr::RETRY("GET", "https://www.ncbi.nlm.nih.gov/geo/",
                      times = 2, pause_base = 0.5, pause_cap = 2,
                      httr::timeout(3))
  httr::status_code(resp) == 200
}, silent = TRUE)
if (inherits(probe_ok, "try-error") || !isTRUE(probe_ok)) {
  stop("GEO site not responding quickly enough right now; try later when responsive.")
}
if (gse_workers > 1) future::plan(future::multisession, workers = gse_workers) else future::plan(sequential)

pkgs_for_workers <- c(
  "httr","jsonlite","readxl","writexl","readr","dplyr","stringr",
  "tibble","purrr","tools"
)

message(sprintf("Processing %d GSEs with %d worker(s) …", length(gse_ids), gse_workers)); flush.console()

res <- progressr::with_progress({
  p <- progressr::progressor(along = gse_ids)
  furrr::future_map(
    gse_ids,
    function(gse) { on.exit(p(message = gse), add = TRUE); try(build_gse_row(gse), silent = TRUE) },
    .options  = furrr::furrr_options(seed = TRUE, packages = pkgs_for_workers),
    .progress = FALSE
  )
})

ok_idx   <- which(purrr::map_lgl(res, ~ !inherits(.x, "try-error") && is.data.frame(.x)))
fail_idx <- which(purrr::map_lgl(res, ~  inherits(.x, "try-error")))

patch_df <- if (length(ok_idx)) dplyr::bind_rows(res[ok_idx]) else tibble()
# annotate failures; flag which ones originated as FTP 404s
orig_404_ids <- failed_404$GEO_ID
fail_df  <- if (length(fail_idx)) {
  tibble(
    GEO_ID = gse_ids[fail_idx],
    error  = purrr::map_chr(res[fail_idx], function(e) {
      ee <- attr(e, "condition"); if (!is.null(ee)) conditionMessage(ee) else "error"
    }),
    note   = ifelse(gse_ids[fail_idx] %in% orig_404_ids,
                    "original FTP 404; HTTP acc.cgi also failed",
                    NA_character_)
  )
} else tibble(GEO_ID = character(), error = character(), note = character())
if (nrow(patch_df) && "PMID" %in% names(patch_df)) {
  pmids <- unique(na.omit(patch_df$`PMID`))
  if (length(pmids)) {
    message("Resolving PMCID/DOI for ", length(pmids), " PMID(s)…"); flush.console()
    pmc_map <- try(fetch_pmc_map(pmids), silent = TRUE)
    if (!inherits(pmc_map, "try-error") && nrow(pmc_map)) {
      patch_df <- patch_df |>
        left_join(pmc_map, by = c("PMID" = "pmid")) |>
        mutate(`PMCID` = coalesce(`PMCID`, pmcid),
               `All PMCIDs` = coalesce(`All PMCIDs`, pmcid),
               `DOI`   = coalesce(`DOI`, doi),
               `All DOIs` = coalesce(`All DOIs`, doi)) |>
        select(-pmcid, -doi)
    }
  }
}
patch_xlsx <- file.path(base_dir, "gse_metadata_text_patch.xlsx")
patch_csv  <- file.path(base_dir, "gse_metadata_text_patch.csv")
fail_csv   <- file.path(base_dir, "gse_metadata_text_patch_failed.csv")

writexl::write_xlsx(list(Results = sanitize_for_excel(patch_df),
                         Failed  = sanitize_for_excel(fail_df)), patch_xlsx)
readr::write_csv(patch_df, patch_csv)
readr::write_csv(fail_df,  fail_csv)
message("Patch written: ", patch_xlsx); flush.console()
key_col <- "GEO Series ID (GSE___)"
meta_old <- try(readxl::read_xlsx(chk_xlsx, sheet = "Metadata"), silent = TRUE)
fail_old <- try(readxl::read_xlsx(chk_xlsx, sheet = "Failed"),   silent = TRUE)
if (inherits(meta_old, "try-error")) meta_old <- tibble()
if (inherits(fail_old, "try-error")) fail_old <- tibble(GEO_ID = character(), error = character(), note = character())

if (nrow(meta_old) && !(key_col %in% names(meta_old))) stop("Existing Metadata sheet missing key column: ", key_col)

coalesce_cols <- function(old, add) {
  all_cols <- union(names(old), names(add))
  for (nm in setdiff(all_cols, names(old))) old[[nm]] <- NA_character_
  for (nm in setdiff(all_cols, names(add))) add[[nm]] <- NA_character_
  old <- dplyr::select(old, all_of(all_cols)); add <- dplyr::select(add, all_of(all_cols))
  idx <- match(old[[key_col]], add[[key_col]]); fill_cols <- setdiff(all_cols, key_col)
  for (nm in fill_cols) {
    patch_vals <- add[[nm]][idx]; take <- is.na(old[[nm]]) | old[[nm]] == ""
    old[[nm]][take] <- patch_vals[take]
  }
  new_rows <- add[!add[[key_col]] %in% old[[key_col]], , drop = FALSE]
  bind_rows(old, new_rows)
}

meta_new <- if (nrow(meta_old)) coalesce_cols(meta_old, patch_df) else patch_df

# Update Failed sheet: remove newly succeeded, add new fails, dedup
succeeded_ids <- patch_df[[key_col]]
fail_keep <- fail_old |> filter(!GEO_ID %in% succeeded_ids)
fail_merged <- bind_rows(fail_keep, fail_df) |> distinct(GEO_ID, .keep_all = TRUE)

# Reorder + (optionally) drop rows not in ids.csv
if (nrow(meta_new)) {
  if (keep_only_ids_in_csv) meta_new <- meta_new[meta_new[[key_col]] %in% id_order, , drop = FALSE]
  ord <- match(meta_new[[key_col]], id_order)
  meta_new$..ord <- ord
  meta_new <- meta_new[order(meta_new$..ord, na.last = TRUE), , drop = FALSE]
  meta_new$..ord <- NULL
  meta_new <- meta_new |> distinct(`GEO Series ID (GSE___)`, .keep_all = TRUE)
}
if (nrow(fail_merged)) {
  if (keep_only_ids_in_csv) fail_merged <- fail_merged[fail_merged$GEO_ID %in% id_order, , drop = FALSE]
  ordf <- match(fail_merged$GEO_ID, id_order)
  fail_merged$..ord <- ordf
  fail_merged <- fail_merged[order(fail_merged$..ord, na.last = TRUE), , drop = FALSE]
  fail_merged$..ord <- NULL
  fail_merged <- fail_merged |> distinct(GEO_ID, .keep_all = TRUE)
}

merge_out <- file.path(base_dir, "gse_metadata_full_checkpoint_merged.xlsx")
writexl::write_xlsx(list(Metadata = sanitize_for_excel(meta_new),
                         Failed   = sanitize_for_excel(fail_merged)), merge_out)
message("Merged workbook written: ", merge_out); flush.console()
