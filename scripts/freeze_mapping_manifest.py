#!/usr/bin/env python3
"""Freeze the IP->ASN/Country/Admin1 mapping snapshot used by the paper run.

This script reads the latest mapping row per IP at a chosen UTC cutoff, records
its row count and a deterministic ClickHouse checksum, then writes a local
SHA-256 contract into config/mapping_manifest_v2.json.  It never exports the
mapping rows or database credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uresil.config import load_config
from uresil.db import CHClient
from uresil.mapping_snapshot import (build_frozen_manifest, query_mapping_snapshot,
                                     write_frozen_manifest)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--cutoff-utc", default=None,
                    help="UTC cutoff, e.g. 2025-02-01 00:00:00; default=max(updated_at)")
    ap.add_argument("--write", action="store_true",
                    help="Write the manifest. Without this flag, print a dry-run payload.")
    args = ap.parse_args()

    cfg = load_config(args.config, run_id="mapping_freeze_check", mode="real")
    table = cfg.table("mapping")
    with CHClient(cfg) as ch:
        snap = query_mapping_snapshot(ch, table, args.cutoff_utc)

    path = cfg.resource_path("mapping_manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if args.write:
        write_frozen_manifest(path, payload, table=table, cutoff=snap["cutoff"],
                              row_count=snap["row_count"], checksum=snap["content_checksum_uint64"])
        print(f"Wrote {path}")
    else:
        text = json.dumps(
            build_frozen_manifest(payload, table=table, cutoff=snap["cutoff"],
                                  row_count=snap["row_count"],
                                  checksum=snap["content_checksum_uint64"]),
            ensure_ascii=False, indent=2
        ) + "\n"
        print(text)
        print("Dry run only. Re-run with --write after reviewing the cutoff and counts.")


if __name__ == "__main__":
    main()
