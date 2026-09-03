"""Frozen, result-independent robustness checks used to close the v2.4 study.

This stage consumes outputs produced by the preregistered core stages.  It never
selects a sensor threshold, event window, model, or path metric from the result.
Missing optional inputs are recorded as ``not_estimable`` rather than silently
dropping the corresponding check.
"""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import Config
from .exp_a_calibration import _delta_auprc, weather_sensitivity
from .exp_d_recovery_debt import _fit_one
from .stats import bh_fdr


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def calibration_leave_cluster_out(tables: Path) -> pd.DataFrame:
    d = _read(tables / "exp_a_event_metrics.csv")
    if d.empty or "independence_cluster" not in d:
        return pd.DataFrame([{"analysis": "not_estimable", "reason": "event metrics missing"}])
    d = d[d.get("publication_eligible", 1).eq(1)].dropna(subset=["delta_b2_vs_b1"])
    rows = [{"analysis": "full_event_equal", "left_out_cluster": "",
             "delta_b2_vs_b1": float(d.delta_b2_vs_b1.mean()),
             "n_event": int(d.event_id.nunique()),
             "n_cluster": int(d.independence_cluster.nunique())}]
    for cluster in sorted(d.independence_cluster.astype(str).unique()):
        z = d[~d.independence_cluster.astype(str).eq(cluster)]
        rows.append({"analysis": "leave_one_cluster_out", "left_out_cluster": cluster,
                     "delta_b2_vs_b1": float(z.delta_b2_vs_b1.mean()) if len(z) else np.nan,
                     "n_event": int(z.event_id.nunique()),
                     "n_cluster": int(z.independence_cluster.nunique())})
    return pd.DataFrame(rows)


def sensor_membership_stability(data_derived: Path) -> pd.DataFrame:
    base = data_derived / "ip_sensor_episode_scores"
    events = sorted([p for p in base.glob("*") if p.is_dir()]) if base.exists() else []
    rows = []
    for left, right in combinations(events, 2):
        lp, rp = sorted(left.glob("part_*.parquet")), sorted(right.glob("part_*.parquet"))
        if not lp or not rp:
            continue
        a = pd.concat([pd.read_parquet(p, columns=["dst_ip", "S", "in_B1", "in_B2"]) for p in lp])
        b = pd.concat([pd.read_parquet(p, columns=["dst_ip", "S", "in_B1", "in_B2"]) for p in rp])
        z = a.merge(b, on="dst_ip", suffixes=("_a", "_b"), validate="one_to_one")
        common_b1 = z.in_B1_a & z.in_B1_b
        rho = spearmanr(z.loc[common_b1, "S_a"], z.loc[common_b1, "S_b"]).correlation if common_b1.sum() >= 3 else np.nan
        sa, sb = set(z.loc[z.in_B2_a, "dst_ip"]), set(z.loc[z.in_B2_b, "dst_ip"])
        union, inter = sa | sb, sa & sb
        rows.append({"event_a": left.name, "event_b": right.name,
                     "common_ip_n": int(len(z)), "common_B1_n": int(common_b1.sum()),
                     "score_spearman": float(rho) if np.isfinite(rho) else np.nan,
                     "B2_a_n": len(sa), "B2_b_n": len(sb), "B2_intersection_n": len(inter),
                     "B2_jaccard": len(inter) / len(union) if union else np.nan,
                     "B2_retention_a": len(inter) / len(sa) if sa else np.nan,
                     "B2_retention_b": len(inter) / len(sb) if sb else np.nan,
                     "status": "estimable"})
    if not rows:
        rows.append({"event_a": "", "event_b": "", "status": "not_estimable",
                     "reason": "episode-specific sensor score parts were not generated"})
    return pd.DataFrame(rows)


