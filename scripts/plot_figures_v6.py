"""Server-side strict redraw of Figures 2--5 from the frozen v5 result.

Figure 1 is intentionally not generated.  This script only changes the
rendering parameters explicitly specified for v6; frozen data and statistics
are read from v5/source artifacts and checked before rendering.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve


STYLE_FIG2 = {
    "ms": 1.8,
    "markeredgewidth": 0.35,
    "elinewidth": 0.45,
    "capsize": 0,
    "alpha": 0.90,
}
STYLE_FIG4 = {
    "ms": 3.0,
    "markeredgewidth": 0.45,
    "elinewidth": 0.65,
    "capthick": 0.65,
    "capsize": 1.2,
}
STYLE_FIG5_DENSE = {
    "ms": 1.55,
    "markeredgewidth": 0.30,
    "elinewidth": 0.40,
    "capsize": 0,
    "alpha": 0.82,
}
STYLE_FIG5_SPARSE = {
    "ms": 3.2,
    "markeredgewidth": 0.45,
    "elinewidth": 0.65,
    "capsize": 1.0,
}

FONT = ["WenQuanYi Zen Hei", "Noto Sans CJK SC", "DejaVu Sans"]
COLORS = {"power": "#C63D2F", "normal": "#2F6F9F", "ink": "#20252B", "grid": "#D9DEE3"}
plt.rcParams.update({
    "font.sans-serif": FONT,
    "axes.unicode_minus": False,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "axes.edgecolor": COLORS["ink"],
    "axes.labelcolor": COLORS["ink"],
    "xtick.color": COLORS["ink"],
    "ytick.color": COLORS["ink"],
    "text.color": COLORS["ink"],
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 7.5,
    "axes.linewidth": 0.75,
})


def save_triplet(fig: plt.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=600, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.04)
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def prepare_output(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for rel in ["figures_main/zh", "figures_main/en", "tables", "scripts", "reports"]:
        (out / rel).mkdir(parents=True, exist_ok=True)
    (out / "FIGURE1_PLACEHOLDER.md").write_text("Figure 1 supplied separately.\n", encoding="utf-8")


def validate_fixed_styles() -> None:
    if STYLE_FIG2["ms"] > 1.9 or STYLE_FIG2["capsize"] != 0 or STYLE_FIG2["elinewidth"] > 0.5:
        raise RuntimeError("Figure 2 fixed-style rule violated")
    if STYLE_FIG4["ms"] > 3.2:
        raise RuntimeError("Figure 4 fixed marker-size rule violated")
    if STYLE_FIG5_DENSE["ms"] > 1.6 or STYLE_FIG5_DENSE["capsize"] > 0 or STYLE_FIG5_DENSE["elinewidth"] > 0.45:
        raise RuntimeError("Figure 5 dense fixed-style rule violated")
    if STYLE_FIG4["capsize"] > 1.2 or STYLE_FIG5_SPARSE["capsize"] <= 0:
        raise RuntimeError("Figure 4/5 sparse fixed-style rule violated")


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, ctr - half), min(1.0, ctr + half)


def fd_edges(values: np.ndarray) -> np.ndarray:
    return np.unique(np.r_[0.0, np.histogram_bin_edges(values, bins="fd"), 1.0])


def summary_with_edges(master: pd.DataFrame, score: str, outcome: str, edges: np.ndarray) -> pd.DataFrame:
    q = master[[score, outcome]].dropna().copy()
    q[score] = pd.to_numeric(q[score], errors="coerce")
    q[outcome] = pd.to_numeric(q[outcome], errors="coerce")
    q = q.dropna()
    rows = []
    for a, b in zip(edges[:-1], edges[1:]):
        z = q[(q[score] >= a) & ((q[score] <= b) if b == edges[-1] else (q[score] < b))]
        if len(z) == 0:
            continue
        n = len(z)
        k = int(z[outcome].sum())
        lo, hi = wilson(k, n)
        rows.append({"score": score, "bin_left": float(a), "bin_right": float(b),
                     "x_mean": float(z[score].mean()), "n": n, "positive": k,
                     "proportion": k / n, "CI_low": lo, "CI_high": hi})
    return pd.DataFrame(rows)


def load_frozen(v5: Path, source: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    master = pd.read_parquet(source / "power_availability_infrastructure_final_validation_v2/data/ip_power_availability_master_v2.parquet")
    auc = pd.read_csv(v5 / "tables/TABLE_F07_final_auc.csv")
    rel = pd.read_csv(v5 / "tables/TABLE_F10_itdk_release_final.csv")
    q = pd.read_csv(v5 / "tables/h4_activity_quintile_summary.csv")
    c = pd.read_csv(v5 / "tables/h4_activity_concentration_summary.csv")
    if len(master) != 1_170_227 or int(master["itdk_202408_T"].dropna().sum()) != 3958:
        raise RuntimeError("Frozen master N/positive count changed")
    return master, auc, rel, q, c


def load_frozen_fig2_tables(v5: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    root = v5 / "tables/v4_snapshot"
    common = pd.read_csv(root / "figure2_common_bins.csv")
    power = pd.read_csv(root / "figure2_power_binned_data.csv")
    normal = pd.read_csv(root / "figure2_normal_binned_data.csv")
    for d in [power, normal]:
        if not np.allclose(d["bin_left"].to_numpy(), common["bin_left"].to_numpy()) or not np.allclose(d["bin_right"].to_numpy(), common["bin_right"].to_numpy()):
            raise RuntimeError("Figure 2 binned data do not match frozen common bin edges")
    return common, power, normal


def figure2(out: Path, lang: str, common: pd.DataFrame, power: pd.DataFrame, normal: pd.DataFrame) -> None:
    zh = lang == "zh"
    fig, axs = plt.subplots(1, 2, figsize=(7.15, 3.35), sharex=True, sharey=True)
    ymax = max(power["CI_high"].max(), normal["CI_high"].max()) * 100 * 1.12
    labels = ["(a) 停电窗口", "(b) 正常时期"] if zh else ["(a) Power window", "(b) Normal period"]
    for ax, d, label, color in zip(axs, [power, normal], labels, [COLORS["power"], COLORS["normal"]]):
        y = d["proportion"].to_numpy() * 100
        lo = np.maximum(0.0, (d["proportion"] - d["CI_low"]).to_numpy() * 100)
        hi = np.maximum(0.0, (d["CI_high"] - d["proportion"]).to_numpy() * 100)
        ax.errorbar(d["x_mean"], y, yerr=[lo, hi], fmt="o",
                    markersize=STYLE_FIG2["ms"], markeredgewidth=STYLE_FIG2["markeredgewidth"],
                    capsize=STYLE_FIG2["capsize"], elinewidth=STYLE_FIG2["elinewidth"],
                    alpha=STYLE_FIG2["alpha"], color=color, ecolor=color,
                    linestyle="none", zorder=2, markerfacecolor=color, markeredgecolor=color)
        ax.text(.02, .98, label, transform=ax.transAxes, ha="left", va="top", fontsize=10)
        ax.set_xlim(-0.01, 1.01)
        ax.set_ylim(0, ymax)
        ax.grid(axis="y", color=COLORS["grid"], linewidth=0.4, alpha=0.25)
    axs[0].set_ylabel("ITDK 中间跳证据比例（%）" if zh else "ITDK intermediate-hop evidence (%)")
    fig.supxlabel("可达率" if zh else "Availability")
    fig.subplots_adjust(left=.10, right=.985, bottom=.17, top=.98, wspace=.08)
    save_triplet(fig, out / "figures_main" / lang / f"figure2_power_normal_itdk_v6_{lang}")


def figure3(out: Path, lang: str, master: pd.DataFrame, auc: pd.DataFrame) -> None:
    zh = lang == "zh"
    z = master[["power_availability", "normal_availability", "itdk_202408_T"]].dropna()
    y = z["itdk_202408_T"].astype(int).to_numpy()
    fig, axs = plt.subplots(1, 2, figsize=(7.25, 3.55))
    series = {
        "power_availability": (COLORS["power"], "停电窗口" if zh else "Power window"),
        "normal_availability": (COLORS["normal"], "正常时期" if zh else "Normal period"),
    }
    for score, (color, label) in series.items():
        s = z[score].to_numpy()
        fpr, tpr, _ = roc_curve(y, s)
        precision, recall, _ = precision_recall_curve(y, s)
        formal = auc.query("scope == 'NATIONWIDE' and score == @score").iloc[0]
        if abs(roc_auc_score(y, s) - float(formal.AUC)) > 1e-12 or abs(average_precision_score(y, s) - float(formal.average_precision)) > 1e-12:
            raise RuntimeError(f"Figure 3 frozen AUC/AP mismatch: {score}")
        axs[0].plot(fpr, tpr, color=color, linewidth=1.1, label=f"{label}  AUC={float(formal.AUC):.3f}")
        axs[1].step(recall, precision, where="post", color=color, linewidth=1.1,
                    label=f"{label}  AP={float(formal.average_precision):.3f}")
    axs[0].plot([0, 1], [0, 1], linestyle="--", color="#555", linewidth=0.9)
    prevalence = float(y.mean())
    axs[1].axhline(prevalence, color="#555", linestyle="--", linewidth=0.9,
                   label=("ITDK 阳性比例基线" if zh else "ITDK prevalence baseline") + f" = {prevalence*100:.3f}%")
    axs[0].text(.02, .98, "(a) ROC", transform=axs[0].transAxes, ha="left", va="top", fontsize=10)
    axs[1].text(.02, .98, "(b) 精确率—召回率" if zh else "(b) Precision–Recall",
                transform=axs[1].transAxes, ha="left", va="top", fontsize=10)
    axs[0].set_xlabel("假阳性率" if zh else "False-positive rate")
    axs[0].set_ylabel("真阳性率" if zh else "True-positive rate")
    axs[1].set_xlabel("召回率" if zh else "Recall")
    axs[1].set_ylabel("精确率" if zh else "Precision")
    for ax in axs:
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.grid(color=COLORS["grid"], linewidth=0.4, alpha=0.25)
    ins = axs[1].inset_axes([.54, .48, .42, .40])
    for score, (color, _) in series.items():
        s = z[score].to_numpy(); precision, recall, _ = precision_recall_curve(y, s)
        ins.step(recall, precision, where="post", color=color, linewidth=1.1)
    ins.axhline(prevalence, color="#555", linestyle="--", linewidth=0.9)
    ins.set_xlim(0, 1); ins.set_ylim(0, .05)
    ins.grid(color=COLORS["grid"], linewidth=0.4, alpha=0.25)
    ins.tick_params(labelsize=8)
    axs[0].legend(frameon=False, fontsize=7.5, loc="lower right")
    axs[1].legend(frameon=False, fontsize=7.5, loc="upper right")
    fig.subplots_adjust(left=.08, right=.99, bottom=.17, top=.98, wspace=.25)
    save_triplet(fig, out / "figures_main" / lang / f"figure3_power_normal_roc_pr_v6_{lang}")


def figure4(out: Path, lang: str, q: pd.DataFrame, c: pd.DataFrame) -> None:
    zh = lang == "zh"
    order = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    q = q.set_index("activity_quintile").loc[order].reset_index()
    c = c.sort_values("top_fraction")
    if set(np.round(c["top_fraction"].to_numpy(), 6)) != {0.1, 0.2, 0.5, 1.0}:
        raise RuntimeError("Figure 4(b) formal points changed")
    fig, axs = plt.subplots(1, 2, figsize=(7.25, 3.35))
    x = np.arange(1, 6); y = q.positive_loss_rate.to_numpy() * 100
    yerr = np.vstack([np.maximum(0.0, (q.positive_loss_rate - q.positive_loss_rate_ci_low).to_numpy() * 100),
                      np.maximum(0.0, (q.positive_loss_rate_ci_high - q.positive_loss_rate).to_numpy() * 100)])
    axs[0].errorbar(x, y, yerr=yerr, fmt="o", color=COLORS["normal"], ecolor=COLORS["normal"],
                    markersize=STYLE_FIG4["ms"], markeredgewidth=STYLE_FIG4["markeredgewidth"],
                    elinewidth=STYLE_FIG4["elinewidth"], capthick=STYLE_FIG4["capthick"],
                    capsize=STYLE_FIG4["capsize"], linestyle="none")
    axs[0].set_xticks(x, order); axs[0].set_ylim(0, 60)
    axs[0].text(.02, .98, "(a) 基线活跃度分组" if zh else "(a) Activity quintiles",
                transform=axs[0].transAxes, ha="left", va="top", fontsize=10)
    axs[1].plot(c.top_fraction.to_numpy() * 100, c.cumulative_positive_loss_share.to_numpy() * 100,
                linestyle="none", marker="o", markersize=STYLE_FIG4["ms"],
                markeredgewidth=STYLE_FIG4["markeredgewidth"], color=COLORS["power"], zorder=3)
    axs[1].plot([0, 100], [0, 100], linestyle="--", color="#666", linewidth=0.9)
    axs[1].text(.02, .98, "(b) 累计损失份额" if zh else "(b) Cumulative loss share",
                transform=axs[1].transAxes, ha="left", va="top", fontsize=10)
    axs[1].set_xlim(-2, 102); axs[1].set_ylim(-2, 102)
    axs[1].set_xticks([0, 20, 40, 60, 80, 100]); axs[1].set_yticks([0, 20, 40, 60, 80, 100])
    axs[0].set_xlabel("基线活跃度五分位" if zh else "Activity quintile")
    axs[0].set_ylabel("正向可达性损失发生比例（%）" if zh else "Positive-loss proportion (%)")
    axs[1].set_xlabel("按基线活跃度降序的累计 IP 占比（%）" if zh else "Cumulative IP share ranked by baseline Activity (%)")
    axs[1].set_ylabel("累计正向可达性损失占比（%）" if zh else "Cumulative positive-loss share (%)")
    for ax in axs:
        ax.grid(color=COLORS["grid"], linewidth=0.4, alpha=0.25)
    fig.subplots_adjust(left=.09, right=.99, bottom=.19, top=.98, wspace=.24)
    save_triplet(fig, out / "figures_main" / lang / f"figure4_activity_loss_v6_{lang}")


def figure5(out: Path, lang: str, master: pd.DataFrame, rel: pd.DataFrame) -> None:
    zh = lang == "zh"
    d_router = summary_with_edges(master, "power_availability", "itdk_202408_router",
                                  fd_edges(master["power_availability"].dropna().to_numpy()))
    d_trace = summary_with_edges(master, "power_availability", "own_traceroute_intermediate",
                                 fd_edges(master["power_availability"].dropna().to_numpy()))
    d_router.to_csv(out / "tables" / f"figure5_router_binned_data_{lang}.csv", index=False)
    d_trace.to_csv(out / "tables" / f"figure5_traceroute_binned_data_{lang}.csv", index=False)
    fig = plt.figure(figsize=(7.45, 2.85))
    gs = fig.add_gridspec(1, 3, width_ratios=[0.78, 1.15, 1.15], wspace=0.24)
    axs = [fig.add_subplot(gs[0, i]) for i in range(3)]
    rel = rel.sort_values("release").reset_index(drop=True)
    yy = np.arange(len(rel))
    axs[0].errorbar(rel.AUC_power, yy,
                    xerr=[np.maximum(0.0, rel.AUC_power-rel.CI_low), np.maximum(0.0, rel.CI_high-rel.AUC_power)],
                    fmt="o", markersize=STYLE_FIG5_SPARSE["ms"], markeredgewidth=STYLE_FIG5_SPARSE["markeredgewidth"],
                    elinewidth=STYLE_FIG5_SPARSE["elinewidth"], capsize=STYLE_FIG5_SPARSE["capsize"],
                    color=COLORS["normal"], ecolor=COLORS["normal"], linestyle="none")
    axs[0].set_yticks(yy, [f"ITDK {x}" for x in rel.release])
    axs[0].set_xlim(.80, .90); axs[0].set_xlabel("ROC-AUC")
    axs[0].set_title("(a) ITDK 时间快照" if zh else "(a) ITDK snapshots", fontsize=9, loc="left", pad=3)
    for i, row in rel.iterrows():
        axs[0].text(row.AUC_power + .012, i, f"{row.AUC_power:.3f}", va="center", ha="left", fontsize=7.5)
    axs[0].grid(axis="x", color=COLORS["grid"], linewidth=0.4, alpha=0.25)
    panels = [
        (axs[1], d_router, "(b) 路由器接口证据" if zh else "(b) Router-interface evidence", "路由器接口证据比例（%）" if zh else "Router-interface evidence (%)"),
        (axs[2], d_trace, "(c) Traceroute 中间跳证据" if zh else "(c) Traceroute intermediate-hop evidence", "Traceroute 中间跳证据比例（%）" if zh else "Traceroute intermediate-hop evidence (%)"),
    ]
    for ax, d, title, ylabel in panels:
        y = d.proportion.to_numpy() * 100
        lo = np.maximum(0.0, (d.proportion - d.CI_low).to_numpy() * 100)
        hi = np.maximum(0.0, (d.CI_high - d.proportion).to_numpy() * 100)
        ax.errorbar(d.x_mean, y, yerr=[lo, hi], fmt="o",
                    markersize=STYLE_FIG5_DENSE["ms"], markeredgewidth=STYLE_FIG5_DENSE["markeredgewidth"],
                    elinewidth=STYLE_FIG5_DENSE["elinewidth"], capsize=STYLE_FIG5_DENSE["capsize"],
                    alpha=STYLE_FIG5_DENSE["alpha"], color=COLORS["normal"], ecolor=COLORS["normal"],
                    linestyle="none")
        ax.set_xlim(0, 1); ax.set_xlabel("可达率" if zh else "Availability"); ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=9, loc="left", pad=3)
        ax.grid(color=COLORS["grid"], linewidth=0.4, alpha=0.25)
    for ax in axs:
        ax.tick_params(labelsize=8)
    fig.subplots_adjust(left=.065, right=.998, bottom=.22, top=.90)
    save_triplet(fig, out / "figures_main" / lang / f"figure5_multisource_robustness_v6_{lang}")


def copy_inputs(out: Path, v5: Path) -> None:
    inputs = [
        v5 / "tables/TABLE_F07_final_auc.csv",
        v5 / "tables/TABLE_F08_final_pr.csv",
        v5 / "tables/TABLE_F10_itdk_release_final.csv",
        v5 / "tables/h4_activity_quintile_summary.csv",
        v5 / "tables/h4_activity_concentration_summary.csv",
        v5 / "tables/v4_snapshot/figure2_common_bins.csv",
        v5 / "tables/v4_snapshot/figure2_power_binned_data.csv",
        v5 / "tables/v4_snapshot/figure2_normal_binned_data.csv",
    ]
    used = out / "tables" / "used_frozen_inputs"
    used.mkdir(parents=True, exist_ok=True)
    for p in inputs:
        shutil.copy2(p, used / p.name)


def write_report(out: Path) -> None:
    (out / "reports/V6_PARAMETER_CHECK.md").write_text(
        "# V6 strict redraw parameter check\n\n"
        "Figure 1 was not generated; `FIGURE1_PLACEHOLDER.md` records that it is supplied separately.\n\n"
        "Frozen values were read from v5/source freeze tables and checked before rendering.\n\n"
        "FROZEN_VALUES_CHANGED = NO\n",
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v5-root", required=True, type=Path)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    validate_fixed_styles()
    prepare_output(args.out)
    master, auc, rel, q, c = load_frozen(args.v5_root, args.source)
    common, power, normal = load_frozen_fig2_tables(args.v5_root)
    copy_inputs(args.out, args.v5_root)
    for lang in ("zh", "en"):
        figure2(args.out, lang, common, power, normal)
        figure3(args.out, lang, master, auc)
        figure4(args.out, lang, q, c)
        figure5(args.out, lang, master, rel)
    shutil.copy2(Path(__file__), args.out / "scripts/plot_figures_v6.py")
    write_report(args.out)
    print(json.dumps({"output": str(args.out), "figures": [2, 3, 4, 5], "figure1": "not_generated",
                      "frozen_values_changed": "NO"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
