"""Build the stable comparison pool without using any outage outcome label."""
from __future__ import annotations

import pandas as pd

from . import sqlutil as S
from .config import Config
from .db import CHClient
from .events import Events, slot_of
from .progress import get_logger, pbar, step
from .simple_calibration import (_overlap_cycle_ids, _prefix_batches,
                                 build_final_calibration_events)


def select_baseline_cycles(cfg: Config, grid: pd.DataFrame, targets: pd.DataFrame) -> list[int]:
    _, segments = build_final_calibration_events(cfg, set(targets.target_admin1.dropna().astype(str)))
    excluded: set[int] = set()
    cycle_h = float(cfg.study["expected_cycle_interval_hours"])
    for _, group in segments.groupby("event_id") if not segments.empty else []:
        excluded.update(_overlap_cycle_ids(
            grid, group, cycle_h=cycle_h,
            min_overlap_fraction=float(cfg.simple_calibration["min_cycle_overlap_fraction"]),
            buffer_minutes=0))
    measurement_start = pd.to_datetime(cfg.study["measurement_start_utc"], utc=True)
    # B1 is label-free and must not learn stability from any war-energy attack
    # window either.  ``clean_baseline_mask`` now excludes attacks only; the
    # reviewed P1/P2 planned windows are excluded explicitly above.
    attack_clean = Events(cfg).clean_baseline_mask(grid)
    clean = grid[grid.is_complete.astype(bool) & attack_clean & ~grid.cycle_id.isin(excluded) &
                 pd.to_datetime(grid.measure_time, utc=True).ge(measurement_start)].copy()
    clean["slot"] = slot_of(clean.measure_time, int(cycle_h))
    # The paper definition uses every eligible clean normal cycle.  A
    # slot-balanced subset is retained only as an explicitly requested
    # robustness option; it must not silently replace the primary Activity
    # denominator.
    slot_balanced = bool(cfg.raw.get("ip_activity", {}).get("slot_balanced_primary", False))
    if slot_balanced:
        per_slot = int(cfg.simple_calibration.get("baseline_cycles_per_slot", 12))
        clean = (clean.sort_values("measure_time").groupby("slot", group_keys=False)
                  .tail(per_slot))
    return sorted(clean.cycle_id.astype("int64").unique())


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    dd = cfg.out_dir("data_derived")
    targets = pd.read_parquet(dd / "target_ip_universe.parquet")
    targets = targets[targets.national_eligible.eq(1)].copy()
    grid = Events(cfg).build_cycle_grid(pd.read_parquet(dd / "cycle_quality.parquet"))
    normal = select_baseline_cycles(cfg, grid, targets)
    if len(normal) < int(cfg.baseline["min_exposure_cycles"]):
        raise RuntimeError("too few complete non-outage cycles for the stable endpoint pool")
    prefixes = targets.prefix24.dropna().astype(str).drop_duplicates().tolist()
    batches = list(_prefix_batches(prefixes, int(cfg.runtime["prefix_batch"])))
    outdir = dd / "ip_sensor_scores_parts"
    outdir.mkdir(parents=True, exist_ok=True)
    outputs = []
    force = bool(cfg.raw.get("_runtime_flags", {}).get("force_stage_recompute", False))
    cycle_seconds = int(cfg.study["expected_cycle_interval_hours"] * 3600)
    with step("Build label-free stable endpoint pool", logger):
        with CHClient(cfg) as ch:
            for index, prefix_batch in pbar(list(enumerate(batches)), desc="baseline batches", unit="batch"):
                path = outdir / f"part_{index:05d}.parquet"
                if path.exists() and path.stat().st_size and not force:
                    outputs.append(str(path))
                    continue
                sql = S.render("12_ip_baseline_reach", ping=cfg.table("ping"),
                               dc=cfg.study["data_center"], prefix_in=S.str_list(prefix_batch),
                               normal_cids=S.int_list(normal), cycle_seconds=cycle_seconds)
                raw = ch.query_df(sql)
                columns = [c for c in ("dst_ip", "prefix24", "target_asn", "target_country",
                                       "target_admin1", "target_city", "target_geo_latitude",
                                       "target_geo_longitude", "target_geo_precision", "target_as_name",
                                       "target_isp_domain", "network_stratum", "regional_eligible",
                                       "country_only_admin1", "group", "analysis_unit_id") if c in targets]
                # Static full scans define a common denominator: a target IP
                # absent from an import-complete cycle contributes y=0.  Start
                # from the target universe and left-join observed responses;
                # never let "responded at least once" define Activity.
                base = targets[targets.prefix24.astype(str).isin(set(map(str, prefix_batch)))][columns].drop_duplicates(
                    ["dst_ip", "prefix24"])
                observed = raw[[c for c in ("dst_ip", "prefix24", "x_normal") if c in raw]].copy()
                d = base.merge(observed, on=["dst_ip", "prefix24"], how="left", validate="one_to_one")
                d["n_normal"] = len(normal)
                d["x_normal"] = pd.to_numeric(d.x_normal, errors="coerce").fillna(0)
                # Activity is a continuous endpoint feature, not a hard gate.
                # Keep the raw estimand required by the research plan and retain
                # the Jeffreys-smoothed value only as an engineering helper.
                d["activity_score_raw"] = d["x_normal"] / float(max(len(normal), 1))
                d["activity_score_smoothed"] = (d["x_normal"] + 0.5) / (len(normal) + 1.0)
                min_activity_cycles = int(cfg.raw.get("ip_activity", {}).get(
                    "min_normal_cycles", cfg.baseline.get("min_exposure_cycles", 24)))
                d["activity_estimable"] = d["n_normal"].ge(min_activity_cycles)
                d["pN"] = d["activity_score_smoothed"]
                # Legacy B1 is retained for compatibility/audit only.  It must
                # never define the canonical IP population or sensitivity pool.
                d["in_B1"] = d["activity_estimable"]
                d["legacy_stable_B1"] = (d["activity_score_smoothed"].ge(
                    float(cfg.baseline.get("stable_ip_resp_rate", 0.8))) & d["activity_estimable"])
                d["in_B2"] = False
                d.to_parquet(path, index=False)
                outputs.append(str(path))
    audit = pd.DataFrame([{"normal_cycle_n": len(normal), "target_ip_n": len(targets),
                           "part_n": len(outputs)}])
    audit_path = cfg.out_dir("results_tables") / "stable_pool_audit.csv"
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    return {"status": "ok", "outputs": [str(outdir), str(audit_path)],
            "normal_cycle_n": len(normal), "part_n": len(outputs)}
