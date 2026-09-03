"""Experiment B — stage-aware held-out attack validation.

v2.4 fixes the most important causal-design error exposed by the real run:
attack start, outage implementation, and externally observed network onset are
not interchangeable.  Matching and pretrend diagnostics use a clean baseline
ending before the earliest credible treatment.  The attack-to-outage interval is
reported as a transition phase, never as untreated pretrend.

For regional events the confirmatory estimand uses independently registered
power-affected regions.  A separate ``network_replication`` estimand uses
third-party network-observed regions only after the confirmatory result is frozen.
"""
from __future__ import annotations

import glob
import json
import pickle
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import linregress, norm, t as student_t
from sklearn.neighbors import NearestNeighbors

from .config import Config, file_sha256
from .event_design import (EventEstimand, build_estimands, clean_baseline_interval,
                           primary_estimand, stage_for_time)
from .events import Events
from .features import event_features_for_series
from .progress import HeartbeatProgress, get_logger, pbar, step
from .provenance import source_tree_sha256
from .sensor_panels import choose_primary_method
from .stats import block_bootstrap_mean

INVALID_ADMIN1 = {"COUNTRY_ONLY_UA", "UNKNOWN_ADMIN1", "UNMAPPED_UA_ADMIN1"}
EXP_B_COMPONENTS = (
    "f4",
    "f5",
    "main",
    "estimand_rows",
    "matches",
    "sensitivity",
    "placebos",
    "method_sensitivity",
    "balances",
    "universe_sensitivity",
    "mean_curves",
)


def _panel_path(cfg: Config, event_id: str) -> Path:
    return cfg.out_dir("data_derived") / "sensor_event_panel" / f"{event_id}.parquet"


def _unit_col(panel: pd.DataFrame) -> str:
    return "analysis_unit_id" if "analysis_unit_id" in panel.columns else "prefix24"



def target_universe_panels(panel: pd.DataFrame, national: bool) -> dict[str, pd.DataFrame]:
    """Return frozen geography-sensitivity panels without changing treatment labels.

    U2 is the national Ukrainian-valid-ASN sensor panel and therefore may contain
    ``COUNTRY_ONLY_UA`` endpoints. U3 additionally requires a valid target Admin1.
    Regional estimands are identifiable only in U3 because country-only endpoints
    cannot be assigned to treated or control regions.
    """
    strict = panel[~panel["target_admin1"].isin(INVALID_ADMIN1)].copy()
    if national:
        return {
            "U2_ukraine_valid_asn": panel.copy(),
            "U3_ukraine_valid_admin1_asn": strict,
        }
    return {"U3_ukraine_valid_admin1_asn": strict}


def _add_relative_time(d: pd.DataFrame, anchor, cfg: Config) -> pd.DataFrame:
    z = d.copy(); z["measure_time"] = pd.to_datetime(z["measure_time"], utc=True)
    a = pd.to_datetime(anchor, utc=True); h = float(cfg.study["expected_cycle_interval_hours"])
    z["rel_h"] = (z["measure_time"] - a).dt.total_seconds() / 3600.0
    z["rel_bin"] = (np.round(z["rel_h"] / h) * h).astype(float)
    return z


def load_event_panel(cfg: Config, row: pd.Series, anchor_shift_h: float = 0.0,
                     method: str | None = None, anchor=None) -> pd.DataFrame:
    p = _panel_path(cfg, str(row["event_id"]))
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_parquet(p); method = method or choose_primary_method(cfg)
    if "method" in d:
        d = d[d["method"].eq(method)].copy()
    if d.empty:
        return d
    if "expected_ip_n" not in d and "expected_response_n" in d:
        d["expected_ip_n"] = d["expected_response_n"]
    if "rtt_median" not in d:
        d["rtt_median"] = np.nan
    a = pd.to_datetime(anchor, utc=True) if anchor is not None else Events.anchor_time(row)
    return _add_relative_time(d, a + pd.Timedelta(hours=float(anchor_shift_h)), cfg)


def annotate_design(panel: pd.DataFrame, event: pd.Series, estimand: EventEstimand,
                    cfg: Config) -> pd.DataFrame:
    d = panel.copy(); b0, b1 = clean_baseline_interval(event, cfg)
    d["is_clean_baseline"] = d["measure_time"].between(b0, b1).astype("int8")
    d["stage"] = [stage_for_time(x, estimand, event, cfg) for x in d["measure_time"]]
    d["estimand_id"] = estimand.estimand_id
    d["claim_scope"] = estimand.claim_scope
    return d


def _baseline_rows(panel: pd.DataFrame) -> pd.DataFrame:
    if "is_clean_baseline" in panel and panel["is_clean_baseline"].eq(1).any():
        return panel[panel["is_clean_baseline"].eq(1)]
    return panel[panel["rel_bin"] < 0]


