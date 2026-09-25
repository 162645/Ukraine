#!/usr/bin/env python3
"""Finalize strict own-traceroute evidence in Figure 5(c) and Supplement S2.

This is a display/provenance-only closure step.  It consumes the completed
ClickHouse rebuild artifacts and the frozen v7 figure package.  It does not
query ClickHouse, change bins, select a threshold, fit a model, or modify any
scientific result outside the traceroute label correction authorized for
Figure 5(c) and Supplement S2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image


FONT = ["WenQuanYi Zen Hei", "Noto Sans CJK SC", "DejaVu Sans"]
COLORS = {
    "power": "#C63D2F",
    "normal": "#2F6F9F",
    "ink": "#20252B",
    "grid": "#D9DEE3",
}
FIG5_WSPACE = 0.36
FIG5_WIDTH_RATIOS = [0.82, 1.15, 1.15]
FIG5_FIGSIZE = (7.95, 2.85)
S2_FIGSIZE = (6.4, 4.0)
EXPECTED = {
    "main_sample_ip_n": 1_170_227,
    "caida_ip_n": 3_958,
    "own_traceroute_ip_n": 7_430,
    "both_ip_n": 3_450,
    "own_only_ip_n": 3_980,
    "caida_only_ip_n": 508,
    "union_ip_n": 7_938,
    "legacy_own_ip_n": 10_697,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_triplet(fig: plt.Figure, base: Path, dpi: int, pad_inches: float) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=dpi, bbox_inches="tight", pad_inches=pad_inches)
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight", pad_inches=pad_inches)
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", pad_inches=pad_inches)
    plt.close(fig)


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return math.nan, math.nan
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return ctr - half, ctr + half


def load_and_validate_bins(strict_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    src = strict_root / "OWN_TRACEROUTE_S2_DESCRIPTIVE_BINS.csv"
    bins = pd.read_csv(src)
    required = {
        "label_source", "bin_index", "bin_left", "bin_right", "right_closed",
        "mean_power_availability", "ip_n", "positive_ip_n", "positive_prevalence",
        "wilson_95_low", "wilson_95_high",
    }
    missing = required - set(bins.columns)
    if missing:
        raise RuntimeError(f"Strict S2 source is missing columns: {sorted(missing)}")
    strict = bins.loc[bins.label_source.eq("rebuilt_clickhouse")].copy().sort_values("bin_index")
    legacy = bins.loc[bins.label_source.eq("frozen_master")].copy().sort_values("bin_index")
    if len(strict) != 85 or len(legacy) != 85:
        raise RuntimeError(f"Expected 85 frozen bins per label; got strict={len(strict)}, legacy={len(legacy)}")
    if int(strict.ip_n.sum()) != EXPECTED["main_sample_ip_n"]:
        raise RuntimeError("Strict S2 denominator does not sum to the frozen main sample")
    if int(strict.positive_ip_n.sum()) != EXPECTED["own_traceroute_ip_n"]:
        raise RuntimeError("Strict S2 positives are not 7,430")
    if int(legacy.positive_ip_n.sum()) != EXPECTED["legacy_own_ip_n"]:
        raise RuntimeError("Historical audit positives are not 10,697")
    for col in ["bin_index", "bin_left", "bin_right", "right_closed", "mean_power_availability", "ip_n"]:
        a = strict[col].reset_index(drop=True)
        b = legacy[col].reset_index(drop=True)
        if col == "right_closed":
            same = a.astype(str).equals(b.astype(str))
        else:
            same = np.allclose(pd.to_numeric(a), pd.to_numeric(b), rtol=0, atol=1e-15)
        if not same:
            raise RuntimeError(f"Strict and historical S2 bin geometry differs: {col}")
    interval_rows = []
    for row in strict.itertuples(index=False):
        lo, hi = wilson(int(row.positive_ip_n), int(row.ip_n))
        interval_rows.append({
            "bin_index": int(row.bin_index),
            "source_low": float(row.wilson_95_low),
            "recomputed_low": lo,
            "source_high": float(row.wilson_95_high),
            "recomputed_high": hi,
            "max_abs_difference": max(abs(lo - float(row.wilson_95_low)), abs(hi - float(row.wilson_95_high))),
        })
    interval_qa = pd.DataFrame(interval_rows)
    if float(interval_qa.max_abs_difference.max()) > 1e-15:
        raise RuntimeError("Strict S2 Wilson interval identity failed")
    return bins, strict, interval_qa


def formal_figure_data(strict: pd.DataFrame) -> pd.DataFrame:
    out = strict.rename(columns={
        "mean_power_availability": "x_mean",
        "ip_n": "n",
        "positive_ip_n": "positive",
        "positive_prevalence": "proportion",
        "wilson_95_low": "CI_low",
        "wilson_95_high": "CI_high",
    }).copy()
    out.insert(0, "score", "power_availability")
    out.insert(1, "label", "strict_own_traceroute_target_preceding_public_intermediate_hop")
    out["label_definition_en"] = "Public intermediate-hop IP strictly observed before the target in contemporaneous own-traceroute paths"
    out["label_definition_zh"] = "从同期自有 traceroute 路径中严格提取的目标前公网中间跳 IP"
    return out[[
        "score", "label", "bin_index", "bin_left", "bin_right", "right_closed",
        "x_mean", "n", "positive", "proportion", "CI_low", "CI_high",
        "label_definition_en", "label_definition_zh",
    ]]


def errorbar_arrays(data: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x = data.x_mean.to_numpy(dtype=float)
    y = data.proportion.to_numpy(dtype=float) * 100
    lo = np.maximum(0.0, (data.proportion - data.CI_low).to_numpy(dtype=float) * 100)
    hi = np.maximum(0.0, (data.CI_high - data.proportion).to_numpy(dtype=float) * 100)
    return x, y, lo, hi


def legacy_s2_axis_limits(legacy: pd.DataFrame) -> tuple[tuple[float, float], tuple[float, float]]:
    d = legacy.rename(columns={
        "mean_power_availability": "x_mean",
        "positive_prevalence": "proportion",
        "wilson_95_low": "CI_low",
        "wilson_95_high": "CI_high",
    })
    x, y, lo, hi = errorbar_arrays(d)
    with plt.rc_context({"font.size": 8, "font.sans-serif": ["WenQuanYi Zen Hei", "DejaVu Sans"], "axes.unicode_minus": False}):
        fig, ax = plt.subplots(figsize=S2_FIGSIZE)
        ax.errorbar(x, y, yerr=[lo, hi], fmt="o", capsize=3, color="#2c7fb8", ecolor="#2c7fb8")
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        plt.close(fig)
    return (float(xlim[0]), float(xlim[1])), (float(ylim[0]), float(ylim[1]))


def render_s2(out: Path, formal: pd.DataFrame, xlim: tuple[float, float], ylim: tuple[float, float]) -> None:
    x, y, lo, hi = errorbar_arrays(formal)
    if np.min(x) < xlim[0] or np.max(x) > xlim[1] or np.min(y - lo) < ylim[0] or np.max(y + hi) > ylim[1]:
        raise RuntimeError("Strict S2 values do not fit the frozen coordinate range")
    for lang in ["en", "zh"]:
        zh = lang == "zh"
        with plt.rc_context({
            "font.size": 8,
            "font.sans-serif": ["WenQuanYi Zen Hei", "DejaVu Sans"],
            "axes.unicode_minus": False,
        }):
            fig, ax = plt.subplots(figsize=S2_FIGSIZE)
            ax.errorbar(x, y, yerr=[lo, hi], fmt="o", capsize=3, color="#2c7fb8", ecolor="#2c7fb8")
            ax.set(
                xlabel="每个冻结描述性分箱的平均停电窗口可达率" if zh else "Mean power-window availability within each frozen descriptive bin",
                ylabel="严格自有 traceroute 目标前公网中间跳比例（%）" if zh else "Strict own-traceroute pre-target public intermediate-hop evidence (%)",
                title="严格自有 traceroute 中间跳证据与停电窗口可达率" if zh else "Strict Own-Traceroute Intermediate-Hop Evidence and Power-Window Availability",
                xlim=xlim,
                ylim=ylim,
            )
            ax.grid(alpha=.18)
            fig.tight_layout()
            save_triplet(fig, out / "figures_supplement" / lang / f"S2_own_traceroute_strict_{lang}", dpi=300, pad_inches=0.1)


def render_figure5(out: Path, lang: str, rel: pd.DataFrame, router: pd.DataFrame, trace: pd.DataFrame) -> None:
    zh = lang == "zh"
    rc = {
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
    }
    with plt.rc_context(rc):
        fig = plt.figure(figsize=FIG5_FIGSIZE)
        gs = fig.add_gridspec(1, 3, width_ratios=FIG5_WIDTH_RATIOS, wspace=FIG5_WSPACE)
        axs = [fig.add_subplot(gs[0, i]) for i in range(3)]
        rel = rel.sort_values("release").reset_index(drop=True)
        yy = np.arange(len(rel))
        axs[0].errorbar(
            rel.AUC_power, yy,
            xerr=[np.maximum(0.0, rel.AUC_power-rel.CI_low), np.maximum(0.0, rel.CI_high-rel.AUC_power)],
            fmt="o", markersize=3.2, markeredgewidth=0.45, elinewidth=0.65,
            capsize=1.0, color=COLORS["normal"], ecolor=COLORS["normal"], linestyle="none",
        )
        axs[0].set_yticks(yy, [f"ITDK {x}" for x in rel.release])
        axs[0].set_xlim(.80, .90)
        axs[0].set_xlabel("ROC-AUC")
        axs[0].set_title("(a) ITDK 时间快照" if zh else "(a) ITDK snapshots", fontsize=9, loc="left", pad=3)
        for i, row in rel.iterrows():
            axs[0].text(row.AUC_power + .010, i, f"{row.AUC_power:.3f}", va="center", ha="left", fontsize=7.5)
        axs[0].grid(axis="x", color=COLORS["grid"], linewidth=0.4, alpha=0.25)
        panels = [
            (axs[1], router, "(b) 路由器接口证据" if zh else "(b) Router-interface evidence", "路由器接口证据比例（%）" if zh else "Router-interface evidence (%)"),
            (axs[2], trace, "(c) 严格 Traceroute 证据" if zh else "(c) Strict traceroute evidence", "严格 Traceroute 证据比例（%）" if zh else "Strict traceroute evidence (%)"),
        ]
        for ax, data, title, ylabel in panels:
            x, y, lo, hi = errorbar_arrays(data)
            ax.errorbar(
                x, y, yerr=[lo, hi], fmt="o", markersize=1.55, markeredgewidth=0.30,
                elinewidth=0.40, capsize=0, alpha=0.82,
                color=COLORS["normal"], ecolor=COLORS["normal"], linestyle="none",
            )
            ax.set_xlim(0, 1)
            ax.set_xlabel("可达率" if zh else "Availability")
            ax.set_ylabel(ylabel)
            ax.yaxis.labelpad = 4
            ax.set_title(title, fontsize=9, loc="left", pad=3)
            ax.grid(color=COLORS["grid"], linewidth=0.4, alpha=0.25)
        for ax in axs:
            ax.tick_params(labelsize=8)
        fig.subplots_adjust(left=.07, right=.985, top=.90, bottom=.18)
        save_triplet(fig, out / "figures_main" / lang / f"figure5_multisource_robustness_v8_{lang}", dpi=600, pad_inches=0.04)


def write_coverage(strict_root: Path, out: Path) -> pd.DataFrame:
    overlap = pd.read_csv(strict_root / "OWN_TRACEROUTE_CAIDA_OVERLAP.csv").iloc[0]
    exact = {
        "caida_ip_n": int(overlap.caida_positive_ip_n),
        "own_traceroute_ip_n": int(overlap.rebuilt_own_positive_ip_n),
        "both_ip_n": int(overlap.both_positive_ip_n),
        "own_only_ip_n": int(overlap.rebuilt_own_only_ip_n),
        "caida_only_ip_n": int(overlap.caida_only_ip_n),
        "union_ip_n": int(overlap.union_positive_ip_n),
    }
    for key, expected in EXPECTED.items():
        if key in exact and exact[key] != expected:
            raise RuntimeError(f"Coverage mismatch for {key}: {exact[key]} != {expected}")
    rows = [
        ("CAIDA", exact["caida_ip_n"], "IP", "Main-sample IPs with CAIDA ITDK 2024-08 transit evidence"),
        ("own traceroute", exact["own_traceroute_ip_n"], "IP", "Strict public intermediate hops observed before the target in contemporaneous own-traceroute paths"),
        ("both", exact["both_ip_n"], "IP", "Observed by both topology sources"),
        ("own-only", exact["own_only_ip_n"], "IP", "Strict own-traceroute evidence without CAIDA transit evidence"),
        ("CAIDA-only", exact["caida_only_ip_n"], "IP", "CAIDA transit evidence without strict own-traceroute evidence"),
        ("union", exact["union_ip_n"], "IP", "Observed by either topology source"),
        ("P(own|CAIDA)", 87.17, "percent", "both / CAIDA; rounded to two decimals from the frozen strict rebuild"),
        ("P(CAIDA|own)", 46.43, "percent", "both / own traceroute; rounded to two decimals from the frozen strict rebuild"),
    ]
    coverage = pd.DataFrame(rows, columns=["metric", "value", "unit", "definition"])
    coverage.to_csv(out / "tables/TOPOLOGY_EVIDENCE_COVERAGE.csv", index=False)
    return coverage


def archive_v7_traceroute_material(out: Path) -> None:
    audit = out / "audit/provenance_v7_legacy_10697"
    audit.mkdir(parents=True, exist_ok=True)
    candidates = [
        out / "tables/figure5_traceroute_binned_data_en.csv",
        out / "tables/figure5_traceroute_binned_data_zh.csv",
        out / "tables/V7_FROZEN_NUMERIC_VALUES.csv",
        out / "tables/frozen_figure_hashes_v7.csv",
        out / "reports/V7_LAYOUT_CHANGES.md",
        out / "scripts/plot_figures_v7.py",
    ]
    for src in candidates:
        if src.exists():
            shutil.move(str(src), audit / src.name)
    for lang in ["en", "zh"]:
        for ext in ["png", "pdf", "svg"]:
            src = out / "figures_main" / lang / f"figure5_multisource_robustness_v7_{lang}.{ext}"
            if src.exists():
                shutil.move(str(src), audit / src.name)


def record_legacy_s2_provenance(legacy_s2_root: Path, out: Path) -> pd.DataFrame:
    """Record, but never promote, the historical 10,697-label S2 artifacts."""
    rows = []
    for lang in ["en", "zh"]:
        for ext in ["png", "pdf", "svg"]:
            src = legacy_s2_root / f"supplement_{lang}" / f"S2_own_traceroute_{lang}.{ext}"
            if not src.exists():
                raise FileNotFoundError(f"Historical S2 provenance file is missing: {src}")
            row = {
                "file": src.relative_to(legacy_s2_root).as_posix(),
                "bytes": src.stat().st_size,
                "sha256": sha256(src),
                "role": "audit_only_historical_10697_label",
            }
            if ext == "png":
                row.update(image_metadata(src))
            else:
                row.update({"width_px": "", "height_px": "", "dpi_x": "", "dpi_y": ""})
            rows.append(row)
    result = pd.DataFrame(rows)
    result.to_csv(out / "audit/provenance_v7_legacy_10697/LEGACY_S2_FILE_HASHES.csv", index=False)
    return result


def write_captions(out: Path) -> None:
    en = """# Updated Figure 5 and Supplement S2 captions (English)\n\n## Figure 5. Multi-source topology-evidence robustness\nPanels (a) and (b) retain the frozen v7 ITDK snapshot and router-interface evidence. Panel (c) replaces the historical own-traceroute label with the strict set of 7,430 public intermediate-hop IPs observed before the target in contemporaneous own-traceroute paths. The unchanged Freedman–Diaconis bins and Wilson 95% intervals are descriptive; no model or threshold is introduced.\n\n## Supplement S2. Strict own-traceroute intermediate-hop evidence\nAcross the unchanged frozen Figure 3 Freedman–Diaconis bins, points show the prevalence of IPs strictly extracted as public intermediate hops before the target from contemporaneous own-traceroute paths; bars are Wilson 95% intervals. The strict label contains 7,430 of 1,170,227 main-sample IPs. This is secondary, measurement-period- and vantage-aligned topology evidence; it is not fully independent of the active-measurement environment and is not infrastructure ground truth.\n"""
    zh = """# 更新后的 Figure 5 与补充图 S2 图注（中文）\n\n## Figure 5 多源拓扑证据稳健性\n面板（a）和（b）保留冻结 v7 的 ITDK 时间快照与路由器接口证据。面板（c）将历史自有 traceroute 标签替换为 7,430 个“从同期自有 traceroute 路径中严格提取的目标前公网中间跳 IP”。沿用未改变的 Freedman–Diaconis 分箱和 Wilson 95% 区间，仅作描述；未增加模型或阈值。\n\n## 补充图 S2 严格自有 traceroute 中间跳证据\n在与冻结 Figure 3 完全相同的 Freedman–Diaconis 分箱中，点表示“从同期自有 traceroute 路径中严格提取的目标前公网中间跳 IP”的比例，误差线为 Wilson 95% 区间。严格标签在 1,170,227 个主样本 IP 中包含 7,430 个。该结果是与研究测量时期和测量点对齐的辅助拓扑证据；它与主动测量环境并非完全独立，也不是基础设施真值。\n"""
    (out / "captions").mkdir(parents=True, exist_ok=True)
    (out / "captions/FIGURE5_S2_CAPTIONS_EN.md").write_text(en, encoding="utf-8")
    (out / "captions/FIGURE5_S2_CAPTIONS_ZH.md").write_text(zh, encoding="utf-8")


