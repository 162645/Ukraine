#!/usr/bin/env python3
"""Render a minimal submission figure set directly from frozen v2.4 outputs.

This renderer deliberately ignores every previously rendered figure.  It reads
only frozen CSV results and produces figures that answer the three paper-level
questions: calibration, held-out attack generalization/measurement, and
ASN-Admin1 fingerprint validation.  It never runs a core experiment.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uresil.config import load_config
from uresil.viz.style import PALETTE, apply_style


PAGE = (12.0, 6.8)
EVENTS = ["E2024_0826_ATTACK", "E2024_0917_SUMY", "E2024_1117_ATTACK",
          "E2024_1128_ATTACK", "E2024_1213_ATTACK", "E2024_1225_ATTACK"]
SHORT = dict(zip(EVENTS, ["08/26", "09/17", "11/17", "11/28", "12/13", "12/25"]))
PLAN_SHORT = {"E2024_0728_PLANNED": "07/28", "E2024_0819_PLANNED": "08/19",
              "E2024_0820_PLANNED": "08/20", "E2024_0821_PLANNED": "08/21",
              "E2024_1209_PLANNED": "12/09"}

TX = {
    "en": {
        "f1": "Figure 1 | Scheduled-outage calibration fails the preregistered gate",
        "f1a": "A  Held-out discrimination",
        "f1b": "B  Event-level B2 - B1",
        "f1c": "C  Pooled calibration gate",
        "auprc": "AUPRC",
        "delta_auprc": "ΔAUPRC (B2 - B1)",
        "excluded": "excluded",
        "gate": "Gate not passed",
        "f2": "Figure 2 | Power-specific B2 does not consistently generalize to held-out attacks",
        "f2a": "A  Change in maximum deficit",
        "f2b": "B  Change in cumulative deficit (AUC)",
        "delta_max": "B2 - B1 maximum reachability deficit",
        "delta_auc": "B2 - B1 cumulative deficit (AUC)",
        "b1_stronger": "B1 stronger",
        "b2_stronger": "B2 stronger",
        "descriptive": "descriptive only",
        "positive_count": "B2 larger in {n}/{d} admissible events",
        "sensitivity_only": "Within-event method sensitivity; no pooled confirmatory test is claimed.",
        "f3": "Figure 3 | Held-out attacks are observable, but their magnitude and recovery are heterogeneous",
        "deficit": "Reachability deficit vs matched baseline",
        "hours": "Hours from registered attack anchor",
        "admissible": "admissible",
        "peak": "peak",
        "recovery": "t90",
        "f4": "Figure 4 | ASN-Admin1 responses are neither repeatable nor predictively validated",
        "f4a": "A  Cross-event rank repeatability",
        "f4b": "B  Rolling held-out prediction",
        "rho": "Spearman ρ",
        "mae": "Event-equal MAE for deficit AUC (lower is better)",
        "prediction_note": "History model: 41.7% apparent gain vs M3\npermutation p = 0.294",
    },
    "zh": {
        "f1": "图1 | 计划停电校准未通过预注册门槛",
        "f1a": "A  留出事件区分能力",
        "f1b": "B  事件级B2 - B1",
        "f1c": "C  总体校准门",
        "auprc": "AUPRC",
        "delta_auprc": "ΔAUPRC（B2 - B1）",
        "excluded": "排除",
        "gate": "校准门未通过",
        "f2": "图2 | 供电特异B2没有稳定泛化到留出攻击",
        "f2a": "A  最大缺口的变化",
        "f2b": "B  累计缺口（AUC）的变化",
        "delta_max": "B2 - B1 最大可达性缺口",
        "delta_auc": "B2 - B1 累计缺口（AUC）",
        "b1_stronger": "B1更强",
        "b2_stronger": "B2更强",
        "descriptive": "仅描述",
        "positive_count": "{d}个可推断事件中，B2在{n}个更大",
        "sensitivity_only": "同一事件内的方法敏感性比较；不声称存在总体确认性检验。",
        "f3": "图3 | 留出攻击可以观测，但影响强度和恢复过程存在明显异质性",
        "deficit": "相对匹配基线的可达性缺口",
        "hours": "相对登记攻击锚点的小时数",
        "admissible": "可推断",
        "peak": "峰值",
        "recovery": "t90",
        "f4": "图4 | ASN-地区响应既不稳定重复，也未通过预测验证",
        "f4a": "A  跨事件等级重复性",
        "f4b": "B  滚动留出预测",
        "rho": "Spearman ρ",
        "mae": "缺口AUC的事件等权MAE（越低越好）",
        "prediction_note": "历史模型相对M3表观改善41.7%\n置换检验p = 0.294",
    },
}


def read(tables: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(tables / name)


def style(cfg, lang: str) -> None:
    apply_style(cfg, lang)
    plt.rcParams.update({"font.size": 11, "axes.labelsize": 11, "axes.titlesize": 11.5,
                         "xtick.labelsize": 9.5, "ytick.labelsize": 9.5,
                         "legend.fontsize": 9.2, "savefig.bbox": None})


def panel(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontweight="bold", pad=10)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)


def calibration(cfg, tables: Path, lang: str):
    t = TX[lang]; style(cfg, lang)
    summary = read(tables, "exp_a_summary.csv")
    pooled = summary.iloc[0]
    event = read(tables, "exp_a_event_metrics.csv").copy()
    fig, axes = plt.subplots(1, 3, figsize=PAGE, gridspec_kw={"width_ratios": [.82, 1.25, 1]})
    m = summary.set_index("method").reindex(["B0", "B1", "B2"]).reset_index()
    ax = axes[0]; bars = ax.bar(m.method, m.auprc, color=["0.72", PALETTE[0], PALETTE[1]], width=.62)
    for b, v in zip(bars, m.auprc): ax.text(b.get_x()+b.get_width()/2, v+.007, f"{v:.3f}", ha="center")
    ax.set_ylim(0, max(m.auprc)*1.22); ax.set_ylabel(t["auprc"]); ax.grid(axis="y", alpha=.3); panel(ax, t["f1a"])
    ax = axes[1]; event["short"] = event.event_id.map(lambda x: PLAN_SHORT.get(x, x))
    event = event.sort_values("delta_b2_vs_b1"); y = np.arange(len(event)); ok = event.publication_eligible.eq(1)
    ax.barh(y, event.delta_b2_vs_b1, color=[PALETTE[1] if x else "0.72" for x in ok], height=.62)
    ax.set_yticks(y, [s if x else f"{s} ({t['excluded']})" for s, x in zip(event.short, ok)])
    ax.axvline(0, color="0.25", lw=.9); ax.set_xlabel(t["delta_auprc"]); ax.grid(axis="x", alpha=.3); panel(ax, t["f1b"])
    ax = axes[2]; p, lo, hi = map(float, [pooled.delta_b2_vs_b1, pooled.delta_ci_lo, pooled.delta_ci_hi])
    ax.errorbar(p, 0, xerr=[[p-lo], [hi-p]], fmt="o", ms=8, capsize=6, color=PALETTE[1])
    ax.axvline(0, color="0.25", lw=.9); ax.set_yticks([0], ["ΔAUPRC"]); ax.set_ylim(-.65, .65); ax.grid(axis="x", alpha=.3)
    ax.text(.5, .18, f"{t['gate']}\n95% CI [{lo:+.3f}, {hi:+.3f}]\np = {float(pooled.permutation_p):.3f}",
            transform=ax.transAxes, ha="center", fontsize=10.5,
            bbox={"boxstyle":"round,pad=.35", "fc":"#F8E7E7", "ec":"#B85C5C"})
    panel(ax, t["f1c"])
    fig.suptitle(t["f1"], fontsize=15, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.82, bottom=.16, left=.08, right=.98, wspace=.45)
    return fig


def attack_generalization(cfg, tables: Path, lang: str):
    t = TX[lang]; style(cfg, lang)
    d = read(tables, "exp_b_method_sensitivity.csv")
    d = d[d.event_id.isin(EVENTS) & d.sensor_method.isin(["B1", "B2"])]
    w = d.pivot(index="event_id", columns="sensor_method", values=["max_deficit", "deficit_auc_full"]).reindex(EVENTS)
    main = read(tables, "exp_b_main_results.csv").set_index("event_id").reindex(EVENTS)
    admissible = main.inference_admissible.eq(1).to_numpy()
    fig, axes = plt.subplots(1, 2, figsize=PAGE, sharey=True)
    specs = [("max_deficit", t["f2a"], t["delta_max"]),
             ("deficit_auc_full", t["f2b"], t["delta_auc"])]
    labels = [SHORT[e] + (f" | {t['descriptive']}" if not admissible[i] else "") for i, e in enumerate(EVENTS)]
    for j, (metric, title, xlabel) in enumerate(specs):
        ax = axes[j]; delta = (w[(metric, "B2")] - w[(metric, "B1")]).to_numpy(float); y = np.arange(len(EVENTS))
        colors = [PALETTE[1] if admissible[i] else "0.60" for i in range(len(EVENTS))]
        ax.hlines(y, 0, delta, color="0.80", lw=1.5); ax.scatter(delta, y, color=colors, s=58, zorder=3)
        ax.axvline(0, color="0.20", lw=1); ax.set_yticks(y, labels); ax.grid(axis="x", alpha=.32)
        if j > 0: ax.tick_params(axis="y", labelleft=False)
        ax.set_xlabel(xlabel); panel(ax, title)
        npos = int(((delta > 0) & admissible).sum()); den = int(admissible.sum())
        ax.text(.98, .06, t["positive_count"].format(n=npos, d=den), transform=ax.transAxes,
                ha="right", fontsize=10, color="#8A3B3B")
        xmin, xmax = ax.get_xlim()
        ax.text(xmin, len(EVENTS)-.25, f"← {t['b1_stronger']}", ha="left", va="bottom", fontsize=9, color="0.4")
        ax.text(xmax, len(EVENTS)-.25, f"{t['b2_stronger']} →", ha="right", va="bottom", fontsize=9, color="0.4")
    axes[0].invert_yaxis()
    fig.text(.98, .055, t["sensitivity_only"], ha="right", fontsize=9.2, color="0.4")
    fig.suptitle(t["f2"], fontsize=15, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.82, bottom=.18, left=.14, right=.98, wspace=.30)
    return fig


def attack_dynamics(cfg, tables: Path, lang: str):
    t = TX[lang]; style(cfg, lang)
    c = read(tables, "f4_event_study.csv")
    c = c[c.event_id.isin(EVENTS) & c.rel_h.between(-24, 72)].copy()
    c["deficit"] = -c.effect; c["lo"] = -c.ci_hi; c["hi"] = -c.ci_lo
    main = read(tables, "exp_b_main_results.csv").set_index("event_id")
    fig, axes = plt.subplots(2, 3, figsize=PAGE, sharex=True, sharey=True)
    for ax, event_id in zip(axes.flat, EVENTS):
        d = c[c.event_id.eq(event_id)].sort_values("rel_h"); row = main.loc[event_id]
        good = int(row.inference_admissible) == 1; color = PALETTE[0] if good else "0.55"
        x=d.rel_h.to_numpy(float); y=d.deficit.to_numpy(float)
        ax.fill_between(x, d.lo.to_numpy(float), d.hi.to_numpy(float), color=color, alpha=.15, linewidth=0)
        ax.plot(x, y, color=color, lw=1.8); ax.axvline(0, color=PALETTE[1], ls="--", lw=1.15); ax.axhline(0, color="0.4", ls=":")
        status = t["admissible"] if good else t["descriptive"]
        panel(ax, f"{SHORT[event_id]} | {status}")
        ax.text(.98, .94, f"{t['peak']} {row.max_deficit:.3f}  |  {t['recovery']} {row.t90_h:.0f}h",
                transform=ax.transAxes, ha="right", va="top", fontsize=8.8, color="0.35")
        ax.set_xticks([-24,0,24,48,72]); ax.grid(True, alpha=.28)
    fig.supylabel(t["deficit"], x=.035); fig.supxlabel(t["hours"], y=.065)
    fig.suptitle(t["f3"], fontsize=15, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.85, bottom=.15, left=.09, right=.98, hspace=.34, wspace=.22)
    return fig


def fingerprint(cfg, tables: Path, lang: str):
    t=TX[lang]; style(cfg, lang)
    repeat=read(tables,"exp_c_repeatability.csv"); repeat=repeat[repeat.target.eq("deficit_auc_full")]
    ev=[e for e in EVENTS if e != "E2024_0917_SUMY"]; mat=np.full((len(ev),len(ev)),np.nan); np.fill_diagonal(mat,1)
    for _,r in repeat.iterrows():
        if r.event_a in ev and r.event_b in ev and r.admissible==1:
            i,j=ev.index(r.event_a),ev.index(r.event_b); mat[i,j]=mat[j,i]=r.spearman_rho
    perf=read(tables,"f8_model_perf.csv"); perf=perf[(perf.target.eq("deficit_auc_full")) & perf.event_id.eq("EVENT_EQUAL")]
    order=["M0_global","M1_admin1","M2_asn","M3_group","M4_ridge_history","M5_gbdt_history"]
    perf=perf.set_index("model").reindex(order).reset_index()
    fig,axes=plt.subplots(1,2,figsize=PAGE,gridspec_kw={"width_ratios":[1.05,1]})
    ax=axes[0]; cmap=plt.get_cmap("RdBu_r").copy(); cmap.set_bad("#E8E8E8")
    im=ax.imshow(np.ma.masked_invalid(mat),vmin=-1,vmax=1,cmap=cmap); labs=[SHORT[e] for e in ev]
    ax.set_xticks(range(len(ev)),labs,rotation=35,ha="right"); ax.set_yticks(range(len(ev)),labs)
    for i in range(len(ev)):
        for j in range(len(ev)):
            ax.text(j,i,"-" if not np.isfinite(mat[i,j]) else f"{mat[i,j]:.2f}",ha="center",va="center",
                    color="white" if np.isfinite(mat[i,j]) and abs(mat[i,j])>.55 else "0.2")
    cb=fig.colorbar(im,ax=ax,fraction=.046,pad=.04); cb.set_label(t["rho"]); panel(ax,t["f4a"])
    ax=axes[1]; y=np.arange(len(perf)); colors=[PALETTE[1] if m=="M4_ridge_history" else "0.65" for m in perf.model]
    ax.hlines(y,0,perf.mae,color="0.82"); ax.scatter(perf.mae,y,color=colors,s=48); ax.set_yticks(y,[m.replace("_"," ") for m in perf.model]); ax.invert_yaxis()
    ax.set_xlim(left=0); ax.set_xlabel(t["mae"]); ax.grid(axis="x",alpha=.3)
    ax.text(.98,.96,t["prediction_note"],transform=ax.transAxes,ha="right",va="top",fontsize=10,
            bbox={"boxstyle":"round,pad=.3","fc":"#F8E7E7","ec":"#B85C5C"}); panel(ax,t["f4b"])
    fig.suptitle(t["f4"],fontsize=15,fontweight="bold",y=.985)
    fig.subplots_adjust(top=.83,bottom=.16,left=.10,right=.98,wspace=.42)
    return fig


def save(cfg, tables: Path, lang: str, out: Path) -> None:
    target=out/lang; target.mkdir(parents=True,exist_ok=True)
    for p in target.glob("CoreFig*.*"): p.unlink()
    funcs=[calibration,attack_generalization,attack_dynamics,fingerprint]
    with PdfPages(target/f"submission_core_figures_{lang}.pdf") as pdf:
        for i,fn in enumerate(funcs,1):
            fig=fn(cfg,tables,lang); pdf.savefig(fig,bbox_inches=None)
            fig.savefig(target/f"CoreFig{i}.pdf",bbox_inches=None)
            fig.savefig(target/f"CoreFig{i}.png",dpi=300,bbox_inches=None)
            fig.savefig(target/f"CoreFig{i}.svg",bbox_inches=None)
            plt.close(fig)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--run-id",required=True); args=ap.parse_args()
    cfg=load_config(run_id=args.run_id,mode="real"); tables=cfg.out_dir("results_tables")
    out=cfg.run_base/"results"/"figures_submission_core"
    for lang in ["en","zh"]: save(cfg,tables,lang,out)
    print(out); return 0


if __name__ == "__main__": raise SystemExit(main())