def _covariates(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel[~panel["target_admin1"].isin(INVALID_ADMIN1)].copy()
    unit = _unit_col(panel); pre = _baseline_rows(panel)
    cov = (pre.groupby([unit, "prefix24", "target_asn", "target_admin1"])
           .agg(pre_mean=("normalized_reach", "mean"), pre_sd=("normalized_reach", "std"),
                expected_ip_n=("expected_ip_n", "median"), rtt_median=("rtt_median", "median"))
           .reset_index())
    if cov.empty:
        return cov
    cov["pre_sd"] = cov["pre_sd"].fillna(0)
    fill = cov["rtt_median"].median() if cov["rtt_median"].notna().any() else 0.0
    cov["rtt_median"] = cov["rtt_median"].fillna(fill)
    return cov


def match_prefixes(panel: pd.DataFrame, affected: list[str], cfg: Config) -> pd.DataFrame:
    """Exact-ASN nearest-neighbour matching using only the clean baseline."""
    cov = _covariates(panel)
    if cov.empty:
        return pd.DataFrame()
    treated = cov[cov["target_admin1"].isin(affected)].copy()
    controls = cov[~cov["target_admin1"].isin(affected)].copy()
    rows, features = [], list(cfg.matching["covariates"]); unit = _unit_col(panel)
    for asn, tg in treated.groupby("target_asn"):
        cg = controls[controls["target_asn"].eq(asn)]; fallback = False
        if cg.empty and cfg.matching.get("fallback_cross_asn", False):
            cg, fallback = controls, True
        if cg.empty:
            continue
        pooled = pd.concat([tg[features], cg[features]], ignore_index=True)
        mu, sd = pooled.mean(), pooled.std().replace(0, 1)
        xt = ((tg[features] - mu) / sd).fillna(0).to_numpy(float)
        xc = ((cg[features] - mu) / sd).fillna(0).to_numpy(float)
        nn = NearestNeighbors(n_neighbors=1).fit(xc); dist, idx = nn.kneighbors(xt)
        max_dist = float(cfg.matching["caliper_sd"]) * np.sqrt(len(features))
        for i, (di, ji) in enumerate(zip(dist[:, 0], idx[:, 0])):
            if di > max_dist:
                continue
            a, b = tg.iloc[i], cg.iloc[int(ji)]
            row = {"pair_id": f"{a[unit]}::{b[unit]}",
                   "treated_unit": a[unit], "control_unit": b[unit],
                   "treated_prefix": a.prefix24, "control_prefix": b.prefix24,
                   "treated_asn": int(a.target_asn), "treated_admin1": a.target_admin1,
                   "control_asn": int(b.target_asn), "control_admin1": b.target_admin1,
                   "distance": float(di), "fallback_cross_asn": int(fallback)}
            for f in features:
                row[f"treated_{f}"] = float(a[f]); row[f"control_{f}"] = float(b[f])
            rows.append(row)
    return pd.DataFrame(rows)


def _smd(a: pd.Series, b: pd.Series) -> float:
    a = pd.to_numeric(a, errors="coerce").dropna(); b = pd.to_numeric(b, errors="coerce").dropna()
    if not len(a) or not len(b):
        return np.nan
    pooled = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    if not np.isfinite(pooled) or pooled == 0:
        return 0.0 if np.isclose(a.mean(), b.mean()) else np.inf
    return float((a.mean() - b.mean()) / pooled)


def balance_diagnostics(panel: pd.DataFrame, affected: list[str], matches: pd.DataFrame,
                        cfg: Config, event_id: str, method: str, estimand_id: str) -> pd.DataFrame:
    cov = _covariates(panel); t = cov[cov["target_admin1"].isin(affected)]
    c = cov[~cov["target_admin1"].isin(affected)]; rows = []
    for f in cfg.matching["covariates"]:
        before = _smd(t[f], c[f])
        after = _smd(matches.get(f"treated_{f}", pd.Series(dtype=float)),
                     matches.get(f"control_{f}", pd.Series(dtype=float))) if not matches.empty else np.nan
        rows.append({"event_id": event_id, "estimand_id": estimand_id,
                     "sensor_method": method, "covariate": f,
                     "smd_before": before, "smd_after": after,
                     "abs_smd_after": abs(after) if np.isfinite(after) else np.nan,
                     "n_treated_candidate": len(t), "n_control_candidate": len(c),
                     "n_matched_pairs": len(matches)})
    return pd.DataFrame(rows)


def paired_dynamic(panel: pd.DataFrame, matches: pd.DataFrame, cfg: Config,
                   event_id: str, seed: int) -> pd.DataFrame:
    """Matched difference-in-differences centered on each pair's clean baseline."""
    if matches.empty:
        return pd.DataFrame()
    unit = _unit_col(panel)
    cols = ["pair_id", "rel_bin", "measure_time", "normalized_reach", "is_clean_baseline"]
    t = panel.merge(matches[["pair_id", "treated_unit"]], left_on=unit, right_on="treated_unit")
    c = panel.merge(matches[["pair_id", "control_unit"]], left_on=unit, right_on="control_unit")
    t = t[["pair_id", "rel_bin", "measure_time", "normalized_reach", "is_clean_baseline"]].rename(
        columns={"normalized_reach": "treated_reach", "is_clean_baseline": "t_clean"})
    c = c[["pair_id", "rel_bin", "measure_time", "normalized_reach", "is_clean_baseline"]].rename(
        columns={"normalized_reach": "control_reach", "is_clean_baseline": "c_clean"})
    z = t.merge(c, on=["pair_id", "rel_bin", "measure_time"])
    z["diff_raw"] = z["treated_reach"] - z["control_reach"]
    clean = z[(z["t_clean"].eq(1)) & (z["c_clean"].eq(1))]
    base = clean.groupby("pair_id")["diff_raw"].mean().rename("pair_baseline")
    if base.empty:
        base = z[z["rel_bin"] < 0].groupby("pair_id")["diff_raw"].mean().rename("pair_baseline")
    z = z.merge(base, on="pair_id", how="inner"); z["diff"] = z["diff_raw"] - z["pair_baseline"]
    rows = []
    for rel, g in z.groupby("rel_bin"):
        mean, lo, hi = block_bootstrap_mean(
            g["diff"], g["pair_id"], n_boot=int(cfg.runtime["n_bootstrap"]),
            ci=float(cfg.inference["ci_level"]), seed=(seed + int(rel * 10)) % (2**32 - 1))
        rows.append({"event_id": event_id, "rel_h": float(rel), "effect": mean,
                     "ci_lo": lo, "ci_hi": hi, "n_prefix": int(g["pair_id"].nunique()),
                     "estimator": "clean_baseline_centered_matched_did"})
    return pd.DataFrame(rows).sort_values("rel_h")


def national_dynamic(panel: pd.DataFrame, cfg: Config, event_id: str, seed: int) -> pd.DataFrame:
    """National deviation from each unit's clean same-slot baseline.

    Falls back to the legacy per-unit pre-event median for compact unit tests or
    legacy panels without ``slot``/``is_clean_baseline`` columns.
    """
    unit = _unit_col(panel); z = panel.copy()
    if "slot" in z and "is_clean_baseline" in z and z["is_clean_baseline"].eq(1).any():
        base = (z[z["is_clean_baseline"].eq(1)]
                .groupby([unit, "slot"])["normalized_reach"].median().rename("prefix_pre").reset_index())
        z = z.merge(base, on=[unit, "slot"], how="left")
        fallback = z[z["is_clean_baseline"].eq(1)].groupby(unit)["normalized_reach"].median()
        z["prefix_pre"] = z["prefix_pre"].fillna(z[unit].map(fallback))
    else:
        pre = z[z["rel_bin"] < 0].groupby(unit)["normalized_reach"].median().rename("prefix_pre")
        z = z.merge(pre, on=unit, how="inner")
    z["dev"] = z["normalized_reach"] - z["prefix_pre"]
    rows = []
    for rel, g in z.groupby("rel_bin"):
        mean, lo, hi = block_bootstrap_mean(
            g["dev"], g[unit], n_boot=int(cfg.runtime["n_bootstrap"]),
            ci=float(cfg.inference["ci_level"]), seed=(seed + int(rel * 10)) % (2**32 - 1))
        rows.append({"event_id": event_id, "rel_h": float(rel), "effect": mean,
                     "ci_lo": lo, "ci_hi": hi, "n_prefix": int(g[unit].nunique()),
                     "estimator": "clean_same_slot_national_deviation"})
    return pd.DataFrame(rows).sort_values("rel_h")


def pretrend_diagnostic(curve: pd.DataFrame, cfg: Config, pre_end_rel_h: float = 0.0) -> dict:
    window = float(cfg.event_windows.get("pretrend_window_h", 24))
    pre = curve[(curve["rel_h"] < pre_end_rel_h) &
                (curve["rel_h"] >= pre_end_rel_h - window)].dropna(subset=["effect"])
    empty = {"pretrend_slope": np.nan, "pretrend_slope_ci_lo": np.nan,
             "pretrend_slope_ci_hi": np.nan, "pretrend_p": np.nan,
             "pretrend_mean": np.nan, "pretrend_mean_ci_lo": np.nan,
             "pretrend_mean_ci_hi": np.nan, "pretrend_equivalent": False,
             "pretrend_n": len(pre), "pretrend_end_rel_h": pre_end_rel_h}
    if len(pre) < 4:
        return empty
    lr = linregress(pre["rel_h"], pre["effect"]); alpha = 1 - float(cfg.inference["ci_level"])
    crit = float(student_t.ppf(1-alpha/2, max(len(pre)-2, 1)))
    slope_se = float(lr.stderr) if np.isfinite(lr.stderr) else np.nan
    slo = float(lr.slope - crit*slope_se) if np.isfinite(slope_se) else np.nan
    shi = float(lr.slope + crit*slope_se) if np.isfinite(slope_se) else np.nan
    if {"ci_lo", "ci_hi"}.issubset(pre.columns):
        se = (pre["ci_hi"] - pre["ci_lo"]) / (2 * 1.96); valid = se.replace(0, np.nan).notna()
        if valid.any():
            w = 1 / se[valid] ** 2; mean = float(np.average(pre.loc[valid, "effect"], weights=w)); mean_se = float(np.sqrt(1/w.sum()))
        else:
            mean = float(pre["effect"].mean()); mean_se = float(pre["effect"].std(ddof=1)/np.sqrt(len(pre)))
    else:
        mean = float(pre["effect"].mean()); mean_se = float(pre["effect"].std(ddof=1)/np.sqrt(len(pre)))
    mlo, mhi = mean - 1.96*mean_se, mean + 1.96*mean_se
    level_margin = float(cfg.event_windows["pretrend_equivalence_margin"])
    slope_margin = float(cfg.event_windows.get("pretrend_slope_equivalence_margin_per_h", 0.002))
    equiv = bool(mlo > -level_margin and mhi < level_margin and
                 np.isfinite(slo) and slo > -slope_margin and shi < slope_margin)
    return {"pretrend_slope": float(lr.slope), "pretrend_slope_ci_lo": slo,
            "pretrend_slope_ci_hi": shi, "pretrend_p": float(lr.pvalue),
            "pretrend_mean": mean, "pretrend_mean_ci_lo": mlo,
            "pretrend_mean_ci_hi": mhi, "pretrend_equivalent": equiv,
            "pretrend_n": len(pre), "pretrend_end_rel_h": pre_end_rel_h}


def curve_features(curve: pd.DataFrame, cfg: Config) -> dict:
    if curve.empty:
        return {}
    s = curve[["rel_h", "effect"]].rename(columns={"effect": "reach_prefix_equal"})
    s["reach_prefix_equal"] = 1 + s["reach_prefix_equal"]
    return event_features_for_series(s, cfg, baseline=1.0, lower_band=0.97,
                                     use_local_pre=False)


def _p_from_ci(effect: float, lo: float, hi: float) -> float:
    if not all(np.isfinite([effect, lo, hi])):
        return np.nan
    se = (hi-lo)/(2*1.96)
    if se <= 0:
        return 0.0 if effect != 0 else 1.0
    return float(2*(1-norm.cdf(abs(effect/se))))


def state_time_from_panel(panel: pd.DataFrame, event: pd.Series, estimand: EventEstimand,
                          cfg: Config, seed: int) -> pd.DataFrame:
    """Admin1 curves centered on each unit's clean same-slot baseline."""
    d = panel[~panel["target_admin1"].isin(INVALID_ADMIN1)].copy(); unit = _unit_col(d)
    clean = d[d["is_clean_baseline"].eq(1)]
    if clean.empty:
        return pd.DataFrame()
    if "slot" in d:
        base = clean.groupby([unit, "slot"])["normalized_reach"].median().rename("base").reset_index()
        d = d.merge(base, on=[unit, "slot"], how="left")
    else:
        base = clean.groupby(unit)["normalized_reach"].median().rename("base")
        d = d.merge(base, on=unit, how="left")
    d["dev"] = d["normalized_reach"] - d["base"]
    rows = []
    for (admin1, rel), g in d.groupby(["target_admin1", "rel_bin"]):
        mean, lo, hi = block_bootstrap_mean(g["dev"], g[unit], n_boot=int(cfg.runtime["n_bootstrap"]),
                                             ci=float(cfg.inference["ci_level"]),
                                             seed=(seed + hash((admin1, rel)) % 100000) % (2**32-1))
        rows.append({"event_id": event["event_id"], "estimand_id": estimand.estimand_id,
                     "claim_scope": estimand.claim_scope, "admin1": admin1, "rel_h": float(rel),
                     "reach_dev": mean, "ci_lo": lo, "ci_hi": hi,
                     "p_value": _p_from_ci(mean, lo, hi), "n_prefix": int(g[unit].nunique())})
    return pd.DataFrame(rows)


def event_mean_curve(panel: pd.DataFrame, event: pd.Series, estimand: EventEstimand) -> pd.DataFrame:
    treated = list(estimand.treated_admin1)
    x = panel if treated == ["ALL"] else panel[panel["target_admin1"].isin(treated)]
    if x.empty:
        return pd.DataFrame()
    clean = x[x["is_clean_baseline"].eq(1)]["normalized_reach"]
    pre = float(clean.median()) if len(clean) else 1.0
    z = x.groupby("rel_bin")["normalized_reach"].mean().rename("raw_reach").reset_index()
    z["reach"] = 1.0 + z["raw_reach"] - pre; z["event_id"] = event["event_id"]
    z["kind"] = "planned" if event["event_family"] == "planned_outage" else "attack"
    z["estimand_id"] = estimand.estimand_id
    z["sensor_method"] = panel["method"].iloc[0] if "method" in panel and len(panel) else ""
    return z.rename(columns={"rel_bin": "rel_h"})


def event_equal_fingerprint(curves: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    rows = []; min_events = int(cfg.figures.get("min_events_per_fingerprint_point", 2))
    for rel in sorted(curves["rel_h"].unique()):
        row = {"rel_h": rel}
        for kind in ("planned", "attack"):
            z = curves[(curves["rel_h"] == rel) & (curves["kind"] == kind)].groupby("event_id")["reach"].mean()
            if len(z) < min_events:
                row.update({f"{kind}_reach": np.nan, f"{kind}_lo": np.nan,
                            f"{kind}_hi": np.nan, f"{kind}_n_events": len(z)})
            else:
                row.update({f"{kind}_reach": z.mean(), f"{kind}_lo": z.quantile(.025),
                            f"{kind}_hi": z.quantile(.975), f"{kind}_n_events": len(z)})
        rows.append(row)
    return pd.DataFrame(rows)


def _clean_placebo_window(cfg: Config, anchor) -> bool:
    cq = pd.read_parquet(cfg.out_dir("data_derived") / "cycle_quality.parquet")
    ev = Events(cfg); grid = ev.build_cycle_grid(cq); clean = ev.clean_baseline_mask(grid)
    lookback = float(cfg.event_windows.get("pretrend_window_h", 24)); post = float(cfg.event_windows["event_study_post_h"])
    lo = pd.to_datetime(anchor, utc=True) - pd.Timedelta(hours=lookback)
    hi = pd.to_datetime(anchor, utc=True) + pd.Timedelta(hours=post)
    z = grid[(grid["measure_time"] >= lo) & (grid["measure_time"] <= hi)]
    return bool(not z.empty and clean.loc[z.index].all())


def national_time_placebos(cfg: Config, event: pd.Series, observed_auc: float, seed: int,
                           logger=None) -> pd.DataFrame:
    npth = cfg.out_dir("data_derived") / "national_cycle_panel.parquet"
    if not npth.exists():
        return pd.DataFrame()
    panel = pd.read_parquet(npth); panel["measure_time"] = pd.to_datetime(panel["measure_time"], utc=True)
    rows = []
    offsets = list(cfg.event_windows["placebo_week_offsets"])
    hb = None
    if logger is not None:
        hb = HeartbeatProgress(logger, f"expB.placebo.time.{event['event_id']}", total=len(offsets),
                               unit="offset", log_every_n=1, log_every_s=30.0)
        hb.start()
    for weeks in offsets:
        anchor = primary_estimand(event).anchor_utc + pd.Timedelta(weeks=int(weeks))
        if not _clean_placebo_window(cfg, anchor):
            rows.append({"event_id": event["event_id"], "placebo_type": "time",
                         "placebo_id": f"week_{weeks:+d}", "status": "skipped_overlap", "auc": np.nan})
            if hb is not None:
                hb.advance(current=f"week_{weeks:+d}", skipped="overlap")
            continue
        lo = anchor - pd.Timedelta(hours=float(cfg.event_windows.get("clean_baseline_lookback_h", 168)))
        hi = anchor + pd.Timedelta(hours=float(cfg.event_windows["event_study_post_h"]))
        pp = panel[panel["measure_time"].between(lo, hi)].copy()
        if pp.empty:
            if hb is not None:
                hb.mark_failed()
                hb.advance(current=f"week_{weeks:+d}", note="empty_panel")
            continue
        h = float(cfg.study["expected_cycle_interval_hours"])
        pp["rel_bin"] = np.round(((pp["measure_time"]-anchor).dt.total_seconds()/3600)/h)*h
        # same-slot baseline from the placebo's own clean week
        pp["slot"] = pp["measure_time"].dt.dayofweek*(24//int(h)) + pp["measure_time"].dt.hour//int(h)
        clean = pp[pp["measure_time"] < anchor-pd.Timedelta(hours=float(cfg.event_windows.get("clean_baseline_buffer_h",6)))]
        base = clean.groupby("slot")["national_reach_prefix_equal"].median()
        pp["effect"] = pp["national_reach_prefix_equal"] - pp["slot"].map(base)
        curve = pp[["rel_bin", "effect"]].rename(columns={"rel_bin": "rel_h"})
        feat = curve_features(curve, cfg)
        rows.append({"event_id": event["event_id"], "placebo_type": "time",
                     "placebo_id": f"week_{weeks:+d}", "status": "ok",
                     "auc": feat.get("deficit_auc_full"), "max_deficit": feat.get("max_deficit"),
                     "observed_auc": observed_auc})
        if hb is not None:
            hb.advance(current=f"week_{weeks:+d}", auc=feat.get("deficit_auc_full"))
    out = pd.DataFrame(rows); valid = out["auc"].dropna() if not out.empty else pd.Series(dtype=float)
    if not out.empty:
        out["empirical_p_auc"] = ((1+(valid >= observed_auc).sum())/(1+len(valid))) if len(valid) and np.isfinite(observed_auc) else np.nan
    if hb is not None:
        hb.finish(valid=len(valid))
    return out


def regional_space_placebos(panel: pd.DataFrame, event: pd.Series, estimand: EventEstimand,
                            cfg: Config, observed_auc: float, seed: int, logger=None) -> pd.DataFrame:
    """Fake-treatment-region placebo using the same event and frozen endpoint panel."""
    affected = set(estimand.treated_admin1); states = sorted(set(panel["target_admin1"]) - INVALID_ADMIN1 - affected)
    k = len(affected); draws = int(cfg.event_windows.get("regional_placebo_draws", 100))
    if k <= 0 or len(states) < k:
        return pd.DataFrame()
    rng = np.random.default_rng(seed + abs(hash(str(event["event_id"]))) % 100000); rows = []
    hb = None
    if logger is not None:
        hb = HeartbeatProgress(logger, f"expB.placebo.region.{event['event_id']}.{estimand.estimand_id}",
                               total=draws, unit="draw", log_every_n=max(1, draws // 10),
                               log_every_s=45.0)
        hb.start()
    for i in range(draws):
        fake = sorted(rng.choice(states, size=k, replace=False).tolist())
        mm = match_prefixes(panel, fake, cfg)
        if len(mm) < int(cfg.matching["min_matched_pairs"]):
            if hb is not None:
                hb.advance(current=f"draw_{i:03d}", matched_pairs=len(mm), skipped="insufficient_pairs")
            continue
        curve = paired_dynamic(panel, mm, cfg, str(event["event_id"]), seed+i)
        feat = curve_features(curve, cfg)
        rows.append({"event_id": event["event_id"], "placebo_type": "fake_region",
                     "placebo_id": f"draw_{i:03d}", "fake_treated": "|".join(fake),
                     "status": "ok", "auc": feat.get("deficit_auc_full"),
                     "max_deficit": feat.get("max_deficit"), "observed_auc": observed_auc,
                     "n_matched_pairs": len(mm)})
        if hb is not None:
            hb.advance(current=f"draw_{i:03d}", matched_pairs=len(mm), auc=feat.get("deficit_auc_full"))
    out = pd.DataFrame(rows); valid = out["auc"].dropna() if not out.empty else pd.Series(dtype=float)
    if not out.empty:
        out["empirical_p_auc"] = ((1+(valid >= observed_auc).sum())/(1+len(valid))) if len(valid) and np.isfinite(observed_auc) else np.nan
    if hb is not None:
        hb.finish(valid=len(valid))
    return out


def _estimand_row(event: pd.Series, estimand: EventEstimand, method: str, national: bool,
                  affected: list[str], match: pd.DataFrame, balance_ok: bool,
                  diag: dict, feat: dict) -> dict:
    return {"event_id": event["event_id"], "event_name_zh": event["event_name_zh"],
            "event_name_en": event["event_name_en"], "analysis_role": event["analysis_role"],
            "estimand_id": estimand.estimand_id, "claim_scope": estimand.claim_scope,
            "confirmatory": int(estimand.confirmatory), "anchor_type": estimand.anchor_type,
            "anchor_utc": estimand.anchor_utc, "treatment_start_utc": estimand.treatment_start_utc,
            "sensor_method": method, "treated": "|".join(affected),
            "control": "clean_same_slot_self_baseline" if national else "same_asn_nearest_prefix",
            "n_matched_pairs": int(len(match)), "matching_balance_ok": int(balance_ok), **diag,
            **{k: feat.get(k, np.nan) for k in ["immediate_drop", "sharpness", "max_deficit",
                                                "deficit_auc_full", "t90_h", "recovery_censored"]}}


def _event_cache_dir(cfg: Config) -> Path:
    return cfg.out_dir("data_derived") / "exp_b_event_cache"


def _event_cache_paths(cfg: Config, event_id: str) -> dict[str, Path]:
    base = _event_cache_dir(cfg)
    base.mkdir(parents=True, exist_ok=True)
    return {
        "payload": base / f"payload_{event_id}.pkl",
        "meta": base / f"done_{event_id}.json",
    }


def _base_checkpoint_signature(cfg: Config, primary_method: str) -> dict[str, Any]:
    return {
        "run_id": cfg.run_id,
        "primary_method": primary_method,
        "frozen_hashes": cfg.frozen_hashes(),
        "source_tree_sha256": source_tree_sha256(cfg.root),
        "anchor_sensitivity_hours": list(cfg.event_windows["anchor_sensitivity_hours"]),
        "placebo_week_offsets": list(cfg.event_windows["placebo_week_offsets"]),
        "regional_placebo_draws": int(cfg.event_windows.get("regional_placebo_draws", 100)),
        "matching": {
            "covariates": list(cfg.matching["covariates"]),
            "caliper_sd": float(cfg.matching["caliper_sd"]),
            "min_matched_pairs": int(cfg.matching["min_matched_pairs"]),
            "max_abs_smd": float(cfg.matching["max_abs_smd"]),
            "fallback_cross_asn": bool(cfg.matching.get("fallback_cross_asn", False)),
        },
        "runtime": {
            "n_bootstrap": int(cfg.runtime["n_bootstrap"]),
            "ci_level": float(cfg.inference["ci_level"]),
            "seed": int(cfg.runtime["random_seed"]),
        },
    }


def _event_checkpoint_signature(cfg: Config, event_id: str, base_signature: dict[str, Any]) -> dict[str, Any]:
    panel_path = _panel_path(cfg, event_id)
    national_path = cfg.out_dir("data_derived") / "national_cycle_panel.parquet"
    signature = dict(base_signature)
    signature.update({
        "event_id": event_id,
        "sensor_event_panel_sha256": file_sha256(panel_path) if panel_path.exists() else None,
        "national_cycle_panel_sha256": file_sha256(national_path) if national_path.exists() else None,
        "checkpoint_version": 1,
    })
    return signature


def _event_checkpoint_valid(paths: dict[str, Path], signature: dict[str, Any]) -> bool:
    if not paths["payload"].exists() or not paths["meta"].exists():
        return False
    try:
        meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    except Exception:
        return False
    return meta == signature


def _load_event_checkpoint(paths: dict[str, Path]) -> dict[str, pd.DataFrame]:
    with paths["payload"].open("rb") as fh:
        payload = pickle.load(fh)
    return {key: payload.get(key, pd.DataFrame()) for key in EXP_B_COMPONENTS}


def _write_event_checkpoint(paths: dict[str, Path], payload: dict[str, pd.DataFrame],
                            signature: dict[str, Any]) -> None:
    payload_tmp = paths["payload"].with_suffix(".tmp")
    meta_tmp = paths["meta"].with_suffix(".tmp")
    with payload_tmp.open("wb") as fh:
        pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
    meta_tmp.write_text(json.dumps(signature, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    payload_tmp.replace(paths["payload"])
    meta_tmp.replace(paths["meta"])


def _payload_store() -> dict[str, list[pd.DataFrame]]:
    return {key: [] for key in EXP_B_COMPONENTS}


def _append_component(store: dict[str, list[pd.DataFrame]], key: str, frame: pd.DataFrame) -> None:
    if frame is None or frame.empty:
        return
    store[key].append(frame)


def _append_event_payload(store: dict[str, list[pd.DataFrame]], payload: dict[str, pd.DataFrame]) -> None:
    for key in EXP_B_COMPONENTS:
        frame = payload.get(key)
        if frame is not None and not frame.empty:
            store[key].append(frame)


def _concat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _event_payload(store: dict[str, list[pd.DataFrame]]) -> dict[str, pd.DataFrame]:
    return {key: _concat_frames(store[key]) for key in EXP_B_COMPONENTS}


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs")); rt = cfg.out_dir("results_tables")
    ev = Events(cfg); seed = int(cfg.runtime["random_seed"]); primary_method = choose_primary_method(cfg)
    attack_rows = list(ev.attacks.iterrows())
    checkpoint_base = _event_cache_dir(cfg)
    checkpoint_base.mkdir(parents=True, exist_ok=True)
    base_signature = _base_checkpoint_signature(cfg, primary_method)
    attack_store = _payload_store()
    event_progress = HeartbeatProgress(logger, "expB.events", total=len(attack_rows),
                                       unit="event", log_every_n=1, log_every_s=45.0)
    with step("Experiment B: stage-aware held-out attack event studies", logger):
        event_progress.start(primary_method=primary_method, checkpoint_dir=checkpoint_base.name)
        for index, (_, event) in enumerate(pbar(attack_rows, total=len(attack_rows), desc="attacks", unit="event"), start=1):
            event_id = str(event["event_id"])
            paths = _event_cache_paths(cfg, event_id)
            signature = _event_checkpoint_signature(cfg, event_id, base_signature)
            if _event_checkpoint_valid(paths, signature):
                cached = _load_event_checkpoint(paths)
                _append_event_payload(attack_store, cached)
                logger.info("expB reuse event checkpoint: %s (%d/%d)", event_id, index, len(attack_rows))
                event_progress.mark_cached()
                event_progress.advance(current=event_id, event_index=index, cached=event_progress.cached)
                continue

            logger.info("expB event start: %s (%d/%d) role=%s method=%s",
                        event_id, index, len(attack_rows), event["analysis_role"], primary_method)
            t0 = time.time()
            event_store = _payload_store()
            raw = load_event_panel(cfg, event, method=primary_method)
            if raw.empty:
                _append_component(event_store, "main", pd.DataFrame([{
                    "event_id": event_id,
                    "status": "missing_event_panel",
                }]))
                payload = _event_payload(event_store)
                _write_event_checkpoint(paths, payload, signature)
                _append_event_payload(attack_store, payload)
                event_progress.mark_failed()
                event_progress.advance(current=event_id, event_index=index, note="missing_event_panel")
                continue

            confirmatory_written = False
            estimands = list(build_estimands(event))
            estimand_progress = HeartbeatProgress(logger, f"expB.estimands.{event_id}", total=len(estimands),
                                                  unit="estimand", log_every_n=1, log_every_s=60.0)
            estimand_progress.start()
            for est_index, estimand in enumerate(estimands, start=1):
                logger.info("expB estimand start: event=%s estimand=%s (%d/%d) confirmatory=%s",
                            event_id, estimand.estimand_id, est_index, len(estimands), int(estimand.confirmatory))
                panel = load_event_panel(cfg, event, method=primary_method, anchor=estimand.anchor_utc)
                panel = annotate_design(panel, event, estimand, cfg)
                affected = list(estimand.treated_admin1); national = affected == ["ALL"] or event["scope_type"] == "national"
                if not national:
                    panel = panel[~panel["target_admin1"].isin(INVALID_ADMIN1)].copy()
                match = pd.DataFrame() if national else match_prefixes(panel, affected, cfg)
                curve = national_dynamic(panel, cfg, event_id, seed) if national else paired_dynamic(panel, match, cfg, event_id, seed)
                if curve.empty:
                    _append_component(event_store, "estimand_rows", pd.DataFrame([{
                        "event_id": event_id,
                        "estimand_id": estimand.estimand_id,
                        "status": "no_identified_curve",
                    }]))
                    estimand_progress.advance(current=estimand.estimand_id, event=event_id, note="no_curve")
                    continue
                transition_h = (estimand.treatment_start_utc-estimand.anchor_utc).total_seconds()/3600
                pre_end = transition_h - float(cfg.event_windows.get("clean_baseline_buffer_h", 6))
                diag = pretrend_diagnostic(curve, cfg, pre_end_rel_h=pre_end); feat = curve_features(curve, cfg)
                if national:
                    bal = pd.DataFrame(); balance_ok = True
                else:
                    bal = balance_diagnostics(panel, affected, match, cfg, event_id, primary_method, estimand.estimand_id)
                    _append_component(event_store, "balances", bal)
                    balance_ok = bool(not bal.empty and bal["abs_smd_after"].notna().all() and
                                      (bal["abs_smd_after"] <= float(cfg.matching["max_abs_smd"])).all())
                design_admissible = bool(national or (len(match) >= int(cfg.matching["min_matched_pairs"]) and balance_ok))
                inference_admissible = bool(design_admissible and diag["pretrend_equivalent"])
                curve = curve.assign(sensor_method=primary_method, design_admissible=int(design_admissible),
                                     inference_admissible=int(inference_admissible), analysis_role=event["analysis_role"],
                                     estimand_id=estimand.estimand_id, claim_scope=estimand.claim_scope,
                                     confirmatory=int(estimand.confirmatory), anchor_utc=estimand.anchor_utc,
                                     treatment_start_utc=estimand.treatment_start_utc)
                _append_component(event_store, "f4", curve)
                st = state_time_from_panel(panel, event, estimand, cfg, seed)
                if not st.empty:
                    st["sensor_method"] = primary_method; st["design_admissible"] = int(design_admissible)
                    st["inference_admissible"] = int(inference_admissible)
                    st["analysis_role"] = event["analysis_role"]
                    st["estimand_id"] = estimand.estimand_id; st["claim_scope"] = estimand.claim_scope
                    st["confirmatory"] = int(estimand.confirmatory); st["anchor_utc"] = estimand.anchor_utc
                    st["treatment_start_utc"] = estimand.treatment_start_utc
                    _append_component(event_store, "f5", st)
                row = _estimand_row(event, estimand, primary_method, national, affected, match, balance_ok, diag, feat)
                row.update({"status": "ok" if design_admissible else "diagnostic_insufficient_pairs",
                            "design_admissible": int(design_admissible),
                            "inference_admissible": int(inference_admissible),
                            "n_treated_prefix": int(panel[_unit_col(panel)].nunique()) if national else int(panel[panel["target_admin1"].isin(affected)][_unit_col(panel)].nunique())})
                _append_component(event_store, "estimand_rows", pd.DataFrame([row]))
                if estimand.confirmatory:
                    _append_component(event_store, "main", pd.DataFrame([row]))
                    confirmatory_written = True
                    if not match.empty:
                        match = match.assign(event_id=event_id, estimand_id=estimand.estimand_id,
                                             sensor_method=primary_method)
                        _append_component(event_store, "matches", match)
                    mc = event_mean_curve(panel, event, estimand)
                    if not mc.empty:
                        _append_component(event_store, "mean_curves", mc)
                    universes = target_universe_panels(panel, national)
                    universe_progress = HeartbeatProgress(logger, f"expB.universe.{event_id}.{estimand.estimand_id}",
                                                          total=len(universes), unit="universe",
                                                          log_every_n=1, log_every_s=30.0)
                    universe_progress.start()
                    for universe_name, upanel in universes.items():
                        if upanel.empty:
                            universe_progress.advance(current=universe_name, note="empty")
                            continue
                        if national:
                            ucurve = national_dynamic(upanel, cfg, event_id, seed)
                            umatch = pd.DataFrame()
                        else:
                            umatch = match_prefixes(upanel, affected, cfg)
                            ucurve = paired_dynamic(upanel, umatch, cfg, event_id, seed)
                        ufeat = curve_features(ucurve, cfg)
                        _append_component(event_store, "universe_sensitivity", pd.DataFrame([{
                            "event_id": event_id, "analysis_role": event["analysis_role"],
                            "estimand_id": estimand.estimand_id, "scope_type": event["scope_type"],
                            "sensor_method": primary_method, "target_universe": universe_name,
                            "n_analysis_unit": int(upanel[_unit_col(upanel)].nunique()),
                            "n_sensor": int(pd.to_numeric(upanel.get("sensor_n"), errors="coerce").fillna(0).sum()),
                            "n_matched_pairs": int(len(umatch)),
                            "immediate_drop": ufeat.get("immediate_drop"),
                            "max_deficit": ufeat.get("max_deficit"),
                            "deficit_auc_full": ufeat.get("deficit_auc_full"),
                            "t90_h": ufeat.get("t90_h"),
                        }]))
                        universe_progress.advance(current=universe_name, matched_pairs=len(umatch))
                    universe_progress.finish()

                    shift_values = list(cfg.event_windows["anchor_sensitivity_hours"])
                    shift_progress = HeartbeatProgress(logger, f"expB.shift.{event_id}.{estimand.estimand_id}",
                                                       total=len(shift_values), unit="shift",
                                                       log_every_n=max(1, len(shift_values) // 3), log_every_s=30.0)
                    shift_progress.start()
                    for shift in shift_values:
                        shifted = load_event_panel(cfg, event, method=primary_method,
                                                   anchor=estimand.anchor_utc+pd.Timedelta(hours=float(shift)))
                        shifted = annotate_design(shifted, event, estimand, cfg)
                        cc = national_dynamic(shifted, cfg, event_id, seed) if national else paired_dynamic(shifted, match, cfg, event_id, seed)
                        ff = curve_features(cc, cfg)
                        _append_component(event_store, "sensitivity", pd.DataFrame([{
                            "event_id": event_id, "estimand_id": estimand.estimand_id,
                            "sensor_method": primary_method, "anchor_shift_h": shift,
                            "max_deficit": ff.get("max_deficit"), "auc": ff.get("deficit_auc_full"),
                            "t90": ff.get("t90_h")
                        }]))
                        shift_progress.advance(current=str(shift), auc=ff.get("deficit_auc_full"))
                    shift_progress.finish()

                    pl = national_time_placebos(cfg, event, float(feat.get("deficit_auc_full", np.nan)), seed,
                                                logger=logger) if national else \
                         regional_space_placebos(panel, event, estimand, cfg,
                                                 float(feat.get("deficit_auc_full", np.nan)), seed,
                                                 logger=logger)
                    if not pl.empty:
                        _append_component(event_store, "placebos", pl)

                    method_progress = HeartbeatProgress(logger, f"expB.methods.{event_id}.{estimand.estimand_id}",
                                                        total=2, unit="method", log_every_n=1, log_every_s=30.0)
                    method_progress.start()
                    for method in ("B1", "B2"):
                        mp = load_event_panel(cfg, event, method=method, anchor=estimand.anchor_utc)
                        if mp.empty:
                            _append_component(event_store, "method_sensitivity", pd.DataFrame([{
                                "event_id": event_id, "estimand_id": estimand.estimand_id,
                                "sensor_method": method, "status": "missing_panel"
                            }]))
                            method_progress.advance(current=method, note="missing_panel")
                            continue
                        mp = annotate_design(mp, event, estimand, cfg)
                        mm = pd.DataFrame() if national else match_prefixes(mp, affected, cfg)
                        mc = national_dynamic(mp, cfg, event_id, seed) if national else paired_dynamic(mp, mm, cfg, event_id, seed)
                        mf = curve_features(mc, cfg)
                        _append_component(event_store, "method_sensitivity", pd.DataFrame([{
                            "event_id": event_id, "estimand_id": estimand.estimand_id,
                            "sensor_method": method, "is_primary": int(method==primary_method),
                            "status": "ok" if not mc.empty else "no_identified_curve",
                            "n_matched_pairs": len(mm), "n_prefix": int(mp[_unit_col(mp)].nunique()),
                            "max_deficit": mf.get("max_deficit"),
                            "deficit_auc_full": mf.get("deficit_auc_full"), "t90_h": mf.get("t90_h")
                        }]))
                        method_progress.advance(current=method, matched_pairs=len(mm), auc=mf.get("deficit_auc_full"))
                    method_progress.finish()
                logger.info("expB estimand done: event=%s estimand=%s matched_pairs=%d design_ok=%d inference_ok=%d",
                            event_id, estimand.estimand_id, len(match), int(design_admissible), int(inference_admissible))
                estimand_progress.advance(current=estimand.estimand_id, event=event_id,
                                          matched_pairs=len(match), confirmatory=int(estimand.confirmatory))
            estimand_progress.finish(event=event_id)
            if not confirmatory_written:
                _append_component(event_store, "main", pd.DataFrame([{
                    "event_id": event_id,
                    "status": "missing_confirmatory_estimand",
                }]))

            payload = _event_payload(event_store)
            _write_event_checkpoint(paths, payload, signature)
            _append_event_payload(attack_store, payload)
            elapsed_s = time.time() - t0
            logger.info("expB event done: %s elapsed=%.1fs f4_rows=%d estimand_rows=%d placebos=%d checkpoint=%s",
                        event_id, elapsed_s, len(payload["f4"]), len(payload["estimand_rows"]),
                        len(payload["placebos"]), paths["payload"].name)
            event_progress.advance(current=event_id, event_index=index, cached=event_progress.cached,
                                   f4_rows=len(payload["f4"]), placebos=len(payload["placebos"]))
        event_progress.finish(cached=event_progress.cached, failed=event_progress.failed)

        planned_curves = []
        planned_rows = pd.concat([ev.planned_train, ev.planned_valid]).drop_duplicates("event_id")
        planned_progress = HeartbeatProgress(logger, "expB.planned_curves", total=len(planned_rows),
                                             unit="event", log_every_n=1, log_every_s=30.0)
        planned_progress.start()
        for _, event in planned_rows.iterrows():
            try:
                est = primary_estimand(event); p = load_event_panel(cfg, event, method=primary_method, anchor=est.anchor_utc)
                if not p.empty:
                    p = annotate_design(p, event, est, cfg)
                    mc = event_mean_curve(p, event, est)
                    if not mc.empty:
                        planned_curves.append(mc)
                planned_progress.advance(current=str(event["event_id"]))
            except Exception:
                planned_progress.mark_failed()
                planned_progress.advance(current=str(event["event_id"]), note="planned_curve_failed")
                continue
        planned_progress.finish(failed=planned_progress.failed)

    f4d = _concat_frames(attack_store["f4"])
    f5d = _concat_frames(attack_store["f5"])
    md = _concat_frames(attack_store["mean_curves"] + planned_curves)
    fp = event_equal_fingerprint(md, cfg) if not md.empty else pd.DataFrame()
    outmap = {
        "f4_event_study.csv": f4d,
        "f5_state_time.csv": f5d,
        "f6_fingerprint.csv": fp,
        "exp_b_main_results.csv": _concat_frames(attack_store["main"]),
        "exp_b_estimand_results.csv": _concat_frames(attack_store["estimand_rows"]),
        "exp_b_matches.csv": _concat_frames(attack_store["matches"]),
        "exp_b_anchor_sensitivity.csv": _concat_frames(attack_store["sensitivity"]),
        "exp_b_placebo.csv": _concat_frames(attack_store["placebos"]),
        "exp_b_method_sensitivity.csv": _concat_frames(attack_store["method_sensitivity"]),
        "exp_b_target_universe_sensitivity.csv": _concat_frames(attack_store["universe_sensitivity"]),
        "exp_b_matching_balance.csv": _concat_frames(attack_store["balances"]),
    }
    for name, d in outmap.items():
        logger.info("expB reducer write: %s rows=%d", name, len(d))
        d.to_csv(rt/name, index=False, encoding="utf-8-sig")
    return {
        "status": "ok",
        "outputs": [str(rt/x) for x in outmap],
        "cached_events": event_progress.cached,
        "computed_events": max(0, event_progress.done - event_progress.cached),
    }
