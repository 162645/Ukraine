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
        fig, ax = plt.subplots(1, 2, figsize=(cfg.figures["double_column_width_in"], 3.0), squeeze=False)
        ax = ax[0]
        for col, lab, color in (("activity_score_raw", "Activity", PALETTE[0]), ("s_reach", "S_i", PALETTE[1])):
            if col in labels:
                x = pd.to_numeric(labels[col], errors="coerce").dropna().sort_values().to_numpy()
                if len(x): ax[0].plot(x, np.arange(1, len(x) + 1) / len(x), label=lab, color=color)
        ax[0].set_xlabel("Activity / S_i"); ax[0].set_ylabel("ECDF"); ax[0].set_ylim(0, 1); ax[0].legend(frameon=False)
        if "activity_decile" in labels:
            dec = labels.groupby("activity_decile", dropna=False).size().reset_index(name="ip_n")
            ax[1].bar(dec.activity_decile.astype(str), dec.ip_n, color=PALETTE[0]); ax[1].set_xlabel("Activity decile (within state)"); ax[1].set_ylabel("IP count"); ax[1].tick_params(axis="x", rotation=45)
        else:
            ax[1].text(.5, .5, "No decile source", ha="center", va="center", transform=ax[1].transAxes); ax[1].set_axis_off()
        outputs += _save(fig, cfg, "fig05_activity_distribution", lsrc, "ECDF of continuous Activity and planned-outage-associated sensitivity.")
        if "s_reach" in labels:
            fig, ax = plt.subplots(1, 3, figsize=(cfg.figures["double_column_width_in"], 3.0)); x = pd.to_numeric(labels.s_reach, errors="coerce").dropna()
            ax[0].plot(np.sort(x), np.arange(1, len(x)+1)/len(x), color=PALETTE[1]); ax[0].axvline(0, color="0.3", ls=":"); ax[0].set_xlabel("S_i"); ax[0].set_ylabel("ECDF")
            ax[1].hist(x, bins=40, color=PALETTE[1], alpha=.85); ax[1].axvline(0, color="0.3", ls=":"); ax[1].set_xlabel("S_i = p_ctrl - p_out"); ax[1].set_ylabel("IP count")
            if "support_episode_n_primary" in labels:
                sup = labels.groupby("support_episode_n_primary", dropna=False).size().reset_index(name="ip_n"); ax[2].bar(sup.support_episode_n_primary.astype(str), sup.ip_n, color=PALETTE[2]); ax[2].set_xlabel("Support episodes"); ax[2].set_ylabel("IP count")
            else: ax[2].text(.5, .5, "No support source", ha="center", va="center", transform=ax[2].transAxes); ax[2].set_axis_off()
            outputs += _save(fig, cfg, "fig06_sensitivity_distribution", lsrc, "Distribution of continuous sensitivity, including negative values and a zero reference.")
            fig, ax = plt.subplots(figsize=(cfg.figures["single_column_width_in"], 3.0)); ax.hexbin(pd.to_numeric(labels.activity_score_raw, errors="coerce"), pd.to_numeric(labels.s_reach, errors="coerce"), gridsize=35, bins="log", cmap=DIVERGING); ax.axhline(0, color="0.3", ls=":"); ax.set_xlabel("Activity"); ax.set_ylabel("S_i")
            outputs += _save(fig, cfg, "fig07_activity_vs_sensitivity", lsrc, "Activity versus continuous planned-outage-associated sensitivity; density is log-count.")
    else: warnings.append("endpoint distribution sources unavailable")

    # H1/H2/H3/H4 summary plots share a common source contract.
    d, src = _source(cfg, "fig12_h3_activity_x_sensitivity")
    if not d.empty and {"activity_decile", "sensitivity_quintile", "peak_drop"}.issubset(d.columns):
        order_d = [f"D{i}" for i in range(1, 11)]; order_q = [f"Q{i}" for i in range(1, 6)]
        p = d.assign(activity_decile=d.activity_decile.astype(str), sensitivity_quintile=d.sensitivity_quintile.astype(str)).pivot_table(index="activity_decile", columns="sensitivity_quintile", values="peak_drop", aggfunc="mean").reindex(index=order_d, columns=order_q)
        fig, ax = plt.subplots(figsize=(cfg.figures["double_column_width_in"], 4.0)); im = ax.imshow(p.to_numpy(float), aspect="auto", cmap=DIVERGING); fig.colorbar(im, ax=ax, label="Peak drop")
        ax.set_xticks(range(len(order_q)), order_q); ax.set_yticks(range(len(order_d)), order_d); ax.set_xlabel("Sensitivity quintile"); ax.set_ylabel("Activity decile")
        for i in range(len(order_d)):
            for j in range(len(order_q)):
                if pd.isna(p.iloc[i, j]):
                    ax.add_patch(plt.Rectangle((j-.5, i-.5), 1, 1, fill=False, hatch="///", edgecolor="0.5", linewidth=0))
        outputs += _save(fig, cfg, "fig12_h3_activity_x_sensitivity", src, "Activity-decile by sensitivity-quintile heatmap; hatched cells have insufficient support and are not imputed.")
    else:
        warnings.append("fig12_h3_activity_x_sensitivity source data unavailable")
    for stem, xlabel, ylabel, xcol in (("fig10_h1_group_heterogeneity", "Group", "Peak drop", "group_id"),
                                       ("fig11_h2_sensitivity_gradient", "Sensitivity quintile", "Peak drop", "sensitivity_quintile"),
                                       ):
        d, src = _source(cfg, stem)
        if d.empty or xcol not in d or "peak_drop" not in d: warnings.append(f"{stem} source data unavailable"); continue
        g = d.groupby(xcol, dropna=False).peak_drop.mean().reset_index(); fig, ax = plt.subplots(figsize=(cfg.figures["double_column_width_in"], 3.0)); ax.plot(g[xcol].astype(str), g.peak_drop, marker="o", color=PALETTE[0]); ax.axhline(0, color="0.3", ls=":"); ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.tick_params(axis="x", rotation=30)
        outputs += _save(fig, cfg, stem, src, f"{ylabel} by {xlabel}; estimates are computed from frozen event-state features.")
    d, src = _source(cfg, "fig14_h4_loss_decomposition")
    if not d.empty and {"group", "population_share", "loss_contribution"}.issubset(d):
        g = d.groupby("group", dropna=False)[["population_share", "loss_contribution"]].mean(); fig, ax = plt.subplots(figsize=(cfg.figures["double_column_width_in"], 3.0)); g.plot.bar(ax=ax, color=[PALETTE[0], PALETTE[1]]); ax.axhline(1, color="0.3", ls=":"); ax.set_xlabel("Group"); ax.set_ylabel("Share"); ax.legend(frameon=False)
        outputs += _save(fig, cfg, "fig14_h4_loss_decomposition", src, "Population share and IPS-loss contribution by frozen endpoint group.")
    else: warnings.append("fig14 source data unavailable")
    # Remaining registered figures use deterministic type-specific renderers.
    # They never manufacture values: an empty source is reported as a warning.
    generic_specs = {
        "fig00a_cycle_quality": ("measure_time", "complete", "UTC cycle", "Complete cycle"),
        "fig00b_cycle_availability": ("measure_time", "available_ip_n", "UTC cycle", "Available IPs"),
        "fig01_oblast_coverage": ("target_admin1", "total_mapped_ip", "Oblast", "IP count"),
        "fig03_power_internet_calendar": ("date", "ips_outage_hours", "Date", "IPS outage hours"),
        "fig04_monthly_outage_hours": ("month", "ips_outage_hours", "Month", "Outage hours"),
        "fig08_attack_overall_signal": ("measure_time", "IPS_ratio", "UTC time", "IPS ratio"),
        "fig09_q1_q5_event_curves": ("rel_h", "effect", "Hours relative to attack", "IPS ratio/effect"),
        "fig13_h3_continuous_association": ("sensitivity_value", "peak_drop", "S_i", "Peak drop"),
        "fig15_network_structure": ("target_asn", "attack_peak_drop", "ASN", "Attack peak drop"),
        "fig16_as_event_timeline": ("rel_h", "reach_dev", "Hours relative to attack", "Reachability deviation"),
        "fig17_rtt_heatmap": ("measure_time", "rtt_change", "UTC time", "RTT change"),
        "fig18_threshold_sensitivity": ("threshold", "outage_hours", "Threshold", "Outage hours"),
        "fig19_power_internet_correlation": ("power_exposure", "internet_impact", "Power exposure", "Internet impact"),
    }
    for stem, (xc, yc, xl, yl) in generic_specs.items():
        if stem in {"fig00a_cycle_quality", "fig00b_cycle_availability", "fig01_oblast_coverage", "fig03_power_internet_calendar", "fig04_monthly_outage_hours", "fig08_attack_overall_signal", "fig09_q1_q5_event_curves", "fig13_h3_continuous_association", "fig15_network_structure", "fig16_as_event_timeline", "fig17_rtt_heatmap", "fig18_threshold_sensitivity", "fig19_power_internet_correlation"}:
            d, src = _source(cfg, stem)
            if d.empty or xc not in d.columns or yc not in d.columns:
                warnings.append(f"{stem} source data unavailable")
                continue
            z = d[[xc, yc]].copy(); z[yc] = pd.to_numeric(z[yc], errors="coerce"); z = z.dropna(subset=[yc])
            if z.empty:
                warnings.append(f"{stem} has no finite plot rows")
                continue
            apply_style(cfg, lang); fig, ax = plt.subplots(figsize=(cfg.figures["double_column_width_in"], 3.0))
            if stem in {"fig00a_cycle_quality", "fig01_oblast_coverage", "fig15_network_structure"}:
                z = z.groupby(xc, as_index=False)[yc].mean().sort_values(yc); ax.barh(z[xc].astype(str), z[yc], color=PALETTE[0])
            else:
                ax.plot(np.arange(len(z)), z[yc].to_numpy(float), color=PALETTE[0], marker="o", markevery=max(1, len(z)//12))
                ax.set_xticks(np.arange(len(z))[::max(1, len(z)//8)], z[xc].astype(str).to_numpy()[::max(1, len(z)//8)], rotation=30, ha="right")
            if xc == "rel_h":
                # Event-aligned curves must expose the registered anchor.
                zero_pos = int(np.flatnonzero(z[xc].to_numpy() == 0)[0]) if (z[xc] == 0).any() else 0
                ax.axvline(zero_pos, color="0.35", ls="--", lw=0.8)
            if "ratio" in yl.lower():
                ax.axhline(1.0, color="0.35", ls=":", lw=0.8)
            ax.set_xlabel(xl); ax.set_ylabel(yl); ax.axhline(0, color="0.3", ls=":")
            outputs += _save(fig, cfg, stem, src, f"{yl} by {xl}; values are shown only when the registered source data are available.")
    return {"outputs": outputs, "warnings": warnings, "status": "ok" if not warnings else "warning"}
