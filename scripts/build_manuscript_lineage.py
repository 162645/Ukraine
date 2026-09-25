#!/usr/bin/env python3
"""Build the single auditable data lineage used by the manuscript.

This program does not draw figures and does not fit a new model.  It closes
the lineage between the verified outage schedule, the frozen calibration
events, the event-level response cache, and the frozen manuscript result
tables.  Scientific inputs are read-only; every generated artifact is written
below ``--output``.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


FILTER_COLUMNS = (
    "analysis_eligible",
    "schedule_positive",
    "confound_free",
    "interval_valid",
)


@dataclass(frozen=True)
class Inputs:
    schedule: Path
    calibration_events: Path
    event_cache: Path
    cycle_quality: Path
    targets: Path
    master: Path
    activity: Path
    h1_script: Path
    activity_script: Path
    baseline_script: Path
    calibration_script: Path
    power_script: Path
    validation_script: Path
    table1: Path
    table2: Path
    auc: Path
    releases: Path
    gee: Path


def input_paths(root: Path) -> Inputs:
    return Inputs(
        schedule=root / "config/planned_outage_schedule_v4_0.csv",
        calibration_events=root / "runs/doc_complete_20260908/results/tables/calibration_events.csv",
        event_cache=root / "runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet",
        cycle_quality=root / "runs/doc_complete_20260908/data_derived/cycle_quality.parquet",
        targets=root / "runs/paper_final_v2_episode_fix_20260910/data_derived/target_ip_universe.parquet",
        master=root / "power_availability_infrastructure_v1/data/ip_power_availability_master.parquet",
        activity=root / "runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity/tables/ip_activity.csv",
        h1_script=root / "src/uresil/h1_endpoint_heterogeneity.py",
        activity_script=root / "src/uresil/activity_stage.py",
        baseline_script=root / "src/uresil/baseline_pool.py",
        calibration_script=root / "src/uresil/simple_calibration.py",
        power_script=root / "power_availability_infrastructure_v1/scripts/power_availability_infrastructure_v1.py",
        validation_script=root / "power_availability_infrastructure_final_validation_v2/scripts/final_validation_v2.py",
        table1=root / "paper_current_final_v2/tables/Table_1_dataset_summary.csv",
        table2=root / "paper_current_final_v2/tables/Table_2_main_results.csv",
        auc=root / "power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv",
        releases=root / "power_availability_infrastructure_final_validation_v2/tables/TABLE_F10_itdk_release_final.csv",
        gee=root / "power_availability_infrastructure_v1/tables/TABLE_04_primary_regression.csv",
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "UNKNOWN"


def require(paths: Iterable[Path]) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError("Required frozen inputs are missing:\n" + "\n".join(missing))


def _as_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def load_schedule(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(path, low_memory=False)
    for col in FILTER_COLUMNS:
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0).astype("int8")
    raw["schedule_start_utc"] = _as_utc(raw["start_utc"])
    raw["schedule_end_utc"] = _as_utc(raw["end_utc"])
    raw["schedule_utc_date"] = raw["schedule_start_utc"].dt.date
    eligible = raw.loc[
        raw[list(FILTER_COLUMNS)].eq(1).all(axis=1)
        & raw["schedule_start_utc"].notna()
        & raw["schedule_end_utc"].notna()
        & raw["event_id"].notna()
    ].copy()
    return raw, eligible


def load_cache_and_calibration(inputs: Inputs) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    columns = [
        "dst_ip", "prefix24", "target_admin1", "event_id",
        "x_normal", "x_outage", "n_normal", "n_outage",
    ]
    cache = pd.read_parquet(inputs.event_cache, columns=columns)
    cache = cache[cache["event_id"].notna()].copy()
    before = len(cache)
    cache = cache.drop_duplicates(["dst_ip", "event_id"])
    duplicate_rows_removed = before - len(cache)
    for col in ["x_normal", "x_outage", "n_normal", "n_outage"]:
        cache[col] = pd.to_numeric(cache[col], errors="coerce").fillna(0.0)

    calibration = pd.read_csv(inputs.calibration_events, low_memory=False)
    calibration["calibration_start_utc"] = _as_utc(calibration["start_utc"])
    calibration["calibration_end_utc"] = _as_utc(calibration["end_utc"])
    calibration = calibration.drop_duplicates("event_id")
    cache_ids = set(cache["event_id"].astype(str))
    calibration = calibration[calibration["event_id"].astype(str).isin(cache_ids)].copy()
    return cache, calibration, duplicate_rows_removed


def _join_unique(values: Iterable[object]) -> str:
    return "|".join(sorted({str(v) for v in values if pd.notna(v) and str(v) != ""}))


def _union_hours(intervals: Iterable[tuple[pd.Timestamp, pd.Timestamp]]) -> float:
    valid = sorted((a, b) for a, b in intervals if pd.notna(a) and pd.notna(b) and b > a)
    if not valid:
        return 0.0
    merged: list[list[pd.Timestamp]] = [[valid[0][0], valid[0][1]]]
    for start, end in valid[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum((b - a).total_seconds() for a, b in merged) / 3600.0


def build_crosswalk(
    raw_schedule: pd.DataFrame,
    eligible_schedule: pd.DataFrame,
    cache: pd.DataFrame,
    calibration: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cache_summary = (
        cache.groupby(["event_id", "target_admin1"], as_index=False)
        .agg(
            analysis_ip_n=("dst_ip", "nunique"),
            power_responsive_sum=("x_outage", "sum"),
            normal_responsive_sum=("x_normal", "sum"),
            power_valid_cycle_n=("n_outage", "max"),
            normal_valid_cycle_n=("n_normal", "max"),
        )
        .rename(columns={"event_id": "cache_event_id", "target_admin1": "oblast"})
    )
    cal_cols = [
        "event_id", "geo_name", "event_date", "calibration_start_utc",
        "calibration_end_utc", "segment_n", "source_record_n", "evidence_tier",
        "use_main", "use_augmented",
    ]
    cal = calibration[[c for c in cal_cols if c in calibration.columns]].rename(
        columns={"event_id": "cache_event_id", "geo_name": "calibration_oblast"}
    )
    opportunities = cache_summary.merge(cal, on="cache_event_id", how="left", validate="one_to_one")

    rows: list[dict[str, object]] = []
    for r in opportunities.itertuples(index=False):
        q = eligible_schedule.loc[
            (eligible_schedule["admin1"].astype(str).eq(str(r.oblast))
             | eligible_schedule["admin1"].astype(str).eq("ALL"))
            & (eligible_schedule["schedule_start_utc"] < r.calibration_end_utc)
            & (eligible_schedule["schedule_end_utc"] > r.calibration_start_utc)
        ].copy()
        event_ids = sorted(q["event_id"].dropna().astype(str).unique())
        status = (
            "EXACT_ONE_SCHEDULE_EVENT"
            if len(event_ids) == 1
            else ("UNMAPPED" if not event_ids else "AMBIGUOUS_MULTIPLE_SCHEDULE_EVENTS")
        )
        schedule_event_id = event_ids[0] if len(event_ids) == 1 else _join_unique(event_ids)
        overlap_intervals = []
        for z in q.itertuples(index=False):
            start = max(z.schedule_start_utc, r.calibration_start_utc)
            end = min(z.schedule_end_utc, r.calibration_end_utc)
            if end > start:
                overlap_intervals.append((start, end))
        rows.append({
            "analysis_event_id": f"PWR::{r.cache_event_id}",
            "schedule_event_id": schedule_event_id,
            "cache_event_id": r.cache_event_id,
            "event_date": r.event_date,
            "oblast": r.oblast,
            "calibration_oblast": r.calibration_oblast,
            "calibration_start_utc": r.calibration_start_utc,
            "calibration_end_utc": r.calibration_end_utc,
            "schedule_admin1": _join_unique(q.get("admin1", [])),
            "schedule_scope": _join_unique(q.get("scope_type_norm", q.get("scope_type", []))),
            "schedule_start_utc": q["schedule_start_utc"].min() if len(q) else pd.NaT,
            "schedule_end_utc": q["schedule_end_utc"].max() if len(q) else pd.NaT,
            "schedule_segment_row_n": int(len(q)),
            "schedule_record_n": int(q["record_id"].nunique()) if len(q) and "record_id" in q else int(len(q)),
            "schedule_source_authority": _join_unique(q.get("source_authority", [])),
            "schedule_source_url_n": int(q["source_url"].nunique()) if len(q) and "source_url" in q else 0,
            "temporal_overlap_hours_union": _union_hours(overlap_intervals),
            "mapping_status": status,
            "included_power_main": status == "EXACT_ONE_SCHEDULE_EVENT",
            "analysis_ip_n": int(r.analysis_ip_n),
            "power_valid_cycle_n": int(r.power_valid_cycle_n),
            "normal_valid_cycle_n": int(r.normal_valid_cycle_n),
            "power_responsive_sum": float(r.power_responsive_sum),
            "normal_responsive_sum": float(r.normal_responsive_sum),
            "calibration_segment_n": getattr(r, "segment_n", np.nan),
            "calibration_source_record_n": getattr(r, "source_record_n", np.nan),
            "evidence_tier": getattr(r, "evidence_tier", ""),
            "use_main": getattr(r, "use_main", np.nan),
            "use_augmented": getattr(r, "use_augmented", np.nan),
        })
    crosswalk = pd.DataFrame(rows).sort_values(["event_date", "oblast", "cache_event_id"])

    # Reproduce the legacy audit's mixed filtering/grouping semantics without
    # using them as the canonical cohort.  The old code first selected eligible
    # event IDs, then grouped *all raw rows* belonging to those IDs by
    # (event_id, admin1).  That is intentionally different from row-level
    # eligibility and is retained only to explain the historical 263/108 counts.
    ok_ids = set(eligible_schedule["event_id"].astype(str))
    cache_date = pd.to_datetime(
        cache["event_id"].astype(str).str.extract(r"(\d{8})")[0],
        format="%Y%m%d",
        errors="coerce",
    ).dt.date
    cache_keys = set(zip(cache["target_admin1"].astype(str), cache_date))
    legacy_groups = []
    raw_for_ids = raw_schedule[raw_schedule["event_id"].astype(str).isin(ok_ids)].copy()
    if "schedule_utc_date" not in raw_for_ids:
        raw_for_ids["schedule_utc_date"] = _as_utc(raw_for_ids["schedule_start_utc"]).dt.date
    for (event_id, admin1), g in raw_for_ids.groupby(["event_id", "admin1"], dropna=False):
        pairs = {(str(a), d) for a, d in zip(g["admin1"].astype(str), g["schedule_utc_date"])}
        matched = any((a, d) in cache_keys or ("ALL", d) in cache_keys for a, d in pairs)
        legacy_groups.append((str(event_id), str(admin1), len(g), int(matched)))
    legacy = pd.DataFrame(
        legacy_groups,
        columns=["event_id", "admin1", "raw_row_n_for_eligible_event_id", "legacy_date_matched"],
    )
    return crosswalk, legacy


def current_date_matched_ids(schedule: pd.DataFrame, cache: pd.DataFrame) -> set[str]:
    state_dates = set(zip(
        schedule.loc[schedule["admin1"].astype(str).ne("ALL"), "admin1"].astype(str),
        schedule.loc[schedule["admin1"].astype(str).ne("ALL"), "schedule_utc_date"],
    ))
    all_dates = set(schedule.loc[schedule["admin1"].astype(str).eq("ALL"), "schedule_utc_date"])
    parsed = pd.to_datetime(
        cache["event_id"].astype(str).str.extract(r"(\d{8})")[0], format="%Y%m%d", errors="coerce"
    ).dt.date
    keep = [((str(a), d) in state_dates) or (d in all_dates) for a, d in zip(cache["target_admin1"], parsed)]
    return set(cache.loc[keep, "event_id"].astype(str))


def count_semantics(
    raw_schedule: pd.DataFrame,
    eligible_schedule: pd.DataFrame,
    legacy: pd.DataFrame,
    crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    represented = crosswalk[crosswalk["mapping_status"].eq("EXACT_ONE_SCHEDULE_EVENT")]
    rows = [
        ("schedule_raw_row_n", len(raw_schedule), "Raw rows in planned_outage_schedule_v4_0.csv"),
        ("schedule_eligible_row_n", len(eligible_schedule), "Rows passing all four row-level inclusion flags"),
        ("schedule_unique_event_id_n", eligible_schedule["event_id"].nunique(), "Unique verified schedule event IDs among eligible rows"),
        ("schedule_event_admin1_date_n", len(eligible_schedule[["event_id", "admin1", "schedule_utc_date"]].drop_duplicates()), "Eligible schedule event × admin1 × UTC-start-date records"),
        ("legacy_schedule_event_admin1_n", len(legacy), "Legacy audit grouping; retained only to explain older counts"),
        ("legacy_date_matched_event_admin1_n", int(legacy["legacy_date_matched"].sum()), "Legacy state/date match count; retained only to explain the historical audit and not used as the manuscript cohort"),
        ("analysis_cache_opportunity_n", len(crosswalk), "Frozen cache event × oblast analysis opportunities"),
        ("analysis_unique_cache_event_id_n", crosswalk["cache_event_id"].nunique(), "Unique cache IDs; not independent verified schedule events"),
        ("analysis_represented_schedule_event_id_n", represented["schedule_event_id"].nunique(), "Verified schedule event IDs actually represented in the frozen main cohort"),
        ("analysis_event_oblast_n", len(represented), "Canonical manuscript Power analysis opportunities"),
        ("analysis_oblast_n", represented["oblast"].nunique(), "Oblasts represented in the canonical Power cohort"),
        ("unmapped_cache_opportunity_n", int(crosswalk["mapping_status"].eq("UNMAPPED").sum()), "Cache opportunities without an overlapping eligible schedule event"),
        ("ambiguous_cache_opportunity_n", int(crosswalk["mapping_status"].str.startswith("AMBIGUOUS").sum()), "Cache opportunities overlapping multiple schedule event IDs"),
    ]
    return pd.DataFrame(rows, columns=["count_name", "value", "definition"])


def rebuild_master_identity(inputs: Inputs, cache: pd.DataFrame, exact_ids: set[str]) -> pd.DataFrame:
    ev = cache[cache["event_id"].astype(str).isin(exact_ids)].copy()
    den = (
        ev.groupby(["target_admin1", "event_id"], as_index=False)
        .agg(power_valid_event=("n_outage", "max"), normal_valid_event=("n_normal", "max"))
    )
    state_den = den.groupby("target_admin1").agg(
        power_valid_probe_count=("power_valid_event", "sum"),
        normal_valid_probe_count=("normal_valid_event", "sum"),
    ).reset_index().rename(columns={"target_admin1": "oblast"})
    agg = ev.groupby("dst_ip", as_index=False).agg(
        power_responsive_count=("x_outage", "sum"),
        normal_responsive_count=("x_normal", "sum"),
    ).rename(columns={"dst_ip": "ip"})

    target = pd.read_parquet(
        inputs.targets,
        columns=["dst_ip", "prefix24", "target_country", "target_admin1", "valid_target_admin1"],
    )
    target = target[
        target["target_country"].astype(str).eq("Ukraine")
        & pd.to_numeric(target["valid_target_admin1"], errors="coerce").fillna(0).eq(1)
    ].rename(columns={"dst_ip": "ip", "target_admin1": "oblast"})
    target = target[["ip", "prefix24", "oblast"]].drop_duplicates("ip")
    rebuilt = target.merge(state_den, on="oblast", how="left").merge(agg, on="ip", how="left")
    for c in ["power_valid_probe_count", "normal_valid_probe_count", "power_responsive_count", "normal_responsive_count"]:
        rebuilt[c] = pd.to_numeric(rebuilt[c], errors="coerce").fillna(0.0)
    rebuilt = rebuilt[rebuilt["power_valid_probe_count"].gt(0)].copy()
    rebuilt["power_availability"] = rebuilt["power_responsive_count"].div(rebuilt["power_valid_probe_count"].replace(0, np.nan))
    rebuilt["normal_availability"] = rebuilt["normal_responsive_count"].div(rebuilt["normal_valid_probe_count"].replace(0, np.nan))

    frozen = pd.read_parquet(
        inputs.master,
        columns=[
            "ip", "power_valid_probe_count", "normal_valid_probe_count",
            "power_responsive_count", "normal_responsive_count",
            "power_availability", "normal_availability",
        ],
    )
    joined = frozen.merge(rebuilt, on="ip", how="outer", suffixes=("_frozen", "_rebuilt"), indicator=True)
    rows = [{
        "field": "ip_set",
        "frozen_row_n": len(frozen),
        "rebuilt_row_n": len(rebuilt),
        "mismatch_n": int(joined["_merge"].ne("both").sum()),
        "max_abs_difference": np.nan,
        "status": "PASS" if joined["_merge"].eq("both").all() else "FAIL",
    }]
    both = joined[joined["_merge"].eq("both")]
    for col in [
        "power_valid_probe_count", "normal_valid_probe_count",
        "power_responsive_count", "normal_responsive_count",
        "power_availability", "normal_availability",
    ]:
        a = pd.to_numeric(both[f"{col}_frozen"], errors="coerce")
        b = pd.to_numeric(both[f"{col}_rebuilt"], errors="coerce")
        same = (a.isna() & b.isna()) | np.isclose(a.fillna(0), b.fillna(0), rtol=0, atol=1e-12)
        diff = (a - b).abs()
        rows.append({
            "field": col,
            "frozen_row_n": len(frozen),
            "rebuilt_row_n": len(rebuilt),
            "mismatch_n": int((~same).sum()),
            "max_abs_difference": float(diff.max()) if diff.notna().any() else 0.0,
            "status": "PASS" if same.all() else "FAIL",
        })
    return pd.DataFrame(rows)


def variable_dictionary(inputs: Inputs) -> pd.DataFrame:
    rows = [
        {
            "manuscript_variable": "power_window_response_rate",
            "manuscript_name_zh": "停电窗口响应率",
            "internal_columns": "power_availability; x_outage; n_outage",
            "numerator": "Eligible outage-window cycles in which the IP returned an ICMP response",
            "denominator": "Valid complete outage-window opportunities for the IP's mapped oblast",
            "time_window": "Verified schedule-overlapping calibration window",
            "analysis_unit": "IP aggregated over included cache-event × oblast opportunities",
            "missingness_rule": "No response row in a valid complete opportunity contributes zero; incomplete acquisition cycles are excluded before denominator construction",
            "source_data": str(inputs.event_cache),
            "source_code": str(inputs.power_script),
        },
        {
            "manuscript_variable": "time_stratified_normal_response_rate",
            "manuscript_name_zh": "时间分层正常参照响应率",
            "internal_columns": "normal_availability; x_normal; n_normal",
            "numerator": "Responses in frozen normal referent opportunities",
            "denominator": "Valid frozen normal referent opportunities",
            "time_window": "Same year/month/weekday/two-hour slot rule; counts are inherited from the frozen event-level cache",
            "analysis_unit": "IP aggregated over included cache-event × oblast opportunities",
            "missingness_rule": "Same valid-opportunity rule as power-window response rate; the cache does not retain raw per-probe paired timestamps",
            "source_data": str(inputs.event_cache),
            "source_code": f"{inputs.calibration_script}; {inputs.validation_script}",
        },
        {
            "manuscript_variable": "clean_baseline_response_rate",
            "manuscript_name_zh": "清洁基线响应率",
            "internal_columns": "activity_raw; x_normal; n_normal",
            "numerator": "Complete clean baseline cycles in which the IP returned a response",
            "denominator": "All eligible complete baseline cycles after registered outage and attack-window exclusions",
            "time_window": "Full clean baseline period, not event-specific matched controls",
            "analysis_unit": "IP",
            "missingness_rule": "IP absent from a complete full-scan cycle is non-response; incomplete cycles never enter the denominator",
            "source_data": str(inputs.activity),
            "source_code": f"{inputs.activity_script}; {inputs.baseline_script}",
        },
        {
            "manuscript_variable": "event_window_reachability_drop",
            "manuscript_name_zh": "事件期可达率下降",
            "internal_columns": "reach_drop; pre_attack_reach; attack_reach",
            "numerator": "pre_attack_reach - attack_reach",
            "denominator": "Dimensionless difference between two response proportions",
            "time_window": "One frozen attack event's pre-event and attack windows",
            "analysis_unit": "IP × attack event",
            "missingness_rule": "Computed only when the event outcome is valid; signed values are retained",
            "source_data": "Frozen H1 event outcomes",
            "source_code": str(inputs.h1_script),
        },
    ]
    return pd.DataFrame(rows)


def result_manifest(
    inputs: Inputs,
    eligible_schedule: pd.DataFrame,
    crosswalk: pd.DataFrame,
    code_commit: str,
) -> pd.DataFrame:
    master = pd.read_parquet(
        inputs.master,
        columns=["ip", "oblast", "power_valid_probe_count", "normal_valid_probe_count", "itdk_202408_T"],
    )
    rows: list[dict[str, object]] = []

    def add(name: str, value: object, sample: str, source_file: Path, source_column: str,
            script: Path, value_scale: str = "count", note: str = "") -> None:
        rows.append({
            "manuscript_name": name,
            "value": value,
            "value_scale": value_scale,
            "analysis_sample": sample,
            "source_file": str(source_file),
            "source_column_or_rule": source_column,
            "generating_script": str(script),
            "code_git_commit": code_commit,
            "source_sha256": sha256(source_file),
            "note": note,
        })

    n = len(master)
    positive = int(pd.to_numeric(master["itdk_202408_T"], errors="coerce").fillna(0).sum())
    sample = "Frozen mapped Power master with positive power-opportunity denominator"
    add("Analyzed IPs", n, sample, inputs.master, "row count", inputs.power_script)
    add("Analyzed oblasts", int(master["oblast"].nunique()), sample, inputs.master, "uniqExact(oblast)", inputs.power_script)
    add("Power valid probe opportunities", int(master["power_valid_probe_count"].sum()), sample, inputs.master, "sum(power_valid_probe_count)", inputs.power_script)
    add("Normal valid probe opportunities", int(master["normal_valid_probe_count"].sum()), sample, inputs.master, "sum(normal_valid_probe_count)", inputs.power_script)
    add("ITDK 2024-08 transit-evidence positives", positive, sample, inputs.master, "sum(itdk_202408_T)", inputs.power_script)
    add("ITDK 2024-08 transit-evidence prevalence", positive / n, sample, inputs.master, "mean(itdk_202408_T)", inputs.power_script, "proportion")
    add("Verified schedule event IDs in eligible schedule universe", int(eligible_schedule["event_id"].nunique()), "Eligible schedule registry", inputs.schedule, "nunique(event_id) after four row-level flags", Path(__file__))
    add("Power analysis event-oblast opportunities", int(crosswalk["included_power_main"].sum()), sample, inputs.event_cache, "canonical temporal-overlap crosswalk rows", Path(__file__))

    if inputs.auc.exists():
        auc = pd.read_csv(inputs.auc)
        nation = auc[auc["scope"].astype(str).eq("NATIONWIDE")]
        for score, label in [("power_availability", "Power"), ("normal_availability", "Normal")]:
            q = nation[nation["score"].astype(str).eq(score)]
            if len(q):
                r = q.iloc[0]
                add(f"{label} ROC-AUC", float(r["AUC"]), sample, inputs.auc, f"scope=NATIONWIDE, score={score}, AUC", inputs.validation_script, "ROC-AUC", f"95% CI [{r.get('CI_low')}, {r.get('CI_high')}]")
                add(f"{label} Average Precision", float(r["average_precision"]), sample, inputs.auc, f"scope=NATIONWIDE, score={score}, average_precision", inputs.validation_script, "average_precision")
    if inputs.gee.exists():
        r = pd.read_csv(inputs.gee).iloc[0]
        add("Primary GEE coefficient", float(r["estimate_log_odds_per_unit"]), sample, inputs.gee, "estimate_log_odds_per_unit", inputs.power_script, "log-odds")
        add("Primary GEE odds ratio", float(r["odds_ratio_per_unit"]), sample, inputs.gee, "odds_ratio_per_unit", inputs.power_script, "odds_ratio", f"OR-scale 95% CI [{r.get('CI_low')}, {r.get('CI_high')}]")
    if inputs.releases.exists():
        rel = pd.read_csv(inputs.releases)
        for _, r in rel.iterrows():
            auc_col = "AUC_power" if "AUC_power" in r else "AUC"
            add(f"ITDK {r['release']} Power ROC-AUC", float(r[auc_col]), sample, inputs.releases, f"release={r['release']}, {auc_col}", inputs.validation_script, "ROC-AUC", f"/24 cluster bootstrap CI [{r.get('CI_low')}, {r.get('CI_high')}]")
    return pd.DataFrame(rows)


def write_missingness_contract(out: Path, inputs: Inputs) -> None:
    (out / "MISSINGNESS_AND_DENOMINATOR_CONTRACT.md").write_text(
        """# Missingness and denominator contract

