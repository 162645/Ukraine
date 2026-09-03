#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${1:-$ROOT/../ukraine_resilience_v2_4_manuscript_figures_v2_4_4.zip}"
if [[ -e "$OUT" ]]; then
  echo "Refusing to overwrite existing package: $OUT" >&2
  exit 2
fi

zip -q -r "$OUT" \
  MANUSCRIPT_FIGURE_README_V2_4_4.md \
  docs/MANUSCRIPT_FIGURE_PLAN_V2_4_4.md \
  scripts/render_manuscript_figures.py \
  src config requirements.txt \
  runs/paper_v24_real_01/run_manifest.json \
  runs/paper_v24_real_01/results/tables \
  runs/paper_v24_real_01/results/figures_manuscript \
  -x '*/__pycache__/*' '*.pyc'

shasum -a 256 "$OUT" > "$OUT.sha256"
echo "$OUT"
echo "$OUT.sha256"
