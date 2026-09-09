#!/usr/bin/env python3
"""Create the immutable episode-fix calibration workbook.

The input workbook is never edited in place.  Legacy episode IDs are copied to
explicit audit columns and new v2 IDs are assigned independently for Primary
and Augmented panels.  A new episode starts when the next reviewed outage
window begins at least one nominal measurement cycle after the previous window
ends (2 h by default).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd


def slug(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").upper()


def assign_events(events: pd.DataFrame, panel: str, flag: str, legacy_col: str,
                  threshold_h: float) -> tuple[pd.Series, pd.DataFrame]:
    ids = pd.Series("", index=events.index, dtype="string")
    audit_rows: list[pd.DataFrame] = []
    selected = events[pd.to_numeric(events[flag], errors="coerce").fillna(0).eq(1)].copy()
    selected["_start"] = pd.to_datetime(selected["outage_start_utc"], utc=True, errors="coerce")
    selected["_end"] = pd.to_datetime(selected["outage_end_utc"], utc=True, errors="coerce")
    for state, g in selected.groupby("state_en", sort=True):
        g = g.sort_values(["_start", "_end", "event_id"]).copy()
        g["prev_end_utc"] = g["_end"].shift(1)
        g["gap_hours"] = (g["_start"] - g["prev_end_utc"]).dt.total_seconds() / 3600.0
        g["new_episode"] = g["prev_end_utc"].isna() | g["gap_hours"].ge(float(threshold_h))
        g["episode_seq"] = g["new_episode"].astype(int).cumsum()
        g["legacy_episode_id"] = g[legacy_col].fillna("").astype(str).str.strip()
        g["episode_id_v2"] = [
            f"EP_{slug(state)}_USE_{panel.upper()}_V2_{int(n):02d}" for n in g["episode_seq"]
        ]
        ids.loc[g.index] = g["episode_id_v2"].astype("string")
        audit_rows.append(g[["event_id", "state_en", "event_date", "prev_end_utc", "gap_hours", "new_episode", "legacy_episode_id", "episode_id_v2"]].assign(panel=panel))
    audit = pd.concat(audit_rows, ignore_index=True) if audit_rows else pd.DataFrame()
    return ids, audit


def revise(input_path: Path, output_path: Path, threshold_h: float = 2.0) -> None:
    events = pd.read_excel(input_path, sheet_name="final_calibration_events")
    segments = pd.read_excel(input_path, sheet_name="final_calibration_segments")
    for df in (events, segments):
        for col in ("episode_id_main", "episode_id_augmented"):
            if col not in df:
                raise ValueError(f"missing required legacy column {col}")
            df[f"legacy_{col}"] = df[col].fillna("").astype(str).str.strip()

    events["episode_id_v2_main"], a_main = assign_events(events, "primary", "use_main", "episode_id_main", threshold_h)
    events["episode_id_v2_augmented"], a_aug = assign_events(events, "augmented", "use_augmented", "episode_id_augmented", threshold_h)
    crosswalk = pd.concat([a_main, a_aug], ignore_index=True)
    # Excel cells cannot store timezone-aware timestamps; the source event
    # sheets retain their original representation, while the crosswalk is an
    # audit table whose UTC semantics are documented in its column names.
    if "prev_end_utc" in crosswalk:
        crosswalk["prev_end_utc"] = pd.to_datetime(crosswalk["prev_end_utc"], utc=True, errors="coerce").dt.tz_localize(None)
    event_map = events.set_index("event_id")[["episode_id_v2_main", "episode_id_v2_augmented"]]
    segments["episode_id_v2_main"] = segments["event_id"].map(event_map["episode_id_v2_main"]).fillna("")
    segments["episode_id_v2_augmented"] = segments["event_id"].map(event_map["episode_id_v2_augmented"]).fillna("")
    segments["episode_rule_v2"] = f"gap_ge_{threshold_h:g}h_nominal_cycle"
    events["episode_rule_v2"] = f"gap_ge_{threshold_h:g}h_nominal_cycle"
    metadata = pd.DataFrame([
        {"field": "freeze_version", "value": "analysis_plan_v2_5_episode_fix"},
        {"field": "episode_rule", "value": f"new episode when next outage_start - previous outage_end >= {threshold_h:g} hours"},
        {"field": "measurement_cycle_hours", "value": 2},
        {"field": "legacy_ids", "value": "retained in legacy_episode_id_main/legacy_episode_id_augmented and original columns"},
        {"field": "formal_use", "value": "episode_id_v2_main for Primary; episode_id_v2_augmented for Augmented"},
    ])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        events.to_excel(writer, sheet_name="final_calibration_events", index=False)
        segments.to_excel(writer, sheet_name="final_calibration_segments", index=False)
        crosswalk.to_excel(writer, sheet_name="episode_id_crosswalk", index=False)
        metadata.to_excel(writer, sheet_name="episode_rule_v2", index=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--threshold-hours", type=float, default=2.0)
    args = ap.parse_args()
    revise(args.input, args.output, args.threshold_hours)
    print(args.output)


if __name__ == "__main__":
    main()
