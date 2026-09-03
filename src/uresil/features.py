"""Event-level resilience features from frozen endpoint-sensor panels.

v2.4 computes every outcome against a clean baseline that ends before the
*earliest* credible treatment boundary.  The attack-to-outage interval is not
used as untreated pre-event data.  The primary feature table follows the frozen
sensor choice: B2 only after successful scheduled-outage validation, otherwise
B1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config
from .event_design import clean_baseline_interval, primary_estimand
from .events import Events
from .progress import get_logger, pbar, step
from .sensor_panels import choose_primary_method

GROUP_KEYS = ["target_asn", "target_country", "target_admin1"]


def _first_consecutive(index: np.ndarray, flags: np.ndarray, k: int) -> float:
    run = 0
    for i, flag in enumerate(flags):
        run = run + 1 if bool(flag) else 0
        if run >= k:
            return float(index[i-k+1])
    return np.nan


def event_features_for_series(s: pd.DataFrame, cfg: Config, *, baseline: float = 1.0,
                              lower_band: float | None = None,
                              reach_col: str = "reach_prefix_equal",
                              use_local_pre: bool = True) -> dict:
    """Extract depth, area, onset, and recovery from one event-relative series.

    ``use_local_pre=False`` is required for attack estimands whose -6:-2 hour
    interval can already be inside an attack-to-outage transition.  In that case
    the caller supplies a clean-baseline level and the immediate effect is
    measured against that frozen level.
    """
    d = s.sort_values("rel_h").dropna(subset=[reach_col]).copy()
    if d.empty:
        return {}
    ew = cfg.event_windows
    R = d.groupby("rel_h")[reach_col].mean().sort_index().astype(float)
    pre_seg = R[(R.index >= ew["immediate_pre_h"][0]) & (R.index <= ew["immediate_pre_h"][1])]
    post_seg = R[(R.index >= ew["immediate_post_h"][0]) & (R.index <= ew["immediate_post_h"][1])]
    local_pre = float(pre_seg.mean()) if use_local_pre and len(pre_seg) else float(baseline)
    base = float(local_pre if np.isfinite(local_pre) else baseline)
    immediate_drop = base - float(post_seg.mean()) if len(post_seg) else np.nan

    win = R[(R.index >= 0) & (R.index <= float(ew["deficit_window_h"]))]
    full = R[(R.index >= 0) & (R.index <= float(ew["deficit_auc_full_h"]))]
    if len(win):
        nadir = float(win.min()); nadir_h = float(win.idxmin())
        max_deficit = max(0.0, base - nadir)
    else:
        nadir = nadir_h = max_deficit = np.nan
    cycle_h = float(cfg.study["expected_cycle_interval_hours"])
    auc = float(((base - full).clip(lower=0) * cycle_h).sum()) if len(full) else np.nan
    auc24_seg = R[(R.index >= 0) & (R.index <= 24)]
    auc24 = float(((base - auc24_seg).clip(lower=0) * cycle_h).sum()) if len(auc24_seg) else np.nan
    diffs = R[(R.index >= -2) & (R.index <= 12)].diff()
    sharpness = float(max(0.0, -diffs.min())) if len(diffs.dropna()) else np.nan

    if lower_band is None or not np.isfinite(lower_band):
        lower_band = base * 0.90
    post = R[R.index >= 0]
    onset = _first_consecutive(post.index.to_numpy(float), post.values < lower_band,
                               int(ew["abnormal_consecutive"])) if len(post) else np.nan

    t50 = t90 = np.nan
    censored = 1
    if np.isfinite(max_deficit) and max_deficit > 0 and np.isfinite(nadir_h):
        after = R[R.index >= nadir_h]
        th50 = nadir + 0.50 * max_deficit
        th90 = nadir + 0.90 * max_deficit
        k = int(ew["recovery_consecutive"])
        t50_abs = _first_consecutive(after.index.to_numpy(float), after.values >= th50, k)
        t90_abs = _first_consecutive(after.index.to_numpy(float), after.values >= th90, k)
        t50 = t50_abs - nadir_h if np.isfinite(t50_abs) else np.nan
        t90 = t90_abs - nadir_h if np.isfinite(t90_abs) else np.nan
        censored = int(not np.isfinite(t90))

    pre_all = R[R.index < 0]
    pre_slope = float(np.polyfit(pre_all.index.values.astype(float), pre_all.values, 1)[0]) if len(pre_all) >= 4 else np.nan
    return {
        "baseline_level": base, "baseline_lower_band": float(lower_band),
        "immediate_drop": immediate_drop, "sharpness": sharpness,
        "max_deficit": max_deficit, "nadir_h": nadir_h,
        "deficit_auc_24h": auc24, "deficit_auc_full": auc,
        "onset_delay_h": onset, "t50_h": t50, "t90_h": t90,
        "recovery_censored": censored, "pretrend_slope": pre_slope,
        "n_cycles": int(len(R)),
    }


def _robust_lower(pre: pd.Series, cfg: Config, baseline: float) -> float:
    z = pd.to_numeric(pre, errors="coerce").dropna()
    if len(z) < 4:
        return baseline * 0.90
    med = float(z.median()); mad = float((z - med).abs().median())
    candidates = [float(z.quantile(float(cfg.baseline["abnormal_quantile"])))]
    if np.isfinite(mad) and mad > 0:
        candidates.append(med - float(cfg.baseline["abnormal_mad_k"]) * mad)
    return float(max(0.0, min(min(candidates), baseline)))


def _aggregate_sensor_panel(panel: pd.DataFrame, event: pd.Series, cfg: Config) -> pd.DataFrame:
    d = panel.copy()
    d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True)
    estimand = primary_estimand(event)
    h = float(cfg.study["expected_cycle_interval_hours"])
    d["rel_h"] = np.round(((d["measure_time"] - estimand.anchor_utc).dt.total_seconds() / 3600.0) / h) * h
    agg = {
        "reach_prefix_equal": ("normalized_reach", "mean"),
        "sensor_reach_prefix_equal": ("sensor_reach", "mean"),
        "eligible_prefix_n": ("prefix24", "nunique"),
        "sensor_n": ("sensor_n", "sum"),
        "expected_response_n": ("expected_response_n", "sum"),
    }
    if "rtt_median" in d.columns:
        agg["rtt_median"] = ("rtt_median", "median")
    return (d.groupby(GROUP_KEYS + ["group", "method", "cycle_id", "measure_time", "rel_h"], dropna=False)
            .agg(**agg).reset_index())


def _event_method_features(panel: pd.DataFrame, event: pd.Series, cfg: Config,
                           method: str) -> list[dict]:
    d = panel[panel["method"].eq(method)].copy()
    if d.empty:
        return []
    gpanel = _aggregate_sensor_panel(d, event, cfg)
    ev = Events(cfg); estimand = primary_estimand(event)
    observed = ev.observed_admin1(event)
    b0, b1 = clean_baseline_interval(event, cfg)
    rows: list[dict] = []
    for group, g in gpanel.groupby("group", sort=False):
        if g["eligible_prefix_n"].max() < int(cfg.group_admission["min_valid_prefix24"]):
            continue
        clean = g[g["measure_time"].between(b0, b1)]
        post = g[g["rel_h"] >= 0]
        if len(clean) < int(cfg.group_admission["min_pre_cycles"]):
            continue
        if len(post) < int(cfg.group_admission["min_post_cycles"]):
            continue
        baseline = float(clean["reach_prefix_equal"].median())
        lower = _robust_lower(clean["reach_prefix_equal"], cfg, baseline)
        feat = event_features_for_series(g[["rel_h", "reach_prefix_equal"]], cfg,
                                         baseline=baseline, lower_band=lower,
                                         use_local_pre=False)
        if not feat:
            continue
        # Recovery debt observable immediately before the earliest treatment boundary.
        debt_start = estimand.treatment_start_utc - pd.Timedelta(hours=24)
        pre24 = g[g["measure_time"].between(debt_start, estimand.treatment_start_utc, inclusive="left")]
        pre_event_reach = float(pre24["reach_prefix_equal"].median()) if not pre24.empty else np.nan
        pre_event_debt = max(0.0, baseline - pre_event_reach) if np.isfinite(pre_event_reach) else np.nan
        first = g.iloc[0]
        treated = estimand.treated_admin1
        feat.update({
            "event_id": event["event_id"], "event_name_zh": event["event_name_zh"],
            "event_name_en": event["event_name_en"], "event_family": event["event_family"],
            "analysis_role": event["analysis_role"], "event_anchor_utc": estimand.anchor_utc,
            "feature_cutoff_utc": estimand.treatment_start_utc,
            "treatment_start_utc": estimand.treatment_start_utc,
            "clean_baseline_start_utc": b0, "clean_baseline_end_utc": b1,
            "estimand_id": estimand.estimand_id, "claim_scope": estimand.claim_scope,
            "sensor_method": method, "group": group,
            "target_asn": int(first["target_asn"]), "target_country": first["target_country"],
            "target_admin1": first["target_admin1"],
            "eligible_prefix_n": int(g["eligible_prefix_n"].max()),
            "sensor_n": int(g["sensor_n"].median()),
            "expected_response_n": float(g["expected_response_n"].median()),
            "is_treated": int(treated == ("ALL",) or first["target_admin1"] in treated),
            "externally_observed": int(first["target_admin1"] in observed),
            "anchor_precision_h": float(event.get("anchor_precision_h", 0) or 0),
            "pre_event_reach_24h": pre_event_reach,
            "pre_event_debt": pre_event_debt,
        })
        rows.append(feat)
    return rows


def build_group_event_features(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    logger = get_logger(cfg.out_dir("logs")); ev = Events(cfg)
    panel_dir = cfg.out_dir("data_derived") / "sensor_event_panel"
    primary = choose_primary_method(cfg); all_rows: list[dict] = []
    with step("Build stage-aware frozen-sensor group-event resilience features", logger):
        for _, event in pbar(list(ev.df.iterrows()), total=len(ev.df), desc="events", unit="event"):
            path = panel_dir / f"{event['event_id']}.parquet"
            if not path.exists():
                logger.warning("Missing sensor event panel: %s", path.name); continue
            panel = pd.read_parquet(path)
            for method in ("B1", "B2"):
                all_rows.extend(_event_method_features(panel, event, cfg, method))
    all_methods = pd.DataFrame(all_rows)
    primary_df = all_methods[all_methods["sensor_method"].eq(primary)].copy() if not all_methods.empty else pd.DataFrame()
    p_all = cfg.out_dir("data_derived") / "group_event_features_all_methods.parquet"
    p_primary = cfg.out_dir("data_derived") / "group_event_features.parquet"
    all_methods.to_parquet(p_all, index=False); primary_df.to_parquet(p_primary, index=False)
    pd.DataFrame([{
        "primary_sensor_method": primary, "n_group_event_primary": len(primary_df),
        "n_group_event_B1": int((all_methods.get("sensor_method") == "B1").sum()) if not all_methods.empty else 0,
        "n_group_event_B2": int((all_methods.get("sensor_method") == "B2").sum()) if not all_methods.empty else 0,
    }]).to_csv(cfg.out_dir("results_tables") / "group_feature_summary.csv", index=False)
    return primary_df, all_methods


def run(cfg: Config) -> dict:
    primary, all_methods = build_group_event_features(cfg)
    outputs = [
        str(cfg.out_dir("data_derived") / "group_event_features.parquet"),
        str(cfg.out_dir("data_derived") / "group_event_features_all_methods.parquet"),
        str(cfg.out_dir("results_tables") / "group_feature_summary.csv"),
    ]
    return {"status": "ok", "outputs": outputs, "n_rows": len(primary),
            "n_rows_all_methods": len(all_methods), "primary_sensor_method": choose_primary_method(cfg)}
