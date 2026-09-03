"""Offline audit helpers for the v2.5 outage-label precision experiment.

This module deliberately does not tune B2.  It validates civil/UTC timestamps,
measures which refinements can be applied at the frozen IP-geolocation grain,
and relabels cached validation observations only where the cache has support.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


EVENT_BY_DATE = {
    "2024-07-28": "E2024_0728_PLANNED",
    "2024-08-19": "E2024_0819_PLANNED",
    "2024-08-20": "E2024_0820_PLANNED",
    "2024-08-21": "E2024_0821_PLANNED",
    "2024-12-09": "E2024_1209_PLANNED",
}


def _civil_to_utc(value: object, zone: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(zone, ambiguous="raise", nonexistent="raise")
    return ts.tz_convert("UTC")


def audit_timestamp_pairs(df: pd.DataFrame, *, local_start="local_start",
                          local_end="local_end", timezone="timezone",
                          start_utc="start_utc", end_utc="end_utc") -> pd.DataFrame:
    """Compare source UTC columns with IANA-zone conversion of civil times."""
    rows = []
    for i, row in df.iterrows():
        zone = str(row.get(timezone) or "Europe/Kyiv")
        result = {"row": i, "timezone": zone}
        for local_col, utc_col, stem in ((local_start, start_utc, "start"),
                                         (local_end, end_utc, "end")):
            local = row.get(local_col)
            expected = pd.to_datetime(row.get(utc_col), utc=True, errors="coerce")
            if pd.isna(local) or str(local).strip() == "" or pd.isna(expected):
                result[f"{stem}_delta_seconds"] = np.nan
                continue
            actual = _civil_to_utc(local, zone)
            result[f"{stem}_delta_seconds"] = (actual - expected).total_seconds()
        rows.append(result)
    out = pd.DataFrame(rows)
    deltas = [c for c in out if c.endswith("_delta_seconds")]
    out["timestamp_pair_valid"] = out[deltas].fillna(0).abs().max(axis=1).eq(0).astype("int8")
    return out


def relabel_cached_national(obs: pd.DataFrame, segments: pd.DataFrame,
                            cycle_hours: float = 2.0,
                            min_overlap_fraction: float = 0.5) -> pd.DataFrame:
    """Apply corrected national segments to cached validation rows.

    Historical matched controls remain controls.  Event-day samples outside a
    known segment are marked unsupported rather than silently called q0.
    """
    out = obs.copy()
    out["measure_time"] = pd.to_datetime(out["measure_time"], utc=True)
    out["label_original"] = pd.to_numeric(out["label"], errors="coerce")
    out["label_refined"] = out["label_original"]
    out["refined_supported"] = 1
    out["national_queue_count_refined"] = pd.to_numeric(out.get("queue_count"), errors="coerce")
    cycle_delta = pd.Timedelta(hours=cycle_hours)
    for date, event_id in EVENT_BY_DATE.items():
        seg = segments[segments["date"].astype(str).eq(date)].copy()
        if seg.empty:
            continue
        seg["start_utc"] = pd.to_datetime(seg["start_utc"], utc=True)
        seg["end_utc"] = pd.to_datetime(seg["end_utc"], utc=True)
        event_rows = out["event_id"].astype(str).eq(event_id) & out["label_original"].eq(1)
        for cycle_id in out.loc[event_rows, "cycle_id"].drop_duplicates():
            idx = event_rows & out["cycle_id"].eq(cycle_id)
            start = out.loc[idx, "measure_time"].iloc[0]
            end = start + cycle_delta
            overlap = []
            for _, s in seg.iterrows():
                hours = max(0.0, (min(end, s.end_utc) - max(start, s.start_utc)).total_seconds() / 3600)
                overlap.append((hours, float(s.queue_count)))
            covered = sum(h for h, _ in overlap)
            positive = sum(h for h, q in overlap if q > 0)
            dose = sum(h * q for h, q in overlap) / covered if covered else np.nan
            out.loc[idx, "national_queue_count_refined"] = dose
            out.loc[idx, "refined_supported"] = int(covered >= cycle_hours * min_overlap_fraction)
            out.loc[idx, "label_refined"] = int(positive >= cycle_hours * min_overlap_fraction) if covered else np.nan
    return out


def precision_feasibility(targets: pd.DataFrame, updates: pd.DataFrame,
                          queue_schedule: pd.DataFrame) -> pd.DataFrame:
    """State what label precision the frozen mapping can honestly support."""
    admin1 = set(targets.loc[targets.get("regional_eligible", 0).eq(1), "target_admin1"].dropna())
    update_admin1 = set(updates["oblast"].dropna())
    queue_admin1 = set(queue_schedule["oblast"].dropna())
    return pd.DataFrame([
        {"label_level": "national_final_corrected", "locally_runnable": 1,
         "reason": "UTC cycle cache and official final national segments are present"},
        {"label_level": "oblast_final_updates", "locally_runnable": int(bool(admin1 & update_admin1)),
         "reason": f"Admin1 mapping present; operator updates overlap {len(admin1 & update_admin1)} mapped oblast(s), but queue-only updates remain probabilistic"},
        {"label_level": "queue_refined_where_supported", "locally_runnable": 0,
         "reason": f"Published queue schedules cover {len(queue_admin1)} oblast(s), but frozen IP mapping has no queue/address/feed identifier"},
        {"label_level": "exact_address_or_feed", "locally_runnable": 0,
         "reason": "No defensible IP-to-address/feed key; city/Admin1 must not be promoted to street-level truth"},
    ])


def package_root(project_root: Path) -> Path:
    v2 = (project_root / "data_external" / "outage_calibration_pack_v2" /
          "ukraine_outage_calibration_data_pack_v2")
    if v2.exists():
        return v2
    return (project_root / "data_external" / "outage_calibration_pack" /
            "ukraine_outage_calibration_data_pack")