This contract is normative for the manuscript lineage.

1. A **complete measurement cycle** is a cycle that passes the frozen Stage-0 acquisition-quality gate.
2. If an IP has no successful-response row inside a complete static-full-scan opportunity, its response numerator contribution is zero.
3. If the acquisition cycle itself is missing or incomplete, the opportunity is excluded before any IP-level denominator is formed; it is never silently converted to non-response.
4. Power-window denominators are valid complete opportunities inherited from the frozen cache and mapped oblast/event cohort.
5. Time-stratified normal referent counts are frozen event-level counts. The audit can verify the referent-selection rule and timestamps at event level, but the cache does not retain raw per-probe paired timestamps. The manuscript must not describe this as a raw probe-level paired case-crossover panel.
6. Clean-baseline response rate uses the broader clean complete-cycle pool and is not interchangeable with the event-specific time-stratified normal referent response rate.
7. Event-window reachability drop is signed: pre-event response proportion minus attack-window response proportion. Negative values are retained.

Authoritative implementations:

- Cycle quality: `%s`
- Clean baseline selection: `%s`
- Activity construction: `%s`
- Power/Normal master: `%s`
- Event reachability drop: `%s`
""" % (
            inputs.cycle_quality,
            inputs.baseline_script,
            inputs.activity_script,
            inputs.power_script,
            inputs.h1_script,
        ),
        encoding="utf-8",
    )


def clickhouse_query(url: str, user: str, password: str, query: str, timeout: int = 3600) -> bytes:
    endpoint = url.rstrip("/") + "/?" + urllib.parse.urlencode({"database": "active_measurement"})
    request = urllib.request.Request(endpoint, data=query.encode("utf-8"), method="POST")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def build_traceroute_provenance(
    out: Path,
    snapshot: Path | None,
    source_repo: Path | None,
    clickhouse_url: str | None,
    clickhouse_user: str | None,
    clickhouse_password: str | None,
) -> dict[str, object]:
    evidence = out / "evidence" / "traceroute_sampler"
    evidence.mkdir(parents=True, exist_ok=True)
    source_hash = "NOT_AVAILABLE"
    source_commit = "NOT_AVAILABLE"
    source_dirty = "NOT_AVAILABLE"
    if snapshot and snapshot.exists():
        destination = evidence / "areaPing.go.server_snapshot"
        shutil.copy2(snapshot, destination)
        source_hash = sha256(destination)
    if source_repo and source_repo.exists():
        source_commit = git_head(source_repo)
        try:
            source_dirty = "DIRTY" if subprocess.check_output(
                ["git", "status", "--porcelain", "--", "kernal/areaPing/areaPing.go"],
                cwd=source_repo, text=True,
            ).strip() else "CLEAN"
        except Exception:
            source_dirty = "UNKNOWN"

    ch_summary: dict[str, object] = {"status": "NOT_QUERIED"}
    if clickhouse_url and clickhouse_user and clickhouse_password:
        table = "`UKRAINE__quarter-traceroute_AWS_frankfurt_2024-06-22`"
        # Persist the authoritative measured-data schema.  The Go sampler is
        # provenance for target selection only; these ClickHouse rows are the
        # actual observed traceroute measurements used by downstream analysis.
        (out / "TRACEROUTE_MEASUREMENT_SCHEMA.tsv").write_bytes(
            clickhouse_query(
                clickhouse_url,
                clickhouse_user,
                clickhouse_password,
                f"DESCRIBE TABLE {table} FORMAT TSVWithNames",
            )
        )

        summary_sql = f"""
