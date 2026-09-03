#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Tries HTTP and native ClickHouse protocols, never writes to the database,
# and reports table metadata without printing credentials.
python3 scripts/inspect_clickhouse.py "$@"
