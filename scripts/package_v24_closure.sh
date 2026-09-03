#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT="${1:-$ROOT/../ukraine_resilience_v2_4_final_closure_v2_4_4.zip}"
if [[ -e "$OUT" ]]; then
  echo "Refusing to overwrite existing package: $OUT" >&2
  exit 2
fi

zip -q -r "$OUT" \
  FINAL_CLOSURE_README_V2_4_4.md \
  LICENSE CITATION.cff requirements.txt requirements-external.txt requirements-weather.txt \
  src scripts config docs \
  data_derived data_external evidence \
  runs/paper_v24_real_01/run_manifest.json \
  runs/paper_v24_real_01/results/tables \
  runs/paper_v24_real_01/results/figures_closure \
  -x '*/__pycache__/*' '*/.pytest_cache/*' '*.pyc'

shasum -a 256 "$OUT" > "$OUT.sha256"
echo "$OUT"
echo "$OUT.sha256"