SELECT
  count() AS measurement_row_n,
  uniqCombined64(dst_ip) AS distinct_target_ip_estimate_n,
  uniqCombined64(prefix24) AS distinct_prefix24_estimate_n,
  uniqExact(cycle_id) AS cycle_n,
  min(measure_time) AS min_measure_time,
  max(measure_time) AS max_measure_time,
  countIf(ip_path_hash != 0) AS structured_path_nonempty_row_n,
  sum(toUInt64(reached_target)) AS reached_target_row_n,
  sum(toUInt64(responded_hop_count)) AS responded_hop_sum,
  sum(toUInt64(star_hop_count)) AS star_hop_sum,
  groupBitXor(cityHash64(concat(toString(cycle_id), '|', prefix24, '|', dst_ip))) AS target_ledger_hash_xor,
  sum(cityHash64(concat(toString(cycle_id), '|', prefix24, '|', dst_ip))) AS target_ledger_hash_sum,
  groupBitXor(cityHash64(concat(toString(cycle_id), '|', dst_ip, '|', toString(hop_count), '|', toString(responded_hop_count), '|', toString(star_hop_count), '|', toString(reached_target), '|', toString(ip_path_hash)))) AS measurement_ledger_hash_xor,
  sum(cityHash64(concat(toString(cycle_id), '|', dst_ip, '|', toString(hop_count), '|', toString(responded_hop_count), '|', toString(star_hop_count), '|', toString(reached_target), '|', toString(ip_path_hash)))) AS measurement_ledger_hash_sum
