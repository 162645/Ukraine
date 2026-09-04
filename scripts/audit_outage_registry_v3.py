#!/usr/bin/env python3
"""Validate the v3.0 outage registry before any ClickHouse-backed run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REQUIRED = {
    "record_id", "event_date", "admin1", "operator", "scope_type",
    "planned_start_local", "planned_end_local", "planned_start_utc",
    "planned_end_utc", "timezone_name", "status_norm", "confidence",
    "impact_note", "source_url", "analysis_eligible", "schema_version",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="config/planned_outage_schedule_v3_0.csv")
    ap.add_argument("--output", default="analysis_outputs/outage_registry_v3_audit.json")
    args = ap.parse_args()
    path = root / args.input
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    errors: list[str] = []
    missing = sorted(REQUIRED - set(df.columns))
    if missing:
        errors.append(f"missing columns: {missing}")
    for c in ("planned_start_utc", "planned_end_utc"):
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
            if df[c].isna().any():
                errors.append(f"invalid {c}: {int(df[c].isna().sum())}")
    if {"planned_start_utc", "planned_end_utc"}.issubset(df):
        if (df["planned_end_utc"] <= df["planned_start_utc"]).any():
            errors.append("non-positive planned interval")
    if "record_id" in df and df["record_id"].duplicated().any():
        errors.append("duplicate record_id")
    if "timezone_name" in df and (~df["timezone_name"].eq("Europe/Kyiv")).any():
        errors.append("timezone_name must be Europe/Kyiv")
    if "source_url" in df and (~df["source_url"].str.startswith("https://")).any():
        errors.append("non-HTTPS source URL")
    if "schema_version" in df and (~df["schema_version"].str.startswith("v3.0")).any():
        errors.append("non-v3.0 schema row")
    result = {
        "input": str(path),
        "rows": int(len(df)),
        "columns": list(df.columns),
        "unique_admin1": int(df["admin1"].nunique()) if "admin1" in df else 0,
        "unique_dates": int(df["event_date"].nunique()) if "event_date" in df else 0,
        "status_counts": df["status_norm"].value_counts().to_dict() if "status_norm" in df else {},
        "scope_counts": df["scope_type"].value_counts().to_dict() if "scope_type" in df else {},
        "analysis_eligible_rows": int(pd.to_numeric(df["analysis_eligible"], errors="coerce").eq(1).sum()) if "analysis_eligible" in df else 0,
        "errors": errors,
        "ok": not errors,
    }
    out = root / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
