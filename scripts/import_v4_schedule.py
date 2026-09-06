#!/usr/bin/env python3
"""Export the research-ready v4 workbook to the frozen analysis CSV contract.

The workbook remains the evidence-preserving source.  This exporter adds only
deterministic analysis aliases and never invents queue, city, or execution
precision that is absent from the source rows.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


SHEET = "schedule_verified_merged_v40"
REQUIRED = {
    "merge_group_id", "event_date", "admin1", "admin2", "operator",
    "scope_type", "restriction_type", "queue_count", "queue_ids_merged",
    "planned_start_local", "planned_end_local", "planned_start_utc",
    "planned_end_utc", "actual_start_utc", "actual_end_utc",
    "timezone_name", "status", "confidence", "announced_at_utc", "source_authority",
    "source_url", "source_grade", "affected_admin1", "experiment_use_v40",
    "emergency_override", "attack_recovery_confounded",
    "technical_outage_confounded", "weather_confounded",
}

KNOWN_EVENT_IDS = {
    "2024-06-10": "E2024_0610_PLANNED",
    "2024-06-21": "E2024_0621_PLANNED",
    "2024-06-24": "E2024_0624_PLANNED",
    "2024-07-07": "E2024_0707_PLANNED",
    "2024-07-20": "E2024_0720_PLANNED",
    "2024-07-28": "E2024_0728_PLANNED",
    "2024-08-19": "E2024_0819_PLANNED",
    "2024-08-20": "E2024_0820_PLANNED",
    "2024-08-21": "E2024_0821_PLANNED",
    "2024-12-09": "E2024_1209_PLANNED",
}


def _flag(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0).astype("int8")


def transform(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy().fillna("")
    missing = sorted(REQUIRED - set(d.columns))
    if missing:
        raise ValueError(f"{SHEET} missing required columns: {missing}")
    for col in d.select_dtypes(include="object"):
        d[col] = d[col].astype(str).str.strip()
    d = d[_flag(d["experiment_use_v40"]).eq(1)].copy()

    cancelled = d["restriction_type"].isin({"no_restriction", "cancelled_hourly_window"})
    cancelled |= d["status"].str.lower().str.contains("cancel", regex=False)
    d["schedule_positive"] = (d["restriction_type"].eq("hourly_schedule") & ~cancelled).astype("int8")
    confounds = [
        "emergency_override", "attack_recovery_confounded",
        "technical_outage_confounded", "weather_confounded",
    ]
    d["confound_free"] = pd.concat([_flag(d[c]) for c in confounds], axis=1).max(axis=1).eq(0).astype("int8")

    date = d["event_date"].astype(str)
    d["record_id"] = d["merge_group_id"]
    d["segment_id"] = d["merge_group_id"]
    d["schema_version"] = "v4.0"
    d["record_role"] = "planned_or_final_dispatch"
    d["scope_type_norm"] = d["scope_type"].str.lower()
    d["status_norm"] = d["status"].str.lower()
    d["queue_id"] = d["queue_ids_merged"]
    d["local_start"] = d["planned_start_local"]
    d["local_end"] = d["planned_end_local"]
    d["start_utc"] = d["planned_start_utc"]
    d["end_utc"] = d["planned_end_utc"]
    d["verified_at_utc"] = d["announced_at_utc"]
    planned_start = pd.to_datetime(d["planned_start_utc"], utc=True, errors="coerce")
    planned_end = pd.to_datetime(d["planned_end_utc"], utc=True, errors="coerce")
    d["interval_valid"] = (planned_start.notna() & planned_end.notna() & planned_end.gt(planned_start)).astype("int8")
    d["analysis_eligible"] = (
        _flag(d["experiment_use_v40"]).eq(1) & d["interval_valid"].eq(1)
    ).astype("int8")
    d["publication_eligible"] = (
        d["analysis_eligible"].eq(1) & d["confound_free"].eq(1)
    ).astype("int8")
    d["final_version"] = 1
    d["event_id"] = [KNOWN_EVENT_IDS.get(x, f"E{x.replace('-', '')}_V4") for x in date]
    d["independence_cluster"] = "V4_DATE_" + date.str.replace("-", "", regex=False)
    d["geo_scope_precision"] = "L3_national"
    d.loc[d["scope_type"].eq("oblast"), "geo_scope_precision"] = "L2_admin1"
    d.loc[d["scope_type"].eq("operator_service_area"), "geo_scope_precision"] = "L2_operator_admin1_proxy"
    d.loc[d["admin2"].ne(""), "geo_scope_precision"] = "L2_admin2_named_ip_city_unresolved"

    if d["segment_id"].eq("").any() or d["segment_id"].duplicated().any():
        raise ValueError("v4 merged rows require unique, non-empty merge_group_id values")
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=Path("config/planned_outage_schedule_v4_0.csv"))
    args = ap.parse_args()
    raw = pd.read_excel(args.input, sheet_name=SHEET, dtype=str, keep_default_na=False)
    out = transform(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"wrote {len(out)} rows and {len(out.columns)} columns to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
