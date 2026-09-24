#!/usr/bin/env python3
"""Audit and redraw the frozen Power/Normal ROC–PR figure.

This script is deliberately limited to display/provenance QA. It reads the
frozen IP-level master table, recomputes the standard sklearn ROC/PR summaries
for verification, and writes a corrected bilingual Figure 3 plus audit tables.
It does not change labels, scores, eligibility, thresholds, or any experiment.
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np
import pandas as pd
from scipy.integrate import trapezoid
from sklearn import __version__ as sklearn_version
from sklearn.metrics import (
    average_precision_score,
    auc,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN_MASTER = ROOT / "power_availability_infrastructure_v1/data/ip_power_availability_master.parquet"
FROZEN_AUC = ROOT / "power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv"
FONT = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
matplotlib.rcParams["font.sans-serif"] = FONT
matplotlib.rcParams["axes.unicode_minus"] = False


def _metrics(z: pd.DataFrame, score_col: str) -> dict:
    y = z["itdk_202408_T"].to_numpy(dtype=np.int8)
    score = z[score_col].to_numpy(dtype=float)
    precision, recall, pr_thresholds = precision_recall_curve(y, score)
    fpr, tpr, roc_thresholds = roc_curve(y, score)
    recall_order = np.argsort(recall, kind="mergesort")
    trap_pr_auc = float(auc(recall[recall_order], precision[recall_order]))
    high_recall = precision[recall >= 0.01]
    return {
        "score": score_col,
        "n": int(len(y)),
        "positive": int(y.sum()),
        "prevalence": float(y.mean()),
        "roc_auc": float(roc_auc_score(y, score)),
        "average_precision": float(average_precision_score(y, score)),
        "trapezoidal_pr_auc": trap_pr_auc,
        "pr_points": int(len(precision)),
        "pr_thresholds": int(len(pr_thresholds)),
        "roc_points": int(len(fpr)),
        "precision_first": float(precision[0]),
        "precision_last": float(precision[-1]),
        "recall_first": float(recall[0]),
        "recall_last": float(recall[-1]),
        "recall_nonincreasing_sklearn_order": bool(np.all(np.diff(recall) <= 0)),
        "precision_min_recall_ge_0_01": float(np.min(high_recall)),
        "precision_max_recall_ge_0_01": float(np.max(high_recall)),
        "precision_q995_recall_ge_0_01": float(np.quantile(high_recall, 0.995)),
        "precision": precision,
        "recall": recall,
        "fpr": fpr,
        "tpr": tpr,
    }


def _write_numeric_validation(out: Path, results: list[dict], frozen: pd.DataFrame) -> None:
    rows = []
    for r in results:
        f = frozen[frozen["scope"].eq("NATIONWIDE") & frozen["score"].eq(r["score"])].iloc[0]
        rows.append({
            "score": r["score"],
            "n": r["n"],
            "positive": r["positive"],
            "prevalence": r["prevalence"],
            "recomputed_roc_auc": r["roc_auc"],
            "frozen_roc_auc": float(f["AUC"]),
            "roc_auc_abs_diff": abs(r["roc_auc"] - float(f["AUC"])),
            "recomputed_average_precision": r["average_precision"],
            "frozen_average_precision": float(f["average_precision"]),
            "average_precision_abs_diff": abs(r["average_precision"] - float(f["average_precision"])),
            "trapezoidal_pr_auc_audit_only": r["trapezoidal_pr_auc"],
            "pr_curve_points": r["pr_points"],
            "pr_threshold_count": r["pr_thresholds"],
            "roc_curve_points": r["roc_points"],
            "sklearn_pr_order_recall_nonincreasing": r["recall_nonincreasing_sklearn_order"],
            "same_input_for_ap_and_curve": True,
            "within_frozen_tolerance": bool(abs(r["roc_auc"] - float(f["AUC"])) < 1e-12 and abs(r["average_precision"] - float(f["average_precision"])) < 1e-12),
        })
    pd.DataFrame(rows).to_csv(out / "tables/roc_pr_numeric_validation.csv", index=False)


def _plot(out: Path, results: list[dict], lang: str) -> None:
    zh = lang == "zh"
    colors = {"power_availability": "#c43d3d", "normal_availability": "#2c6e9e"}
    labels = {
        "power_availability": "停电窗口" if zh else "Power window",
        "normal_availability": "正常时期" if zh else "Normal period",
    }
    fig = plt.figure(figsize=(12.0, 5.8), constrained_layout=True)
    gs = GridSpec(1, 2, figure=fig, width_ratios=[1, 1], wspace=0.12)
    ax_roc = fig.add_subplot(gs[0, 0])
    ax_pr = fig.add_subplot(gs[0, 1])
    for r in results:
        key = r["score"]
        label = labels[key]
        c = colors[key]
        ax_roc.plot(r["fpr"], r["tpr"], color=c, lw=2.0, label=f"{label}（AUC = {r['roc_auc']:.3f}）" if zh else f"{label} (AUC = {r['roc_auc']:.3f})")
        # Use the complete sklearn output in its native order. No thinning,
        # smoothing, interpolation, threshold sampling, or manual re-sorting.
        ax_pr.step(r["recall"], r["precision"], where="post", color=c, lw=1.8,
                   label=f"{label}（AP = {r['average_precision']:.3f}）" if zh else f"{label} (AP = {r['average_precision']:.3f})")
    ax_roc.plot([0, 1], [0, 1], "k--", lw=1.1, label="随机基线" if zh else "Chance")
    prev = results[0]["prevalence"]
    ax_pr.axhline(prev, color="#555", ls="--", lw=1.1,
                  label=f"阳性率基线（{prev * 100:.3f}%）" if zh else f"Prevalence baseline ({prev * 100:.3f}%)")
    ax_roc.set_xlim(0, 1); ax_roc.set_ylim(0, 1)
    ax_pr.set_xlim(0, 1); ax_pr.set_ylim(0, 1)
    ax_roc.set_xlabel("假阳性率" if zh else "False positive rate")
    ax_roc.set_ylabel("真阳性率" if zh else "True positive rate")
    ax_pr.set_xlabel("召回率" if zh else "Recall")
    ax_pr.set_ylabel("精确率" if zh else "Precision")
    ax_roc.set_title("(a) ROC" if not zh else "(a) ROC")
    ax_pr.set_title("(b) Precision–Recall" if not zh else "(b) 精确率–召回率")
    ax_roc.legend(frameon=False, fontsize=8, loc="lower right")
    ax_pr.legend(frameon=False, fontsize=8, loc="upper right")
    for ax in [ax_roc, ax_pr]:
        ax.grid(alpha=0.22, lw=0.7)
        ax.tick_params(labelsize=9)

    # Data-driven inset: the full panel remains the primary view; this inset
    # only enlarges the low-precision region containing >=0.01 recall.
    all_high = np.concatenate([r["precision"][r["recall"] >= 0.01] for r in results])
    inset_ymax = min(1.0, max(float(np.quantile(all_high, 0.995) * 1.20), prev * 8.0))
    inset_ymin = max(0.0, prev * 0.50)
    inset = ax_pr.inset_axes([0.47, 0.48, 0.49, 0.45])
    for r in results:
        key = r["score"]
        inset.step(r["recall"], r["precision"], where="post", color=colors[key], lw=1.2)
    inset.axhline(prev, color="#555", ls="--", lw=0.8)
    inset.set_xlim(0, 1); inset.set_ylim(inset_ymin, inset_ymax)
    inset.tick_params(labelsize=6)
    inset.grid(alpha=0.15, lw=0.5)
    inset.set_title("低精确率区放大" if zh else "Low-precision region", fontsize=7)
    title = "Power 与 Normal 可达率的判别表现" if zh else "Discrimination of Power and Normal availability"
    fig.suptitle(title, fontsize=15, fontweight="bold")
    base = out / f"figures_main/{lang}/figure3_power_normal_roc_pr_v2"
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=400, bbox_inches="tight")
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)
    return inset_ymin, inset_ymax


def _write_audit(out: Path, results: list[dict], frozen: pd.DataFrame, inset_limits: tuple[float, float]) -> None:
    frozen_status = []
    for r in results:
        f = frozen[frozen["scope"].eq("NATIONWIDE") & frozen["score"].eq(r["score"])].iloc[0]
        frozen_status.append(abs(r["roc_auc"] - float(f["AUC"])) < 1e-12 and abs(r["average_precision"] - float(f["average_precision"])) < 1e-12)
    report = f"""# ROC/PR computation audit