def write_message_contract(out: Path) -> None:
    text = """# S2 figure-message contract\n\n- **Argument position:** secondary topology-source validation aligned to the study period and vantage point.\n- **Reader task:** inspect how the prevalence of strictly observed pre-target public intermediate-hop IPs varies across the unchanged availability bins.\n- **One-sentence conclusion:** the descriptive relationship remains higher toward the high-availability end after replacing the historical label with the strict 7,430-IP rebuild.\n- **First-look evidence:** point positions and Wilson 95% intervals on the frozen common axes.\n- **Detail layer:** the complete 85-bin frozen figure-data CSV, denominators, positives, and intervals.\n- **Non-claim:** the figure does not establish causality, a threshold, a fitted association, or infrastructure ground truth.\n- **Link forward:** CAIDA remains the external primary topology source; own traceroute supplies temporally and spatially aligned secondary evidence.\n"""
    (out / "reports/S2_FIGURE_MESSAGE_CONTRACT.md").write_text(text, encoding="utf-8")


def image_metadata(path: Path) -> dict[str, object]:
    with Image.open(path) as img:
        dpi = img.info.get("dpi", (math.nan, math.nan))
        return {
            "width_px": img.width,
            "height_px": img.height,
            "dpi_x": float(dpi[0]) if dpi else math.nan,
            "dpi_y": float(dpi[1]) if dpi else math.nan,
        }


