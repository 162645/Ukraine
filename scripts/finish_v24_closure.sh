#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export MPLBACKEND=Agg
export MPLCONFIGDIR="${MPLCONFIGDIR:-$ROOT/.mplconfig}"
mkdir -p "$MPLCONFIGDIR"

RUN_ID="paper_v24_real_01"
EXECUTE_EXTERNAL=0
while (($#)); do
  case "$1" in
    --run-id) RUN_ID="$2"; shift 2 ;;
    --execute-external) EXECUTE_EXTERNAL=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$RUN_ID" == */* || "$RUN_ID" == *..* ]]; then
  echo "Unsafe RUN_ID: $RUN_ID" >&2
  exit 2
fi
if [[ ! -f "runs/$RUN_ID/results/tables/exp_a_summary.csv" ]]; then
  echo "Existing completed v2.4 run not found: runs/$RUN_ID" >&2
  exit 2
fi

echo "[1/7] Prepare external inputs (this never reruns the core experiment)"
if [[ "$EXECUTE_EXTERNAL" == "1" ]]; then
  python3 scripts/prepare_closure_external_data.py --execute
else
  python3 scripts/prepare_closure_external_data.py --dry-run
fi

echo "[2/7] Archive v2.4.4 corrected public evidence when network is enabled"
if [[ "$EXECUTE_EXTERNAL" == "1" ]]; then
  python3 scripts/archive_public_sources.py \
    --registry config/closure_source_corrections_v2_4_4.csv --overwrite || true
else
  echo "Dry run: public evidence downloads skipped"
fi

echo "[3/7] Verify local evidence archive when available"
python3 scripts/verify_evidence_archive.py --root . || true

echo "[4/7] Audit closure inputs"
python3 scripts/check_external_closure_inputs.py --root . || true

echo "[5/7] Check whether event-specific B2 membership was persisted"
python3 scripts/check_b2_event_stability_estimability.py \
  --run-dir "runs/$RUN_ID" \
  --output "runs/$RUN_ID/results/tables/b2_event_stability_estimability.json"

echo "[6/7] Run frozen incremental sensitivities on existing tables/caches"
PYTHONPATH=src python3 scripts/run_closure_sensitivities.py --run-id "$RUN_ID" || true

echo "[7/7] Render bilingual closure figures"
PYTHONPATH=src python3 scripts/render_closure_figures.py --run-id "$RUN_ID"
PYTHONPATH=src python3 scripts/render_manuscript_figures.py --run-id "$RUN_ID"

echo "Done: runs/$RUN_ID/results/tables/final_closure_sensitivity_status.csv"
echo "No ClickHouse core stage was executed."