FROM {table}
SETTINGS max_threads = 8, max_memory_usage = 8589934592
FORMAT JSONEachRow
"""
        raw = clickhouse_query(clickhouse_url, clickhouse_user, clickhouse_password, summary_sql)
        ch_summary = json.loads(raw.decode("utf-8").strip())
        ch_summary["status"] = "PASS"
        ch_summary["database"] = "active_measurement"
        ch_summary["table"] = table.strip("`")

        cycle_sql = f"""
SELECT
  cycle_id,
  min(measure_time) AS measure_time,
  count() AS measurement_row_n,
  uniqCombined64(prefix24) AS prefix24_estimate_n,
  uniqCombined64(dst_ip) AS distinct_target_ip_estimate_n,
  countIf(ip_path_hash != 0) AS structured_path_nonempty_row_n,
  sum(toUInt64(reached_target)) AS reached_target_row_n,
  sum(toUInt64(responded_hop_count)) AS responded_hop_sum,
  sum(toUInt64(star_hop_count)) AS star_hop_sum,
  groupBitXor(cityHash64(concat(toString(cycle_id), '|', prefix24, '|', dst_ip))) AS target_hash_xor,
  sum(cityHash64(concat(toString(cycle_id), '|', prefix24, '|', dst_ip))) AS target_hash_sum,
  groupBitXor(cityHash64(concat(toString(cycle_id), '|', dst_ip, '|', toString(hop_count), '|', toString(responded_hop_count), '|', toString(star_hop_count), '|', toString(reached_target), '|', toString(ip_path_hash)))) AS measurement_hash_xor,
  sum(cityHash64(concat(toString(cycle_id), '|', dst_ip, '|', toString(hop_count), '|', toString(responded_hop_count), '|', toString(star_hop_count), '|', toString(reached_target), '|', toString(ip_path_hash)))) AS measurement_hash_sum
