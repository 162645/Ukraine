#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [[ $# -gt 0 && ${1:-} != --* ]]; then
  RUN_ID="$1"
  shift
else
  RUN_ID="paper_v25_regional_01"
fi

# Delegate to the exact v2.4 production launcher.  This preserves its
# .env.local/UR_CH_* loading, retry policy, safe resume, Python environment and
# ClickHouse connectivity checks while run_all.py supplies the v2.5 regional
# stage and database-first stage order.
exec ./scripts/run_paper.sh --run-id "$RUN_ID" "$@"
