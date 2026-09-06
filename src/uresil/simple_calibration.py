"""Simple weak-supervision calibration from regional scheduled outages.

The selector deliberately does not infer an IP's power operator or queue.  A
regional schedule is only a candidate exposure window.  An endpoint is retained
when it is stable before the window, loses reachability inside the window, and
recovers afterwards.  Independent unplanned energy shocks provide the external
validation in later pipeline stages.
"""
from __future__ import annotations

import json
import re
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
                             valid_admin1: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one event per Admin1-date plus its exact schedule segments.

    Multiple queue/operator rows on the same day are unioned at cycle-mapping
    time.  Operator and queue values remain provenance only and never define IP
    membership.
    """
    d = schedule.copy()
    eligible = _flag(d, "analysis_eligible", 1).eq(1)
    eligible &= _flag(d, "publication_eligible", 1).eq(1)
    eligible &= _flag(d, "confound_free", 1).eq(1)
    if "schedule_positive" in d:
        eligible &= d["schedule_positive"].astype(bool)
    if "scope_type_norm" in d:
        scope = d["scope_type_norm"].astype(str).str.lower()
    else:
        scope = d.get("scope_type", pd.Series("", index=d.index)).astype(str).str.lower()
    d = d[eligible & ~scope.eq("national")].copy()
    d["scope_type_norm"] = scope.loc[d.index]
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
        for admin1 in regions:
            rows.append({
                "target_admin1": admin1, "event_date": date,
                "start_utc": start, "end_utc": end,
                "uses_actual_time": int(has_actual),
                "operator": str(row.get("operator", "") or ""),
                "queue": str(row.get("queue_id", row.get("queue_ids_merged", "")) or ""),
                "record_id": str(row.get("record_id", row.get("segment_id", "")) or ""),
                "source_url": str(row.get("verified_source_url", row.get("source_url", "")) or ""),
            })
    segments = pd.DataFrame(rows)
    if segments.empty:
        return pd.DataFrame(), segments
    groups = []
    for (admin1, date), group in segments.groupby(["target_admin1", "event_date"], sort=True):
        event_id = f"CAL_{_slug(admin1)}_{str(date).replace('-', '')}"
        groups.append({
            "event_id": event_id, "geo_level": "oblast", "geo_name": admin1,
            "event_date": date, "start_utc": group.start_utc.min(),
            "end_utc": group.end_utc.max(), "segment_n": int(len(group)),
            "actual_time_segment_n": int(group.uses_actual_time.sum()),
            "operators": "|".join(sorted(set(x for x in group.operator if x))),
            "source_record_n": int(group.record_id.nunique()),
        })
        segments.loc[group.index, "event_id"] = event_id
    return pd.DataFrame(groups).sort_values(["event_date", "geo_name"]).reset_index(drop=True), segments


def _overlap_cycle_ids(grid: pd.DataFrame, segments: pd.DataFrame, *, cycle_h: float,
                       min_overlap_fraction: float, buffer_minutes: int) -> list[int]:
    if segments.empty:
        return []
    mt = pd.to_datetime(grid.measure_time, utc=True)
    cycle_end = mt + pd.Timedelta(hours=cycle_h)
    overlap = pd.Series(0.0, index=grid.index)
    buffer = pd.Timedelta(minutes=buffer_minutes)
    for _, row in segments.iterrows():
        start = pd.to_datetime(row.start_utc, utc=True) + buffer
        end = pd.to_datetime(row.end_utc, utc=True) - buffer
        if end <= start:
            continue
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
    if not outage:
        return {k: [] for k in ("normal", "pre", "outage", "post")}
    mt = pd.to_datetime(grid.measure_time, utc=True)
    start = pd.to_datetime(event.start_utc, utc=True)
    end = pd.to_datetime(event.end_utc, utc=True)
    complete = grid.is_complete.astype(bool)
    pre = grid.loc[complete & mt.ge(start - pd.Timedelta(hours=float(scfg["pre_window_h"]))) & mt.lt(start),
                   "cycle_id"].astype("int64").tolist()
    post = grid.loc[complete & mt.ge(end) & mt.lt(end + pd.Timedelta(hours=float(scfg["post_window_h"]))),
                    "cycle_id"].astype("int64").tolist()
    slots = set(slot_of(grid.loc[grid.cycle_id.isin(outage), "measure_time"], int(cycle_h)).astype(int))
    before = grid.loc[complete & mt.lt(start) & ~grid.cycle_id.isin(all_outage_ids)].copy()
    before["slot"] = slot_of(before.measure_time, int(cycle_h))
    before = before[before.slot.isin(slots)]
    if not before.empty:
        before["distance"] = (pd.to_datetime(before.measure_time, utc=True) - start).abs()
        need = max(len(outage), 1) * int(scfg["normal_cycles_per_outage_cycle"])
        normal = before.sort_values(["distance", "measure_time"]).head(need).cycle_id.astype("int64").tolist()
    else:
        normal = []
    return {"normal": sorted(set(normal)), "pre": sorted(set(pre)),
            "outage": sorted(set(outage)), "post": sorted(set(post))}


def score_event_rows(raw: pd.DataFrame, cycle_sets: dict[str, list[int]], cfg: Config) -> pd.DataFrame:
    """Apply the frozen single-event stable-drop-recovery rule."""
    d = raw.copy()
    scfg = cfg.simple_calibration
    for phase in ("normal", "pre", "outage", "post"):
        n = len(cycle_sets[phase])
        d[f"n_{phase}"] = n
        d[f"p_{phase}"] = pd.to_numeric(d[f"x_{phase}"], errors="coerce").fillna(0) / max(n, 1)
    d["drop"] = d.p_pre - d.p_outage
    d["recovery"] = d.p_post - d.p_outage
    d["signature"] = d[["drop", "recovery"]].min(axis=1)
    d["placebo_nonresponse"] = 1.0 - d.p_normal
    enough = (d.n_normal.ge(int(scfg["min_normal_cycles"])) &
              d.n_pre.ge(int(scfg["min_pre_cycles"])) &
              d.n_outage.ge(int(scfg["min_outage_cycles"])) &
              d.n_post.ge(int(scfg["min_post_cycles"])))
    d["is_event_candidate"] = (
        enough & d.p_normal.ge(float(scfg["stable_reach_rate"])) &
        d.p_pre.ge(float(scfg["stable_reach_rate"])) &
        d["drop"].ge(float(scfg["min_drop"])) &
        d["recovery"].ge(float(scfg["min_recovery"])) &
        d["placebo_nonresponse"].le(float(scfg["max_placebo_nonresponse"]))
    )
    return d


def _prefix_batches(values: list[str], size: int):
    for i in range(0, len(values), size):
        yield values[i:i + size]


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
            normal_cids=S.int_list(cycles["normal"]), pre_cids=S.int_list(cycles["pre"]),
            outage_cids=S.int_list(cycles["outage"]), post_cids=S.int_list(cycles["post"]),
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


def aggregate_sensors(candidates: pd.DataFrame) -> pd.DataFrame:
    """Collapse event candidates to one auditable row per calibrated endpoint."""
    if candidates.empty:
        return pd.DataFrame(columns=["dst_ip", "support_event_n", "sensor_score", "is_power_sensitive"])
    d = candidates[candidates.is_event_candidate.astype(bool)].copy()
    if d.empty:
        return pd.DataFrame(columns=["dst_ip", "support_event_n", "sensor_score", "is_power_sensitive"])
    strongest = d.sort_values(["dst_ip", "signature"], ascending=[True, False]).drop_duplicates("dst_ip")
    summary = (d.groupby("dst_ip", as_index=False)
               .agg(support_event_n=("event_id", "nunique"),
                    median_drop=("drop", "median"), median_recovery=("recovery", "median"),
                    sensor_score=("signature", "max")))
    keep = [c for c in ("dst_ip", "prefix24", "target_admin1", "target_city",
                        "target_isp_domain", "target_asn", "network_stratum", "event_id",
                        "pre_reach", "outage_reach", "post_reach", "drop", "recovery") if c in strongest]
    strongest = strongest[keep].rename(columns={"event_id": "calibration_event_id",
                                                "drop": "strongest_drop",
                                                "recovery": "strongest_recovery"})
    out = strongest.merge(summary, on="dst_ip", how="inner", validate="one_to_one")
    out["is_power_sensitive"] = True
    return out.sort_values(["sensor_score", "dst_ip"], ascending=[False, True]).reset_index(drop=True)


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    dd, rt = cfg.out_dir("data_derived"), cfg.out_dir("results_tables")
    targets = pd.read_parquet(dd / "target_ip_universe.parquet")
    targets = targets[targets.get("regional_eligible", pd.Series(False, index=targets.index)).astype(bool)].copy()
    candidate_columns = [c for c in ("dst_ip", "prefix24", "target_admin1", "target_city",
                                     "target_isp_domain", "target_asn", "network_stratum",
                                     "regional_eligible") if c in targets]
    candidate_path = dd / "candidate_ips.parquet"
    targets[candidate_columns].to_parquet(candidate_path, index=False)
    grid = Events(cfg).build_cycle_grid(pd.read_parquet(dd / "cycle_quality.parquet"))
    events, segments = build_calibration_events(
        cfg.load_schedule_registry(), set(targets.target_admin1.dropna().astype(str)))
    if events.empty:
        raise RuntimeError("no eligible regional scheduled-outage calibration events")
    event_path = rt / "calibration_events.csv"
    events.to_csv(event_path, index=False, encoding="utf-8-sig")
    cycle_h = float(cfg.study["expected_cycle_interval_hours"])
    all_outage_ids: set[int] = set()
    for _, group in segments.groupby("event_id"):
        all_outage_ids.update(_overlap_cycle_ids(
            grid, group, cycle_h=cycle_h,
            min_overlap_fraction=float(cfg.simple_calibration["min_cycle_overlap_fraction"]),
            buffer_minutes=int(cfg.simple_calibration["transition_buffer_minutes"])))
    cache = dd / "simple_calibration" / "event_candidates"
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
                estimable = (len(cycles["normal"]) >= int(cfg.simple_calibration["min_normal_cycles"]) and
                             len(cycles["pre"]) >= int(cfg.simple_calibration["min_pre_cycles"]) and
                             len(cycles["outage"]) >= int(cfg.simple_calibration["min_outage_cycles"]) and
                             len(cycles["post"]) >= int(cfg.simple_calibration["min_post_cycles"]) and
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
                            scored["pre_reach"] = scored.p_pre
                            scored["outage_reach"] = scored.p_outage
                            scored["post_reach"] = scored.p_post
                            selected = scored[scored.is_event_candidate].copy()
                        selected.to_parquet(path, index=False)
                if not selected.empty:
                    candidate_parts.append(selected)
                audit_rows.append({
                    "event_id": event_id, "geo_name": event.geo_name,
                    "normal_cycle_n": len(cycles["normal"]), "pre_cycle_n": len(cycles["pre"]),
                    "outage_cycle_n": len(cycles["outage"]), "post_cycle_n": len(cycles["post"]),
                    "candidate_ip_pool_n": int(region_targets.dst_ip.nunique()),
                    "selected_ip_n": int(selected.dst_ip.nunique()) if not selected.empty else 0,
                    "estimable": int(estimable), "event_index": int(index + 1),
                })
                logger.info("calibration event %d/%d %s estimable=%s selected=%d",
                            index + 1, len(events), event_id, estimable,
                            0 if selected.empty else selected.dst_ip.nunique())
    candidates = pd.concat(candidate_parts, ignore_index=True) if candidate_parts else pd.DataFrame()
    sensors = aggregate_sensors(candidates)
    sensor_path = dd / "calibrated_sensors.parquet"
    sensors.to_parquet(sensor_path, index=False)
    sensors.to_csv(rt / "calibrated_sensors.csv", index=False, encoding="utf-8-sig")
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(rt / "calibration_event_audit.csv", index=False, encoding="utf-8-sig")
    summary = {
        "candidate_ip_n": int(targets.dst_ip.nunique()), "calibration_event_n": int(len(events)),
        "estimable_event_n": int(audit.estimable.sum()), "calibrated_sensor_n": int(len(sensors)),
        "repeated_support_sensor_n": int(sensors.support_event_n.ge(2).sum()) if not sensors.empty else 0,
        "claim_scope": "scheduled-outage-calibrated candidate sensors; not IP-level electrical ground truth",
    }
    summary_path = rt / "calibration_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok" if len(sensors) else "warning",
            "outputs": [str(candidate_path), str(event_path), str(sensor_path),
                        str(rt / "calibrated_sensors.csv"), str(rt / "calibration_event_audit.csv"),
                        str(summary_path)], **summary}