FROM {table}
GROUP BY cycle_id
ORDER BY cycle_id
SETTINGS max_threads = 8, max_memory_usage = 8589934592
FORMAT CSVWithNames
"""
        (out / "TRACEROUTE_MEASUREMENT_MANIFEST_BY_CYCLE.csv").write_bytes(
            clickhouse_query(clickhouse_url, clickhouse_user, clickhouse_password, cycle_sql)
        )

        sample_sql = f"""
SELECT
  cycle_id, measure_time, data_center, prefix24, dst_ip,
  hop_count, responded_hop_count, star_hop_count, reached_target,
  ip_path_hash, as_path_hash, asgeo_path_hash, probe_ts_us,
  substring(raw_trace, 1, 512) AS raw_trace_prefix
FROM {table}
WHERE length(raw_trace) > 0
LIMIT 20
SETTINGS max_threads = 1, max_memory_usage = 1073741824
FORMAT JSONEachRow
"""
        (out / "TRACEROUTE_MEASUREMENT_SAMPLE.jsonl").write_bytes(
            clickhouse_query(clickhouse_url, clickhouse_user, clickhouse_password, sample_sql)
        )

    (out / "TRACEROUTE_PROVENANCE.md").write_text(
        f"""# Traceroute provenance

## Recovered sampler