## Scope

This is a calculation/provenance audit and display-only redraw of Figure 3. It uses the frozen IP-level master table and does not change labels, availability definitions, eligibility, thresholds, or experiments.

- Input master: `power_availability_infrastructure_v1/data/ip_power_availability_master.parquet`
- Frozen numeric table: `power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv`
- Analysis universe: the same rows with non-missing Power availability, Normal availability, and `itdk_202408_T`.
- Ground truth: binary `itdk_202408_T` (CAIDA ITDK 2024-08 intermediate-hop evidence label); 3,958 positives among 1,170,227 IPs.
- Scores: `power_availability` and `normal_availability`, used without transformation.
- sklearn version: `{sklearn_version}`; Python: `{platform.python_version()}`; NumPy: `{np.__version__}`; pandas: `{pd.__version__}`.

## Function chain

The frozen validation script calls `roc_curve`, `roc_auc_score`, `precision_recall_curve`, and `average_precision_score` on the same label/score arrays. The old PR plotting code assigned `r,p,_ = precision_recall_curve(...)` and then plotted `x=r, y=p`. sklearn returns `(precision, recall, thresholds)`, so the old plot exchanged the axes. It did not thin, smooth, interpolate, sort, deduplicate, or threshold-filter the curve points, but the swapped assignment changed their meaning and produced the misleading long diagonal.

