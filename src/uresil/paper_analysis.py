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


def _feature_tables(cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    dd = cfg.out_dir("data_derived", ensure=False)
    all_f = _read(dd / "group_event_features_all_methods.parquet")
    labels = _read(cfg.out_dir("results_tables", ensure=False) / "b1_full_sensitivity_labels.parquet")
    return all_f, labels


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
    f["ip_n"] = pd.to_numeric(f.get("sensor_n", 0), errors="coerce").fillna(0)
    f["baseline_ips"] = pd.to_numeric(f.get("expected_response_n", np.nan), errors="coerce")
    f["peak_drop"] = pd.to_numeric(f.get("max_deficit", np.nan), errors="coerce")
    f["outage_hours"] = pd.to_numeric(f.get("outage_hours", np.nan), errors="coerce")
    f["recovery_time_h"] = pd.to_numeric(f.get("t90_h", np.nan), errors="coerce")
    base = ["event_id", "admin1", "ip_n", "baseline_ips", "peak_drop", "outage_hours", "recovery_time_h"]
    h1 = []
    for method, typ, split in (("ACTIVITY", "activity", None), ("S_REACH", "sensitivity", None)):
        z = f[f.get("sensor_method", "").eq(method)].copy()
        if z.empty:
            continue
        z["group_id"] = z.get("sensitivity_stratum", z.get("group", "")).astype(str)
        z["group_type"] = typ
        h1.append(z[base + ["group_type", "group_id"]])
    if h1:
        empty["h1_ip_group_heterogeneity"] = pd.concat(h1, ignore_index=True)
    q = f[f.get("sensor_method", "").eq("S_REACH")].copy()
    if not q.empty:
        q["sensitivity_quintile"] = q.get("sensitivity_stratum", "").astype(str)
        empty["h2_sensitivity_generalization"] = q[base + ["sensitivity_quintile"]].groupby(
            ["event_id", "admin1", "sensitivity_quintile"], as_index=False).agg(
                ip_n=("ip_n", "sum"), peak_drop=("peak_drop", "mean"), outage_hours=("outage_hours", "mean"), recovery_time_h=("recovery_time_h", "mean"))
    j = f[f.get("sensor_method", "").eq("ACTIVITY_S_REACH")].copy()
    if not j.empty:
        parts = j.get("sensitivity_stratum", "").astype(str).str.split("|", n=1, expand=True)
        j["activity_decile"] = parts[0]
        j["sensitivity_quintile"] = parts[1]
        empty["h3_activity_x_sensitivity"] = j.groupby(
            ["event_id", "admin1", "activity_decile", "sensitivity_quintile"], as_index=False).agg(
                ip_n=("ip_n", "sum"), peak_drop=("peak_drop", "mean"), outage_hours=("outage_hours", "mean"), recovery_time_h=("recovery_time_h", "mean"))
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
            h4["population_share"] = h4["eligible_ip_n"] / h4.groupby(["event_id", "admin1"])["eligible_ip_n"].transform("sum").replace(0, np.nan)
            h4["loss_contribution"] = h4["ips_loss"] / h4.groupby(["event_id", "admin1"])["ips_loss"].transform("sum").replace(0, np.nan)
            h4["over_contribution_ratio"] = h4["loss_contribution"] / h4["population_share"].replace(0, np.nan)
            empty["h4_ips_loss_decomposition"] = h4
    return empty


def run(cfg) -> dict:
    logger = get_logger(cfg.out_dir("logs")); rt = cfg.out_dir("results_tables"); fd = cfg.out_dir("results_figure_data")
    with step("Build H1-H4 tables and paper source-data contract", logger):
        features, labels = _feature_tables(cfg)
        tables = _h1_h2_h3_h4(features)
        # Promote existing attack association/recovery outputs without changing
        # their frozen-label semantics.
        existing = rt / "attack_continuous_sensitivity_association.csv"
        if existing.exists():
            assoc = _read(existing)
            if not assoc.empty:
                tables["h2_continuous_association"] = assoc
        for name, table in tables.items():
            _write(table, rt / f"{name}.csv")
        if not labels.empty:
            _write(labels, fd / "fig05_activity_sensitivity_labels.csv")
            _write(labels[[c for c in labels.columns if c in {"dst_ip", "target_admin1", "activity_score_raw", "activity_decile", "s_reach", "s_reach_quintile", "support_episode_n_primary"}]], fd / "fig07_activity_vs_sensitivity.csv")
        canonical = _read(cfg.out_dir("data_derived", ensure=False) / "canonical_ips_fbs_2h.parquet")
        if not canonical.empty:
            _write(canonical, fd / "fig02_ips_fbs_oblast_time.csv")
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
                else:
                    _write(pd.DataFrame(), src)
            meta = {"figure_id": stem, "research_question": spec["hypothesis"],
                    "hypothesis": spec["hypothesis"], "x_axis": spec["x_axis"], "y_axis": spec["y_axis"],
                    "aggregation": "event-state or event-equal where available", "baseline": "frozen clean pre-event or prior 7-day mean",
                    "event_anchor": "external registry; never curve-selected", "sample_definition": "frozen canonical or label population as stated",
                    "source_table": src.name, "data_rows": int(len(_read(src)))}
            (fd / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "outputs": [str(rt / f"{x}.csv") for x in tables] + [str(fd)],
            "h1_rows": len(tables["h1_ip_group_heterogeneity"]), "h2_rows": len(tables["h2_sensitivity_generalization"]),
            "h3_rows": len(tables["h3_activity_x_sensitivity"]), "h4_rows": len(tables["h4_ips_loss_decomposition"])}