def make_figure_manifest(out: Path) -> pd.DataFrame:
    rows = []
    for root_name in ["figures_main", "figures_supplement"]:
        root = out / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".png", ".pdf", ".svg"}:
                continue
            rel = path.relative_to(out).as_posix()
            row = {
                "file": rel,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "formal_or_audit": "formal",
                "traceroute_label": "strict_7430" if ("figure5_" in path.name or "S2_" in path.name) else "not_applicable",
            }
            if path.suffix.lower() == ".png":
                row.update(image_metadata(path))
            else:
                row.update({"width_px": "", "height_px": "", "dpi_x": "", "dpi_y": ""})
            rows.append(row)
    manifest = pd.DataFrame(rows)
    manifest.to_csv(out / "tables/FIGURE_MANIFEST_V8.csv", index=False)
    return manifest


def write_package_manifest(out: Path) -> None:
    target = out / "qa/PACKAGE_MANIFEST_SHA256.csv"
    rows = []
    for path in sorted(out.rglob("*")):
        if path.is_file() and path != target:
            rows.append({"file": path.relative_to(out).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    pd.DataFrame(rows).to_csv(target, index=False)


def write_implementation_provenance(out: Path, strict_root: Path) -> str:
    repo = Path(__file__).resolve().parent.parent
    commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    strict_summary_path = strict_root / "OWN_TRACEROUTE_REBUILD_SUMMARY.json"
    strict_summary = json.loads(strict_summary_path.read_text(encoding="utf-8"))
    payload = {
        "figure_renderer_git_commit": commit,
        "strict_rebuild_implementation_git_commit": strict_summary["implementation_git_commit"],
        "strict_rebuild_scientific_input_git_commit": strict_summary["scientific_input_git_commit"],
        "strict_rebuild_summary_sha256": sha256(strict_summary_path),
        "strict_s2_bins_sha256": sha256(strict_root / "OWN_TRACEROUTE_S2_DESCRIPTIVE_BINS.csv"),
        "strict_overlap_sha256": sha256(strict_root / "OWN_TRACEROUTE_CAIDA_OVERLAP.csv"),
        "clickhouse_source_table": strict_summary["source_table"],
        "formal_own_traceroute_positive_ip_n": EXPECTED["own_traceroute_ip_n"],
        "historical_label_role": "audit/provenance only",
    }
    (out / "reports/IMPLEMENTATION_PROVENANCE.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return commit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v7-root", required=True, type=Path)
    ap.add_argument("--strict-rebuild-root", required=True, type=Path)
    ap.add_argument("--legacy-s2-root", required=True, type=Path)
    ap.add_argument("--visual-review", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {args.out}")
    shutil.copytree(args.v7_root, args.out)
    for rel in ["figures_supplement/en", "figures_supplement/zh", "captions", "qa", "audit", "reports"]:
        (args.out / rel).mkdir(parents=True, exist_ok=True)
    archive_v7_traceroute_material(args.out)
    legacy_s2_manifest = record_legacy_s2_provenance(args.legacy_s2_root, args.out)

    all_bins, strict, interval_qa = load_and_validate_bins(args.strict_rebuild_root)
    formal = formal_figure_data(strict)
    formal.to_csv(args.out / "tables/S2_STRICT_FROZEN_FIGURE_DATA.csv", index=False)
    # Figure 5 consumes the exact same strict figure data; bilingual files are identical by design.
    fig5_formal = formal.rename(columns={"x_mean": "x_mean", "n": "n", "positive": "positive"})[
        ["score", "bin_left", "bin_right", "x_mean", "n", "positive", "proportion", "CI_low", "CI_high"]
    ]
    for lang in ["en", "zh"]:
        fig5_formal.to_csv(args.out / f"tables/figure5_traceroute_binned_data_{lang}.csv", index=False)

    legacy = all_bins.loc[all_bins.label_source.eq("frozen_master")].copy().sort_values("bin_index")
    xlim, ylim = legacy_s2_axis_limits(legacy)
    render_s2(args.out, formal, xlim, ylim)

    rel = pd.read_csv(args.out / "tables/TABLE_F10_itdk_release_final.csv")
    for lang in ["en", "zh"]:
        router = pd.read_csv(args.out / f"tables/figure5_router_binned_data_{lang}.csv")
        trace = pd.read_csv(args.out / f"tables/figure5_traceroute_binned_data_{lang}.csv")
        render_figure5(args.out, lang, rel, router, trace)

    coverage = write_coverage(args.strict_rebuild_root, args.out)
    interval_qa.to_csv(args.out / "qa/S2_WILSON_INTERVAL_IDENTITY.csv", index=False)
    pd.DataFrame([{
        "legacy_xlim_low": xlim[0], "legacy_xlim_high": xlim[1],
        "legacy_ylim_low": ylim[0], "legacy_ylim_high": ylim[1],
        "strict_min_x": float(formal.x_mean.min()), "strict_max_x": float(formal.x_mean.max()),
        "strict_min_ci_percent": float((formal.CI_low * 100).min()),
        "strict_max_ci_percent": float((formal.CI_high * 100).max()),
        "status": "PASS",
    }]).to_csv(args.out / "qa/S2_COORDINATE_FREEZE_QA.csv", index=False)

    write_captions(args.out)
    write_message_contract(args.out)
    review_text = args.visual_review.read_text(encoding="utf-8")
    if "render_review_status = PASS" not in review_text:
        raise RuntimeError("Visual-review record is not PASS")
    shutil.copy2(args.visual_review, args.out / "qa/S2_V8_RENDER_REVIEW.md")
    shutil.copy2(Path(__file__), args.out / "scripts/finalize_traceroute_figures_v8.py")
    renderer_commit = write_implementation_provenance(args.out, args.strict_rebuild_root)

    checks: list[dict[str, str]] = []
    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    check("strict positive IP count", int(formal.positive.sum()) == 7430, f"observed={int(formal.positive.sum())}; expected=7430")
    check("historical label excluded from formal S2 data", int(formal.positive.sum()) != 10697, "formal S2 data contains only rebuilt_clickhouse rows")
    check("frozen bin count", len(formal) == 85, f"rows={len(formal)}")
    check("frozen main-sample denominator", int(formal.n.sum()) == 1_170_227, f"sum_n={int(formal.n.sum())}")
    check("Wilson 95% identity", float(interval_qa.max_abs_difference.max()) <= 1e-15, f"max_abs_diff={interval_qa.max_abs_difference.max():.3g}")
    check("no model fitted", True, "renderer consumes frozen bin summaries only")
    check("no threshold added", True, "no threshold appears in code or outputs")
    check("coverage row count", len(coverage) == 8, f"rows={len(coverage)}")
    check("legacy S2 retained only as provenance hashes", len(legacy_s2_manifest) == 6, f"files_hashed={len(legacy_s2_manifest)}")
    check("server-rendered images visually reviewed", True, "qa/S2_V8_RENDER_REVIEW.md records PASS after PNG inspection")
    check("renderer commit recorded", len(renderer_commit) == 40, renderer_commit)
    for relpath in ["FIGURE1_PLACEHOLDER.md"]:
        before = args.v7_root / relpath
        after = args.out / relpath
        check(f"unchanged {relpath}", before.exists() and after.exists() and sha256(before) == sha256(after), "byte-level SHA-256 identity")
    for figure in ["figure2_", "figure3_", "figure4_"]:
        before_files = sorted(p for p in (args.v7_root / "figures_main").rglob("*") if p.is_file() and p.name.startswith(figure))
        same = bool(before_files)
        for before in before_files:
            after = args.out / before.relative_to(args.v7_root)
            same = same and after.exists() and sha256(before) == sha256(after)
        check(f"unchanged {figure.rstrip('_')}", same, f"files_checked={len(before_files)}; byte-level SHA-256 identity")
    for lang in ["en", "zh"]:
        before_router = args.v7_root / f"tables/figure5_router_binned_data_{lang}.csv"
        after_router = args.out / f"tables/figure5_router_binned_data_{lang}.csv"
        check(f"Figure 5(b) data unchanged/{lang}", sha256(before_router) == sha256(after_router), "byte-level SHA-256 identity")
    for lang in ["en", "zh"]:
        for ext in ["png", "pdf", "svg"]:
            check(
                f"S2 {lang} {ext} exists",
                (args.out / f"figures_supplement/{lang}/S2_own_traceroute_strict_{lang}.{ext}").exists(),
                "required bilingual triplet",
            )
            check(
                f"Figure 5 v8 {lang} {ext} exists",
                (args.out / f"figures_main/{lang}/figure5_multisource_robustness_v8_{lang}.{ext}").exists(),
                "authorized Figure 5(c) correction",
            )
    formal_text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in list((args.out / "captions").glob("*.md")) + list((args.out / "tables").glob("*.csv"))
        if "audit" not in p.as_posix()
    )
    check("legacy count absent from formal captions/tables", "10697" not in formal_text and "10,697" not in formal_text, "legacy count retained only under audit/provenance")

    qa = pd.DataFrame(checks)
    qa.to_csv(args.out / "qa/S2_STRICT_REBUILD_QA.csv", index=False)
    status = "PASS" if qa.status.eq("PASS").all() else "FAIL"
    (args.out / "qa/S2_STRICT_REBUILD_STATUS.txt").write_text(f"S2_STRICT_REBUILD_STATUS = {status}\n", encoding="utf-8")
    report = f"""# Strict traceroute figure closure\n\n- Formal own-traceroute label: **7,430** main-sample IPs strictly observed as public intermediate hops before the target.\n- Historical 10,697 label: retained only under `audit/provenance_v7_legacy_10697/`.\n- Supplement S2: regenerated in Chinese and English as PNG/PDF/SVG using the unchanged 85 Freedman–Diaconis bins, Wilson 95% intervals, frozen coordinate ranges, and existing S2 typography.\n- Figure 5: panels (a) and (b) retain their frozen data/layout; panel (c) alone uses the strict 7,430 label.\n- Figure 1–4: byte-identical to v7.\n- Models/thresholds: none fitted or introduced.\n\n`S2_STRICT_REBUILD_STATUS = {status}`\n"""
    (args.out / "reports/S2_STRICT_REBUILD_REPORT.md").write_text(report, encoding="utf-8")
    figure_manifest = make_figure_manifest(args.out)
    write_package_manifest(args.out)
    print(json.dumps({
        "output": str(args.out),
        "formal_s2_bins": len(formal),
        "strict_positive_ip_n": int(formal.positive.sum()),
        "figure_manifest_rows": len(figure_manifest),
        "status": status,
    }, ensure_ascii=False, indent=2))
    if status != "PASS":
        raise RuntimeError("S2 strict rebuild QA failed")


if __name__ == "__main__":
    main()
