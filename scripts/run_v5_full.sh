#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_ID="${1:-v5_simple_calibration_01}"
if [[ -f .env.local ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env.local
  set +a
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export UR_CH_REQUIRE_MEMORY_GUARD="${UR_CH_REQUIRE_MEMORY_GUARD:-1}"
python run_all.py --mode real --run-id "$RUN_ID" --stage all --resume