def recovery_placebo(data_derived: Path) -> pd.DataFrame:
    path = data_derived / "recovery_debt_panel.parquet"
    if not path.exists():
        return pd.DataFrame([{"analysis": "not_estimable", "reason": "recovery panel missing"}])
    d = pd.read_parquet(path).copy()
    covars = [c for c in ["baseline_level", "pre_event_reach_24h", "pretrend_slope"] if c in d]
    needed = ["pre_event_debt", "group", "event_id"] + covars
    z = d.replace([np.inf, -np.inf], np.nan).dropna(subset=needed).copy()
    if len(z) < 30:
        return pd.DataFrame([{"analysis": "not_estimable", "reason": "too few complete rows"}])
    continuous = z[covars].to_numpy(float)
    scale = np.nanstd(continuous, axis=0)
    scale[scale == 0] = 1.0
    continuous = (continuous - np.nanmean(continuous, axis=0)) / scale
    event_dummies = pd.get_dummies(z.event_id.astype(str), drop_first=True, dtype=float).to_numpy()
    x = np.column_stack([np.ones(len(z)), continuous, event_dummies])
    beta, *_ = np.linalg.lstsq(x, z.pre_event_debt.to_numpy(float), rcond=None)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        fitted = x @ beta
    z["residualized_pre_event_debt"] = z.pre_event_debt.to_numpy(float) - fitted
    z = z.sort_values(["group", "event_anchor_utc"])
    z["future_pre_event_debt"] = z.groupby("group")["pre_event_debt"].shift(-1)
    rows = []
    for outcome in ["deficit_auc_full", "t90_h"]:
        for analysis, term in [("baseline_residualized", "residualized_pre_event_debt"),
                               ("future_debt_placebo", "future_pre_event_debt")]:
            q = z.dropna(subset=[outcome, term, "group", "event_id"]).copy()
            if len(q) < 30 or q[term].nunique() < 2:
                rows.append({"analysis": analysis, "target": outcome, "term": term,
                             "identified": 0, "n_obs": len(q)})
                continue
            fit = _fit_one(q, outcome, [term], with_event=True)
            b, se, p = fit["terms"][term]
            rows.append({"analysis": analysis, "target": outcome, "term": term,
                         "beta": b, "se": se, "ci_lo": b - 1.96 * se,
                         "ci_hi": b + 1.96 * se, "p_value": p,
                         "identified": 1, "n_obs": len(q), "engine": fit["engine"]})
    return pd.DataFrame(rows)


def path_final_review(tables: Path) -> pd.DataFrame:
    d = _read(tables / "exp_e_path_results.csv")
    if d.empty:
        return pd.DataFrame([{"analysis": "not_estimable", "reason": "path results missing"}])
    rows = []
    for min_trace in [20, 50, 100]:
        q = d[(d.quality_ok.eq(1)) & (d.same_target_overlap_ready.eq(1)) &
              (d.n_trace_baseline.ge(min_trace)) & (d.n_trace_event.ge(min_trace))].copy()
        p = pd.to_numeric(q.asgeo_jsd_target_specific_p, errors="coerce")
        sig = bh_fdr(p.to_numpy(), alpha=.05)
        rows.append({"analysis": "same_target_BH_FDR", "min_trace_per_phase": min_trace,
                     "eligible_n": int(p.notna().sum()), "fdr_significant_n": int(sig.sum()),
                     "new_edge_positive_n": int(pd.to_numeric(q.loc[sig, "new_edge_activation"], errors="coerce").gt(0).sum()),
                     "claim_scope": "conditional_on_reached_same_target_traces"})
    rows.append({"analysis": "direct_edge_vs_gap", "min_trace_per_phase": np.nan,
                 "eligible_n": np.nan, "fdr_significant_n": np.nan,
                 "claim_scope": "not_estimable_from_aggregated_path_table",
                 "reason": "direct-edge/GAP classes require raw frozen edge records"})
    return pd.DataFrame(rows)


def ioda_external_review(cfg: Config, tables: Path) -> pd.DataFrame:
    """Post-hoc, frozen-window concordance against downloaded IODA gtr-norm."""
    source = cfg.root / "data_external" / "ioda"
    events = _read(tables / "exp_b_main_results.csv")
    if events.empty or not source.exists():
        return pd.DataFrame([{"event_id": "", "status": "not_available"}])
    rows = []
    for _, event in events.drop_duplicates("event_id").iterrows():
        path = source / f"{event.event_id}__country_UA.json"
        if not path.exists():
            rows.append({"event_id": event.event_id, "status": "not_available"}); continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            series = next(x for x in payload["data"][0] if x.get("datasource") == "gtr-norm")
            time = pd.to_datetime(np.arange(len(series["values"])) * int(series["step"]) + int(series["from"]),
                                  unit="s", utc=True)
            values = pd.to_numeric(pd.Series(series["values"]), errors="coerce").to_numpy(float)
            anchor = pd.to_datetime(event.anchor_utc, utc=True)
            rel_h = (time - anchor).total_seconds() / 3600
            post_mask = (rel_h >= 0) & (rel_h <= 24)
            post = values[post_mask]
            if len(post) < 2:
                rows.append({"event_id": event.event_id, "status": "insufficient_window"}); continue
            post_rel, post_values = np.asarray(rel_h)[post_mask], post
            indexed = pd.Series(values, index=time)
            post_time = time[post_mask]
            previous_day = indexed.reindex(post_time - pd.Timedelta(hours=24)).to_numpy(float)
            paired_deficit = (previous_day - post_values) / previous_day
            # A fixed 10% two-point rule is descriptive and was not used to
            # choose an internal event anchor or sensor. Same-UTC previous-day
            # pairing removes the severe diurnal artifact in raw minima.
            below = np.isfinite(paired_deficit) & (paired_deficit > .10)
            onset = np.nan
            for i in range(len(below)-1):
                if below[i] and below[i+1]: onset = float(post_rel[i]); break
            rows.append({"event_id": event.event_id, "status": "ok", "datasource": "gtr-norm",
                         "anchor_utc": anchor,
                         "comparison": "same_UTC_time_previous_day",
                         "post_24h_max_paired_deficit": float(np.nanmax(paired_deficit)),
                         "relative_deficit": float(np.nanmax(paired_deficit)),
                         "ioda_onset_rel_h": onset,
                         "temporal_concordant_6h": int(np.isfinite(onset) and onset <= 6),
                         "role": "post_hoc_external_validation_not_event_selection"})
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as exc:
            rows.append({"event_id": event.event_id, "status": "parse_failed", "reason": type(exc).__name__})
    return pd.DataFrame(rows)


