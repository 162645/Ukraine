#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="${1:-v4_regional_operator_isp_20260905}"
cd "$ROOT_DIR"

# Internal ClickHouse traffic must not be sent to a workstation proxy.
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
export NO_PROXY="10.112.136.29,127.0.0.1,localhost"
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-8}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-8}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-8}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-8}"

available_kib="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
if [[ -z "$available_kib" || "$available_kib" -lt 20971520 ]]; then
  echo "Refusing to start: less than 20 GiB host memory is available." >&2
  exit 2
fi

mkdir -p "runs/$RUN_ID"
exec 9>"runs/$RUN_ID/.full_run.lock"
if ! flock -n 9; then
  echo "Run $RUN_ID is already active." >&2
  exit 3
fi

if [[ -s "runs/$RUN_ID/manifest.json" ]]; then
  exec python -u run_all.py \
    --config config/experiment_v2.local.yaml \
    --run-id "$RUN_ID" \
    --mode real \
    --stage all \
    --resume
fi

exec python -u run_all.py \
  --config config/experiment_v2.local.yaml \
  --run-id "$RUN_ID" \
  --mode real \
  --stage all
