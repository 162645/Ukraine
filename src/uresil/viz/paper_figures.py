"""Compact, publication-sized figures for the registered paper source tables."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .style import PALETTE, DIVERGING, apply_style


def _source(cfg, stem):
    p = cfg.out_dir("results_figure_data", ensure=False) / f"{stem}.csv"
    if not p.exists() or not p.stat().st_size:
        return pd.DataFrame(), p
    try:
        return pd.read_csv(p), p
    except pd.errors.EmptyDataError:
        return pd.DataFrame(), p


def _save(fig, cfg, stem, source, alt):
    out = cfg.out_dir("results_figures", ensure=False); out.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("png", "pdf", "svg"):
        p = out / f"{stem}.{ext}"; fig.savefig(p, dpi=cfg.figures.get("png_dpi", 600) if ext == "png" else None,
                                                  bbox_inches="tight"); paths.append(str(p))
    plt.close(fig)
    (out / f"{stem}.alt.txt").write_text(alt, encoding="utf-8")
    (out / f"{stem}.meta.json").write_text(json.dumps({"figure_id": stem, "source_table": source.name,
        "formats": ["png", "pdf", "svg"], "title_in_figure": False, "alt_text": alt}, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def render(cfg, lang="en"):
    """Render available research-plan figures; missing evidence is reported."""
    apply_style(cfg, lang); outputs = []; warnings = []
    # Figure 2: canonical aligned IPS/FBS lanes.
    d, src = _source(cfg, "fig02_ips_fbs_oblast_time")
    if not d.empty and {"measure_time", "admin1"}.issubset(d):
        d["measure_time"] = pd.to_datetime(d.measure_time, utc=True); states = sorted(d.admin1.dropna().unique())
        times = sorted(d.measure_time.dropna().unique()); ti = {x: i for i, x in enumerate(times)}; si = {x: i for i, x in enumerate(states)}
        fig, ax = plt.subplots(2, 1, figsize=(cfg.figures["double_column_width_in"], 4.8), sharex=True)
        for a, flag, col, label in ((ax[0], "ips_outage", "#D55E00", "IPS"), (ax[1], "fbs_outage", "#009E73", "FBS")):
            for _, r in d[d.get(flag, False).fillna(False)].iterrows():
                a.vlines(ti[r.measure_time], si[r.admin1] - .35, si[r.admin1] + .35, color=col, lw=.6)
            a.set_yticks(range(len(states)), states); a.set_ylabel(label); a.set_facecolor("#eeeeee")
        ax[-1].set_xlabel("UTC 2-hour measurement cycle")
        outputs += _save(fig, cfg, "fig02_ips_fbs_oblast_time", src, "Aligned IPS and FBS outage lanes by Ukrainian Oblast; missing cycles are gray.")
    else: warnings.append("fig02 source data unavailable")

    # Figure 5/6/7: continuous endpoint distributions and relationship.
    labels, lsrc = _source(cfg, "fig07_activity_vs_sensitivity")
    if not labels.empty and "activity_score_raw" in labels:
        fig, ax = plt.subplots(figsize=(cfg.figures["single_column_width_in"], 3.0))
        for col, lab, color in (("activity_score_raw", "Activity", PALETTE[0]), ("s_reach", "S_i", PALETTE[1])):
            if col in labels:
                x = pd.to_numeric(labels[col], errors="coerce").dropna().sort_values().to_numpy()
                if len(x): ax.plot(x, np.arange(1, len(x) + 1) / len(x), label=lab, color=color)
        ax.set_xlabel("Continuous score"); ax.set_ylabel("ECDF"); ax.set_ylim(0, 1); ax.legend(frameon=False)
        outputs += _save(fig, cfg, "fig05_activity_distribution", lsrc, "ECDF of continuous Activity and planned-outage-associated sensitivity.")
        if "s_reach" in labels:
            fig, ax = plt.subplots(figsize=(cfg.figures["single_column_width_in"], 3.0)); x = pd.to_numeric(labels.s_reach, errors="coerce").dropna()
            ax.hist(x, bins=40, color=PALETTE[1], alpha=.85); ax.axvline(0, color="0.3", ls=":"); ax.set_xlabel("S_i = p_ctrl - p_out"); ax.set_ylabel("IP count")
            outputs += _save(fig, cfg, "fig06_sensitivity_distribution", lsrc, "Distribution of continuous sensitivity, including negative values and a zero reference.")
            fig, ax = plt.subplots(figsize=(cfg.figures["single_column_width_in"], 3.0)); ax.hexbin(pd.to_numeric(labels.activity_score_raw, errors="coerce"), pd.to_numeric(labels.s_reach, errors="coerce"), gridsize=35, bins="log", cmap=DIVERGING); ax.axhline(0, color="0.3", ls=":"); ax.set_xlabel("Activity"); ax.set_ylabel("S_i")
            outputs += _save(fig, cfg, "fig07_activity_vs_sensitivity", lsrc, "Activity versus continuous planned-outage-associated sensitivity; density is log-count.")
    else: warnings.append("endpoint distribution sources unavailable")

    # H1/H2/H3/H4 summary plots share a common source contract.
    for stem, xlabel, ylabel, xcol in (("fig10_h1_group_heterogeneity", "Group", "Peak drop", "group_id"),
                                       ("fig11_h2_sensitivity_gradient", "Sensitivity quintile", "Peak drop", "sensitivity_quintile"),
                                       ("fig12_h3_activity_x_sensitivity", "Sensitivity quintile", "Peak drop", "sensitivity_quintile")):
        d, src = _source(cfg, stem)
        if d.empty or xcol not in d or "peak_drop" not in d: warnings.append(f"{stem} source data unavailable"); continue
        g = d.groupby(xcol, dropna=False).peak_drop.mean().reset_index(); fig, ax = plt.subplots(figsize=(cfg.figures["double_column_width_in"], 3.0)); ax.plot(g[xcol].astype(str), g.peak_drop, marker="o", color=PALETTE[0]); ax.axhline(0, color="0.3", ls=":"); ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.tick_params(axis="x", rotation=30)
        outputs += _save(fig, cfg, stem, src, f"{ylabel} by {xlabel}; estimates are computed from frozen event-state features.")
    d, src = _source(cfg, "fig14_h4_loss_decomposition")
    if not d.empty and {"group", "population_share", "loss_contribution"}.issubset(d):
        g = d.groupby("group", dropna=False)[["population_share", "loss_contribution"]].mean(); fig, ax = plt.subplots(figsize=(cfg.figures["double_column_width_in"], 3.0)); g.plot.bar(ax=ax, color=[PALETTE[0], PALETTE[1]]); ax.axhline(1, color="0.3", ls=":"); ax.set_xlabel("Group"); ax.set_ylabel("Share"); ax.legend(frameon=False)
        outputs += _save(fig, cfg, "fig14_h4_loss_decomposition", src, "Population share and IPS-loss contribution by frozen endpoint group.")
    else: warnings.append("fig14 source data unavailable")
    return {"outputs": outputs, "warnings": warnings, "status": "ok" if not warnings else "warning"}
