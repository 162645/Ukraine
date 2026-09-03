"""Auxiliary operator-level falsification; never trains or selects B2."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config
from .exp_b_event_study import (annotate_design, balance_diagnostics, load_event_panel,
                                match_prefixes, paired_dynamic, pretrend_diagnostic)
from .event_design import primary_estimand
from .progress import get_logger, step
from .sensor_panels import choose_primary_method
from .stats import block_bootstrap_mean


EVENT_ID = "E2024_0724_OBLAST_FALSIFICATION"
TREATED = "Zaporizhzhia Oblast"
CONTROL = "Volyn Oblast"


def _window_pair_effect(panel: pd.DataFrame, matches: pd.DataFrame, start, end,
                        cfg: Config) -> tuple[float, float, float, int, int]:
    unit = "analysis_unit_id" if "analysis_unit_id" in panel else "prefix24"
    t = panel.merge(matches[["pair_id", "treated_unit"]], left_on=unit, right_on="treated_unit")
    c = panel.merge(matches[["pair_id", "control_unit"]], left_on=unit, right_on="control_unit")
    keep = ["pair_id", "measure_time", "normalized_reach", "is_clean_baseline"]
    t = t[keep].rename(columns={"normalized_reach": "treated", "is_clean_baseline": "t_clean"})
    c = c[keep].rename(columns={"normalized_reach": "control", "is_clean_baseline": "c_clean"})
    z = t.merge(c, on=["pair_id", "measure_time"])
    z["raw_diff"] = z["treated"] - z["control"]
    clean = z[z["t_clean"].eq(1) & z["c_clean"].eq(1)]
    base = clean.groupby("pair_id")["raw_diff"].mean()
    z["pair_baseline"] = z["pair_id"].map(base)
    cycle_h = float(cfg.study["expected_cycle_interval_hours"])
    cycle_start = pd.to_datetime(z["measure_time"], utc=True)
    cycle_end = cycle_start + pd.Timedelta(hours=cycle_h)
    start, end = pd.to_datetime(start, utc=True), pd.to_datetime(end, utc=True)
    left = cycle_start.where(cycle_start > start, start)
    right = cycle_end.where(cycle_end < end, end)
    overlap = ((right - left).dt.total_seconds() / 3600).clip(lower=0)
    threshold = float(cfg.calibration.get("min_cycle_schedule_overlap_fraction", 0.5))
    window = z[overlap.div(cycle_h).ge(threshold)].copy()
    window["did"] = window["raw_diff"] - window["pair_baseline"]
    values = window.groupby("pair_id")["did"].mean().dropna()
    if values.empty:
        return np.nan, np.nan, np.nan, 0, 0
    mean, lo, hi = block_bootstrap_mean(values, values.index.to_series(),
                                         n_boot=int(cfg.runtime["n_bootstrap"]),
                                         ci=float(cfg.inference["ci_level"]),
                                         seed=int(cfg.runtime["random_seed"]) + 724)
    return mean, lo, hi, int(values.size), int(window["measure_time"].nunique())


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    tables = cfg.out_dir("results_tables")
    events = cfg.load_event_registry()
    rows = events[events["event_id"].eq(EVENT_ID)]
    if rows.empty:
        raise RuntimeError(f"Missing frozen event {EVENT_ID}")
    event = rows.iloc[0]
    method = choose_primary_method(cfg)
    with step("Auxiliary oblast operator falsification", logger):
        panel = load_event_panel(cfg, event, method=method)
        if panel.empty:
            raise RuntimeError("Missing operator-falsification sensor panel")
        panel = panel[panel["target_admin1"].isin([TREATED, CONTROL])].copy()
        estimand = primary_estimand(event)
        panel = annotate_design(panel, event, estimand, cfg)
        matches = match_prefixes(panel, [TREATED], cfg)
        balance = balance_diagnostics(panel, [TREATED], matches, cfg, EVENT_ID, method,
                                      "operator_execution_vs_cancellation")
        curve = paired_dynamic(panel, matches, cfg, EVENT_ID,
                               int(cfg.runtime["random_seed"]) + 724)
        diag = pretrend_diagnostic(curve, cfg)
        operator = cfg.load_oblast_execution_registry()
        contrast = operator[operator["contrast_id"].eq("C2024_0724_ZP_VOL")]
        start, end = contrast["start_utc"].max(), contrast["end_utc"].min()
        effect, lo, hi, n_pairs_window, n_cycles = _window_pair_effect(
            panel, matches, start, end, cfg)
        arm_prefix = panel.groupby("target_admin1")["prefix24"].nunique().to_dict()
        common_asn = len(set(panel.loc[panel["target_admin1"].eq(TREATED), "target_asn"]) &
                         set(panel.loc[panel["target_admin1"].eq(CONTROL), "target_asn"]))
        rcfg = cfg.calibration["regional_falsification"]
        balance_ok = bool(not balance.empty and balance["abs_smd_after"].notna().all() and
                          balance["abs_smd_after"].max() <= float(cfg.matching["max_abs_smd"]))
        support_ok = (arm_prefix.get(TREATED, 0) >= int(rcfg["min_prefix24_per_arm"]) and
                      arm_prefix.get(CONTROL, 0) >= int(rcfg["min_prefix24_per_arm"]) and
                      common_asn >= int(rcfg["min_common_asn"]) and n_cycles >= 1)
        estimable = bool(support_ok and len(matches) >= int(cfg.matching["min_matched_pairs"]) and
                         balance_ok and diag["pretrend_equivalent"] and np.isfinite(effect))
        summary = pd.DataFrame([{
            "event_id": EVENT_ID, "contrast_id": "C2024_0724_ZP_VOL",
            "sensor_method": method, "treated_admin1": TREATED, "control_admin1": CONTROL,
            "window_start_utc": start, "window_end_utc": end,
            "partial_queue_treatment": 1, "ip_queue_mapping_available": 0,
            "treated_prefix_n": arm_prefix.get(TREATED, 0),
            "control_prefix_n": arm_prefix.get(CONTROL, 0), "common_asn_n": common_asn,
            "matched_pair_n": len(matches), "window_pair_n": n_pairs_window,
            "window_cycle_n": n_cycles, "balance_ok": int(balance_ok),
            "pretrend_equivalent": int(diag["pretrend_equivalent"]),
            "effect_did": effect, "ci_lo": lo, "ci_hi": hi,
            "estimable": int(estimable),
            "mechanism_direction_consistent": int(estimable and effect < 0),
            "high_confidence_negative_effect": int(estimable and hi < 0),
            "claim_scope": "auxiliary_partial-queue_operator-falsification_not_ip-level_outage_truth",
        }])
        summary.to_csv(tables / "exp_g_oblast_falsification_summary.csv", index=False)
        matches.to_csv(tables / "exp_g_oblast_matches.csv", index=False)
        balance.to_csv(tables / "exp_g_oblast_balance.csv", index=False)
        curve.to_csv(tables / "exp_g_oblast_curve.csv", index=False)
    return {"status": "ok" if estimable else "diagnostic_only_no_admissible_group",
            "outputs": [str(tables / name) for name in (
                "exp_g_oblast_falsification_summary.csv", "exp_g_oblast_matches.csv",
                "exp_g_oblast_balance.csv", "exp_g_oblast_curve.csv")],
            "estimable": estimable}
