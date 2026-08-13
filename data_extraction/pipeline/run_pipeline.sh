#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pipeline_dir="$root_dir/pipeline"
cd "$root_dir"

if [ -f "$root_dir/.env" ]; then
  set -a
  source "$root_dir/.env"
  set +a
fi

if [ -x "$root_dir/.venv/bin/python" ]; then
  python_bin="$root_dir/.venv/bin/python"
else
  python_bin="${python_bin:-python3}"
fi

export geo_r_workers="${geo_r_workers:-1}"
export project_root="$root_dir"
export ids_file="${ids_file:-$root_dir/ids.csv}"
export pipeline_excel_file="${pipeline_excel_file:-$root_dir/geo_master_access.xlsx}"

run_r() {
  echo
  echo "==> $1"
  Rscript "$pipeline_dir/$1"
}

run_py() {
  echo
  echo "==> $1"
  local script_name="$1"
  shift
  "$python_bin" "$pipeline_dir/$script_name" "$@"
}

echo "Project root: $root_dir"
echo "Python: $python_bin"
echo "R workers: $geo_r_workers"

run_r "01_extract_geo_metadata.R"
run_r "02_repair_geo_metadata.R"

if [ -n "${geo_metadata_input:-}" ] && [ -f "$geo_metadata_input" ]; then
  export geo_metadata_input
elif [ -f "$root_dir/gse_metadata_full_checkpoint_merged.xlsx" ]; then
  export geo_metadata_input="$root_dir/gse_metadata_full_checkpoint_merged.xlsx"
elif [ -f "$root_dir/gse_metadata_full_checkpoint.xlsx" ]; then
  export geo_metadata_input="$root_dir/gse_metadata_full_checkpoint.xlsx"
elif [ -f "$root_dir/gse_metadata_full.xlsx" ]; then
  export geo_metadata_input="$root_dir/gse_metadata_full.xlsx"
else
  echo "No GEO metadata workbook found after R extraction." >&2
  exit 1
fi

run_py "03_annotate_open_access.py"
run_py "04_download_papers.py"
run_py "05_download_supplements.py"
run_py "07_validate_supplements.py" --root "$root_dir"
run_py "06_chunk_papers.py"
run_py "08_validate_papers.py" --root "$root_dir"
run_py "09_run_gemini_extraction.py"
run_py "11_build_sendable_workbook.py" \
  --metadata "$geo_metadata_input" \
  --ai "$root_dir/ai_annotated.xlsx" \
  --output "$root_dir/geo_metadata_with_ai_sendable.xlsx"

echo
echo "Pipeline complete."
echo "Raw AI workbook: $root_dir/ai_annotated.xlsx"
echo "Sendable workbook: $root_dir/geo_metadata_with_ai_sendable.xlsx"
