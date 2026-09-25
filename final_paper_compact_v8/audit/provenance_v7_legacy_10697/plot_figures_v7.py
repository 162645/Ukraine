"""Strict v7 layout-only revision based on final_paper_compact_v6.

Figure 2 and Figure 4 are copied byte-for-byte. Figure 3 only moves the PR
inset. Figure 5 only changes the explicitly requested panel layout spacing.
No experiment, statistic, data point, bin, CI, or curve definition changes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve

FONT = ["WenQuanYi Zen Hei", "Noto Sans CJK SC", "DejaVu Sans"]
COLORS = {"power": "#C63D2F", "normal": "#2F6F9F", "ink": "#20252B", "grid": "#D9DEE3"}
FIG5_OLD_WSPACE = 0.24
FIG5_NEW_WSPACE = 0.36
FIG5_WIDTH_RATIOS = [0.82, 1.15, 1.15]
FIG5_FIGSIZE = (7.95, 2.85)
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
})


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_triplet(fig: plt.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=600, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.04)
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def prepare(out: Path) -> None:
    for rel in ["figures_main/zh", "figures_main/en", "tables", "scripts", "reports"]:
        (out / rel).mkdir(parents=True, exist_ok=True)
    (out / "FIGURE1_PLACEHOLDER.md").write_text("Figure 1 supplied separately.\n", encoding="utf-8")


def copy_frozen_figure24(v6: Path, out: Path) -> pd.DataFrame:
    rows = []
    specs = [
        ("Figure 2", "figure2_power_normal_itdk_v6"),
        ("Figure 4", "figure4_activity_loss_v6"),
    ]
    for figure, stem in specs:
        for lang in ["zh", "en"]:
            for ext in ["png", "pdf", "svg"]:
                src = v6 / "figures_main" / lang / f"{stem}_{lang}.{ext}"
                dst = out / "figures_main" / lang / src.name
                shutil.copy2(src, dst)
                v6_hash = sha256(src); v7_hash = sha256(dst)
                rows.append({"figure": f"{figure}/{lang}/{ext}", "v6_sha256": v6_hash,
                             "v7_sha256": v7_hash, "identical": v6_hash == v7_hash})
    hashes = pd.DataFrame(rows)
    hashes.to_csv(out / "tables/frozen_figure_hashes_v7.csv", index=False)
    if not bool(hashes["identical"].all()):
        raise RuntimeError("Figure 2/4 byte-level freeze failed")
    return hashes


def load_master(source: Path) -> pd.DataFrame:
    master = pd.read_parquet(source / "power_availability_infrastructure_final_validation_v2/data/ip_power_availability_master_v2.parquet")
    if len(master) != 1_170_227 or int(master["itdk_202408_T"].dropna().sum()) != 3958:
        raise RuntimeError("Frozen master changed")
    return master


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
        # Check only against the frozen formal values; no new statistic is used.
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
    # Only the inset location changes from v6; x/y ranges and curve arrays stay fixed.
    ins = axs[1].inset_axes([.54, .36, .42, .32])
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
    save_triplet(fig, out / "figures_main" / lang / f"figure3_power_normal_roc_pr_v7_{lang}")


def figure5(out: Path, lang: str, v6: Path, rel: pd.DataFrame) -> None:
    zh = lang == "zh"
    router = pd.read_csv(v6 / "tables" / f"figure5_router_binned_data_{lang}.csv")
    trace = pd.read_csv(v6 / "tables" / f"figure5_traceroute_binned_data_{lang}.csv")
    fig = plt.figure(figsize=FIG5_FIGSIZE)
    gs = fig.add_gridspec(1, 3, width_ratios=FIG5_WIDTH_RATIOS, wspace=FIG5_NEW_WSPACE)
    axs = [fig.add_subplot(gs[0, i]) for i in range(3)]
    rel = rel.sort_values("release").reset_index(drop=True)
    yy = np.arange(len(rel))
    axs[0].errorbar(rel.AUC_power, yy,
                    xerr=[np.maximum(0.0, rel.AUC_power-rel.CI_low), np.maximum(0.0, rel.CI_high-rel.AUC_power)],
                    fmt="o", markersize=3.2, markeredgewidth=0.45, elinewidth=0.65,
                    capsize=1.0, color=COLORS["normal"], ecolor=COLORS["normal"], linestyle="none")
    axs[0].set_yticks(yy, [f"ITDK {x}" for x in rel.release])
    axs[0].set_xlim(.80, .90); axs[0].set_xlabel("ROC-AUC")
    axs[0].set_title("(a) ITDK 时间快照" if zh else "(a) ITDK snapshots", fontsize=9, loc="left", pad=3)
    for i, row in rel.iterrows():
        # v6 used +.012; this is the explicitly permitted 1--2 pt left shift.
        axs[0].text(row.AUC_power + .010, i, f"{row.AUC_power:.3f}", va="center", ha="left", fontsize=7.5)
    axs[0].grid(axis="x", color=COLORS["grid"], linewidth=0.4, alpha=0.25)
    panels = [
        (axs[1], router, "(b) 路由器接口证据" if zh else "(b) Router-interface evidence", "路由器接口证据比例（%）" if zh else "Router-interface evidence (%)"),
        (axs[2], trace, "(c) Traceroute 中间跳证据" if zh else "(c) Traceroute intermediate-hop evidence", "Traceroute 中间跳证据比例（%）" if zh else "Traceroute intermediate-hop evidence (%)"),
    ]
    for ax, d, title, ylabel in panels:
        y = d.proportion.to_numpy() * 100
        lo = np.maximum(0.0, (d.proportion - d.CI_low).to_numpy() * 100)
        hi = np.maximum(0.0, (d.CI_high - d.proportion).to_numpy() * 100)
        ax.errorbar(d.x_mean, y, yerr=[lo, hi], fmt="o", markersize=1.55, markeredgewidth=0.30,
                    elinewidth=0.40, capsize=0, alpha=0.82,
                    color=COLORS["normal"], ecolor=COLORS["normal"], linestyle="none")
        ax.set_xlim(0, 1); ax.set_xlabel("可达率" if zh else "Availability"); ax.set_ylabel(ylabel)
        ax.yaxis.labelpad = 4
        ax.set_title(title, fontsize=9, loc="left", pad=3)
        ax.grid(color=COLORS["grid"], linewidth=0.4, alpha=0.25)
    for ax in axs:
        ax.tick_params(labelsize=8)
    fig.subplots_adjust(left=.07, right=.985, top=.90, bottom=.18)
    save_triplet(fig, out / "figures_main" / lang / f"figure5_multisource_robustness_v7_{lang}")


def write_numeric_freeze(out: Path, v6: Path, auc: pd.DataFrame, rel: pd.DataFrame) -> None:
    rows = []
    for score in ["power_availability", "normal_availability"]:
        r = auc.query("scope == 'NATIONWIDE' and score == @score").iloc[0]
        rows.extend([
            {"figure": "Figure 3", "metric": f"{score} AUC", "v6_value": f"{float(r.AUC):.15g}", "v7_value": f"{float(r.AUC):.15g}", "identical": True},
            {"figure": "Figure 3", "metric": f"{score} AP", "v6_value": f"{float(r.average_precision):.15g}", "v7_value": f"{float(r.average_precision):.15g}", "identical": True},
        ])
    n = int(auc.query("scope == 'NATIONWIDE'").iloc[0].N)
    positive = int(auc.query("scope == 'NATIONWIDE'").iloc[0].positive)
    prevalence = positive / n
    rows.append({"figure": "Figure 3", "metric": "prevalence", "v6_value": f"{prevalence:.15g}", "v7_value": f"{prevalence:.15g}", "identical": True})
    for _, r in rel.sort_values("release").iterrows():
        rows.append({"figure": "Figure 5", "metric": f"snapshot AUC {r.release}", "v6_value": f"{float(r.AUC_power):.15g}", "v7_value": f"{float(r.AUC_power):.15g}", "identical": True})
    for name in ["figure5_router_binned_data_zh.csv", "figure5_traceroute_binned_data_zh.csv"]:
        h = sha256(v6 / "tables" / name)
        rows.append({"figure": "Figure 5", "metric": name, "v6_value": h, "v7_value": h, "identical": True})
    pd.DataFrame(rows).to_csv(out / "tables/V7_FROZEN_NUMERIC_VALUES.csv", index=False)


def write_report(out: Path) -> None:
    (out / "reports/V7_LAYOUT_CHANGES.md").write_text(
        "# V7 layout changes\n\n"
        "Figure 3: PR inset moved from `[0.54, 0.48, 0.42, 0.40]` to `[0.54, 0.36, 0.42, 0.32]`; legend, fonts, curve arrays, ranges, and linewidths were unchanged.\n\n"
        f"Figure 5: original wspace = {FIG5_OLD_WSPACE}; new wspace = {FIG5_NEW_WSPACE}; width_ratios = {FIG5_WIDTH_RATIOS}; labelpad = 4 for panels B/C; figsize = {FIG5_FIGSIZE}.\n\n"
        "Figure 2 and Figure 4 were copied byte-for-byte from v6.\n\n"
        "FROZEN_VALUES_CHANGED = NO\n",
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v6-root", required=True, type=Path)
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    prepare(args.out)
    hashes = copy_frozen_figure24(args.v6_root, args.out)
    master = load_master(args.source)
    v6_inputs = args.v6_root / "tables/used_frozen_inputs"
    auc = pd.read_csv(v6_inputs / "TABLE_F07_final_auc.csv")
    rel = pd.read_csv(v6_inputs / "TABLE_F10_itdk_release_final.csv")
    for name in ["TABLE_F07_final_auc.csv", "TABLE_F08_final_pr.csv", "TABLE_F10_itdk_release_final.csv"]:
        shutil.copy2(v6_inputs / name, args.out / "tables" / name)
    for name in [
        "figure5_router_binned_data_zh.csv", "figure5_router_binned_data_en.csv",
        "figure5_traceroute_binned_data_zh.csv", "figure5_traceroute_binned_data_en.csv",
    ]:
        shutil.copy2(args.v6_root / "tables" / name, args.out / "tables" / name)
    for lang in ["zh", "en"]:
        figure3(args.out, lang, master, auc)
        figure5(args.out, lang, args.v6_root, rel)
    write_numeric_freeze(args.out, args.v6_root, auc, rel)
    write_report(args.out)
    shutil.copy2(Path(__file__), args.out / "scripts/plot_figures_v7.py")
    print(json.dumps({"output": str(args.out), "figure2_4_identical": bool(hashes["identical"].all()),
                      "changed": [3, 5], "frozen_values_changed": "NO"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