- Server source: `/home/test/GlobalPing_ZT/kernal/areaPing/areaPing.go`
- Source repository HEAD: `{source_commit}`
- Source file worktree status: `{source_dirty}`
- Frozen source SHA-256: `{source_hash}`
- Frozen snapshot: `evidence/traceroute_sampler/areaPing.go.server_snapshot`

The recovered `Traceroute` function executes four measurements per C segment. It chooses one host address from each of the ranges 1–63, 65–127, 129–191, and 192–254. The implementation calls `rand.Seed(time.Now().UnixNano())` during measurement, so there is no fixed historical seed that can reproduce the same random choices.

The actual selected destination and its measured route are stored in ClickHouse. `dst_ip` recovers the historical target; `hop_count`, `responded_hop_count`, `star_hop_count`, `reached_target`, `hop_path`, `ip_path_hash`, and `raw_trace` are measurement-result fields. The sampler snapshot is not treated as measured data.

## Frozen measured traceroute ledger

ClickHouse status: `{ch_summary.get('status')}`. The authoritative measurements remain in the read-only ClickHouse table because committing hundreds of millions of rows to Git would be inappropriate. `TRACEROUTE_MEASUREMENT_SCHEMA.tsv` freezes its schema; `TRACEROUTE_MEASUREMENT_MANIFEST_BY_CYCLE.csv` records observed-route counts plus order-independent hashes; `TRACEROUTE_MEASUREMENT_SAMPLE.jsonl` is a small auditable sample. Fields ending in `_estimate_n` use ClickHouse `uniqCombined64` to bound memory on the shared server and are explicitly estimates; row counts and both ledger hashes are exact deterministic scans of the structured measurement columns. `raw_trace` is sampled but is not decompressed across the full table because the normalized hop/path columns carry the measured result used downstream. The full measured ledger can be queried with:

