"""Frozen event registry, anchor variants, treatment scope, and cycle labels."""
from __future__ import annotations

import pandas as pd

from .config import Config


def slot_of(ts, cycle_h: int = 2):
    x = pd.to_datetime(ts, utc=True)
    slots_per_day = 24 // cycle_h
    if isinstance(x, pd.Timestamp):
        return int(x.dayofweek) * slots_per_day + int(x.hour) // cycle_h
    return (x.dt.dayofweek * slots_per_day + x.dt.hour // cycle_h).astype("int16")


def split_admin1(raw: object) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    if s == "ALL":
        return ["ALL"]
    return [x.strip() for x in s.split("|") if x.strip()]


class Events:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.df = cfg.load_event_registry()
        self.df = self.df[self.df["analysis_ready"].eq(1)].copy()
        self.available_df = self.df.copy()
        self.schedule = cfg.load_schedule_registry()
        availability = cfg.out_dir("results_tables") / "event_data_availability.csv"
        if availability.exists() and availability.stat().st_size:
            a = pd.read_csv(availability, dtype={"event_id": str})
            if "data_available" in a:
                keep = set(a.loc[pd.to_numeric(a["data_available"], errors="coerce").fillna(0).eq(1), "event_id"])
                self.available_df = self.df[self.df["event_id"].isin(keep)].copy()

    def by_role(self, *roles: str, available_only: bool = True) -> pd.DataFrame:
        base = self.available_df if available_only else self.df
        return base[base["analysis_role"].isin(roles)].copy()

    @property
    def planned_train(self): return self.by_role("planned_train")
    @property
    def planned_valid(self): return self.by_role("planned_valid")
    @property
    def planned_aux(self): return self.by_role("planned_aux_confounded")
    @property
    def attacks(self): return self.by_role("attack_national", "attack_regional", "blind_test", "stress_test")
    @property
    def primary_attacks(self): return self.by_role("attack_national", "attack_regional", "blind_test")

    @staticmethod
    def anchor_time(row: pd.Series, variant: str = "primary") -> pd.Timestamp:
        if variant == "primary":
            return pd.to_datetime(row.get("primary_anchor_utc"), utc=True, errors="coerce")
        mapping = {
            "attack": "attack_start_utc",
            "outage": "outage_start_utc",
            "network": "network_anomaly_start_utc",
            "lower": "anchor_lower_utc",
            "upper": "anchor_upper_utc",
        }
        return pd.to_datetime(row.get(mapping.get(variant, variant)), utc=True, errors="coerce")

    @staticmethod
    def treated_admin1(row: pd.Series) -> list[str]:
        return split_admin1(row.get("analysis_treated_admin1"))

    @staticmethod
    def power_admin1(row: pd.Series) -> list[str]:
        return split_admin1(row.get("power_affected_admin1"))

    @staticmethod
    def observed_admin1(row: pd.Series) -> list[str]:
        return split_admin1(row.get("network_observed_admin1"))

    def build_cycle_grid(self, cycle_quality: pd.DataFrame) -> pd.DataFrame:
        g = cycle_quality.copy()
        g["measure_time"] = pd.to_datetime(g["measure_time"], utc=True)
        g["slot"] = slot_of(g["measure_time"], int(self.cfg.study["expected_cycle_interval_hours"]))
        if "is_complete" not in g:
            g["is_complete"] = 1
        if "is_analysis_cycle" in g:
            g["is_complete"] = g["is_analysis_cycle"].astype("int8")
        return g.sort_values("measure_time").reset_index(drop=True)

    def clean_baseline_mask(self, grid: pd.DataFrame) -> pd.Series:
        pad = pd.Timedelta(days=int(self.cfg.baseline["exclude_event_pad_days"]))
        mt = pd.to_datetime(grid["measure_time"], utc=True)
        mask = grid["is_complete"].astype(bool).copy()
        for _, row in self.df.iterrows():
            starts = [row.get("attack_start_utc"), row.get("outage_start_utc"), row.get("anchor_lower_utc")]
            ends = [row.get("outage_end_utc"), row.get("power_recovery_end_utc"),
                    row.get("network_recovery_end_utc"), row.get("anchor_upper_utc")]
            starts = [pd.to_datetime(x, utc=True, errors="coerce") for x in starts]
            ends = [pd.to_datetime(x, utc=True, errors="coerce") for x in ends]
            starts = [x for x in starts if pd.notna(x)]
            ends = [x for x in ends if pd.notna(x)]
            if not starts:
                continue
            lo = min(starts) - pad
            hi = (max(ends) if ends else min(starts)) + pad
            mask &= ~((mt >= lo) & (mt <= hi))
        return mask

    @staticmethod
    def cycles_in_window(grid: pd.DataFrame, start, end) -> list[int]:
        s = pd.to_datetime(start, utc=True, errors="coerce")
        e = pd.to_datetime(end, utc=True, errors="coerce")
        if pd.isna(s) or pd.isna(e):
            return []
        mt = pd.to_datetime(grid["measure_time"], utc=True)
        return grid.loc[(mt >= s) & (mt <= e) & grid["is_complete"].astype(bool), "cycle_id"].astype("int64").tolist()

    def schedule_cycles(self, grid: pd.DataFrame, row: pd.Series, *, positive: bool,
                        end_before=None) -> list[int]:
        event_id = str(row.get("event_id", ""))
        queue_mask = self.schedule["queue_count"].gt(0) if positive else self.schedule["queue_count"].eq(0)
        segments = self.schedule[(self.schedule["event_id"].eq(event_id)) & queue_mask].copy()
        if end_before is not None:
            cutoff = pd.to_datetime(end_before, utc=True, errors="coerce")
            segments = segments[segments["end_utc"].le(cutoff)]
        if segments.empty:
            return []
        mt = pd.to_datetime(grid["measure_time"], utc=True)
        cycle_h = float(self.cfg.study["expected_cycle_interval_hours"])
        cycle_end = mt + pd.Timedelta(hours=cycle_h)
        overlap_h = pd.Series(0.0, index=grid.index)
        for _, seg in segments.iterrows():
            start = pd.to_datetime(seg["start_utc"], utc=True)
            end = pd.to_datetime(seg["end_utc"], utc=True)
            left = mt.where(mt > start, start)
            right = cycle_end.where(cycle_end < end, end)
            overlap_h += ((right - left).dt.total_seconds() / 3600).clip(lower=0)
        threshold = float(self.cfg.calibration.get("min_cycle_schedule_overlap_fraction", 0.5))
        keep = overlap_h.div(cycle_h).clip(upper=1).ge(threshold) & grid["is_complete"].astype(bool)
        return grid.loc[keep, "cycle_id"].astype("int64").tolist()

    def outage_cycles(self, grid: pd.DataFrame, row: pd.Series) -> list[int]:
        event_id = str(row.get("event_id", ""))
        if self.schedule["event_id"].eq(event_id).any():
            return self.schedule_cycles(grid, row, positive=True)
        return self.cycles_in_window(grid, row.get("outage_start_utc"), row.get("outage_end_utc"))

    def schedule_event_metadata(self, event_id: str) -> dict:
        d = self.schedule[self.schedule["event_id"].eq(str(event_id))]
        if d.empty:
            return {"independence_cluster": str(event_id), "publication_eligible": 0}
        return {
            "independence_cluster": str(d["independence_cluster"].iloc[0] or event_id),
            "publication_eligible": int(pd.to_numeric(d["publication_eligible"], errors="coerce").max()),
            "max_queue_count": float(pd.to_numeric(d["queue_count"], errors="coerce").max()),
        }

    def schedule_cycle_dose(self, grid: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
        """Time-weighted queue count for every cycle overlapping a registered day."""
        segments = self.schedule[self.schedule["event_id"].eq(str(row.get("event_id", "")))]
        if segments.empty:
            return pd.DataFrame(columns=["cycle_id", "queue_count"])
        mt = pd.to_datetime(grid["measure_time"], utc=True)
        cycle_h = float(self.cfg.study["expected_cycle_interval_hours"])
        cycle_end = mt + pd.Timedelta(hours=cycle_h)
        weighted = pd.Series(0.0, index=grid.index)
        covered = pd.Series(0.0, index=grid.index)
        for _, seg in segments.iterrows():
            start = pd.to_datetime(seg["start_utc"], utc=True)
            end = pd.to_datetime(seg["end_utc"], utc=True)
            left = mt.where(mt > start, start)
            right = cycle_end.where(cycle_end < end, end)
            overlap = ((right - left).dt.total_seconds() / 3600).clip(lower=0)
            weighted += overlap * float(seg["queue_count"])
            covered += overlap
        out = grid.loc[covered.gt(0), ["cycle_id"]].copy()
        out["queue_count"] = weighted.loc[covered.gt(0)].div(covered.loc[covered.gt(0)]).to_numpy()
        return out

    def event_window(self, row: pd.Series, anchor_variant: str = "primary") -> tuple[pd.Timestamp, pd.Timestamp]:
        """Absolute panel interval including clean baseline and all event stages.

        v2.4 no longer assumes that the primary outcome anchor is the beginning of
        treatment.  For attacks, the physical strike can precede the outage or an
        externally observed network anomaly by hours.  Event panels therefore
        begin before the earliest credible treatment boundary.
        """
        if anchor_variant == "primary":
            from .event_design import event_panel_interval
            return event_panel_interval(row, self.cfg)
        a = self.anchor_time(row, anchor_variant)
        return (a + pd.Timedelta(hours=float(self.cfg.event_windows["event_study_pre_h"])),
                a + pd.Timedelta(days=float(self.cfg.event_windows["recovery_window_days"])))

    def planned_train_cycles(self, grid: pd.DataFrame) -> list[int]:
        out = []
        for _, row in self.planned_train.iterrows():
            out.extend(self.outage_cycles(grid, row))
        return sorted(set(out))

    def normal_control_cycles(self, grid: pd.DataFrame) -> list[int]:
        return grid.loc[self.clean_baseline_mask(grid), "cycle_id"].astype("int64").tolist()