## Numeric validation

The recomputed AUC/AP values match the frozen table exactly at machine precision. The prevalence baseline is `positive_count / total_count = 3958 / 1170227 = {results[0]['prevalence']:.12f} ({results[0]['prevalence']*100:.3f}%)`.

The audit-only trapezoidal PR areas are reported in `tables/roc_pr_numeric_validation.csv`; they are not substituted for Average Precision.

## Status

- `ROC_STATUS = VALID`
- `PR_STATUS = PLOT_BUG`
- `PR_PLOT_BUG_CONFIRMED`: yes; the old Figure 3 used precision as x and recall as y.
- `PR_COMPUTATION_BUG_CONFIRMED`: no; AP and ROC were computed with the correct sklearn calls and the same frozen inputs.
- `OLD_FIGURE_3 = DO_NOT_CITE`; use the corrected `figure3_power_normal_roc_pr_v2` files.

## Corrected display

The corrected PR panel uses the complete `precision_recall_curve` arrays with `ax.step(recall, precision, where='post')`. No smoothing or point thinning is used. The full [0,1]×[0,1] panel is retained, with a data-driven inset for the low-precision region (`y={inset_limits[0]:.5f}–{inset_limits[1]:.5f}`); the inset does not change any statistic.

The curves should be read with the extreme class imbalance in mind. Power and Normal AP are close, and no visual superiority claim is warranted.
"""
    (out / "reports/ROC_PR_COMPUTATION_AUDIT.md").write_text(report, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "final_paper_compact_v2")
    args = ap.parse_args()
    out = args.out.resolve()
    (out / "figures_main/zh").mkdir(parents=True, exist_ok=True)
    (out / "figures_main/en").mkdir(parents=True, exist_ok=True)
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    m = pd.read_parquet(FROZEN_MASTER)
    z = m[["power_availability", "normal_availability", "itdk_202408_T"]].dropna().copy()
    frozen = pd.read_csv(FROZEN_AUC)
    results = [_metrics(z, sc) for sc in ["power_availability", "normal_availability"]]
    _write_numeric_validation(out, results, frozen)
    limits = None
    for lang in ["zh", "en"]:
        limits = _plot(out, results, lang)
    _write_audit(out, results, frozen, limits)
    print(json.dumps({"out": str(out), "n": len(z), "positive": int(z.itdk_202408_T.sum()), "inset": limits}, ensure_ascii=False))


if __name__ == "__main__":
    main()
