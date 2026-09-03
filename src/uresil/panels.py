"""Memory-bounded response aggregation and zero-inclusive analysis panels.

The ping table contains successful responses only.  Under the explicitly confirmed
static full-scan design, absence of a response in a complete analysis cycle is a
zero.  Sparse response parts are therefore never averaged without a denominator.
All large operations are performed in ClickHouse or one small time partition at a
time; the full prefix-cycle table is never concatenated in Python.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd

from . import sqlutil as S
from .config import Config
from .db import CHClient
from .events import Events
from .progress import get_logger, pbar, step


def _time_edges(start: str, end: str, days: int):
    s = pd.Timestamp(start, tz="UTC").floor("D")
    e = pd.Timestamp(end, tz="UTC")
    cur = s
    while cur <= e:
        nxt = min(cur + pd.Timedelta(days=days), e + pd.Timedelta(seconds=1))
        yield cur, nxt, f"{cur:%Y%m%d}_{nxt:%Y%m%d}"
        cur = nxt


def _parts(path: Path) -> list[str]:
    return sorted(glob.glob(str(path / "part_*.parquet")))


def build_observed_panel(cfg: Config, ch: CHClient) -> list[str]:
    logger = get_logger(cfg.out_dir("logs"))
    out_dir = cfg.out_dir("data_derived") / "prefix_response_sparse"
    out_dir.mkdir(parents=True, exist_ok=True)
    h = int(cfg.study["expected_cycle_interval_hours"])
    days = int(cfg.runtime.get("panel_batch_days", 2))
    edges = list(_time_edges(cfg.study["start_utc"], cfg.study["end_utc"], days))
    written = []
    with step("Build partitioned sparse prefix-response panel", logger):
        for s, e, tag in pbar(edges, desc="prefix response batches", unit="batch"):
            p = out_dir / f"part_{tag}.parquet"
            if p.exists():
                written.append(str(p)); continue
            sql = S.render("03_prefix_panel", ping=cfg.table("ping"),
                           batch_start=s.strftime("%Y-%m-%d %H:%M:%S"),
                           batch_end=e.strftime("%Y-%m-%d %H:%M:%S"),
                           dc=cfg.study["data_center"], cycle_seconds=h*3600,
                           cycle_hours=h, slots_per_day=24//h)
            df = ch.query_df(sql)
            if df.empty:
                continue
            df["measure_time"] = pd.to_datetime(df["measure_time"], utc=True)
            df.to_parquet(p, index=False, compression="zstd")
            written.append(str(p))
    return written


def compute_baseline_expected(cfg: Config, cq: pd.DataFrame, ch: CHClient) -> pd.DataFrame:
    """Compute same-slot expectations in ClickHouse with complete-cycle denominators."""
    logger = get_logger(cfg.out_dir("logs"))
    ev = Events(cfg)
    grid = ev.build_cycle_grid(cq)
    clean = grid.loc[ev.clean_baseline_mask(grid), ["cycle_id", "slot"]]
    if clean.empty:
        raise RuntimeError("No clean baseline cycles")
    h = int(cfg.study["expected_cycle_interval_hours"])
    parts = []
    slot_groups = list(clean.groupby("slot"))
    with step("Compute zero-inclusive prefix-slot baseline in ClickHouse", logger):
        for slot, slot_df in pbar(slot_groups, desc="baseline slots", unit="slot"):
            q = S.render("09_baseline_expected", ping=cfg.table("ping"),
                         dc=cfg.study["data_center"], cycle_seconds=h*3600,
                         cycle_hours=h, slots_per_day=24//h,
                         clean_cids=S.int_list(slot_df["cycle_id"].astype(int).tolist()))
            d = ch.query_df(q)
            if d.empty:
                continue
            parts.append(d)
    if not parts:
        raise RuntimeError("No baseline expectations were produced")
    agg = pd.concat(parts, ignore_index=True)
    slot_n = clean.groupby("slot")["cycle_id"].nunique().rename("baseline_slot_cycles")
    agg = agg.merge(slot_n.reset_index(), on="slot", how="left")
    agg["expected_ip_n"] = agg["observed_ip_sum"] / agg["baseline_slot_cycles"].replace(0, np.nan)
    agg["response_cycle_rate"] = agg["responding_cycles"] / agg["baseline_slot_cycles"].replace(0, np.nan)
    agg = agg[agg["baseline_slot_cycles"] >= int(cfg.baseline["min_baseline_cycles_per_slot"])]
    p = cfg.out_dir("data_derived") / "baseline_expected.parquet"
    agg.to_parquet(p, index=False, compression="zstd")
    return agg


def _eligible_targets(cfg: Config) -> pd.DataFrame:
    """National panel admits Ukrainian country-only targets; regional code filters them."""
    tu = pd.read_parquet(cfg.out_dir("data_derived") / "target_universe.parquet")
    flag = "national_prefix_eligible" if "national_prefix_eligible" in tu else "valid_prefix_mapping"
    z = tu[tu[flag].eq(1) & tu["valid_target_asn"].eq(1) & tu["target_country"].eq("Ukraine")].copy()
    return z[["prefix24", "target_asn", "target_country", "target_admin1", "candidate_ip_n", "group"]].drop_duplicates("prefix24")


def _read_part(path: str, columns: list[str] | None = None,
               min_cid: int | None = None, max_cid: int | None = None) -> pd.DataFrame:
    filters = []
    if min_cid is not None: filters.append(("cycle_id", ">=", int(min_cid)))
    if max_cid is not None: filters.append(("cycle_id", "<=", int(max_cid)))
    try:
        return pd.read_parquet(path, columns=columns, filters=filters or None)
    except Exception:
        d = pd.read_parquet(path, columns=columns)
        if min_cid is not None: d = d[d["cycle_id"] >= min_cid]
        if max_cid is not None: d = d[d["cycle_id"] <= max_cid]
        return d


def build_dense_group_and_national(cfg: Config, cq: pd.DataFrame, expected: pd.DataFrame,
                                   targets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    grid = Events(cfg).build_cycle_grid(cq)
    grid = grid[grid["is_complete"].eq(1)][["cycle_id", "measure_time", "slot"]].copy()
    exp = expected.merge(targets, on="prefix24", how="inner")
    exp = exp[exp["expected_ip_n"] >= float(cfg.baseline["min_expected_responses"])]
    group_slot = (exp.groupby(["group", "target_asn", "target_country", "target_admin1", "slot"])
                  .agg(expected_ip_sum=("expected_ip_n", "sum"),
                       eligible_prefix_n=("prefix24", "nunique")).reset_index())
    national_slot = (exp.groupby("slot")
                     .agg(expected_ip_sum=("expected_ip_n", "sum"),
                          eligible_prefix_n=("prefix24", "nunique")).reset_index())

    group_parts, nat_parts = [], []
    keep = exp[["prefix24", "slot", "expected_ip_n", "group", "target_asn",
                "target_country", "target_admin1"]]
    for p in pbar(_parts(cfg.out_dir("data_derived") / "prefix_response_sparse"),
                  desc="aggregate sparse parts", unit="part"):
        d = _read_part(p, ["prefix24", "cycle_id", "slot", "observed_ip_n", "rtt_median"])
        if d.empty: continue
        s = d.merge(keep, on=["prefix24", "slot"], how="inner")
        if s.empty: continue
        s["prefix_norm"] = s["observed_ip_n"] / s["expected_ip_n"].replace(0, np.nan)
        group_parts.append((s.groupby(["group", "cycle_id"])
                            .agg(observed_ip_sum=("observed_ip_n", "sum"),
                                 prefix_norm_sum=("prefix_norm", "sum"),
                                 responding_prefix_n=("prefix24", "nunique"),
                                 rtt_median=("rtt_median", "median")).reset_index()))
        nat_parts.append((s.groupby("cycle_id")
                          .agg(observed_ip_sum=("observed_ip_n", "sum"),
                               prefix_norm_sum=("prefix_norm", "sum"),
                               responding_prefix_n=("prefix24", "nunique")).reset_index()))
    if not group_parts:
        raise RuntimeError("No sparse prefix responses joined the frozen target universe")
    obs_g = (pd.concat(group_parts, ignore_index=True)
             .groupby(["group", "cycle_id"])
             .agg(observed_ip_sum=("observed_ip_sum", "sum"),
                  prefix_norm_sum=("prefix_norm_sum", "sum"),
                  responding_prefix_n=("responding_prefix_n", "sum"),
                  rtt_median=("rtt_median", "median")).reset_index())
    # responding_prefix_n is not used as a denominator; duplicate cycle rows across parts
    # should not occur because parts are non-overlapping time intervals.
    groups = group_slot[["group", "target_asn", "target_country", "target_admin1"]].drop_duplicates()
    dense = (groups.merge(grid, how="cross")
             .merge(group_slot, on=["group", "target_asn", "target_country", "target_admin1", "slot"], how="left")
             .merge(obs_g, on=["group", "cycle_id"], how="left"))
    for c in ["observed_ip_sum", "prefix_norm_sum", "responding_prefix_n"]:
        dense[c] = dense[c].fillna(0)
    dense["reach_ip_weighted"] = dense["observed_ip_sum"] / dense["expected_ip_sum"].replace(0, np.nan)
    dense["reach_prefix_equal"] = dense["prefix_norm_sum"] / dense["eligible_prefix_n"].replace(0, np.nan)
    dense.to_parquet(cfg.out_dir("data_derived") / "group_cycle_panel.parquet", index=False, compression="zstd")

    obs_n = (pd.concat(nat_parts, ignore_index=True).groupby("cycle_id")
             .agg(observed_ip_sum=("observed_ip_sum", "sum"),
                  prefix_norm_sum=("prefix_norm_sum", "sum"),
                  responding_prefix_n=("responding_prefix_n", "sum")).reset_index())
    nat = grid.merge(national_slot, on="slot", how="left").merge(obs_n, on="cycle_id", how="left")
    for c in ["observed_ip_sum", "prefix_norm_sum", "responding_prefix_n"]:
        nat[c] = nat[c].fillna(0)
    nat["national_reach_ip_weighted"] = nat["observed_ip_sum"] / nat["expected_ip_sum"].replace(0, np.nan)
    nat["national_reach_prefix_equal"] = nat["prefix_norm_sum"] / nat["eligible_prefix_n"].replace(0, np.nan)
    nat.to_parquet(cfg.out_dir("data_derived") / "national_cycle_panel.parquet", index=False, compression="zstd")
    nat[["measure_time", "national_reach_prefix_equal"]].rename(
        columns={"national_reach_prefix_equal": "national_reach"}).to_csv(
        cfg.out_dir("results_tables") / "f2_signal.csv", index=False, encoding="utf-8-sig")
    return dense, nat


def build_group_baseline_stats(cfg: Config, group_panel: pd.DataFrame, cq: pd.DataFrame) -> pd.DataFrame:
    ev = Events(cfg)
    eg = ev.build_cycle_grid(cq)
    clean_ids = set(eg.loc[ev.clean_baseline_mask(eg), "cycle_id"])
    d = group_panel[group_panel["cycle_id"].isin(clean_ids)].copy()
    b = (d.groupby("group")["reach_prefix_equal"]
         .agg(baseline_median="median", baseline_mean="mean", baseline_sd="std",
              baseline_p05=lambda x: x.quantile(float(cfg.baseline["abnormal_quantile"])),
              baseline_mad=lambda x: (x-x.median()).abs().median(), baseline_cycles="count")
         .reset_index())
    b.to_parquet(cfg.out_dir("data_derived") / "group_baseline_stats.parquet", index=False)
    return b


def _event_observed(cfg: Config, cycle_ids: pd.Series) -> pd.DataFrame:
    if cycle_ids.empty:
        return pd.DataFrame()
    lo, hi = int(cycle_ids.min()), int(cycle_ids.max())
    rows = []
    cols = ["prefix24", "cycle_id", "observed_ip_n", "rtt_median", "rtt_n"]
    for p in _parts(cfg.out_dir("data_derived") / "prefix_response_sparse"):
        d = _read_part(p, cols, lo, hi)
        if not d.empty:
            d = d[d["cycle_id"].isin(set(cycle_ids.astype(int)))]
            if not d.empty: rows.append(d)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=cols)


def build_event_prefix_panels(cfg: Config, cq: pd.DataFrame, expected: pd.DataFrame,
                              targets: pd.DataFrame) -> list[str]:
    """Build B0 diagnostic event panels; B1/B2 panels are built after Experiment A."""
    ev = Events(cfg)
    grid = ev.build_cycle_grid(cq)
    exp = expected.merge(targets, on="prefix24", how="inner")
    exp = exp[exp["expected_ip_n"] >= float(cfg.baseline["min_expected_responses"])]
    out_dir = cfg.out_dir("data_derived") / "event_prefix_panel"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for _, row in pbar(list(ev.df.iterrows()), total=len(ev.df), desc="B0 event panels", unit="event"):
        lo, hi = ev.event_window(row)
        cycles = grid[(grid["measure_time"] >= lo) & (grid["measure_time"] <= hi) & grid["is_complete"].eq(1)][
            ["cycle_id", "measure_time", "slot"]]
        if cycles.empty: continue
        obs = _event_observed(cfg, cycles["cycle_id"])
        chunks = []
        for slot, cg in cycles.groupby("slot"):
            ps = exp[exp["slot"].eq(slot)][["prefix24", "expected_ip_n", "baseline_rtt_median", "group",
                                                    "target_asn", "target_country", "target_admin1"]]
            if ps.empty: continue
            x = cg.merge(ps, how="cross").merge(obs, on=["prefix24", "cycle_id"], how="left")
            x["observed_ip_n"] = x["observed_ip_n"].fillna(0)
            x["normalized_reach"] = x["observed_ip_n"] / x["expected_ip_n"].replace(0, np.nan)
            chunks.append(x)
        if not chunks: continue
        panel = pd.concat(chunks, ignore_index=True)
        panel["event_id"] = row["event_id"]
        p = out_dir / f"{row['event_id']}.parquet"
        panel.to_parquet(p, index=False, compression="zstd")
        written.append(str(p))
    return written


def write_timeline(cfg: Config) -> None:
    ev = Events(cfg).df.copy()
    out = pd.DataFrame({
        "event_id": ev["event_id"], "label_zh": ev["event_name_zh"], "label_en": ev["event_name_en"],
        "kind": np.where(ev["event_family"].eq("planned_outage"), "planned", "attack"),
        "start_utc": ev["primary_anchor_utc"], "end_utc": ev["outage_end_utc"],
        "anchor_type": ev["primary_anchor_type"], "precision_h": ev["anchor_precision_h"],
    })
    out.to_csv(cfg.out_dir("results_tables") / "f2_timeline.csv", index=False, encoding="utf-8-sig")


def run(cfg: Config) -> dict:
    cq = pd.read_parquet(cfg.out_dir("data_derived") / "cycle_quality.parquet")
    with CHClient(cfg) as ch:
        observed_outputs = build_observed_panel(cfg, ch)
        expected = compute_baseline_expected(cfg, cq, ch)
    targets = _eligible_targets(cfg)
    group, _ = build_dense_group_and_national(cfg, cq, expected, targets)
    build_group_baseline_stats(cfg, group, cq)
    event_outputs = build_event_prefix_panels(cfg, cq, expected, targets)
    write_timeline(cfg)
    return {"status": "ok", "outputs": observed_outputs + event_outputs + [
        str(cfg.out_dir("data_derived") / "baseline_expected.parquet"),
        str(cfg.out_dir("data_derived") / "group_cycle_panel.parquet"),
        str(cfg.out_dir("data_derived") / "national_cycle_panel.parquet"),
    ]}
