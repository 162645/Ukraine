"""State-level planned-outage weak supervision for continuous IP sensitivity.

Planned outages are not used to label an endpoint as electrically powered or
not.  For every stable IP in an explicitly covered state we compare a scheduled
outage cycle with clean, same-state, same-weekday-and-slot cycles.  The frozen
outputs are two separate continuous quantities: reachability sensitivity and
conditional RTT sensitivity.  War attacks are never used here; they are opened
only after these scores have been frozen.
"""
from __future__ import annotations

import json
import re
import glob
from pathlib import Path

import numpy as np
import pandas as pd

from . import sqlutil as S
from .config import Config
from .db import CHClient
from .events import Events, slot_of
from .progress import get_logger, pbar, step


def _flag(frame: pd.DataFrame, name: str, default: int = 0) -> pd.Series:
    if name not in frame:
        return pd.Series(default, index=frame.index, dtype="int8")
    return pd.to_numeric(frame[name], errors="coerce").fillna(default).astype("int8")


def _tokens(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    excluded = {"", "ALL", "MULTIPLE_UNSPECIFIED", "multiple unspecified oblasts"}
    return [x.strip() for x in str(value).replace(";", "|").split("|")
            if x.strip() not in excluded]


def _slug(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").upper()


def build_calibration_events(schedule: pd.DataFrame,
                             valid_admin1: set[str] | None = None,
                             registry: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one event per Admin1-date plus its exact schedule segments.

    Multiple queue/operator rows on the same day are unioned at cycle-mapping
    time.  Operator and queue values remain provenance only and never define IP
    membership.
    """
    d = schedule.copy()
    eligible = _flag(d, "analysis_eligible", 1).eq(1)
    eligible &= _flag(d, "publication_eligible", 1).eq(1)
    eligible &= _flag(d, "confound_free", 1).eq(1)
    if "scope_type_norm" in d:
        scope = d["scope_type_norm"].astype(str).str.lower()
    else:
        scope = d.get("scope_type", pd.Series("", index=d.index)).astype(str).str.lower()
    d = d[eligible & ~scope.eq("national")].copy()
    d["scope_type_norm"] = scope.loc[d.index]
    if registry is not None:
        wanted = registry.copy()
        wanted["event_date"] = wanted.event_date.astype(str)
        d["_registry_geo"] = d.apply(
            lambda r: (_tokens(r.get("affected_admin1")) or _tokens(r.get("admin1")) or [""])[0], axis=1)
        d["_registry_date"] = d.event_date.astype(str)
        d = d.merge(wanted, left_on=["_registry_geo", "_registry_date"],
                    right_on=["geo_name", "event_date"], how="inner", suffixes=("", "_registry"))
        expected_scope = d.scope_requirement.astype(str).str.lower()
        actual_scope = d.scope_type_norm.astype(str).str.lower()
        d = d[expected_scope.eq(actual_scope)].copy()
    valid = set(valid_admin1 or [])
    rows = []
    for _, row in d.iterrows():
        # affected_admin1 is the explicit treatment geography when present;
        # admin1 is only a fallback. This avoids treating an announcement's
        # publisher location as its affected location.
        regions = _tokens(row.get("affected_admin1")) or _tokens(row.get("admin1"))
        if valid:
            regions = [x for x in regions if x in valid]
        actual_start = pd.to_datetime(row.get("actual_start_utc"), utc=True, errors="coerce")
        actual_end = pd.to_datetime(row.get("actual_end_utc"), utc=True, errors="coerce")
        has_actual = pd.notna(actual_start) and pd.notna(actual_end) and actual_end > actual_start
        start = actual_start if has_actual else pd.to_datetime(
            row.get("start_utc", row.get("planned_start_utc")), utc=True, errors="coerce")
        end = actual_end if has_actual else pd.to_datetime(
            row.get("end_utc", row.get("planned_end_utc")), utc=True, errors="coerce")
        if pd.isna(start) or pd.isna(end) or end <= start:
            continue
        date = str(row.get("event_date") or start.date())
        positive = int(_flag(pd.DataFrame([row]), "schedule_positive", 0).iloc[0])
        for admin1 in regions:
            rows.append({
                "target_admin1": admin1, "event_date": date,
                "schedule_positive": positive,
                "start_utc": start, "end_utc": end,
                "uses_actual_time": int(has_actual),
                "operator": str(row.get("operator", "") or ""),
                "queue": str(row.get("queue_id", row.get("queue_ids_merged", "")) or ""),
                "record_id": str(row.get("record_id", row.get("segment_id", "")) or ""),
                "source_url": str(row.get("verified_source_url", row.get("source_url", "")) or ""),
                "evidence_tier": str(row.get("evidence_tier", "unregistered") or "unregistered"),
                "scope_requirement": str(row.get("scope_requirement", "") or ""),
            })
    # A+ registry rows may carry a separately verified explicit no-restriction
    # interval where the source expresses a gap between two state windows rather
    # than emitting a standalone schedule row.  It is retained as evidence, not
    # inferred from an arbitrary unlisted gap.
    if registry is not None and {"explicit_clear_start_utc", "explicit_clear_end_utc"}.issubset(registry.columns):
        for _, row in registry.iterrows():
            start = pd.to_datetime(row.get("explicit_clear_start_utc"), utc=True, errors="coerce")
            end = pd.to_datetime(row.get("explicit_clear_end_utc"), utc=True, errors="coerce")
            if pd.notna(start) and pd.notna(end) and end > start:
                rows.append({
                    "target_admin1": str(row.geo_name), "event_date": str(row.event_date),
                    "schedule_positive": 0, "start_utc": start, "end_utc": end,
                    "uses_actual_time": 1, "operator": "formal_registry_verified_clear",
                    "queue": "", "record_id": f"{row.registry_id}_CLEAR",
                    "source_url": "", "evidence_tier": str(row.evidence_tier),
                    "scope_requirement": str(row.scope_requirement),
                })
    segments = pd.DataFrame(rows)
    if segments.empty:
        return pd.DataFrame(), segments
    groups = []
    for (admin1, date), group in segments.groupby(["target_admin1", "event_date"], sort=True):
        outage_group = group[group.schedule_positive.eq(1)]
        if outage_group.empty:
            continue
        event_id = f"CAL_{_slug(admin1)}_{str(date).replace('-', '')}"
        groups.append({
            "event_id": event_id, "geo_level": "oblast", "geo_name": admin1,
            "event_date": date, "start_utc": outage_group.start_utc.min(),
            "end_utc": outage_group.end_utc.max(), "segment_n": int(len(outage_group)),
            "explicit_clear_segment_n": int((group.schedule_positive.eq(0)).sum()),
            "actual_time_segment_n": int(outage_group.uses_actual_time.sum()),
            "operators": "|".join(sorted(set(x for x in outage_group.operator if x))),
            "source_record_n": int(outage_group.record_id.nunique()),
            "evidence_tier": str(group.evidence_tier.iloc[0]) if "evidence_tier" in group else "unregistered",
            "scope_requirement": str(group.scope_requirement.iloc[0]) if "scope_requirement" in group else "",
        })
        segments.loc[group.index, "event_id"] = event_id
    events = pd.DataFrame(groups).sort_values(["geo_name", "start_utc"]).reset_index(drop=True)
    # Consecutive daily schedules are one sustained restriction episode, not
    # independent evidence.  Daily windows remain query units, while later
    # aggregation first averages inside this episode identifier.
    events["episode_id"] = ""
    for admin1, index in events.groupby("geo_name").groups.items():
        episode = 0; previous_end = None
        for i in index:
            start, end = events.loc[i, "start_utc"], events.loc[i, "end_utc"]
            if previous_end is not None and start - previous_end > pd.Timedelta(hours=36):
                episode += 1
            events.loc[i, "episode_id"] = f"EP_{_slug(admin1)}_{episode + 1:02d}"
            previous_end = max(previous_end, end) if previous_end is not None else end
    segments = segments.merge(events[["event_id", "episode_id"]], on="event_id", how="inner")
    return events.sort_values(["event_date", "geo_name"]).reset_index(drop=True), segments


def _overlap_cycle_ids(grid: pd.DataFrame, segments: pd.DataFrame, *, cycle_h: float,
                       min_overlap_fraction: float, buffer_minutes: int,
                       schedule_positive: int | None = 1) -> list[int]:
    if schedule_positive is not None and "schedule_positive" in segments:
        segments = segments[segments.schedule_positive.eq(schedule_positive)]
    if segments.empty:
        return []
    mt = pd.to_datetime(grid.measure_time, utc=True)
    cycle_end = mt + pd.Timedelta(hours=cycle_h)
    buffer = pd.Timedelta(minutes=buffer_minutes)
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for _, row in segments.iterrows():
        start = pd.to_datetime(row.start_utc, utc=True) + buffer
        end = pd.to_datetime(row.end_utc, utc=True) - buffer
        if end > start:
            intervals.append((start, end))
    # Queue/operator rows can describe the same state outage interval.  Merge
    # them before measuring overlap so duplicated queues never manufacture a
    # fully treated two-hour cycle.
    merged: list[list[pd.Timestamp]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    overlap = pd.Series(0.0, index=grid.index)
    for start, end in merged:
        left = mt.where(mt > start, start)
        right = cycle_end.where(cycle_end < end, end)
        overlap += ((right - left).dt.total_seconds() / 3600).clip(lower=0)
    keep = overlap.clip(upper=cycle_h).div(cycle_h).ge(min_overlap_fraction)
    keep &= grid.is_complete.astype(bool)
    return grid.loc[keep, "cycle_id"].astype("int64").drop_duplicates().tolist()


def event_cycle_sets(event: pd.Series, segments: pd.DataFrame, grid: pd.DataFrame,
                     cfg: Config, all_outage_ids: set[int]) -> dict[str, list[int]]:
    """Map one regional schedule day to pre/outage/post and matched normal cycles."""
    scfg = cfg.simple_calibration
    cycle_h = float(cfg.study["expected_cycle_interval_hours"])
    outage = _overlap_cycle_ids(
        grid, segments, cycle_h=cycle_h,
        min_overlap_fraction=float(scfg["min_cycle_overlap_fraction"]),
        buffer_minutes=int(scfg["transition_buffer_minutes"]),
    )
    clear = _overlap_cycle_ids(
        grid, segments, cycle_h=cycle_h,
        min_overlap_fraction=float(scfg["min_cycle_overlap_fraction"]), buffer_minutes=0,
        schedule_positive=0)
    if not outage:
        return {k: [] for k in ("normal", "clear", "pre", "outage", "post")}
    mt = pd.to_datetime(grid.measure_time, utc=True)
    start = pd.to_datetime(event.start_utc, utc=True)
    end = pd.to_datetime(event.end_utc, utc=True)
    complete = grid.is_complete.astype(bool)
    pre = grid.loc[complete & mt.ge(start - pd.Timedelta(hours=float(scfg["pre_window_h"]))) & mt.lt(start),
                   "cycle_id"].astype("int64").tolist()
    post = grid.loc[complete & mt.ge(end) & mt.lt(end + pd.Timedelta(hours=float(scfg["post_window_h"]))),
                    "cycle_id"].astype("int64").tolist()
    slots = set(slot_of(grid.loc[grid.cycle_id.isin(outage), "measure_time"], int(cycle_h)).astype(int))
    # Same-weekday, same-slot clean controls may lie on either side of the
    # scheduled window.  Restricting them to the past makes early-study A/A+
    # events structurally inestimable even when later clean observations exist.
    attack_clean = Events(cfg).clean_baseline_mask(grid)
    controls = grid.loc[complete & attack_clean & ~grid.cycle_id.isin(all_outage_ids)].copy()
    controls["slot"] = slot_of(controls.measure_time, int(cycle_h))
    controls = controls[controls.slot.isin(slots)]
    if not controls.empty:
        midpoint = start + (end - start) / 2
        controls["distance"] = (pd.to_datetime(controls.measure_time, utc=True) - midpoint).abs()
        need = max(len(outage), 1) * int(scfg["normal_cycles_per_outage_cycle"])
        normal = controls.sort_values(["distance", "measure_time"]).head(need).cycle_id.astype("int64").tolist()
    else:
        normal = []
    return {"normal": sorted(set(normal)), "clear": sorted(set(clear)), "pre": sorted(set(pre)),
            "outage": sorted(set(outage)), "post": sorted(set(post))}


def score_event_rows(raw: pd.DataFrame, cycle_sets: dict[str, list[int]], cfg: Config) -> pd.DataFrame:
    """Score one state-level planned-outage event without outcome thresholding."""
    d = raw.copy()
    scfg = cfg.simple_calibration
    for phase in ("normal", "clear", "pre", "outage", "post"):
        n = len(cycle_sets.get(phase, []))
        d[f"n_{phase}"] = n
        d[f"p_{phase}"] = pd.to_numeric(d.get(f"x_{phase}", pd.Series(0, index=d.index)), errors="coerce").fillna(0) / max(n, 1)
    if d["n_clear"].eq(0).all():
        d["p_clear"] = np.nan
    # The matched normal cycles, rather than the immediately preceding period,
    # define the registered counterfactual.  ``pre``/``post`` remain diagnostic
    # fields only: a real planned outage can span most of a day.
    d["s_reach_event"] = d.p_normal - d.p_outage
    d["s_reach_explicit_clear"] = d.p_clear - d.p_outage
    d["drop"] = d.p_pre - d.p_outage
    d["recovery"] = d.p_post - d.p_outage
    d["placebo_nonresponse"] = 1.0 - d.p_normal
    normal_rtt = pd.to_numeric(d.get("rtt_normal", pd.Series(np.nan, index=d.index)), errors="coerce")
    outage_rtt = pd.to_numeric(d.get("rtt_outage", pd.Series(np.nan, index=d.index)), errors="coerce")
    d["s_rtt_event"] = (outage_rtt - normal_rtt) / normal_rtt.where(normal_rtt.gt(0))
    clear_rtt = pd.to_numeric(d.get("rtt_clear", pd.Series(np.nan, index=d.index)), errors="coerce")
    d["s_rtt_explicit_clear"] = (outage_rtt - clear_rtt) / clear_rtt.where(clear_rtt.gt(0))
    if d["n_clear"].eq(0).all():
        d["s_rtt_explicit_clear"] = np.nan
    d["rtt_estimable"] = normal_rtt.gt(0) & outage_rtt.notna()
    d["is_event_usable"] = (
        d.n_normal.ge(int(scfg["min_normal_cycles"])) &
        d.n_outage.ge(int(scfg["min_outage_cycles"])) &
        d.p_normal.ge(float(scfg["stable_reach_rate"]))
    )
    # Compatibility alias for downstream readers of early run artifacts.  It
    # now means usable state-level evidence, never a positive/negative label.
    d["is_event_candidate"] = d["is_event_usable"]
    return d


def _prefix_batches(values: list[str], size: int):
    for i in range(0, len(values), size):
        yield values[i:i + size]


def b1_score_parts(data_derived: Path) -> list[str]:
    """Locate baseline-score parts; isolated to keep the real-run entry testable."""
    return sorted(glob.glob(str(data_derived / "ip_sensor_scores_parts" / "part_*.parquet")))


def _query_event(ch: CHClient, cfg: Config, targets: pd.DataFrame,
                 cycles: dict[str, list[int]]) -> pd.DataFrame:
    prefixes = targets.prefix24.dropna().astype(str).drop_duplicates().tolist()
    all_ids = sorted(set().union(*[set(v) for v in cycles.values()]))
    frames = []
    batches = list(_prefix_batches(prefixes, int(cfg.runtime["prefix_batch"])))
    for _, prefix_batch in pbar(list(enumerate(batches, 1)), desc="calibration query", unit="batch"):
        sql = S.render(
            "11_ip_event_signature", ping=cfg.table("ping"), dc=cfg.study["data_center"],
            prefix_in=S.str_list(prefix_batch), cycle_seconds=int(cfg.study["expected_cycle_interval_hours"] * 3600),
            normal_cids=S.int_list(cycles.get("normal", [])), pre_cids=S.int_list(cycles.get("pre", [])),
            outage_cids=S.int_list(cycles.get("outage", [])), post_cids=S.int_list(cycles.get("post", [])),
            clear_cids=S.int_list(cycles.get("clear", [])),
            all_cids=S.int_list(all_ids),
        )
        part = ch.query_df(sql)
        if not part.empty:
            frames.append(part)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    columns = [c for c in ("dst_ip", "prefix24", "target_admin1", "target_city",
                           "target_isp_domain", "target_asn", "network_stratum") if c in targets]
    return out.merge(targets[columns].drop_duplicates(["dst_ip", "prefix24"]),
                     on=["dst_ip", "prefix24"], how="inner", validate="many_to_one")


def _within_state_tertile(frame: pd.DataFrame, column: str, output: str) -> pd.Series:
    """Frozen low/middle/high strata, calculated independently within a state."""
    out = pd.Series(pd.NA, index=frame.index, dtype="string")
    for _, index in frame.groupby("target_admin1").groups.items():
        values = pd.to_numeric(frame.loc[index, column], errors="coerce")
        if values.notna().sum() < 3 or values.nunique(dropna=True) < 3:
            continue
        ranks = values.rank(method="average", pct=True)
        out.loc[index] = pd.cut(ranks, [0, 1 / 3, 2 / 3, 1],
                                labels=["low", "middle", "high"], include_lowest=True).astype("string")
    return out


def aggregate_sensors(candidates: pd.DataFrame) -> pd.DataFrame:
    """Freeze primary and proxy-augmented continuous per-IP sensitivities."""
    if candidates.empty:
        return pd.DataFrame(columns=["dst_ip", "support_event_n", "sensor_score", "is_power_sensitive"])
    usable = candidates.get("is_event_usable", candidates.get("is_event_candidate", False))
    d = candidates[pd.Series(usable, index=candidates.index).astype(bool)].copy()
    if d.empty:
        return pd.DataFrame(columns=["dst_ip", "support_event_n", "sensor_score", "is_power_sensitive"])
    for column in ("s_reach_explicit_clear", "s_rtt_explicit_clear"):
        if column not in d:
            d[column] = np.nan
    if "evidence_tier" not in d:
        # Compatibility for unit fixtures and pre-registry artifacts.
        d["evidence_tier"] = "primary_A"
    identity = [c for c in ("dst_ip", "prefix24", "target_admin1", "target_city",
                            "target_isp_domain", "target_asn", "network_stratum") if c in d]
    # Day windows inside one continuous restriction episode do not add
    # independent evidence.  Collapse them before estimating each IP score.
    if "episode_id" not in d:
        d["episode_id"] = d["event_id"]
    def summarize(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=identity)
        episode = (frame.groupby([*identity, "episode_id"], as_index=False)
                   .agg(s_reach_event=("s_reach_event", "mean"), s_rtt_event=("s_rtt_event", "mean"),
                        s_reach_explicit_clear=("s_reach_explicit_clear", "mean"),
                        s_rtt_explicit_clear=("s_rtt_explicit_clear", "mean"),
                        rtt_estimable=("rtt_estimable", "sum"), p_normal=("p_normal", "mean"),
                        p_outage=("p_outage", "mean"), drop=("drop", "mean"), recovery=("recovery", "mean")))
        return (episode.groupby(identity, as_index=False)
                .agg(support_episode_n=("episode_id", "nunique"),
                     s_reach=("s_reach_event", "mean"), s_reach_median=("s_reach_event", "median"),
                     s_rtt=("s_rtt_event", "mean"), s_rtt_event_n=("rtt_estimable", "sum"),
                     normal_reach=("p_normal", "mean"), outage_reach=("p_outage", "mean"),
                     s_reach_explicit_clear=("s_reach_explicit_clear", "mean"),
                     s_rtt_explicit_clear=("s_rtt_explicit_clear", "mean"),
                     diagnostic_pre_drop=("drop", "mean"), diagnostic_recovery=("recovery", "mean")))

    primary = summarize(d[d.evidence_tier.isin({"primary_A", "primary_Aplus"})])
    augmented = summarize(d)
    # The primary score is the formal estimand.  The augmented score is only a
    # documented robustness contrast that adds operator-service-area evidence.
    summary = augmented.merge(primary, on=identity, how="left", suffixes=("_proxy_augmented", ""))
    if summary.empty:
        return summary
    summary["s_reach_tier"] = _within_state_tertile(summary, "s_reach", "s_reach_tier")
    summary["s_rtt_tier"] = _within_state_tertile(summary, "s_rtt", "s_rtt_tier")
    summary["support_event_n"] = summary["support_episode_n"]
    summary["calibration_design"] = "B1_state_same_weekday_slot_clean_cycle"
    # This flag is intentionally not used for method selection.  It preserves
    # a readable indicator that a score is supported by at least one event.
    summary["is_power_sensitive"] = summary["support_event_n"].fillna(0).gt(0)
    summary["has_primary_score"] = summary["support_event_n"].fillna(0).gt(0)
    summary["has_proxy_augmented_score"] = summary["support_episode_n_proxy_augmented"].fillna(0).gt(0)
    return summary.sort_values(["target_admin1", "s_reach", "dst_ip"], ascending=[True, False, True]).reset_index(drop=True)


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    dd, rt = cfg.out_dir("data_derived"), cfg.out_dir("results_tables")
    universe = pd.read_parquet(dd / "target_ip_universe.parquet")
    targets = universe.copy()
    # Calibration starts only after the label-free B1 stability filter.  This
    # prevents transient/poorly observed endpoints from acquiring a spurious
    # sensitivity score because one schedule window happened to be sparse.
    parts = b1_score_parts(dd)
    if not parts:
        raise RuntimeError("B1 stable pool is required before state sensitivity calibration")
    b1 = pd.concat([pd.read_parquet(p, columns=["dst_ip", "prefix24", "in_B1"]) for p in parts],
                   ignore_index=True)
    b1 = b1[b1.in_B1.astype(bool)].drop_duplicates(["dst_ip", "prefix24"])
    targets = targets.merge(b1[["dst_ip", "prefix24"]], on=["dst_ip", "prefix24"], how="inner")
    targets = targets[targets.get("regional_eligible", pd.Series(False, index=targets.index)).astype(bool)].copy()
    candidate_columns = [c for c in ("dst_ip", "prefix24", "target_admin1", "target_city",
                                     "target_isp_domain", "target_asn", "network_stratum",
                                     "regional_eligible") if c in targets]
    candidate_path = dd / "candidate_ips.parquet"
    targets[candidate_columns].to_parquet(candidate_path, index=False)
    grid = Events(cfg).build_cycle_grid(pd.read_parquet(dd / "cycle_quality.parquet"))
    registry = cfg.load_calibration_event_registry()
    events, segments = build_calibration_events(
        cfg.load_schedule_registry(), set(targets.target_admin1.dropna().astype(str)), registry)
    if events.empty:
        raise RuntimeError("no eligible regional scheduled-outage calibration events")
    event_path = rt / "calibration_events.csv"
    events.to_csv(event_path, index=False, encoding="utf-8-sig")
    cycle_h = float(cfg.study["expected_cycle_interval_hours"])
    # All eligible local planned-outage windows are excluded from matched
    # controls, including records outside the formal calibration whitelist.
    _, all_segments = build_calibration_events(
        cfg.load_schedule_registry(), set(targets.target_admin1.dropna().astype(str)))
    all_outage_ids: set[int] = set()
    for _, group in all_segments.groupby("event_id"):
        all_outage_ids.update(_overlap_cycle_ids(
            grid, group, cycle_h=cycle_h,
            min_overlap_fraction=float(cfg.simple_calibration["min_cycle_overlap_fraction"]),
            buffer_minutes=int(cfg.simple_calibration["transition_buffer_minutes"])))
    cache = dd / "simple_calibration" / "event_sensitivity_v4_registry"
    cache.mkdir(parents=True, exist_ok=True)
    audit_rows, candidate_parts = [], []
    with step("Simple scheduled-outage sensor calibration", logger):
        with CHClient(cfg) as ch:
            for index, event in events.iterrows():
                event_id = str(event.event_id)
                path = cache / f"{event_id}.parquet"
                event_segments = segments[segments.event_id.eq(event_id)]
                cycles = event_cycle_sets(event, event_segments, grid, cfg, all_outage_ids)
                region_targets = targets[targets.target_admin1.eq(event.geo_name)]
                # Pre/post windows diagnose transition and recovery only. They
                # do not identify S_i = matched-normal reach minus outage reach.
                estimable = (len(cycles["normal"]) >= int(cfg.simple_calibration["min_normal_cycles"]) and
                             len(cycles["outage"]) >= int(cfg.simple_calibration["min_outage_cycles"]) and
                             not region_targets.empty)
                selected = pd.DataFrame()
                if estimable:
                    if path.exists() and path.stat().st_size:
                        selected = pd.read_parquet(path)
                    else:
                        raw = _query_event(ch, cfg, region_targets, cycles)
                        if not raw.empty:
                            scored = score_event_rows(raw, cycles, cfg)
                            scored["event_id"] = event_id
                            scored["episode_id"] = event.episode_id
                            scored["evidence_tier"] = event.evidence_tier
                            scored["pre_reach"] = scored.p_pre
                            scored["outage_reach"] = scored.p_outage
                            scored["post_reach"] = scored.p_post
                            selected = scored[scored.is_event_usable].copy()
                        selected.to_parquet(path, index=False)
                if not selected.empty:
                    candidate_parts.append(selected)
                audit_rows.append({
                    "event_id": event_id, "geo_name": event.geo_name,
                    "normal_cycle_n": len(cycles["normal"]), "pre_cycle_n": len(cycles["pre"]),
                    "outage_cycle_n": len(cycles["outage"]), "post_cycle_n": len(cycles["post"]),
                    "explicit_clear_cycle_n": len(cycles["clear"]), "episode_id": event.episode_id,
                    "evidence_tier": event.evidence_tier, "scope_requirement": event.scope_requirement,
                    "candidate_ip_pool_n": int(region_targets.dst_ip.nunique()),
                    "scored_stable_ip_n": int(selected.dst_ip.nunique()) if not selected.empty else 0,
                    "estimable": int(estimable), "event_index": int(index + 1),
                })
                logger.info("calibration event %d/%d %s estimable=%s scored_stable=%d",
                            index + 1, len(events), event_id, estimable,
                            0 if selected.empty else selected.dst_ip.nunique())
    candidates = pd.concat(candidate_parts, ignore_index=True) if candidate_parts else pd.DataFrame()
    sensors = aggregate_sensors(candidates)
    sensor_path = dd / "calibrated_sensors.parquet"
    sensors.to_parquet(sensor_path, index=False)
    sensors.to_csv(rt / "calibrated_sensors.csv", index=False, encoding="utf-8-sig")
    # Preserve one transparent state for every measured endpoint.  Missing S_i
    # is never silently recoded as zero or as electrical insensitivity.
    label_columns = [c for c in ("dst_ip", "prefix24", "target_admin1", "target_city", "target_asn",
                                 "network_stratum", "regional_eligible") if c in universe]
    labels = universe[label_columns].drop_duplicates(["dst_ip", "prefix24"])
    labels = labels.merge(b1.assign(in_B1=1)[["dst_ip", "prefix24", "in_B1"]],
                          on=["dst_ip", "prefix24"], how="left")
    labels["in_B1"] = labels.in_B1.fillna(0).astype("int8")
    score_columns = [c for c in sensors.columns if c not in {"target_city", "target_asn", "network_stratum"}]
    labels = labels.merge(sensors[score_columns].drop_duplicates(["dst_ip", "prefix24"]),
                          on=["dst_ip", "prefix24", "target_admin1"], how="left")
    labels["sensitivity_status"] = np.select(
        [labels.in_B1.eq(0), ~labels.get("regional_eligible", pd.Series(False, index=labels.index)).astype(bool),
         labels.get("has_primary_score", pd.Series(False, index=labels.index)).fillna(False),
         labels.get("has_proxy_augmented_score", pd.Series(False, index=labels.index)).fillna(False)],
        ["not_B1_stable", "not_regional", "primary_estimable", "proxy_only_estimable"],
        default="no_registered_event_support")
    label_path = dd / "ip_sensitivity_labels.parquet"
    labels.to_parquet(label_path, index=False)
    labels.to_csv(rt / "ip_sensitivity_labels.csv", index=False, encoding="utf-8-sig")
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(rt / "calibration_event_audit.csv", index=False, encoding="utf-8-sig")
    summary = {
        "candidate_ip_n": int(targets.dst_ip.nunique()), "calibration_event_n": int(len(events)),
        "estimable_event_n": int(audit.estimable.sum()), "calibrated_sensor_n": int(len(sensors)),
        "all_ip_label_n": int(len(labels)),
        "primary_sensor_n": int(sensors.has_primary_score.sum()) if not sensors.empty else 0,
        "proxy_augmented_sensor_n": int(sensors.has_proxy_augmented_score.sum()) if not sensors.empty else 0,
        "repeated_support_ip_n": int(sensors.support_event_n.ge(2).sum()) if not sensors.empty else 0,
        "claim_scope": "frozen continuous state-level planned-outage sensitivity; not IP-level electrical ground truth",
    }
    summary_path = rt / "calibration_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok" if len(sensors) else "warning",
            "outputs": [str(candidate_path), str(event_path), str(sensor_path), str(label_path),
                        str(rt / "calibrated_sensors.csv"), str(rt / "ip_sensitivity_labels.csv"), str(rt / "calibration_event_audit.csv"),
                        str(summary_path)], **summary}
