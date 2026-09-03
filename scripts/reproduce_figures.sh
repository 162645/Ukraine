#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
: "${RUN_ID:?Set RUN_ID to the completed real run identifier}"
python3 run_all.py --mode real --run-id "$RUN_ID" --stage figures validate --resume --force