```sql
SELECT cycle_id, measure_time, data_center, prefix24, dst_ip,
       hop_count, responded_hop_count, star_hop_count, reached_target,
       hop_path, ip_path_hash, raw_trace, probe_ts_us
FROM active_measurement.`UKRAINE__quarter-traceroute_AWS_frankfurt_2024-06-22`
ORDER BY cycle_id, prefix24, dst_ip;
```

Global source-table summary is recorded in `TRACEROUTE_PROVENANCE.json`.
""",
        encoding="utf-8",
    )
    (out / "TRACEROUTE_PROVENANCE.json").write_text(
        json.dumps({
            "source_repo_head": source_commit,
            "source_file_status": source_dirty,
            "source_sha256": source_hash,
            "sampling_ranges": [[1, 63], [65, 127], [129, 191], [192, 254]],
            "fixed_seed_available": False,
            "actual_target_field": "dst_ip",
            "clickhouse": ch_summary,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ch_summary


def write_input_manifest(out: Path, inputs: Inputs) -> pd.DataFrame:
    rows = []
    for name, path in inputs.__dict__.items():
        rows.append({
            "input_name": name,
            "path": str(path),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else None,
            "sha256": sha256(path) if path.exists() and path.is_file() else None,
        })
    manifest = pd.DataFrame(rows)
    manifest.to_csv(out / "INPUT_FILE_MANIFEST.csv", index=False)
    return manifest


def run(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = input_paths(root)
    require([
        inputs.schedule, inputs.calibration_events, inputs.event_cache, inputs.cycle_quality,
        inputs.targets, inputs.master, inputs.activity, inputs.h1_script,
        inputs.activity_script, inputs.baseline_script, inputs.calibration_script,
        inputs.power_script, inputs.validation_script,
    ])
    scientific_input_commit = git_head(root)
    implementation_commit = git_head(Path(__file__).resolve().parents[1])
    input_manifest = write_input_manifest(out, inputs)
    raw_schedule, eligible_schedule = load_schedule(inputs.schedule)
    cache, calibration, duplicate_rows_removed = load_cache_and_calibration(inputs)
    crosswalk, legacy = build_crosswalk(raw_schedule, eligible_schedule, cache, calibration)
    crosswalk.to_csv(out / "MANUSCRIPT_EVENT_CROSSWALK.csv", index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
    counts = count_semantics(raw_schedule, eligible_schedule, legacy, crosswalk)
    counts.to_csv(out / "EVENT_COUNT_SEMANTICS.csv", index=False)

    exact_ids = set(crosswalk.loc[crosswalk["mapping_status"].eq("EXACT_ONE_SCHEDULE_EVENT"), "cache_event_id"].astype(str))
    date_ids = current_date_matched_ids(eligible_schedule, cache)
    cohort_identity = pd.DataFrame([
        {"check": "date_matched_vs_temporal_overlap_cache_event_ids", "left_n": len(date_ids), "right_n": len(exact_ids), "left_only_n": len(date_ids - exact_ids), "right_only_n": len(exact_ids - date_ids), "status": "PASS" if date_ids == exact_ids else "FAIL"},
        {"check": "crosswalk_unique_schedule_event_per_cache_opportunity", "left_n": len(crosswalk), "right_n": int(crosswalk["mapping_status"].eq("EXACT_ONE_SCHEDULE_EVENT").sum()), "left_only_n": int(crosswalk["mapping_status"].ne("EXACT_ONE_SCHEDULE_EVENT").sum()), "right_only_n": 0, "status": "PASS" if crosswalk["mapping_status"].eq("EXACT_ONE_SCHEDULE_EVENT").all() else "FAIL"},
        {"check": "calibration_oblast_matches_cache_oblast", "left_n": len(crosswalk), "right_n": int(crosswalk["oblast"].astype(str).eq(crosswalk["calibration_oblast"].astype(str)).sum()), "left_only_n": int(crosswalk["oblast"].astype(str).ne(crosswalk["calibration_oblast"].astype(str)).sum()), "right_only_n": 0, "status": "PASS" if crosswalk["oblast"].astype(str).eq(crosswalk["calibration_oblast"].astype(str)).all() else "FAIL"},
    ])
    cohort_identity.to_csv(out / "COHORT_IDENTITY_QA.csv", index=False)
    master_identity = rebuild_master_identity(inputs, cache, exact_ids)
    master_identity.to_csv(out / "MASTER_IDENTITY_QA.csv", index=False)

    variables = variable_dictionary(inputs)
    variables.to_csv(out / "MANUSCRIPT_VARIABLE_DICTIONARY.csv", index=False)
    write_missingness_contract(out, inputs)
    results = result_manifest(inputs, eligible_schedule, crosswalk, implementation_commit)
    results.to_csv(out / "MANUSCRIPT_RESULT_MANIFEST.csv", index=False)

    password = os.environ.get(args.clickhouse_password_env, "") if args.clickhouse_password_env else ""
    ch_summary = build_traceroute_provenance(
        out,
        args.traceroute_sampler_snapshot,
        args.traceroute_source_repo,
        args.clickhouse_url,
        args.clickhouse_user,
        password,
    )

    gates = {
        "crosswalk_all_exact": bool(crosswalk["mapping_status"].eq("EXACT_ONE_SCHEDULE_EVENT").all()),
        "cohort_identity_pass": bool(cohort_identity["status"].eq("PASS").all()),
        "master_identity_pass": bool(master_identity["status"].eq("PASS").all()),
        "input_manifest_complete": bool(input_manifest["exists"].all()),
        "traceroute_sampler_frozen": (out / "evidence/traceroute_sampler/areaPing.go.server_snapshot").exists(),
        "traceroute_measurement_schema_generated": (out / "TRACEROUTE_MEASUREMENT_SCHEMA.tsv").exists(),
        "traceroute_measurement_digest_generated": (out / "TRACEROUTE_MEASUREMENT_MANIFEST_BY_CYCLE.csv").exists(),
    }
    reanalysis_required = not (
        gates["crosswalk_all_exact"]
        and gates["cohort_identity_pass"]
        and gates["master_identity_pass"]
    )
    status = "PASS" if all(gates.values()) else "PASS_WITH_PROVENANCE_LIMIT" if not reanalysis_required else "FAIL_REANALYSIS_REQUIRED"
    summary = {
        "status": status,
        "implementation_git_commit": implementation_commit,
        "scientific_input_git_commit": scientific_input_commit,
        "scientific_results_recomputed": False,
        "figures_generated": False,
        "duplicate_cache_rows_removed_before_main_semantics": duplicate_rows_removed,
        "schedule_eligible_event_ids": int(eligible_schedule["event_id"].nunique()),
        "schedule_event_ids_represented_in_main": int(crosswalk.loc[crosswalk["included_power_main"], "schedule_event_id"].nunique()),
        "analysis_event_oblast_opportunities": int(crosswalk["included_power_main"].sum()),
        "gates": gates,
        "reanalysis_required": reanalysis_required,
        "clickhouse_traceroute_status": ch_summary.get("status"),
    }
    (out / "LINEAGE_CLOSURE_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "LINEAGE_CLOSURE_REPORT.md").write_text(
        "# Manuscript scientific-lineage closure\n\n"
        f"- Status: **{status}**\n"
        f"- Lineage implementation commit used on the server: `{implementation_commit}`\n"
        f"- Frozen scientific-input repository commit: `{scientific_input_commit}`\n"
        f"- Eligible verified schedule event IDs: **{summary['schedule_eligible_event_ids']}**\n"
        f"- Schedule event IDs represented in the main frozen cohort: **{summary['schedule_event_ids_represented_in_main']}**\n"
        f"- Canonical cache-event × oblast analysis opportunities: **{summary['analysis_event_oblast_opportunities']}**\n"
        f"- Main Power/Normal reanalysis required: **{'YES' if reanalysis_required else 'NO'}**\n"
        "- New models fitted: **NO**\n"
        "- Figures generated: **NO**\n\n"
        "A `NO` reanalysis decision means the interval-overlap crosswalk selects exactly the same cache-event cohort and reproduces every frozen master numerator, denominator, and response-rate column. It does not waive the documented event-level-cache limitation for normal referents.\n",
        encoding="utf-8",
    )

    output_rows = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "OUTPUT_FILE_MANIFEST.csv"):
        output_rows.append({"file": path.relative_to(out).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    pd.DataFrame(output_rows).to_csv(out / "OUTPUT_FILE_MANIFEST.csv", index=False)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="Read-only scientific project root")
    parser.add_argument("--output", type=Path, required=True, help="Lineage artifact output directory")
    parser.add_argument("--traceroute-sampler-snapshot", type=Path)
    parser.add_argument("--traceroute-source-repo", type=Path)
    parser.add_argument("--clickhouse-url")
    parser.add_argument("--clickhouse-user")
    parser.add_argument("--clickhouse-password-env", default="CLICKHOUSE_PASSWORD")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
