#!/usr/bin/env python3
"""Render a compact bilingual closure figure set from an existing v2.4 run."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uresil.config import load_config
from uresil.viz.style import PALETTE, apply_style


ZH = {
    "c1_title": "计划停电校准：事件异质性与总体门槛",
    "event_delta": "事件级 ΔAUPRC（B2 - B1）",
    "pooled": "总体预注册估计",
    "gate_fail": "校准门槛：未通过",
    "c2_title": "留出能源攻击的可推断性与影响规模",
    "drop": "事件锚点后即时缺口",
    "max": "最大可达缺口",
    "admissible": "可推断",
    "descriptive": "仅描述（预趋势未通过）",
    "c3_title": "滚动留出预测：表观改善未通过置换门槛",
    "observed": "观测缺口 AUC（小时）",
    "predicted": "预测缺口 AUC（小时）",
    "mae": "事件等权 MAE",
    "c4_title": "恢复债务与条件性路径稳健性",
    "coefficient": "回归系数（95%置信区间）",
    "fdr": "通过 BH-FDR 的 ASGeo 单元数",
    "trace": "每阶段最少有效 Trace 数",
    "residual": "基线残差化债务",
    "future": "未来债务安慰剂",
    "c5_title": "独立 IODA 信号的事件窗口一致性",
    "ioda_deficit": "IODA gtr-norm 相对缺口",
    "ioda_onset": "IODA 异常起点（相对事件小时）",
    "c6_title": "官方高温预警敏感性（不替代 ERA5 调整）",
    "warning_delta": "ΔAUPRC（B2 - B1）",
    "all_data": "全部冻结验证数据",
    "exclude_warning": "排除官方高温预警期",
    "exclude_severe": "排除官方严重高温期",
    "partial_note": "仅检验预警窗口；连续温度混杂仍待 ERA5",
}
EN = {
    "c1_title": "Scheduled-outage calibration: event heterogeneity and pooled gate",
    "event_delta": "Event-level ΔAUPRC (B2 - B1)",
    "pooled": "Pooled preregistered estimate",
    "gate_fail": "Calibration gate: not passed",
    "c2_title": "Inference eligibility and impact magnitude in held-out energy attacks",
    "drop": "Immediate deficit after outcome anchor",
    "max": "Maximum reachability deficit",
    "admissible": "Inference-admissible",
    "descriptive": "Descriptive only (pretrend failed)",
    "c3_title": "Rolling held-out prediction: apparent gain fails the permutation gate",
    "observed": "Observed deficit AUC (h)",
    "predicted": "Predicted deficit AUC (h)",
    "mae": "Event-equal MAE",
    "c4_title": "Recovery-debt and conditional path robustness",
    "coefficient": "Regression coefficient (95% CI)",
    "fdr": "ASGeo units passing BH-FDR",
    "trace": "Minimum valid traces per phase",
    "residual": "Baseline-residualized debt",
    "future": "Future-debt placebo",
    "c5_title": "Event-window concordance in independent IODA signals",
    "ioda_deficit": "Relative IODA gtr-norm deficit",
    "ioda_onset": "IODA anomaly onset (hours from event)",
    "c6_title": "Official heat-warning sensitivity (not an ERA5 substitute)",
    "warning_delta": "ΔAUPRC (B2 - B1)",
    "all_data": "All frozen validation rows",
    "exclude_warning": "Exclude official heat-warning periods",
    "exclude_severe": "Exclude severe heat-warning periods",
    "partial_note": "Warning-window test only; continuous-temperature confounding awaits ERA5",
}


def read(tables: Path, name: str) -> pd.DataFrame:
    path = tables / name
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def c1(cfg, tables, lang):
    tx = ZH if lang == "zh" else EN
    e = read(tables, "exp_a_event_metrics.csv")
    e = e[e.publication_eligible.eq(1)].sort_values("delta_b2_vs_b1")
    s = read(tables, "exp_a_summary.csv").iloc[0]
    apply_style(cfg, lang)
    fig, ax = plt.subplots(1, 2, figsize=(7.16, 3.15), gridspec_kw={"width_ratios": [1.3, 1]})
    cmap = {c: PALETTE[i] for i, c in enumerate(sorted(e.independence_cluster.unique()))}
    ax[0].barh(np.arange(len(e)), e.delta_b2_vs_b1, color=[cmap[x] for x in e.independence_cluster])
    ax[0].set_yticks(np.arange(len(e)), e.event_id.str.replace("E2024_", "", regex=False).str.replace("_PLANNED", "", regex=False))
    ax[0].axvline(0, color="0.25", lw=.8); ax[0].set_xlabel(tx["event_delta"]); ax[0].grid(axis="x")
    point, lo, hi = map(float, [s.delta_b2_vs_b1, s.delta_ci_lo, s.delta_ci_hi])
    ax[1].errorbar(point, 0, xerr=[[point-lo], [hi-point]], fmt="o", capsize=4, color=PALETTE[2])
    ax[1].axvline(0, color="0.25", lw=.8); ax[1].set_yticks([0], [tx["pooled"]]); ax[1].grid(axis="x")
    ax[1].text(.03, .08, f"{tx['gate_fail']}\npermutation p = {float(s.permutation_p):.3f}", transform=ax[1].transAxes)
    fig.suptitle(tx["c1_title"], fontsize=10, fontweight="bold"); fig.tight_layout()
    return fig


def c2(cfg, tables, lang):
    tx = ZH if lang == "zh" else EN
    d = read(tables, "exp_b_main_results.csv")
    d = d[d.analysis_role.isin(["attack_national", "attack_regional", "blind_test"])].copy()
    d = d.sort_values("max_deficit")
    apply_style(cfg, lang); fig, ax = plt.subplots(figsize=(7.16, 3.35))
    y = np.arange(len(d)); ok = d.inference_admissible.eq(1)
    for col, marker, label, color in [("immediate_drop", "o", tx["drop"], PALETTE[0]),
                                       ("max_deficit", "s", tx["max"], PALETTE[1])]:
        ax.scatter(d[col], y, marker=marker, color=color, label=label, s=38)
    for i, good in enumerate(ok):
        if not good: ax.axhspan(i-.38, i+.38, color="0.85", alpha=.55)
    labels = [f"{eid}  |  {tx['admissible'] if good else tx['descriptive']}" for eid, good in zip(d.event_id, ok)]
    ax.set_yticks(y, labels); ax.axvline(0, color="0.25", lw=.8); ax.set_xlabel(tx["max"])
    ax.legend(ncol=2, loc="upper center", bbox_to_anchor=(.5, -.14)); ax.grid(axis="x"); ax.set_title(tx["c2_title"], fontweight="bold")
    fig.tight_layout(); return fig


def c3(cfg, tables, lang):
    tx = ZH if lang == "zh" else EN
    p = read(tables, "f8_pred_scatter.csv")
    p = p[(p.target.eq("deficit_auc_full")) & (p.model.eq("M4_ridge_history"))]
    perf = read(tables, "f8_model_perf.csv")
    perf = perf[(perf.target.eq("deficit_auc_full")) & perf.event_id.eq("EVENT_EQUAL")].sort_values("mae")
    s = read(tables, "exp_c_summary.csv").iloc[0]
    apply_style(cfg, lang); fig, ax = plt.subplots(1, 2, figsize=(7.16, 3.15))
    for i, (event, g) in enumerate(p.groupby("event_id")):
        ax[0].scatter(g.actual, g.pred, s=13, alpha=.6, label=event, color=PALETTE[i])
    lo = min(p.actual.min(), p.pred.min()); hi = max(p.actual.max(), p.pred.max())
    ax[0].plot([lo, hi], [lo, hi], "--", color="0.3"); ax[0].set_xlabel(tx["observed"]); ax[0].set_ylabel(tx["predicted"])
    ax[0].legend(fontsize=6); ax[0].grid(True)
    ax[1].barh(perf.model, perf.mae, color=PALETTE[:len(perf)]); ax[1].set_xlabel(tx["mae"]); ax[1].grid(axis="x")
    ax[1].text(.98, .05, f"M4 vs M3: {float(s.relative_mae_improvement):+.1%}\npermutation p = {float(s.permutation_p):.3f}", ha="right", transform=ax[1].transAxes)
    fig.suptitle(tx["c3_title"], fontsize=10, fontweight="bold"); fig.tight_layout(); return fig


def c4(cfg, tables, lang):
    tx = ZH if lang == "zh" else EN
    r = read(tables, "sens_recovery_debt_placebo.csv")
    r = r[(r.target.eq("deficit_auc_full")) & r.identified.eq(1)]
    p = read(tables, "sens_path_final_review.csv")
    p = p[p.analysis.eq("same_target_BH_FDR")]
    apply_style(cfg, lang); fig, ax = plt.subplots(1, 2, figsize=(7.16, 3.15))
    labels = [tx["residual"] if x == "baseline_residualized" else tx["future"] for x in r.analysis]
    y = np.arange(len(r)); ax[0].errorbar(r.beta, y, xerr=[r.beta-r.ci_lo, r.ci_hi-r.beta], fmt="o", capsize=3, color=PALETTE[2])
    ax[0].axvline(0, color="0.25", lw=.8); ax[0].set_yticks(y, labels); ax[0].set_xlabel(tx["coefficient"]); ax[0].grid(axis="x")
    ax[1].plot(p.min_trace_per_phase, p.fdr_significant_n, marker="o", color=PALETTE[0]); ax[1].set_xlabel(tx["trace"]); ax[1].set_ylabel(tx["fdr"]); ax[1].set_ylim(bottom=0); ax[1].grid(True)
    fig.suptitle(tx["c4_title"], fontsize=10, fontweight="bold"); fig.tight_layout(); return fig


def c5(cfg, tables, lang):
    tx = ZH if lang == "zh" else EN
    d = read(tables, "sens_ioda_external_validation.csv")
    d = d[d.status.eq("ok")].sort_values("relative_deficit")
    if d.empty: raise ValueError("No parsed IODA validation rows")
    apply_style(cfg, lang); fig, ax = plt.subplots(1, 2, figsize=(7.16, 3.15))
    y = np.arange(len(d)); colors = [PALETTE[2] if x else "0.65" for x in d.temporal_concordant_6h]
    ax[0].barh(y, d.relative_deficit, color=colors); ax[0].set_yticks(y, d.event_id); ax[0].set_xlabel(tx["ioda_deficit"]); ax[0].grid(axis="x")
    ax[1].scatter(d.ioda_onset_rel_h, y, color=colors); ax[1].axvspan(0, 6, color=PALETTE[2], alpha=.12)
    ax[1].axvline(0, color="0.25", lw=.8); ax[1].set_yticks(y, []); ax[1].set_xlabel(tx["ioda_onset"]); ax[1].grid(axis="x")
    fig.suptitle(tx["c5_title"], fontsize=10, fontweight="bold"); fig.tight_layout(); return fig


def c6(cfg, tables, lang):
    tx = ZH if lang == "zh" else EN
    d = read(tables, "sens_official_heat_warning.csv")
    wanted = ["all_unadjusted", "exclude_official_heat_warning",
              "exclude_official_severe_heat_warning"]
    labels = [tx["all_data"], tx["exclude_warning"], tx["exclude_severe"]]
    d = d.set_index("analysis").reindex(wanted).reset_index()
    apply_style(cfg, lang); fig, ax = plt.subplots(figsize=(7.16, 3.15))
    y = np.arange(len(d))
    colors = [PALETTE[0], PALETTE[2], PALETTE[3]]
    ax.barh(y, d.delta_b2_vs_b1, color=colors)
    ax.set_yticks(y, labels); ax.invert_yaxis(); ax.axvline(0, color="0.25", lw=.8)
    ax.set_xlabel(tx["warning_delta"]); ax.grid(axis="x")
    for yi, value in zip(y, d.delta_b2_vs_b1):
        if np.isfinite(value):
            ax.text(value, yi, f" {value:+.3f}", va="center", ha="left" if value >= 0 else "right")
    ax.text(.01, -.22, tx["partial_note"], transform=ax.transAxes, fontsize=7, color="0.35")
    ax.set_title(tx["c6_title"], fontweight="bold"); fig.tight_layout(); return fig


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--run-id", required=True); args = ap.parse_args()
    cfg = load_config(run_id=args.run_id, mode="real"); tables = cfg.out_dir("results_tables")
    out = cfg.run_base / "results" / "figures_closure"; out.mkdir(parents=True, exist_ok=True)
    funcs = [c1, c2, c3, c4, c5, c6]
    for lang in ["en", "zh"]:
        lang_out = out / lang; lang_out.mkdir(parents=True, exist_ok=True)
        with PdfPages(lang_out / f"closure_figures_{lang}.pdf") as pdf:
            for i, fn in enumerate(funcs, 1):
                fig = fn(cfg, tables, lang); pdf.savefig(fig, bbox_inches="tight")
                fig.savefig(lang_out / f"C{i}.png", dpi=300, bbox_inches="tight")
                fig.savefig(lang_out / f"C{i}.svg", bbox_inches="tight")
                plt.close(fig)
    print(out); return 0


if __name__ == "__main__":
    raise SystemExit(main())
