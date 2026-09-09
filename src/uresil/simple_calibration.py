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


def build_final_calibration_events(cfg: Config, valid_admin1: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build frozen calibration units directly from the reviewed Excel workbook.

    This is deliberately separate from ``build_calibration_events``: no legacy
    schedule eligibility field or inferred episode can enter the v5 estimand.
    """
    event_book, segment_book = cfg.load_final_calibration_input()
    cutoff = pd.to_datetime(cfg.study["measurement_start_utc"], utc=True)
    valid = set(valid_admin1 or [])
    event_book = event_book[event_book.measurement_start_ok.eq(1)].copy()
    event_book = event_book[(event_book.use_main.eq(1)) | (event_book.use_augmented.eq(1))].copy()
    if valid:
        event_book = event_book[event_book.state_en.astype(str).isin(valid)].copy()
    # An event that begins before active measurement is an audit record only,
    # never a calibration unit.  Keeping this boundary here also protects B1
    # and control selection when a workbook is revised later.
    event_book = event_book[pd.to_datetime(event_book.outage_start_utc, utc=True, errors="coerce").ge(cutoff)].copy()
    segments = segment_book[segment_book.event_id.astype(str).isin(event_book.event_id.astype(str))].copy()
    segments = segments[segments.segment_type.isin(["outage", "explicit_clear"])].copy()
    segments = segments[segments.start_utc.ge(cutoff)].copy()
    if valid:
        segments = segments[segments.state_en.astype(str).isin(valid)].copy()
    if segments.empty:
        return pd.DataFrame(), pd.DataFrame()
    segments = segments.rename(columns={"state_en": "target_admin1"})
    segments["schedule_positive"] = segments.segment_type.eq("outage").astype("int8")
    segments["event_date"] = segments.event_date.astype(str)
    groups = []
    for event_id, group in segments.groupby("event_id", sort=True):
        outage = group[group.schedule_positive.eq(1)]
        if outage.empty:
            continue
        book = event_book[event_book.event_id.astype(str).eq(str(event_id))]
        if book.empty:
            continue
        row = book.iloc[0]
        groups.append({
            "event_id": str(event_id), "geo_level": str(row.get("geo_level", "oblast")),
            "geo_name": str(row.state_en), "event_date": str(row.event_date),
            "start_utc": outage.start_utc.min(), "end_utc": outage.end_utc.max(),
            "segment_n": int(len(outage)),
            "explicit_clear_segment_n": int(group.segment_type.eq("explicit_clear").sum()),
            "source_record_n": int(outage.segment_id.nunique()),
            "evidence_tier": str(row.evidence_tier), "quality": str(row.get("quality", "")),
            "use_main": int(row.use_main), "use_augmented": int(row.use_augmented),
            "episode_id_main": str(row.episode_id_main or ""),
            "episode_id_augmented": str(row.episode_id_augmented or ""),
            "measurement_start_utc": cutoff,
        })
    events = pd.DataFrame(groups)
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
    # Normal activity is a covariate, not an admission gate.  Keep the old
    # response-rate rule as a diagnostic flag only; low-Activity endpoints are
    # part of the estimand and must remain eligible when cycle support exists.
    d["legacy_stable_normal"] = d.p_normal.ge(float(scfg.get("stable_reach_rate", 0.8)))
    d["is_event_candidate"] = (
        d.n_normal.ge(int(scfg["min_normal_cycles"])) &
        d.n_outage.ge(int(scfg["min_outage_cycles"]))
    )
    # Legacy readers/tests still consume is_event_usable as the old stable
    # diagnostic.  The formal pipeline uses is_event_candidate, so Activity
    # below 0.8 is retained in the primary estimand rather than filtered.
    d["is_event_usable"] = d["is_event_candidate"] & d["legacy_stable_normal"]
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


def _within_state_quantile(frame: pd.DataFrame, column: str, q: int, output: str) -> pd.Series:
    """Assign descriptive within-state quantiles without filtering endpoints."""
    out = pd.Series(pd.NA, index=frame.index, dtype="string")
    for _, index in frame.groupby("target_admin1").groups.items():
        values = pd.to_numeric(frame.loc[index, column], errors="coerce")
        if values.notna().sum() < q or values.nunique(dropna=True) < q:
            continue
        ranks = values.rank(method="average", pct=True)
        labels = [f"Q{i}" for i in range(1, q + 1)]
        out.loc[index] = pd.cut(ranks, [i / q for i in range(q + 1)],
                                labels=labels, include_lowest=True).astype("string")
    return out


def _within_state_tertile(frame: pd.DataFrame, column: str, output: str) -> pd.Series:
    """Backward-compatible legacy tertile labels."""
    out = _within_state_quantile(frame, column, 3, output)
    return out.map({"Q1": "low", "Q2": "middle", "Q3": "high"}).astype("string")


def aggregate_sensors(candidates: pd.DataFrame) -> pd.DataFrame:
    """Freeze distinct P1 and P1+P2 continuous per-IP sensitivities."""
    if candidates.empty:
        return pd.DataFrame(columns=["dst_ip", "support_episode_n", "s_reach_primary", "s_rtt_primary", "s_reach_augmented", "s_rtt_augmented"])
    usable = candidates.get("is_event_candidate", candidates.get("is_event_usable", False))
    d = candidates[pd.Series(usable, index=candidates.index).astype(bool)].copy()
    if d.empty:
        return pd.DataFrame(columns=["dst_ip", "support_episode_n", "s_reach_primary", "s_rtt_primary", "s_reach_augmented", "s_rtt_augmented"])
    for column in ("s_reach_explicit_clear", "s_rtt_explicit_clear"):
        if column not in d:
            d[column] = np.nan
    if "use_main" not in d:
        d["use_main"] = 1
    if "use_augmented" not in d:
        d["use_augmented"] = 1
    identity = [c for c in ("dst_ip", "prefix24", "target_admin1", "target_city",
                            "target_isp_domain", "target_asn", "network_stratum") if c in d]
    # Day windows inside one continuous restriction episode do not add
    # independent evidence.  Collapse them before estimating each IP score.
    def summarize(frame: pd.DataFrame, episode_column: str, suffix: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=identity)
        if episode_column not in frame:
            frame[episode_column] = frame["event_id"]
        frame["episode_id"] = frame[episode_column].replace("", pd.NA).fillna(frame["event_id"])
        episode = (frame.groupby([*identity, "episode_id"], as_index=False)
                   .agg(s_reach_event=("s_reach_event", "mean"), s_rtt_event=("s_rtt_event", "mean"),
                        s_reach_explicit_clear=("s_reach_explicit_clear", "mean"),
                        s_rtt_explicit_clear=("s_rtt_explicit_clear", "mean"),
                        rtt_estimable=("rtt_estimable", "sum"), p_normal=("p_normal", "mean"),
                        p_outage=("p_outage", "mean"), drop=("drop", "mean"), recovery=("recovery", "mean")))
        episode = episode.rename(columns={"episode_id": episode_column})
        out = (episode.groupby(identity, as_index=False)
                .agg(support_episode_n=(episode_column, "nunique"),
                     s_reach=("s_reach_event", "mean"), s_reach_median=("s_reach_event", "median"),
                     s_rtt=("s_rtt_event", "mean"), s_rtt_event_n=("rtt_estimable", "sum"),
                     normal_reach=("p_normal", "mean"), outage_reach=("p_outage", "mean"),
                     s_reach_explicit_clear=("s_reach_explicit_clear", "mean"),
                     s_rtt_explicit_clear=("s_rtt_explicit_clear", "mean"),
                     diagnostic_pre_drop=("drop", "mean"), diagnostic_recovery=("recovery", "mean")))
        return out.rename(columns={c: f"{c}_{suffix}" for c in out.columns if c not in identity})

    primary = summarize(d[d.use_main.eq(1)].copy(), "episode_id_main", "primary")
    augmented = summarize(d[d.use_augmented.eq(1)].copy(), "episode_id_augmented", "augmented")
    summary = primary.merge(augmented, on=identity, how="outer")
    if summary.empty:
        return summary
    summary["s_reach_quintile"] = _within_state_quantile(summary, "s_reach_primary", 5, "s_reach_quintile")
    summary["s_rtt_quintile"] = _within_state_quantile(summary, "s_rtt_primary", 5, "s_rtt_quintile")
    # Legacy aliases are preserved for old readers, but Q1--Q5 are canonical.
    summary["s_reach_tier"] = _within_state_tertile(summary, "s_reach_primary", "s_reach_tier")
    summary["s_rtt_tier"] = _within_state_tertile(summary, "s_rtt_primary", "s_rtt_tier")
    summary["support_episode_n"] = summary["support_episode_n_primary"]
    summary["support_event_n"] = summary["support_episode_n_primary"]
    summary["calibration_design"] = "all_activity_supported_state_same_weekday_slot_clean_cycle"
    # This flag is intentionally not used for method selection.  It preserves
    # a readable indicator that a score is supported by at least one event.
    summary["has_primary_score"] = summary["s_reach_primary"].notna()
    summary["has_augmented_score"] = summary["s_reach_augmented"].notna()
    # Aliases keep downstream attack-panel readers compatible; they always use
    # the formal P1 score and never create a binary electrical label.
    summary["s_reach"] = summary["s_reach_primary"]
    summary["s_rtt"] = summary["s_rtt_primary"]
    summary["has_proxy_augmented_score"] = summary["has_augmented_score"]
    return summary.sort_values(["target_admin1", "s_reach_primary", "dst_ip"], ascending=[True, False, True]).reset_index(drop=True)


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs")); dd, rt = cfg.out_dir("data_derived"), cfg.out_dir("results_tables")
    universe = pd.read_parquet(dd / "target_ip_universe.parquet")
    parts = b1_score_parts(dd)
    if not parts: raise RuntimeError("endpoint score parts are required before calibration")
    # Canonical sensitivity population: every regional target with sufficient
    # clean-cycle support.  Do not apply the legacy response-rate B1 gate.
    support = pd.concat([pd.read_parquet(p, columns=["dst_ip", "prefix24", "activity_estimable",
                                                       "activity_score_raw", "activity_score_smoothed",
                                                       "n_normal", "x_normal"])
                         for p in parts], ignore_index=True)
    support = support[support.activity_estimable.astype(bool)].drop_duplicates(["dst_ip", "prefix24"])
    targets = universe.merge(support[["dst_ip", "prefix24"]], on=["dst_ip", "prefix24"], how="inner")
    targets = targets[targets.regional_eligible.astype(bool)].copy()
    candidate_path = dd / "candidate_ips.parquet"; targets.to_parquet(candidate_path, index=False)
    grid = Events(cfg).build_cycle_grid(pd.read_parquet(dd / "cycle_quality.parquet"))
    events, segments = build_final_calibration_events(cfg, set(targets.target_admin1.dropna().astype(str)))
    if events.empty: raise RuntimeError("no reviewed P1/P2 calibration events after measurement boundary")
    events.to_csv(rt / "calibration_events.csv", index=False, encoding="utf-8-sig")
    cycle_h = float(cfg.study["expected_cycle_interval_hours"]); all_outage_ids: set[int] = set()
    for _, group in segments[segments.schedule_positive.eq(1)].groupby("event_id"):
        all_outage_ids.update(_overlap_cycle_ids(grid, group, cycle_h=cycle_h, min_overlap_fraction=float(cfg.simple_calibration["min_cycle_overlap_fraction"]), buffer_minutes=int(cfg.simple_calibration["transition_buffer_minutes"])))
    cache = dd / "simple_calibration" / "event_sensitivity_v5_excel"; cache.mkdir(parents=True, exist_ok=True)
    force = bool(cfg.raw.get("_runtime_flags", {}).get("force_stage_recompute", False))
    audit_rows, candidate_parts = [], []
    with step("Reviewed Excel planned-outage calibration", logger):
        with CHClient(cfg) as ch:
            for index, event in events.iterrows():
                event_id = str(event.event_id); event_segments = segments[segments.event_id.astype(str).eq(event_id)]
                cycles = event_cycle_sets(event, event_segments, grid, cfg, all_outage_ids)
                region_targets = targets[targets.target_admin1.eq(event.geo_name)]
                reasons = []
                if region_targets.empty: reasons.append("no_activity_supported_ip_for_state")
                if len(cycles["outage"]) < int(cfg.simple_calibration["min_outage_cycles"]): reasons.append("insufficient_outage_cycles")
                if len(cycles["normal"]) < int(cfg.simple_calibration["min_normal_cycles"]): reasons.append("insufficient_normal_controls")
                estimable = not reasons; selected = pd.DataFrame(); path = cache / f"{event_id}.parquet"
                if estimable:
                    if path.exists() and path.stat().st_size and not force: selected = pd.read_parquet(path)
                    else:
                        raw = _query_event(ch, cfg, region_targets, cycles)
                        if not raw.empty:
                            scored = score_event_rows(raw, cycles, cfg)
                            scored["event_id"] = event_id
                            for col in ("use_main", "use_augmented", "episode_id_main", "episode_id_augmented", "evidence_tier"):
                                scored[col] = event[col]
                            selected = scored[scored.is_event_candidate].copy()
                        selected.to_parquet(path, index=False)
                    # Old cache parts are still valid expensive query results;
                    # restore immutable event metadata before episode reduction.
                    if not selected.empty:
                        selected["event_id"] = event_id
                        for col in ("use_main", "use_augmented", "episode_id_main", "episode_id_augmented", "evidence_tier"):
                            selected[col] = event[col]
                if not selected.empty: candidate_parts.append(selected)
                audit_rows.append({"event_id": event_id, "geo_name": event.geo_name, "event_date": event.event_date,
                    "use_main": event.use_main, "use_augmented": event.use_augmented, "episode_id_main": event.episode_id_main,
                    "episode_id_augmented": event.episode_id_augmented, "normal_cycle_n": len(cycles["normal"]),
                    "outage_cycle_n": len(cycles["outage"]), "explicit_clear_cycle_n": len(cycles["clear"]),
                    "pre_cycle_n": len(cycles["pre"]), "post_cycle_n": len(cycles["post"]),
                    "candidate_ip_pool_n": int(region_targets.dst_ip.nunique()), "scored_stable_ip_n": int(selected.dst_ip.nunique()) if not selected.empty else 0,
                    "sensitivity_estimable": int(estimable), "recovery_estimable": int(len(cycles["post"]) >= int(cfg.simple_calibration["min_post_cycles"])),
                    "not_estimable_reason": "|".join(reasons), "measurement_start_utc": cfg.study["measurement_start_utc"]})
    candidates = pd.concat(candidate_parts, ignore_index=True) if candidate_parts else pd.DataFrame()
    # Explicit research-plan artifacts.  These are separate from the legacy
    # B1-named files so downstream paper code cannot confuse diagnostics with
    # the canonical population.
    if candidates.empty:
        pd.DataFrame().to_parquet(dd / "ip_event_sensitivity.parquet", index=False)
    else:
        candidates.to_parquet(dd / "ip_event_sensitivity.parquet", index=False)
    sensors = aggregate_sensors(candidates); sensor_path = dd / "calibrated_sensors.parquet"; sensors.to_parquet(sensor_path, index=False)
    audit = pd.DataFrame(audit_rows); audit.to_csv(rt / "calibration_event_audit.csv", index=False, encoding="utf-8-sig")
    episode_audit = pd.concat([audit[audit.use_main.eq(1)].groupby(["geo_name", "episode_id_main"], as_index=False).agg(event_n=("event_id", "nunique"), estimable_event_n=("sensitivity_estimable", "sum")).assign(analysis="primary"), audit[audit.use_augmented.eq(1)].groupby(["geo_name", "episode_id_augmented"], as_index=False).agg(event_n=("event_id", "nunique"), estimable_event_n=("sensitivity_estimable", "sum")).assign(analysis="augmented")], ignore_index=True)
    episode_audit.to_csv(rt / "calibration_episode_audit.csv", index=False, encoding="utf-8-sig")
    labels = targets[[c for c in ("dst_ip", "prefix24", "target_admin1", "target_city", "target_asn", "network_stratum") if c in targets]].drop_duplicates(["dst_ip", "prefix24"]).copy(); labels["in_B1"] = 1
    labels = labels.merge(support[["dst_ip", "prefix24", "activity_score_raw", "activity_score_smoothed",
                                   "n_normal", "x_normal"]], on=["dst_ip", "prefix24"], how="left", validate="one_to_one")
    labels = labels.merge(sensors, on=["dst_ip", "prefix24", "target_admin1"], how="left", suffixes=("", "_score"))
    # Activity is a continuous covariate.  Deciles are descriptive, within
    # Admin1, and never used as a population gate.  States with fewer than ten
    # distinct estimable values remain explicitly ungrouped (NA).
    labels["activity_decile"] = _within_state_quantile(
        labels, "activity_score_raw", int(cfg.raw.get("ip_activity", {}).get("quantiles", 10)),
        "activity_decile")
    min_events = int(cfg.raw.get("ip_sensitivity", {}).get("min_independent_events",
                        cfg.simple_calibration.get("min_independent_events", 3)))
    support_n = pd.to_numeric(labels.get("support_episode_n_primary", pd.Series(np.nan, index=labels.index)), errors="coerce")
    labels["support_ge_2"] = support_n.ge(2).fillna(False)
    labels["support_ge_3"] = support_n.ge(3).fillna(False)
    labels["support_ge_4"] = support_n.ge(4).fillna(False)
    labels["primary_estimable"] = labels.s_reach_primary.notna() & support_n.ge(min_events).fillna(False)
    aug_support_n = pd.to_numeric(labels.get("support_episode_n_augmented", pd.Series(np.nan, index=labels.index)), errors="coerce")
    labels["augmented_estimable"] = labels.s_reach_augmented.notna() & aug_support_n.ge(min_events).fillna(False)
    p1_states = set(events.loc[events.use_main.eq(1), "geo_name"]); p2_states = set(events.loc[events.use_augmented.eq(1), "geo_name"])
    labels["not_estimable_reason"] = np.where(labels.primary_estimable, "", np.where(~labels.target_admin1.isin(p1_states), "no_calibration_event_for_state", "insufficient_measurement_support"))
    labels["augmented_not_estimable_reason"] = np.where(labels.augmented_estimable, "", np.where(~labels.target_admin1.isin(p2_states), "no_calibration_event_for_state", "insufficient_measurement_support"))
    labels.to_parquet(rt / "b1_full_sensitivity_labels.parquet", index=False); labels.to_csv(rt / "b1_full_sensitivity_labels.csv", index=False, encoding="utf-8-sig")
    labels.to_parquet(dd / "ip_activity.parquet", index=False)
    labels[labels.primary_estimable].to_parquet(dd / "ip_sensitivity.parquet", index=False)
    primary = labels[labels.primary_estimable].copy(); augmented = labels[labels.augmented_estimable].copy(); primary.to_csv(rt / "calibrated_sensitivity_primary.csv", index=False, encoding="utf-8-sig"); augmented.to_csv(rt / "calibrated_sensitivity_augmented.csv", index=False, encoding="utf-8-sig")
    state_summary = labels.groupby("target_admin1", dropna=False).agg(
        activity_supported_ip_n=("dst_ip", "nunique"),
        primary_ip_n=("primary_estimable", "sum"),
        augmented_ip_n=("augmented_estimable", "sum"),
        support_ge_2_ip_n=("support_ge_2", "sum"),
        support_ge_3_ip_n=("support_ge_3", "sum"),
        support_ge_4_ip_n=("support_ge_4", "sum"),
        s_reach_primary_mean=("s_reach_primary", "mean"),
        s_reach_augmented_mean=("s_reach_augmented", "mean"),
    ).reset_index()
    state_summary["b1_ip_n_legacy"] = state_summary["activity_supported_ip_n"]
    state_summary.to_csv(rt / "state_sensitivity_summary.csv", index=False, encoding="utf-8-sig")
    funnel = pd.DataFrame([{"stage":"raw_ip", "n": universe.dst_ip.nunique()}, {"stage":"regional_ip", "n": universe[universe.regional_eligible.astype(bool)].dst_ip.nunique()}, {"stage":"activity_supported_ip", "n": labels.dst_ip.nunique()}, {"stage":"activity_supported_with_P1_state", "n": labels[labels.target_admin1.isin(p1_states)].dst_ip.nunique()}, {"stage":"P1_estimable", "n": int(labels.primary_estimable.sum())}, {"stage":"activity_supported_with_P1P2_state", "n": labels[labels.target_admin1.isin(p2_states)].dst_ip.nunique()}, {"stage":"P1P2_estimable", "n": int(labels.augmented_estimable.sum())}]); funnel.to_csv(rt / "calibration_funnel.csv", index=False, encoding="utf-8-sig")
    labels.loc[~labels.primary_estimable].groupby("not_estimable_reason").size().reset_index(name="ip_n").to_csv(rt / "calibration_not_estimable_reasons.csv", index=False, encoding="utf-8-sig")
    both = labels[labels.primary_estimable & labels.augmented_estimable].copy()
    robust_rows = []
    for state, x in both.groupby("target_admin1"):
        robust_rows.append({"target_admin1": state, "ip_n": len(x), "pearson_r": x.s_reach_primary.corr(x.s_reach_augmented), "spearman_rho": x.s_reach_primary.corr(x.s_reach_augmented, method="spearman"), "tier_agreement": (x.s_reach_tier == _within_state_tertile(x, "s_reach_augmented", "tmp")).mean()})
    pd.DataFrame(robust_rows).to_csv(rt / "primary_vs_augmented_robustness.csv", index=False, encoding="utf-8-sig")
    summary = {"raw_ip_n": int(universe.dst_ip.nunique()), "b1_ip_n": int(len(labels)), "calibration_event_n": int(len(events)), "primary_sensor_n": int(labels.primary_estimable.sum()), "augmented_sensor_n": int(labels.augmented_estimable.sum())}; (rt / "calibration_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"status": "ok", "outputs": [str(rt / x) for x in ("calibration_event_audit.csv", "calibration_episode_audit.csv", "b1_full_sensitivity_labels.csv", "calibrated_sensitivity_primary.csv", "calibrated_sensitivity_augmented.csv", "state_sensitivity_summary.csv", "calibration_funnel.csv", "primary_vs_augmented_robustness.csv")] + [str(dd / x) for x in ("ip_activity.parquet", "ip_event_sensitivity.parquet", "ip_sensitivity.parquet")], **summary}