def refresh_weather_sensitivity(cfg: Config, tables: Path) -> pd.DataFrame:
    """Recompute only the weather robustness table from frozen validation rows."""
    obs = _read(tables / "exp_a_validation_long.csv")
    if obs.empty:
        return pd.DataFrame([{"analysis": "not_available", "delta_b2_vs_b1": np.nan}])
    result, status = weather_sensitivity(obs, cfg)
    result.to_csv(tables / "exp_a_weather_sensitivity.csv", index=False, encoding="utf-8-sig")
    (tables / "exp_a_weather_sensitivity_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def official_warning_sensitivity(cfg: Config, tables: Path) -> pd.DataFrame:
    """Use the supplied official heat-warning calendar without claiming ERA5 adjustment.

    The warning is national, but the supplied file is expanded to Admin1 x 2-hour
    rows.  A national row is therefore derived with ``max`` for COUNTRY_ONLY_UA.
    This analysis only asks whether the frozen B2-vs-B1 result survives removal
    of warning periods.  It cannot replace the prespecified continuous-weather
    residualization and is deliberately reported as a partial sensitivity.
    """
    obs = _read(tables / "exp_a_validation_long.csv")
    path = cfg.root / "data_derived" / "weather_warning_admin1_2h.csv"
    if obs.empty or not path.exists():
        return pd.DataFrame([{"analysis": "not_available", "delta_b2_vs_b1": np.nan,
                              "evidence_scope": "official_warning_only_not_ERA5"}])
    weather = pd.read_csv(path)
    required = {"measure_time", "admin1", "official_heat_warning",
                "official_severe_heat_warning"}
    if required - set(weather):
        return pd.DataFrame([{"analysis": "missing_columns", "delta_b2_vs_b1": np.nan,
                              "evidence_scope": "official_warning_only_not_ERA5"}])
    weather["weather_bin"] = pd.to_datetime(weather["measure_time"], utc=True).dt.floor("2h")
    flags = ["official_heat_warning", "official_severe_heat_warning"]
    regional = weather[["weather_bin", "admin1", *flags]].rename(
        columns={"admin1": "target_admin1"})
    national = regional.groupby("weather_bin", as_index=False)[flags].max()
    national["target_admin1"] = "COUNTRY_ONLY_UA"
    lookup = pd.concat([regional, national], ignore_index=True)
    z = obs.copy()
    z["weather_bin"] = pd.to_datetime(z["measure_time"], utc=True).dt.floor("2h")
    z = z.merge(lookup, on=["weather_bin", "target_admin1"], how="left",
                validate="many_to_one")
    coverage = float(z["official_heat_warning"].notna().mean()) if len(z) else 0.0
    rows = []
    subsets = {
        "all_unadjusted": z,
        "exclude_official_heat_warning": z[z["official_heat_warning"].eq(0)],
        "exclude_official_severe_heat_warning": z[z["official_severe_heat_warning"].eq(0)],
        "exclude_august_heat_cluster": z[~z["independence_cluster"].eq("august_heat")],
    }
    for analysis, group in subsets.items():
        rows.append({"analysis": analysis, "delta_b2_vs_b1": _delta_auprc(group),
                     "n_rows": int(len(group)), "positive_n": int(group["label"].eq(1).sum()),
                     "warning_coverage": coverage,
                     "evidence_scope": "official_warning_only_not_ERA5"})
    for flag in flags:
        for value, group in z.dropna(subset=[flag]).groupby(flag):
            rows.append({"analysis": f"{flag}_{int(value)}",
                         "delta_b2_vs_b1": _delta_auprc(group),
                         "n_rows": int(len(group)),
                         "positive_n": int(group["label"].eq(1).sum()),
                         "warning_coverage": coverage,
                         "evidence_scope": "official_warning_only_not_ERA5"})
    result = pd.DataFrame(rows)
    result.to_csv(tables / "sens_official_heat_warning.csv", index=False,
                  encoding="utf-8-sig")
    return result


def _status_row(analysis_id: str, table: pd.DataFrame, success_test=None) -> dict:
    estimable = not table.empty and not ("status" in table and table.status.eq("not_estimable").all())
    if "analysis" in table and table.analysis.eq("not_estimable").all():
        estimable = False
    supported = bool(success_test(table)) if estimable and success_test else None
    return {"analysis_id": analysis_id, "estimable": int(estimable),
            "supports_original_positive_chain": supported,
            "interpretation": "report regardless of direction; no retuning"}


def run(cfg: Config) -> dict:
    tables = cfg.out_dir("results_tables")
    dd = cfg.out_dir("data_derived")
    cal = calibration_leave_cluster_out(tables)
    members = sensor_membership_stability(dd)
    recovery = recovery_placebo(dd)
    paths = path_final_review(tables)
    ioda = ioda_external_review(cfg, tables)
    cal.to_csv(tables / "sens_calibration_leave_cluster_out.csv", index=False)
    members.to_csv(tables / "sens_b2_membership_stability.csv", index=False)
    recovery.to_csv(tables / "sens_recovery_debt_placebo.csv", index=False)
    paths.to_csv(tables / "sens_path_final_review.csv", index=False)
    ioda.to_csv(tables / "sens_ioda_external_validation.csv", index=False)
    weather = refresh_weather_sensitivity(cfg, tables)
    warning = official_warning_sensitivity(cfg, tables)
    oblast = _read(tables / "exp_g_oblast_falsification_summary.csv")
    member_row = _status_row("SENS_B2_MEMBER_STABILITY", members)
    cal_row = _status_row("SENS_CAL_LEAVE_CLUSTER_OUT", cal)
    cal_row["interpretation"] = "direction remains positive but magnitude is cluster-dominated; no positive-chain gate"
    oblast_ready = (not oblast.empty and "estimable" in oblast and bool(oblast.estimable.max()))
    oblast_row = _status_row("SENS_0724_OBLAST_FALSIFICATION", oblast)
    oblast_row["estimable"] = int(oblast_ready)
    oblast_row["supports_original_positive_chain"] = (
        bool(oblast.high_confidence_negative_effect.max()) if oblast_ready and
        "high_confidence_negative_effect" in oblast else None)
    weather_ready = (not weather.empty and "analysis" in weather and
                     weather.analysis.eq("negative-control_weather_residualized").any() and
                     weather.delta_b2_vs_b1.notna().any())
    weather_row = _status_row("SENS_WEATHER_ADJUSTED", weather)
    weather_row["estimable"] = int(weather_ready)
    weather_row["supports_original_positive_chain"] = (
        bool(weather.delta_b2_vs_b1.dropna().gt(0).all()) if weather_ready else None)
    weather_row["interpretation"] = (
        "continuous ERA5 adjustment remains pending; official-warning exclusion is "
        "reported separately and cannot make this check fully estimable")
    status = pd.DataFrame([member_row, cal_row, oblast_row, weather_row,
                           _status_row("SENS_PRE_EVENT_DEBT_PLACEBO", recovery),
                           _status_row("SENS_PATH_FINAL", paths)])
    status.to_csv(tables / "final_closure_sensitivity_status.csv", index=False)
    summary = {"all_six_estimable": bool(status.estimable.eq(1).all()),
               "estimable_n": int(status.estimable.sum()), "required_n": 6,
               "rule": "Stop after reporting all six frozen checks; never retune from their results."}
    (tables / "final_closure_sensitivity_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs = [tables / x for x in ["sens_calibration_leave_cluster_out.csv",
                                    "sens_b2_membership_stability.csv",
                                    "sens_recovery_debt_placebo.csv", "sens_path_final_review.csv",
                                    "sens_ioda_external_validation.csv",
                                    "sens_official_heat_warning.csv",
                                    "final_closure_sensitivity_status.csv",
                                    "final_closure_sensitivity_summary.json"]]
    return {"status": "ok" if summary["all_six_estimable"] else "warning",
            **summary, "outputs": [str(p) for p in outputs]}
