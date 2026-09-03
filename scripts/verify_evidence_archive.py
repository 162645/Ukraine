#!/usr/bin/env python3
"""Verify critical public snapshots and required Telegram Desktop JSON evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    root_default = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(root_default))
    ap.add_argument("--registry", default="config/source_post_registry_v1.csv")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    rows = pd.read_csv(root / args.registry, dtype=str, keep_default_na=False)
    tg_manifest = root / "evidence/telegram_exports/telegram_export_manifest.json"
    telegram = {x["source_id"]: x for x in json.loads(tg_manifest.read_text(encoding="utf-8"))} if tg_manifest.exists() else {}
    checks = []
    for _, row in rows.iterrows():
        if row["archive_required"] != "1":
            continue
        expected_rel = row["expected_snapshot"].strip()
        public_path = root / expected_rel if expected_rel else None
        meta_path = public_path.with_suffix(public_path.suffix + ".meta.json") if public_path else None
        public_ok = False
        if public_path and public_path.is_file() and meta_path and meta_path.is_file():
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            public_ok = sha256(public_path) == str(metadata.get("sha256", "")).lower()
        telegram_required = bool(row["critical"] == "1" and row["telegram_channel"].strip())
        telegram_ok = row["source_id"] in telegram if telegram_required else True
        checks.append({"source_id": row["source_id"], "public_or_dataset_snapshot_ok": public_ok,
                       "telegram_json_required": telegram_required, "telegram_json_ok": telegram_ok,
                       "submission_ready": bool(public_ok and telegram_ok)})
    payload = {"ok": bool(checks and all(x["submission_ready"] for x in checks)), "checks": checks}
    out = root / "evidence/evidence_verification_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
