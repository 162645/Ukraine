"""Research-plan outputs for H1--H4 and the paper source-data contract.

This stage never invents missing results.  It reduces the frozen attack
features and frozen endpoint labels into machine-readable tables, writes a
figure-data file and metadata for every registered paper figure, and records
which inputs were unavailable.  Empty/blocked outputs are explicit rather
than silently replaced by synthetic values.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .progress import get_logger, step

FIGURE_SPECS = {
    "fig01_oblast_coverage": {"hypothesis": "data quality", "x_axis": "ever-responsive IP count", "y_axis": "Oblast"},
    "fig00a_cycle_quality": {"hypothesis": "data quality", "x_axis": "UTC 2-hour cycle", "y_axis": "cycle completeness"},
    "fig00b_cycle_availability": {"hypothesis": "data quality", "x_axis": "UTC 2-hour cycle", "y_axis": "available IP count"},
    "fig02_ips_fbs_oblast_time": {"hypothesis": "macro prerequisite", "x_axis": "UTC 2-hour cycle", "y_axis": "Oblast"},
    "fig03_power_internet_calendar": {"hypothesis": "macro validation", "x_axis": "day of month", "y_axis": "month"},
    "fig04_monthly_outage_hours": {"hypothesis": "macro validation", "x_axis": "month", "y_axis": "outage hours"},
    "fig05_activity_distribution": {"hypothesis": "H1/H3", "x_axis": "activity", "y_axis": "IP CDF/count"},
    "fig06_sensitivity_distribution": {"hypothesis": "H2", "x_axis": "S_i", "y_axis": "CDF/count"},
    "fig07_activity_vs_sensitivity": {"hypothesis": "H3", "x_axis": "activity", "y_axis": "S_i"},
    "fig08_attack_overall_signal": {"hypothesis": "macro context", "x_axis": "hours relative to attack", "y_axis": "signal ratio"},
    "fig09_q1_q5_event_curves": {"hypothesis": "H2", "x_axis": "hours relative to attack", "y_axis": "IPS ratio"},
    "fig10_h1_group_heterogeneity": {"hypothesis": "H1", "x_axis": "D1-D10 or Q1-Q5", "y_axis": "peak IPS drop"},
    "fig11_h2_sensitivity_gradient": {"hypothesis": "H2", "x_axis": "Q1-Q5", "y_axis": "attack outcome"},
    "fig12_h3_activity_x_sensitivity": {"hypothesis": "H3", "x_axis": "Q1-Q5", "y_axis": "D1-D10"},
    "fig13_h3_continuous_association": {"hypothesis": "H3", "x_axis": "continuous S_i", "y_axis": "attack outcome"},
    "fig14_h4_loss_decomposition": {"hypothesis": "H4", "x_axis": "group", "y_axis": "loss contribution"},
    "fig15_network_structure": {"hypothesis": "extension", "x_axis": "high-sensitivity share", "y_axis": "attack drop"},
    "fig16_as_event_timeline": {"hypothesis": "extension", "x_axis": "hours relative to attack", "y_axis": "ASN"},
    "fig17_rtt_heatmap": {"hypothesis": "auxiliary RTT", "x_axis": "time", "y_axis": "ASN/Q"},
    "fig18_threshold_sensitivity": {"hypothesis": "robustness", "x_axis": "threshold", "y_axis": "outage hours/effect"},
    "fig19_power_internet_correlation": {"hypothesis": "macro validation", "x_axis": "power exposure", "y_axis": "internet impact"},
}


def _read(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_parquet(path, **kwargs) if path.suffix == ".parquet" else pd.read_csv(path, **kwargs)
    except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _quality_table(cfg) -> pd.DataFrame:
    """Flatten the validator JSON without treating JSON as CSV."""
    p = cfg.out_dir("results_tables", ensure=False) / "quality_report.json"
    if not p.exists():
        return pd.DataFrame(columns=["check", "ok", "detail"])
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return pd.DataFrame(columns=["check", "ok", "detail"])
    rows = []
    checks = obj.get("checks", obj) if isinstance(obj, dict) else {}
    if isinstance(checks, dict):
        for name, value in checks.items():
            if isinstance(value, dict):
                row = {"check": name, **value}
            else:
                row = {"check": name, "ok": bool(value), "detail": str(value)}
            rows.append(row)
    out = pd.DataFrame(rows)
    for c in ("check", "ok", "detail"):
        if c not in out:
            out[c] = pd.Series(dtype="object")
    return out[["check", "ok", "detail"] + [c for c in out.columns if c not in {"check", "ok", "detail"}]]


def _feature_tables(cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    dd = cfg.out_dir("data_derived", ensure=False)
    all_f = _read(dd / "group_event_features_all_methods.parquet")
    labels = _read(cfg.out_dir("results_tables", ensure=False) / "b1_full_sensitivity_labels.parquet")
    return all_f, labels


def _attack_metric_tables(cfg) -> dict[str, pd.DataFrame]:
    """Adapt the lightweight frozen-label attack summaries to H1--H4.

    This is the preferred source after the observational Exp-B rewrite.  The
    feature-panel route remains as a backwards-compatible fallback for old
    runs, but no matching or prediction output is required for the paper
    tables.
    """
    rt = cfg.out_dir("results_tables", ensure=False)
    m = _read(rt / "exp_b_main_results.csv")
    out = {}
    if m.empty or not {"event_id", "admin1", "group_type", "sensitivity_group"}.issubset(m.columns):
        return out
    base = [c for c in ("event_id", "admin1", "ip_n", "peak_drop", "outage_hours", "recovery_time_h") if c in m]
    h1 = m[m.group_type.isin(["ACTIVITY", "S_REACH"])].copy()
    if not h1.empty:
        h1 = h1.rename(columns={"sensitivity_group": "group_id"})
        h1["group_type"] = h1.group_type.astype(str).str.lower().replace({"s_reach": "sensitivity", "activity": "activity"})
        out["h1_ip_group_heterogeneity"] = h1[[*base, "group_type", "group_id"]]
    h2 = m[m.group_type.eq("S_REACH")].copy()
    if not h2.empty:
        h2 = h2.rename(columns={"sensitivity_group": "sensitivity_quintile"})
        out["h2_sensitivity_generalization"] = h2[[*base, "sensitivity_quintile"]]
    h3 = m[m.group_type.eq("ACTIVITY_S_REACH")].copy()
    if not h3.empty:
        parts = h3.sensitivity_group.astype(str).str.split("|", n=1, expand=True)
        h3["activity_decile"] = parts[0]; h3["sensitivity_quintile"] = parts[1]
        out["h3_activity_x_sensitivity"] = h3[[*base, "activity_decile", "sensitivity_quintile"]]
    h4 = _read(rt / "exp_b_loss_decomposition.csv")
    if not h4.empty:
        h4 = h4.rename(columns={"sensitivity_group": "group"})
        out["h4_ips_loss_decomposition"] = h4
    return out


def _h1_h2_h3_h4(features: pd.DataFrame) -> dict[str, pd.DataFrame]:
    empty = {
        "h1_ip_group_heterogeneity": pd.DataFrame(columns=["event_id", "admin1", "group_type", "group_id", "ip_n", "baseline_ips", "min_ips_ratio", "peak_drop", "outage_hours", "recovery_time_h", "support_cycles"]),
        "h2_sensitivity_generalization": pd.DataFrame(columns=["event_id", "admin1", "sensitivity_quintile", "ip_n", "peak_drop", "outage_hours", "recovery_time_h"]),
        "h2_continuous_association": pd.DataFrame(columns=["event_id", "admin1", "sensitivity_value", "peak_drop", "outage_hours", "recovery_time_h"]),
        "h3_activity_x_sensitivity": pd.DataFrame(columns=["event_id", "admin1", "activity_decile", "sensitivity_quintile", "ip_n", "peak_drop", "outage_hours", "recovery_time_h"]),
        "h4_ips_loss_decomposition": pd.DataFrame(columns=["event_id", "admin1", "group_type", "group", "eligible_ip_n", "population_share", "baseline_responsive", "event_responsive", "ips_loss", "loss_contribution", "over_contribution_ratio"]),
    }
    if features.empty:
        return empty
    f = features.copy()
    f["admin1"] = f.get("target_admin1", pd.Series("", index=f.index)).astype(str)
    f["target_asn"] = pd.to_numeric(f.get("target_asn", pd.Series(np.nan, index=f.index)), errors="coerce")
    f["prefix24"] = f.get("prefix24", pd.Series("", index=f.index)).astype(str)
    f["ip_n"] = pd.to_numeric(f.get("sensor_n", 0), errors="coerce").fillna(0)
    f["baseline_ips"] = pd.to_numeric(f.get("expected_response_n", np.nan), errors="coerce")
    f["peak_drop"] = pd.to_numeric(f.get("max_deficit", np.nan), errors="coerce")
    f["outage_hours"] = pd.to_numeric(f.get("outage_hours", np.nan), errors="coerce")
    f["recovery_time_h"] = pd.to_numeric(f.get("t90_h", np.nan), errors="coerce")
    def with_ci(frame, keys):
        out = frame.groupby(keys, dropna=False).agg(
            ip_n=("ip_n", "sum"), peak_drop=("peak_drop", "mean"), outage_hours=("outage_hours", "mean"), recovery_time_h=("recovery_time_h", "mean")).reset_index()
        stats = frame.groupby(keys, dropna=False)["peak_drop"].agg(["count", "std"]).reset_index()
        out = out.merge(stats, on=keys, how="left")
        se = out["std"] / np.sqrt(out["count"].replace(0, np.nan))
        out["peak_drop_ci_lo"] = out.peak_drop - 1.96 * se
        out["peak_drop_ci_hi"] = out.peak_drop + 1.96 * se
        return out.drop(columns=["count", "std"])
    base = ["event_id", "admin1", "target_asn", "prefix24", "ip_n", "baseline_ips", "peak_drop", "outage_hours", "recovery_time_h"]
    h1 = []
    for method, typ, split in (("ACTIVITY", "activity", None), ("S_REACH", "sensitivity", None)):
        z = f[f.get("sensor_method", "").eq(method)].copy()
        if z.empty:
            continue
        z["group_id"] = z.get("sensitivity_stratum", z.get("group", "")).astype(str)
        z["group_type"] = typ
        h1.append(z[base + ["group_type", "group_id"]])
    if h1:
        h1d = pd.concat(h1, ignore_index=True)
        empty["h1_ip_group_heterogeneity"] = h1d.merge(
            with_ci(h1d, ["event_id", "admin1", "group_type", "group_id"])[["event_id", "admin1", "group_type", "group_id", "peak_drop_ci_lo", "peak_drop_ci_hi"]],
            on=["event_id", "admin1", "group_type", "group_id"], how="left")
    q = f[f.get("sensor_method", "").eq("S_REACH")].copy()
    if not q.empty:
        q["sensitivity_quintile"] = q.get("sensitivity_stratum", "").astype(str)
        empty["h2_sensitivity_generalization"] = with_ci(q, ["event_id", "admin1", "sensitivity_quintile"])
    j = f[f.get("sensor_method", "").eq("ACTIVITY_S_REACH")].copy()
    if not j.empty:
        parts = j.get("sensitivity_stratum", "").astype(str).str.split("|", n=1, expand=True)
        j["activity_decile"] = parts[0]
        j["sensitivity_quintile"] = parts[1]
        empty["h3_activity_x_sensitivity"] = with_ci(j, ["event_id", "admin1", "activity_decile", "sensitivity_quintile"])
    overall = f[f.get("sensor_method", "").eq("ALL")].copy()
    groups = f[f.get("sensor_method", "").isin(["ACTIVITY", "S_REACH"])].copy()
    if not groups.empty:
        rows = []
        for keys, g in groups.groupby(["event_id", "admin1", "sensor_method", "sensitivity_stratum"], dropna=False):
            event, admin1, method, group = keys
            eligible = float(g.ip_n.sum())
            b = float(g.baseline_ips.sum())
            e = float((g.baseline_ips * (1 - g.peak_drop.clip(lower=0))).sum()) if b > 0 else np.nan
            rows.append({"event_id": event, "admin1": admin1, "group_type": str(method), "group": str(group), "eligible_ip_n": eligible,
                         "population_share": np.nan, "baseline_responsive": b, "event_responsive": e, "ips_loss": b-e})
        h4 = pd.DataFrame(rows)
        if not h4.empty:
            # Activity D1--D10 and sensitivity Q1--Q5 are two alternative
            # decompositions of the same population.  Their denominators must
            # be computed separately; pooling both label systems would make
            # population shares and loss contributions sum to the wrong total.
            denom_keys = ["event_id", "admin1", "group_type"]
            h4["population_share"] = h4["eligible_ip_n"] / h4.groupby(denom_keys)["eligible_ip_n"].transform("sum").replace(0, np.nan)
            h4["loss_contribution"] = h4["ips_loss"] / h4.groupby(denom_keys)["ips_loss"].transform("sum").replace(0, np.nan)
            h4["over_contribution_ratio"] = h4["loss_contribution"] / h4["population_share"].replace(0, np.nan)
            empty["h4_ips_loss_decomposition"] = h4
    return empty


def run(cfg) -> dict:
    logger = get_logger(cfg.out_dir("logs")); rt = cfg.out_dir("results_tables"); fd = cfg.out_dir("results_figure_data")
    with step("Build H1-H4 tables and paper source-data contract", logger):
        features, labels = _feature_tables(cfg)
        tables = _h1_h2_h3_h4(features)
        # Prefer the direct frozen-label attack summaries when available.  A
        # legacy feature table may still exist from an older run, but it must
        # not mask the new observational H1--H4 estimand.
        attack_tables = _attack_metric_tables(cfg)
        for name, table in attack_tables.items():
            if not table.empty:
                tables[name] = table
        # Compact paper tables requested by the plan.  Counts are derived from
        # frozen artifacts only; absent artifacts produce zero rows, never
        # fabricated estimates.
        universe = _read(cfg.out_dir("data_derived", ensure=False) / "target_ip_universe.parquet")
        if not universe.empty:
            n_all = universe.dst_ip.nunique() if "dst_ip" in universe else 0
            regional = universe[universe.get("regional_eligible", 0).astype(bool)] if "regional_eligible" in universe else universe.iloc[0:0]
            def counts(frame):
                return {"ip_count": int(frame.dst_ip.nunique()) if "dst_ip" in frame else 0,
                        "prefix24_count": int(frame.prefix24.nunique()) if "prefix24" in frame else 0,
                        "asn_count": int(frame.target_asn.nunique()) if "target_asn" in frame else 0,
                        "admin1_count": int(frame.target_admin1.nunique()) if "target_admin1" in frame else 0}
            base_n = max(n_all, 1)
            def flagged(flag):
                mask = labels.get(flag, pd.Series(False, index=labels.index))
                return labels[mask.astype(bool)]
            summary_rows = [
                {"stage": "All target IPs", **counts(universe)},
                {"stage": "Ever responsive", **counts(universe)},
                {"stage": "Valid Admin1", **counts(regional)},
            ]
            if not labels.empty:
                summary_rows += [
                    {"stage": "Activity estimable", **counts(labels)},
                    {"stage": "Sensitivity estimable >=2", **counts(flagged("support_ge_2"))},
                    {"stage": "Sensitivity estimable >=3", **counts(flagged("support_ge_3"))},
                    {"stage": "Sensitivity estimable >=4", **counts(flagged("support_ge_4"))},
                ]
            summary = pd.DataFrame(summary_rows)
            summary["retained_pct"] = 100.0 * summary.ip_count / base_n
            _write(summary, rt / "dataset_summary.csv")
        else:
            _write(pd.DataFrame(columns=["stage", "ip_count", "prefix24_count", "asn_count", "admin1_count", "retained_pct"]), rt / "dataset_summary.csv")
        events = _read(rt / "calibration_events.csv")
        event_audit = _read(rt / "calibration_event_audit.csv")
        if not events.empty:
            ce = events.copy()
            rename = {"geo_name": "state", "event_date": "date", "start_utc": "start", "end_utc": "end", "evidence_tier": "evidence_tier", "episode_id_main": "episode_id"}
            ce = ce.rename(columns=rename)
            if not event_audit.empty and "event_id" in event_audit:
                ce = ce.merge(event_audit[[c for c in ("event_id", "outage_cycle_n", "explicit_clear_cycle_n") if c in event_audit]], on="event_id", how="left")
            ce["support_cycles"] = ce.get("outage_cycle_n", pd.Series(np.nan, index=ce.index))
            ce["explicit_clear"] = ce.get("explicit_clear_cycle_n", pd.Series(np.nan, index=ce.index)).gt(0)
            for c in ("state", "date", "start", "end", "quality", "evidence_tier", "episode_id", "explicit_clear", "support_cycles"):
                if c not in ce: ce[c] = np.nan
            _write(ce[["event_id", "state", "date", "start", "end", "quality", "evidence_tier", "episode_id", "explicit_clear", "support_cycles"]], rt / "calibration_event_summary.csv")
        else:
            _write(pd.DataFrame(columns=["event_id", "state", "date", "start", "end", "quality", "evidence_tier", "episode_id", "explicit_clear", "support_cycles"]), rt / "calibration_event_summary.csv")
        attacks = _read(cfg.root / str(cfg.raw.get("freeze", {}).get("event_registry", "config/event_registry_v2.csv")))
        if not attacks.empty:
            aa = attacks[attacks.get("analysis_role", "").astype(str).str.startswith("attack")].copy()
            aa = aa.rename(columns={"primary_anchor_utc": "date", "attack_start_utc": "attack_start", "outage_start_utc": "power_impact_start", "outage_end_utc": "recovery_window", "analysis_treated_admin1": "affected_states", "label_quality": "confidence"})
            aa["main_window"] = aa.get("network_anomaly_start_utc", pd.Series("", index=aa.index))
            for c in ("event_id", "date", "attack_start", "power_impact_start", "main_window", "affected_states", "recovery_window", "confidence"):
                if c not in aa: aa[c] = np.nan
            _write(aa[["event_id", "date", "attack_start", "power_impact_start", "main_window", "affected_states", "recovery_window", "confidence"]], rt / "attack_event_summary.csv")
        else:
            _write(pd.DataFrame(columns=["event_id", "date", "attack_start", "power_impact_start", "main_window", "affected_states", "recovery_window", "confidence"]), rt / "attack_event_summary.csv")
        _write(_quality_table(cfg), rt / "data_quality_summary.csv")
        # Threshold/support robustness is a pre-registered grid.  It is a
        # contract table until real attack outcomes are available.
        thresholds = []
        for x in np.arange(.80, .981, .02): thresholds.append({"signal": "IPS", "threshold": round(float(x), 2)})
        for x in np.arange(.85, .991, .01): thresholds.append({"signal": "FBS", "threshold": round(float(x), 2)})
        for x in (2, 3, 4): thresholds.append({"signal": "sensitivity_support", "threshold": x})
        _write(pd.DataFrame(thresholds), rt / "threshold_sensitivity.csv")
        # Promote existing attack association/recovery outputs without changing
        # their frozen-label semantics.
        existing = rt / "attack_continuous_sensitivity_association.csv"
        if existing.exists():
            assoc = _read(existing)
            if not assoc.empty:
                tables["h2_continuous_association"] = assoc
        for name, table in tables.items():
            _write(table, rt / f"{name}.csv")
        main_rows = []
        for hyp, name, metric in (("H1", "h1_ip_group_heterogeneity", "peak_drop"), ("H2", "h2_sensitivity_generalization", "peak_drop"), ("H2", "h2_sensitivity_generalization", "outage_hours"), ("H2", "h2_sensitivity_generalization", "recovery_time_h"), ("H3", "h3_activity_x_sensitivity", "peak_drop"), ("H3", "h3_activity_x_sensitivity", "outage_hours"), ("H3", "h3_activity_x_sensitivity", "recovery_time_h"), ("H4", "h4_ips_loss_decomposition", "loss_contribution")):
            t = tables[name]
            if t.empty or metric not in t: continue
            # Event-equal summary: first average states within each event,
            # then average registered events.  This prevents a nationwide
            # attack from receiving more weight merely because it names more
            # affected oblasts.
            if {"event_id", "admin1"}.issubset(t.columns):
                z = t[["event_id", "admin1", metric]].copy()
                z[metric] = pd.to_numeric(z[metric], errors="coerce")
                z = z.dropna(subset=[metric]).groupby(["event_id", "admin1"], dropna=False)[metric].mean().reset_index()
                v = z.groupby("event_id", dropna=False)[metric].mean().dropna()
            else:
                v = pd.to_numeric(t[metric], errors="coerce").dropna()
            if v.empty: continue
            se = v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else np.nan
            main_rows.append({"Hypothesis": hyp, "Metric": metric, "Effect": float(v.mean()), "CI_lo": float(v.mean() - 1.96 * se) if pd.notna(se) else np.nan, "CI_hi": float(v.mean() + 1.96 * se) if pd.notna(se) else np.nan, "Support": int(len(v)), "Aggregation": "event_equal", "Conclusion": "descriptive; inferential conclusion requires real event support"})
        _write(pd.DataFrame(main_rows, columns=["Hypothesis", "Metric", "Effect", "CI_lo", "CI_hi", "Support", "Aggregation", "Conclusion"]), rt / "h1_h4_main_results.csv")
        # Explicit validation artifacts make the evidence boundary auditable.
        h4 = tables["h4_ips_loss_decomposition"]
        if h4.empty:
            _write(pd.DataFrame(columns=["event_id", "admin1", "contribution_sum", "ok"]), rt / "h4_validation.csv")
        else:
            chk_keys = ["event_id", "admin1"] + (["group_type"] if "group_type" in h4 else [])
            chk = h4.groupby(chk_keys, dropna=False)["loss_contribution"].sum().reset_index(name="contribution_sum")
            chk["ok"] = np.isclose(chk["contribution_sum"], 1.0, atol=1e-6)
            _write(chk, rt / "h4_validation.csv")
        assoc = _read(rt / "attack_continuous_sensitivity_association.csv")
        _write(assoc, rt / "attack_validation_summary.csv")
        if not labels.empty:
            _write(labels, fd / "fig05_activity_sensitivity_labels.csv")
            _write(labels, fd / "fig05_activity_distribution.csv")
            _write(labels[[c for c in labels.columns if c in {"dst_ip", "target_admin1", "activity_score_raw", "activity_decile", "s_reach", "s_reach_quintile", "support_episode_n_primary"}]], fd / "fig07_activity_vs_sensitivity.csv")
            activity_rows = []
            a = pd.to_numeric(labels.get("activity_score_raw"), errors="coerce")
            for x in a.dropna().sort_values().to_numpy():
                activity_rows.append({"kind": "ecdf", "activity": float(x), "ip_n": 1})
            if "activity_decile" in labels:
                dec = labels.groupby("activity_decile", dropna=False).size().reset_index(name="ip_n")
                dec["kind"] = "decile"
                dec["population_share"] = dec.ip_n / dec.ip_n.sum()
                activity_rows.extend(dec.rename(columns={"activity_decile": "activity"}).to_dict("records"))
            _write(pd.DataFrame(activity_rows, columns=["kind", "activity", "ip_n", "population_share"]), rt / "activity_distribution.csv")
            sens_rows = []
            s = pd.to_numeric(labels.get("s_reach_primary"), errors="coerce")
            for x in s.dropna().sort_values().to_numpy():
                sens_rows.append({"kind": "ecdf", "s_reach": float(x), "ip_n": 1})
            if "support_episode_n_primary" in labels:
                sup = labels.groupby("support_episode_n_primary", dropna=False).size().reset_index(name="ip_n")
                sup["kind"] = "support"
                sens_rows.extend(sup.rename(columns={"support_episode_n_primary": "support_episode_n"}).to_dict("records"))
            _write(pd.DataFrame(sens_rows, columns=["kind", "s_reach", "support_episode_n", "ip_n"]), rt / "sensitivity_distribution.csv")
            _write(labels[[c for c in labels.columns if c in {"dst_ip", "target_admin1", "s_reach_primary", "s_reach", "support_episode_n_primary", "s_reach_quintile"}]], fd / "fig06_sensitivity_distribution.csv")
        else:
            _write(pd.DataFrame(columns=["kind", "activity", "ip_n", "population_share"]), rt / "activity_distribution.csv")
            _write(pd.DataFrame(columns=["kind", "s_reach", "support_episode_n", "ip_n"]), rt / "sensitivity_distribution.csv")
            _write(pd.DataFrame(columns=["dst_ip", "target_admin1", "s_reach_primary", "s_reach", "support_episode_n_primary", "s_reach_quintile"]), fd / "fig05_activity_distribution.csv")
            _write(pd.DataFrame(columns=["dst_ip", "target_admin1", "s_reach_primary", "s_reach", "support_episode_n_primary", "s_reach_quintile"]), fd / "fig06_sensitivity_distribution.csv")
        canonical = _read(cfg.out_dir("data_derived", ensure=False) / "canonical_ips_fbs_2h.parquet")
        if not canonical.empty:
            _write(canonical, fd / "fig02_ips_fbs_oblast_time.csv")
            c = canonical.copy(); c["measure_time"] = pd.to_datetime(c.measure_time, utc=True)
            monthly = c.assign(month=c.measure_time.dt.strftime("%Y-%m")).groupby("month", as_index=False).agg(
                ips_outage_hours=("ips_outage", "sum"), fbs_outage_hours=("fbs_outage", "sum"))
            monthly["ips_outage_hours"] *= 2; monthly["fbs_outage_hours"] *= 2
            _write(monthly, fd / "fig04_monthly_outage_hours.csv")
            cal = c.assign(date=c.measure_time.dt.date, month=c.measure_time.dt.strftime("%Y-%m"))
            cal = cal.groupby(["month", "date"], as_index=False).agg(ips_outage_hours=("ips_outage", "sum"), fbs_outage_hours=("fbs_outage", "sum"))
            cal["ips_outage_hours"] *= 2; cal["fbs_outage_hours"] *= 2
            # Join scheduled calibration exposure to the canonical network
            # calendar when event windows are available.  Missing schedules
            # remain NA rather than being interpreted as zero exposure.
            cal_net = c.assign(date=c.measure_time.dt.date, month=c.measure_time.dt.strftime("%Y-%m"))
            cal_net = cal_net.groupby(["month", "date", "admin1"], as_index=False).agg(
                ips_outage_hours=("ips_outage", "sum"), fbs_outage_hours=("fbs_outage", "sum"))
            cal_net["ips_outage_hours"] *= 2; cal_net["fbs_outage_hours"] *= 2
            planned = _read(rt / "calibration_events.csv")
            if not planned.empty and {"geo_name", "start_utc", "end_utc"}.issubset(planned.columns):
                rows = []
                for _, e in planned.iterrows():
                    s, en = pd.to_datetime(e.start_utc, utc=True, errors="coerce"), pd.to_datetime(e.end_utc, utc=True, errors="coerce")
                    if pd.isna(s) or pd.isna(en): continue
                    for day in pd.date_range(s.normalize(), en.normalize(), freq="D", tz="UTC"):
                        lo, hi = max(s, day), min(en, day + pd.Timedelta(days=1))
                        rows.append({"month": day.strftime("%Y-%m"), "date": day.date(), "admin1": str(e.geo_name), "planned_power_hours": max(0.0, (hi-lo).total_seconds()/3600.0)})
                if rows:
                    planned = pd.DataFrame(rows).groupby(["month", "date", "admin1"], as_index=False).planned_power_hours.sum()
                    cal_net = cal_net.merge(planned, on=["month", "date", "admin1"], how="outer")
            _write(cal_net, fd / "fig03_power_internet_calendar.csv")
            fingerprint = _read(rt / "f6_fingerprint.csv")
            _write(fingerprint if not fingerprint.empty else c, fd / "fig08_attack_overall_signal.csv")
        else:
            _write(pd.DataFrame(columns=["month", "ips_outage_hours", "fbs_outage_hours"]), fd / "fig04_monthly_outage_hours.csv")
            _write(pd.DataFrame(columns=["month", "date", "ips_outage_hours", "fbs_outage_hours"]), fd / "fig03_power_internet_calendar.csv")
            _write(pd.DataFrame(columns=["measure_time", "admin1", "IPS_ratio", "FBS_ratio"]), fd / "fig08_attack_overall_signal.csv")
        if not universe.empty:
            u = universe.copy()
            if "target_admin1" in u:
                cov = u.groupby("target_admin1", dropna=False).agg(total_mapped_ip=("dst_ip", "nunique")).reset_index()
                if not labels.empty:
                    z = labels.groupby("target_admin1").agg(activity_estimable_ip=("dst_ip", "nunique"), sensitivity_ip=("primary_estimable", "sum"), sensitivity_support3_ip=("support_ge_3", "sum")).reset_index()
                    cov = cov.merge(z, on="target_admin1", how="left")
                _write(cov, fd / "fig01_oblast_coverage.csv")
        else:
            _write(pd.DataFrame(columns=["target_admin1", "total_mapped_ip", "activity_estimable_ip", "sensitivity_ip", "sensitivity_support3_ip"]), fd / "fig01_oblast_coverage.csv")
        # Figure 9 is the held-out Q1--Q5 attack characterization, not the
        # legacy generic event-study renderer.  Keep event/state rows in the
        # source table, but make the aggregation contract explicit so the
        # renderer can average states within event and then events equally.
        sens_curve = _read(rt / "exp_b_sensitivity_curves.csv")
        if not sens_curve.empty and {"rel_h", "IPS_ratio", "group_type", "sensitivity_group"}.issubset(sens_curve.columns):
            qcurve = sens_curve[sens_curve.group_type.astype(str).eq("S_REACH")].copy()
            qcurve = qcurve.rename(columns={"IPS_ratio": "reach", "sensitivity_group": "sensitivity_quintile"})
            qcurve["sensitivity_quintile"] = qcurve.sensitivity_quintile.astype(str)
            # One row is one event × relative cycle × quintile after state
            # averaging.  Plotting code performs the final event-equal mean.
            keys = [c for c in ("event_id", "rel_h", "sensitivity_quintile") if c in qcurve.columns]
            qcurve = (qcurve.groupby(keys, dropna=False)
                      .agg(reach=("reach", "mean"), state_n=("admin1", "nunique"))
                      .reset_index())
            _write(qcurve, fd / "fig09_q1_q5_event_curves.csv")
        else:
            event_curve = _read(rt / "f4_event_study.csv")
            _write(event_curve if not event_curve.empty else pd.DataFrame(columns=["rel_h", "effect"]), fd / "fig09_q1_q5_event_curves.csv")
        _write(_read(rt / "attack_continuous_sensitivity_association.csv"), fd / "fig13_h3_continuous_association.csv")
        _write(_read(rt / "f5_state_time.csv"), fd / "fig16_as_event_timeline.csv")
        cycle_quality = _read(rt / "cycle_quality.csv")
        _write(cycle_quality if not cycle_quality.empty else pd.DataFrame(columns=["measure_time", "complete", "available_ip_n"]), fd / "fig00a_cycle_quality.csv")
        _write(cycle_quality if not cycle_quality.empty else pd.DataFrame(columns=["measure_time", "available_ip_n"]), fd / "fig00b_cycle_availability.csv")
        _write(pd.DataFrame(columns=["target_asn", "admin1", "high_sensitivity_share", "attack_peak_drop"]), fd / "fig15_network_structure.csv")
        if not features.empty and {"target_asn", "sensor_method", "sensitivity_stratum", "peak_drop"}.issubset(features.columns):
            ff = features.copy(); ff["target_asn"] = pd.to_numeric(ff.target_asn, errors="coerce")
            ff["high_sensitivity"] = ff.sensitivity_stratum.astype(str).isin(["Q4", "Q5"])
            structure = ff.groupby(["target_asn", "admin1"], dropna=False).agg(high_sensitivity_share=("high_sensitivity", "mean"), attack_peak_drop=("peak_drop", "mean"), sensor_n=("sensor_n", "sum") if "sensor_n" in ff else ("high_sensitivity", "size")).reset_index()
            _write(structure, fd / "fig15_network_structure.csv")
        if not assoc.empty and {"admin1", "sensitivity_metric"}.issubset(assoc.columns):
            rtt = assoc[assoc.sensitivity_metric.astype(str).str.contains("rtt", case=False, na=False)].copy()
            _write(rtt, fd / "fig17_rtt_heatmap.csv")
        else:
            _write(pd.DataFrame(columns=["measure_time", "target_asn", "sensitivity_quintile", "rtt_change"]), fd / "fig17_rtt_heatmap.csv")
        _write(pd.DataFrame(columns=["power_exposure", "internet_impact", "admin1"]), fd / "fig19_power_internet_correlation.csv")
        # Every declared paper figure gets a deterministic source CSV and a
        # metadata sidecar.  Empty sources are honest missing-evidence markers.
        for stem, spec in FIGURE_SPECS.items():
            src = fd / f"{stem}.csv"
            if not src.exists():
                if stem.startswith("fig10"):
                    _write(tables["h1_ip_group_heterogeneity"], src)
                elif stem.startswith("fig11"):
                    _write(tables["h2_sensitivity_generalization"], src)
                elif stem.startswith("fig12"):
                    _write(tables["h3_activity_x_sensitivity"], src)
                elif stem.startswith("fig13"):
                    _write(tables["h2_continuous_association"], src)
                elif stem.startswith("fig14"):
                    _write(tables["h4_ips_loss_decomposition"], src)
                elif stem.startswith("fig18"):
                    _write(_read(rt / "threshold_sensitivity.csv"), src)
                elif stem == "fig00a_cycle_quality":
                    _write(_read(fd / "fig00a_cycle_quality.csv"), src)
                elif stem == "fig00b_cycle_availability":
                    _write(_read(fd / "fig00b_cycle_availability.csv"), src)
                else:
                    # Keep a readable CSV even when the upstream table is not
                    # available yet; an empty file is not a valid source-data
                    # artifact and hides the missing-evidence state.
                    _write(pd.DataFrame(columns=["status"]), src)
            meta = {"figure_id": stem, "research_question": spec["hypothesis"],
                    "hypothesis": spec["hypothesis"], "x_axis": spec["x_axis"], "y_axis": spec["y_axis"],
                    "aggregation": "event-state or event-equal where available", "baseline": "frozen clean pre-event or prior 7-day mean",
                    "event_anchor": "external registry; never curve-selected", "sample_definition": "frozen canonical or label population as stated",
                    "source_table": src.name, "data_rows": int(len(_read(src)))}
            (fd / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "outputs": [str(rt / f"{x}.csv") for x in tables] + [str(rt / x) for x in ("dataset_summary.csv", "calibration_event_summary.csv", "attack_event_summary.csv", "activity_distribution.csv", "sensitivity_distribution.csv", "h1_h4_main_results.csv", "threshold_sensitivity.csv", "data_quality_summary.csv", "h4_validation.csv", "attack_validation_summary.csv")] + [str(fd)],
            "h1_rows": len(tables["h1_ip_group_heterogeneity"]), "h2_rows": len(tables["h2_sensitivity_generalization"]),
            "h3_rows": len(tables["h3_activity_x_sensitivity"]), "h4_rows": len(tables["h4_ips_loss_decomposition"])}
