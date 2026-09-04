#!/usr/bin/env python3
"""Render the reviewer-facing v2.4 manuscript figure set from frozen outputs.

The four main figures follow the paper's inferential chain. Diagnostics and
partial sensitivities are kept in a separate supplement. This script never
runs a core experiment or changes a frozen result.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uresil.config import load_config
from uresil.viz.style import PALETTE, apply_style


TEXT = {
    "en": {
        "design_flow_title": "Figure 1 | From scheduled outages to a falsifiable resilience test",
        "flow_schedule": "Official outage schedules",
        "flow_schedule_sub": "date · local hours · queue intensity",
        "flow_probe": "Two-hour active probing",
        "flow_probe_sub": "longitudinal IP reachability",
        "flow_calibrate": "Calibrate candidate sensors",
        "flow_calibrate_sub": "B0 vs B1 vs power-specific B2",
        "flow_freeze": "Freeze before evaluation",
        "flow_freeze_sub": "sensor rule · anchors · estimands",
        "flow_attack": "Held-out wartime attacks",
        "flow_attack_sub": "impact · recovery · external check",
        "flow_fingerprint": "ASN × Admin1 fingerprint",
        "flow_fingerprint_sub": "repeatability · future prediction",
        "flow_observed": "OBSERVED / REGISTERED",
        "flow_inferred": "TESTED INFERENCES",
        "flow_warning": "Reachability loss is not assumed to be a power outage; each arrow is an empirical gate.",
        "overview_title": "Figure 2 | Empirical closure of the proposed inference chain",
        "overview_q1": "1  Calibrate sensors",
        "overview_q2": "2  Quantify held-out attacks",
        "overview_q3": "3  Test resilience fingerprints",
        "overview_e1": "ΔAUPRC = +0.008\n95% CI crosses 0; p = 0.323",
        "overview_e2": "5/6 internally admissible\n1/6 IODA onsets within 6 h",
        "overview_e3": "repeatability ρ = 0.179; ICC = 0\nprediction p = 0.294",
        "not_supported": "NOT SUPPORTED",
        "partial": "PARTIAL",
        "conditional_status": "CONDITIONAL",
        "overview_secondary": "Secondary evidence (does not rescue the chain): recovery debt → deficit AUC, p = 0.016; same-target ASGeo shifts, 6/52 units.",
        "overview_bottom": "Positive chain not established: scheduled outages did not validate B2 sensors,\nand ASN-Admin1 fingerprints were not repeatable or predictive.\nThe study closes as a negative/boundary result.",
        "cal_title": "Figure 3 | Scheduled-outage calibration is directionally positive but fails the preregistered gate",
        "methods": "A  Sensor-panel discrimination",
        "method_y": "AUPRC",
        "method_note": "B2 - B1 = +0.008",
        "dynamics_title": "Figure 5 | Event-time reachability deficits are visible, but not uniformly inference-admissible",
        "dynamics_y": "Reachability deficit vs matched baseline",
        "dynamics_x": "Hours from registered attack anchor",
        "post24": "first 24 h",
        "design_title": "Figure 2 | Registered outage schedules and held-out wartime events",
        "design_timeline": "A  Frozen event chronology and experimental role",
        "schedule_panel": "B  Calibration schedules (local time, final dispatch)",
        "schedule_x": "Local hour (Europe/Kyiv)",
        "schedule_cb": "Simultaneous outage queues",
        "attack_panel": "C  Held-out attack scope and impact",
        "attack_impact_x": "Maximum reachability deficit",
        "b_general_title": "Figure 4 | Power-specific B2 does not consistently strengthen held-out attack signals",
        "b_peak": "A  Maximum reachability deficit",
        "b_auc": "B  Cumulative deficit (AUC)",
        "b_t90": "C  Recovery time t90 (hours)",
        "b_general_note": "Paired within event; descriptive method sensitivity. Gray event fails the primary pretrend gate.",
        "b1_general": "B1 responsive panel",
        "b2_power": "B2 power-specific panel",
        "eb_profile_title": "Experiment B | Event-level impact and recovery profile",
        "eb_immediate": "A  Immediate deficit",
        "eb_maximum": "B  Maximum deficit",
        "eb_auc": "C  Cumulative deficit (AUC)",
        "eb_recovery": "D  Recovery t90 (hours)",
        "eb_anchor_title": "Experiment B | Sensitivity to shifting the registered anchor by ±6 hours",
        "eb_anchor_y": "Maximum reachability deficit",
        "eb_anchor_x": "Anchor shift (hours)",
        "eb_anchor_note": "A stable event should not disappear under a small, plausible anchor shift.",
        "eb_gate_title": "Experiment B | Which events support internal and external inference?",
        "eb_balance": "Matched balance",
        "eb_pretrend": "Pretrend",
        "eb_internal": "Internal inference",
        "eb_ioda": "IODA onset ≤6 h",
        "eb_pass": "pass",
        "eb_fail": "fail",
        "eb_matrix_note": "Only 1/6 events passes all four displayed gates; Sumy fails the primary pretrend gate.",
        "national": "national",
        "regional": "regional",
        "descriptive_short": "descriptive",
        "fig1": "Figure 1 | Temporal separation and the scheduled-outage calibration gate",
        "timeline": "A  Frozen study timeline",
        "train": "Planned-outage training",
        "valid": "Planned-outage validation",
        "attack": "Held-out energy attacks",
        "excluded": "excluded",
        "event": "B  Validation-event heterogeneity",
        "event_x": "Event-level ΔAUPRC (B2 - B1)",
        "pooled": "C  Preregistered pooled gate",
        "pooled_label": "Pooled ΔAUPRC",
        "gate": "Gate not passed",
        "fig2": "Figure 2 | Observable impact in held-out attacks and external concordance",
        "impact": "A  Internal active-measurement deficits",
        "impact_x": "Reachability deficit",
        "immediate": "Immediate",
        "maximum": "Maximum within event window",
        "admissible": "Inference-admissible",
        "descriptive": "Descriptive only",
        "external": "B  Internal vs independent IODA deficit",
        "internal_x": "Internal maximum deficit",
        "ioda_y": "IODA maximum paired deficit",
        "concordant": "Onset within 6 h",
        "delayed": "No onset within 6 h",
        "fig3": "Figure 6 | ASN-Admin1 fingerprints are weakly repeatable and not predictively validated",
        "repeat": "A  Cross-event rank repeatability (deficit AUC)",
        "rho": "Spearman ρ",
        "insufficient": "insufficient overlap",
        "prediction": "B  Rolling held-out prediction",
        "mae": "Event-equal MAE for deficit AUC (lower is better)",
        "history": "History model",
        "apparent": "41.7% apparent gain vs M3\npermutation p = 0.294",
        "fig4": "Figure 5 | Conditional secondary evidence: recovery debt and surviving paths",
        "auc": "A  Later deficit AUC",
        "t90": "B  Recovery time (t90)",
        "coef": "Coefficient (95% CI)",
        "residual": "Residual debt",
        "future": "Future placebo",
        "paths": "C  Same-target ASGeo shifts",
        "trace": "Minimum valid traces per phase",
        "fdr": "BH-FDR significant units",
        "conditional": "Same-target reached traces only",
        "s1": "Supplement S1 | Calibration sensitivity without retuning",
        "cluster": "A  Leave-one-cluster-out heterogeneity",
        "warning": "B  Official heat-warning exclusion",
        "warning_note": "Warning-window test only; not a continuous ERA5 adjustment",
        "s2": "Supplement S2 | Why the July 24 operator contrast is not inferential",
        "s3": "Supplement S3 | Independent IODA timing concordance is weak",
        "s4": "Supplement S4 | Conditional recovery-debt and surviving-path evidence",
        "did": "Difference-in-differences effect",
        "failed": "Not estimable: balance and pretrend gates failed",
        "cycles": "Only 2 measurement cycles in the contrast window",
    },
    "zh": {
        "design_flow_title": "图1 | 从计划停电到可证伪的网络韧性检验",
        "flow_schedule": "官方停电计划",
        "flow_schedule_sub": "日期 · 当地时段 · 队列强度",
        "flow_probe": "每两小时主动探测",
        "flow_probe_sub": "长期IP可达性序列",
        "flow_calibrate": "校准候选传感器",
        "flow_calibrate_sub": "B0、B1与供电特异B2比较",
        "flow_freeze": "留出检验前冻结",
        "flow_freeze_sub": "传感器规则 · 锚点 · 估计目标",
        "flow_attack": "留出的战时能源攻击",
        "flow_attack_sub": "影响 · 恢复 · 外部核验",
        "flow_fingerprint": "ASN × 一级行政区指纹",
        "flow_fingerprint_sub": "重复性 · 未来事件预测",
        "flow_observed": "直接观测 / 精确登记",
        "flow_inferred": "需要实证检验的推断",
        "flow_warning": "不预设“IP不可达”等同于停电；每一条箭头都是必须通过的证据门。",
        "overview_title": "图2 | 预设推断链的实证闭环",
        "overview_q1": "1  校准供电敏感传感器",
        "overview_q2": "2  量化留出能源攻击",
        "overview_q3": "3  检验ASN-地区韧性指纹",
        "overview_e1": "ΔAUPRC = +0.008\n95%置信区间跨0；p = 0.323",
        "overview_e2": "内部设计5/6可推断\nIODA仅1/6在6小时内出现异常",
        "overview_e3": "重复性ρ = 0.179；ICC = 0\n预测置换p = 0.294",
        "not_supported": "不支持",
        "partial": "部分支持",
        "conditional_status": "条件性证据",
        "overview_secondary": "次要证据（不能挽救主链）：恢复债务→缺口AUC，p = 0.016；同目标ASGeo变化，6/52个单元。",
        "overview_bottom": "正向推断链未成立：计划停电没有验证B2传感器，\nASN-地区指纹也没有表现出稳定重复性和预测性。\n实验以负向/边界性结论完成科学闭环。",
        "cal_title": "图3 | 计划停电校准方向为正，但未通过预注册门槛",
        "methods": "A  传感器面板区分能力",
        "method_y": "AUPRC",
        "method_note": "B2 - B1 = +0.008",
        "dynamics_title": "图5 | 多次攻击出现事件时点缺口，但并非全部可推断",
        "dynamics_y": "相对匹配基线的可达性缺口",
        "dynamics_x": "相对登记攻击锚点的小时数",
        "post24": "攻击后24小时",
        "design_title": "图2 | 登记停电计划与留出的战时能源事件",
        "design_timeline": "A  冻结事件时间线与实验角色",
        "schedule_panel": "B  校准事件的最终调度计划（当地时间）",
        "schedule_x": "当地小时（Europe/Kyiv）",
        "schedule_cb": "同时停电队列数",
        "attack_panel": "C  留出攻击：登记范围与观测影响",
        "attack_impact_x": "最大可达性缺口",
        "b_general_title": "图4 | 供电特异B2没有在留出攻击中稳定增强信号",
        "b_peak": "A  最大可达性缺口",
        "b_auc": "B  累计缺口（AUC）",
        "b_t90": "C  恢复时间t90（小时）",
        "b_general_note": "同一事件内配对比较，仅作为方法敏感性；灰色事件未通过主要预趋势门。",
        "b1_general": "B1一般响应性面板",
        "b2_power": "B2供电特异面板",
        "eb_profile_title": "实验B | 各轮攻击的影响强度与恢复概览",
        "eb_immediate": "A  即时缺口",
        "eb_maximum": "B  最大缺口",
        "eb_auc": "C  累计缺口（AUC）",
        "eb_recovery": "D  恢复时间t90（小时）",
        "eb_anchor_title": "实验B | 登记锚点前后平移±6小时的敏感性",
        "eb_anchor_y": "最大可达性缺口",
        "eb_anchor_x": "锚点平移（小时）",
        "eb_anchor_note": "稳定的事件结论不应因小幅、合理的锚点平移而消失。",
        "eb_gate_title": "实验B | 哪些事件同时支持内部推断和外部验证？",
        "eb_balance": "匹配平衡",
        "eb_pretrend": "预趋势",
        "eb_internal": "内部可推断",
        "eb_ioda": "IODA 6小时内异常",
        "eb_pass": "通过",
        "eb_fail": "未通过",
        "eb_matrix_note": "六轮事件中仅1轮同时通过图示四道门；Sumy未通过主要预趋势门。",
        "national": "全国",
        "regional": "区域",
        "descriptive_short": "仅描述",
        "fig1": "图1 | 时间隔离与计划停电校准门",
        "timeline": "A  冻结研究时间线",
        "train": "计划停电训练",
        "valid": "计划停电验证",
        "attack": "留出能源攻击",
        "excluded": "排除",
        "event": "B  验证事件异质性",
        "event_x": "事件级 ΔAUPRC（B2 - B1）",
        "pooled": "C  预注册总体门槛",
        "pooled_label": "总体 ΔAUPRC",
        "gate": "校准门未通过",
        "fig2": "图2 | 留出攻击的可观测影响与外部一致性",
        "impact": "A  内部主动测量缺口",
        "impact_x": "可达性缺口",
        "immediate": "即时缺口",
        "maximum": "事件窗口最大缺口",
        "admissible": "可推断",
        "descriptive": "仅描述",
        "external": "B  内部测量与独立 IODA 缺口",
        "internal_x": "内部最大缺口",
        "ioda_y": "IODA 最大配对缺口",
        "concordant": "6小时内出现异常",
        "delayed": "6小时内无异常",
        "fig3": "图6 | ASN-地区指纹重复性弱，预测未获验证",
        "repeat": "A  跨事件等级重复性（缺口 AUC）",
        "rho": "Spearman ρ",
        "insufficient": "重叠不足",
        "prediction": "B  滚动留出预测",
        "mae": "缺口 AUC 的事件等权 MAE（越低越好）",
        "history": "历史模型",
        "apparent": "相对 M3 表观改善 41.7%\n置换检验 p = 0.294",
        "fig4": "图5 | 条件性次要证据：恢复债务与存活路径",
        "auc": "A  后续缺口 AUC",
        "t90": "B  恢复时间（t90）",
        "coef": "回归系数（95%置信区间）",
        "residual": "基线残差化债务",
        "future": "未来债务安慰剂",
        "paths": "C  同目标 ASGeo 路径变化",
        "trace": "每阶段最少有效 Trace 数",
        "fdr": "通过 BH-FDR 的单元数",
        "conditional": "仅限成功到达同一目标的 Trace",
        "s1": "补充图S1 | 不调参的校准敏感性",
        "cluster": "A  留一独立事件簇异质性",
        "warning": "B  排除官方高温预警窗口",
        "warning_note": "仅为预警窗口检验，不等同于 ERA5 连续温度调整",
        "s2": "补充图S2 | 7月24日运营商对照为何不可推断",
        "s3": "补充图S3 | 独立IODA信号的时序一致性较弱",
        "s4": "补充图S4 | 条件性恢复债务与存活路径证据",
        "did": "双重差分效应",
        "failed": "不可估计：平衡与预趋势门均未通过",
        "cycles": "对照窗口仅包含 2 个测量周期",
    },
}


EVENT_SHORT = {
    "E2024_0707_PLANNED": "07/07",
    "E2024_0720_PLANNED": "07/20",
    "E2024_0728_PLANNED": "07/28",
    "E2024_0819_PLANNED": "08/19",
    "E2024_0820_PLANNED": "08/20",
    "E2024_0821_PLANNED": "08/21",
    "E2024_1209_PLANNED": "12/09",
    "E2024_0826_ATTACK": "08/26",
    "E2024_0917_SUMY": "09/17",
    "E2024_1117_ATTACK": "11/17",
    "E2024_1128_ATTACK": "11/28",
    "E2024_1213_ATTACK": "12/13",
    "E2024_1225_ATTACK": "12/25",
}

MAIN_PAGE = (12.0, 6.8)
SUPP_PAGE = MAIN_PAGE


def manuscript_style(cfg, lang: str) -> None:
    """A fixed, reviewer-readable profile that survives PDF fit-to-page."""
    apply_style(cfg, lang)
    plt.rcParams.update({
        "font.size": 11,
        "axes.labelsize": 11,
        "axes.titlesize": 11.5,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "legend.fontsize": 9,
        "lines.linewidth": 1.7,
        "lines.markersize": 6,
        "savefig.bbox": None,
    })


def read(tables: Path, name: str) -> pd.DataFrame:
    path = tables / name
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def panel_label(ax, label: str) -> None:
    ax.set_title(label, loc="left", fontsize=11.5, fontweight="bold", pad=10)


def clean_axis(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def fig_study_design(cfg, tables: Path, lang: str):
    """Plain-language schematic for the introduction/methods, with no causal shortcut."""
    tx = TEXT[lang]
    manuscript_style(cfg, lang)
    fig, ax = plt.subplots(figsize=MAIN_PAGE)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    def box(x, y, w, h, title, subtitle, fc, ec):
        patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=.012,rounding_size=.012",
                               facecolor=fc, edgecolor=ec, linewidth=1.35)
        ax.add_patch(patch)
        ax.text(x+w/2, y+h*.63, title, ha="center", va="center", fontsize=11,
                fontweight="bold", color="0.15")
        ax.text(x+w/2, y+h*.31, subtitle, ha="center", va="center", fontsize=9.5,
                color="0.30")
        return (x, y, w, h)

    # Registered/observed inputs.
    ax.text(.19, .88, tx["flow_observed"], ha="center", fontsize=10.5,
            fontweight="bold", color=PALETTE[0])
    b1 = box(.045, .62, .29, .18, tx["flow_schedule"], tx["flow_schedule_sub"],
             "#E8F2F8", PALETTE[0])
    b2 = box(.045, .35, .29, .18, tx["flow_probe"], tx["flow_probe_sub"],
             "#E8F2F8", PALETTE[0])

    # The inferential chain.
    ax.text(.69, .88, tx["flow_inferred"], ha="center", fontsize=10.5,
            fontweight="bold", color=PALETTE[1])
    b3 = box(.405, .57, .23, .20, tx["flow_calibrate"], tx["flow_calibrate_sub"],
             "#FFF2D9", PALETTE[1])
    b4 = box(.405, .28, .23, .17, tx["flow_freeze"], tx["flow_freeze_sub"],
             "#F2F2F2", "0.45")
    b5 = box(.705, .57, .25, .20, tx["flow_attack"], tx["flow_attack_sub"],
             "#FFF2D9", PALETTE[1])
    b6 = box(.705, .28, .25, .17, tx["flow_fingerprint"], tx["flow_fingerprint_sub"],
             "#F9E3E3", "#B54A4A")

    def arrow(x1, y1, x2, y2, color="0.42"):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                    mutation_scale=13, linewidth=1.35, color=color))

    arrow(b1[0]+b1[2], b1[1]+b1[3]/2, b3[0], b3[1]+b3[3]*.68)
    arrow(b2[0]+b2[2], b2[1]+b2[3]/2, b3[0], b3[1]+b3[3]*.32)
    arrow(b3[0]+b3[2]/2, b3[1], b4[0]+b4[2]/2, b4[1]+b4[3])
    arrow(b4[0]+b4[2], b4[1]+b4[3]/2, b5[0], b5[1]+b5[3]/2)
    arrow(b5[0]+b5[2]/2, b5[1], b6[0]+b6[2]/2, b6[1]+b6[3])

    ax.text(.5, .105, tx["flow_warning"], ha="center", va="center", fontsize=10.5,
            color="#8A3B3B",
            bbox={"boxstyle": "round,pad=.42", "fc": "#FAEEEE", "ec": "#B85C5C", "lw": 1})
    fig.suptitle(tx["design_flow_title"], fontsize=15, fontweight="bold", y=.96)
    fig.subplots_adjust(left=.025, right=.975, top=.90, bottom=.04)
    return fig


def fig_overview(cfg, tables: Path, lang: str):
    """A data-backed closure map: the missing visual link in the prior set."""
    tx = TEXT[lang]
    manuscript_style(cfg, lang)
    fig, ax = plt.subplots(figsize=MAIN_PAGE)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    xs = [.06, .365, .67]
    widths = [.265] * 3
    titles = [tx["overview_q1"], tx["overview_q2"], tx["overview_q3"]]
    evidence = [tx["overview_e1"], tx["overview_e2"], tx["overview_e3"]]
    verdicts = [tx["not_supported"], tx["partial"], tx["not_supported"]]
    fills = ["#F9E3E3", "#FFF2CC", "#F9E3E3"]
    edges = ["#B54A4A", "#B07A00", "#B54A4A"]
    for i, (x, w, title, ev, verdict, fill, edge) in enumerate(
            zip(xs, widths, titles, evidence, verdicts, fills, edges)):
        box = FancyBboxPatch((x, .39), w, .40, boxstyle="round,pad=.012,rounding_size=.015",
                             facecolor=fill, edgecolor=edge, linewidth=1.5)
        ax.add_patch(box)
        ax.text(x + w/2, .71, title, ha="center", va="center", fontsize=11.5,
                fontweight="bold", color="0.15")
        ax.text(x + w/2, .57, ev, ha="center", va="center", fontsize=10.5,
                linespacing=1.4, color="0.20")
        ax.text(x + w/2, .44, verdict, ha="center", va="center", fontsize=10.5,
                fontweight="bold", color=edge)
        if i < 2:
            arrow = FancyArrowPatch((x + w + .006, .59), (xs[i+1] - .006, .59),
                                    arrowstyle="-|>", mutation_scale=13,
                                    color="0.45", linewidth=1.2)
            ax.add_patch(arrow)
    ax.text(.5, .29, tx["overview_secondary"], ha="center", va="center", fontsize=10,
            color="#3579A8",
            bbox={"boxstyle": "round,pad=.4", "fc": "#E4EFF7", "ec": "#3579A8", "lw": 1})
    ax.text(.5, .13, tx["overview_bottom"], ha="center", va="center", fontsize=11,
            linespacing=1.45, color="0.15",
            bbox={"boxstyle": "round,pad=.55", "fc": "#F3F3F3", "ec": "0.55", "lw": 1})
    fig.suptitle(tx["overview_title"], fontsize=15, fontweight="bold", y=.96)
    fig.subplots_adjust(left=.025, right=.975, top=.90, bottom=.04)
    return fig


def fig_registered_timeline(cfg, tables: Path, lang: str):
    """Show treatment schedules and held-out attacks without implying IP-level outages."""
    tx = TEXT[lang]
    events = pd.read_csv(cfg.root / "config/event_registry_v2.csv")
    schedules = pd.read_csv(cfg.resource_path("schedule_registry"))
    attacks = read(tables, "exp_b_main_results.csv").sort_values("anchor_utc").copy()
    manuscript_style(cfg, lang)
    fig = plt.figure(figsize=MAIN_PAGE)
    gs = fig.add_gridspec(2, 2, height_ratios=[.72, 1.35], width_ratios=[1.38, 1],
                          hspace=.55, wspace=.42)

    # A: one frozen chronology, explicitly separating supervision from evaluation.
    ax = fig.add_subplot(gs[0, :])
    role_specs = [
        ("planned_train", 2, tx["train"], PALETTE[0], "o"),
        ("planned_valid", 1, tx["valid"], PALETTE[2], "s"),
        ("attack_national|attack_regional|blind_test|stress_test", 0,
         tx["attack"], PALETTE[1], "D"),
    ]
    start, end = pd.Timestamp("2024-06-22"), pd.Timestamp("2025-01-09")
    for role_expr, y, label, color, marker in role_specs:
        d = events[events.analysis_role.astype(str).str.contains(role_expr, regex=True)].copy()
        d["time"] = pd.to_datetime(d.primary_anchor_utc).dt.tz_localize(None)
        d = d[d.time.between(start, end)]
        ax.scatter(d.time, np.full(len(d), y), s=44, marker=marker, color=color,
                   edgecolor="white", linewidth=.6, zorder=3, label=label)
        august_group = {"E2024_0819_PLANNED", "E2024_0820_PLANNED", "E2024_0821_PLANNED"}
        for k, (_, row) in enumerate(d.iterrows()):
            if row.event_id in august_group:
                continue
            short = EVENT_SHORT.get(row.event_id, row.time.strftime("%m/%d"))
            if row.event_id == "E2024_1209_PLANNED":
                short += f" ({tx['excluded']})"
            ax.annotate(short, (row.time, y), xytext=(0, 9 if k % 2 == 0 else -13),
                        textcoords="offset points", ha="center",
                        va="bottom" if k % 2 == 0 else "top", fontsize=8.6)
        if role_expr == "planned_valid" and set(d.event_id).intersection(august_group):
            group_label = "08/19-21 (3 events)" if lang == "en" else "08/19-21（3个事件）"
            ax.annotate(group_label, (pd.Timestamp("2024-08-20"), y), xytext=(0, 9),
                        textcoords="offset points", ha="center", va="bottom", fontsize=8.6)
    ax.set_xlim(start, end); ax.set_ylim(-.55, 2.55); ax.set_yticks([])
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.grid(axis="x", alpha=.35)
    ax.legend(ncol=3, frameon=False, loc="upper center", bbox_to_anchor=(.5, -.20))
    panel_label(ax, tx["design_timeline"]); clean_axis(ax)

    # B: actual final schedule segments used for calibration, at interpretable hourly resolution.
    ax = fig.add_subplot(gs[1, 0])
    schedule_ids = ["E2024_0707_PLANNED", "E2024_0720_PLANNED", "E2024_0728_PLANNED",
                    "E2024_0819_PLANNED", "E2024_0820_PLANNED", "E2024_0821_PLANNED"]
    grid = np.zeros((len(schedule_ids), 48), dtype=float)
    for i, event_id in enumerate(schedule_ids):
        for _, row in schedules[schedules.event_id.eq(event_id)].iterrows():
            st = pd.Timestamp(str(row.local_start)[:19]); en = pd.Timestamp(str(row.local_end)[:19])
            base = st.normalize()
            lo = max(0, int(round((st - base).total_seconds() / 1800)))
            hi = min(48, int(round((en - base).total_seconds() / 1800)))
            grid[i, lo:hi] = float(row.queue_count)
    im = ax.imshow(grid, aspect="auto", interpolation="nearest", cmap="YlOrRd", vmin=0, vmax=3,
                   extent=[0, 24, len(schedule_ids)-.5, -.5])
    ax.set_xticks(np.arange(0, 25, 4)); ax.set_xlabel(tx["schedule_x"])
    ax.set_yticks(np.arange(len(schedule_ids)), [EVENT_SHORT[x] for x in schedule_ids])
    for y in np.arange(.5, len(schedule_ids), 1): ax.axhline(y, color="white", lw=.7)
    cb = fig.colorbar(im, ax=ax, fraction=.035, pad=.025, ticks=[0, 1, 2, 3])
    cb.set_label(tx["schedule_cb"])
    panel_label(ax, tx["schedule_panel"])

    # C: event identity, scope and measured magnitude; this is a compact Experiment-B index.
    ax = fig.add_subplot(gs[1, 1])
    attacks["short"] = attacks.event_id.map(EVENT_SHORT)
    y = np.arange(len(attacks))
    colors = [PALETTE[1] if x == 1 else "0.55" for x in attacks.inference_admissible]
    ax.hlines(y, 0, attacks.max_deficit, color="0.80", lw=1.4)
    ax.scatter(attacks.max_deficit, y, color=colors, s=48, zorder=3)
    labels = []
    for _, row in attacks.iterrows():
        scope = tx["national"] if row.treated == "ALL" else tx["regional"]
        if row.inference_admissible != 1: scope += f"; {tx['descriptive_short']}"
        labels.append(f"{row.short}  {scope}")
    ax.set_yticks(y, labels); ax.invert_yaxis(); ax.axvline(0, color="0.25", lw=.8)
    ax.set_xlabel(tx["attack_impact_x"]); ax.grid(axis="x", alpha=.35)
    panel_label(ax, tx["attack_panel"]); clean_axis(ax)

    fig.suptitle(tx["design_title"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.90, bottom=.12, left=.105, right=.975)
    return fig


def fig_calibration(cfg, tables: Path, lang: str):
    tx = TEXT[lang]
    metrics = read(tables, "exp_a_event_metrics.csv").copy()
    summary = read(tables, "exp_a_summary.csv").iloc[0]
    methods = read(tables, "exp_a_summary.csv")
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(1, 3, figsize=MAIN_PAGE,
                             gridspec_kw={"width_ratios": [.82, 1.3, 1]})
    ax = axes[0]
    m = methods.set_index("method").reindex(["B0", "B1", "B2"]).reset_index()
    colors = ["0.70", PALETTE[0], PALETTE[2]]
    bars = ax.bar(m.method, m.auprc, color=colors, width=.62)
    for bar, val in zip(bars, m.auprc):
        ax.text(bar.get_x() + bar.get_width()/2, val + .008, f"{val:.3f}",
                ha="center", va="bottom", fontsize=9.5)
    ax.set_ylim(0, max(m.auprc) * 1.24); ax.set_ylabel(tx["method_y"])
    ax.text(.5, .92, tx["method_note"], transform=ax.transAxes, ha="center",
            fontsize=10, color="#B54A4A")
    ax.grid(axis="y", alpha=.35); panel_label(ax, tx["methods"]); clean_axis(ax)

    ax = axes[1]
    metrics["short"] = metrics.event_id.map(EVENT_SHORT)
    metrics = metrics.sort_values("delta_b2_vs_b1")
    y = np.arange(len(metrics)); eligible = metrics.publication_eligible.eq(1)
    ax.barh(y, metrics.delta_b2_vs_b1,
            color=[PALETTE[2] if ok else "0.72" for ok in eligible], height=.62)
    labels = [s if ok else f"{s} ({tx['excluded']})" for s, ok in zip(metrics.short, eligible)]
    ax.set_yticks(y, labels); ax.axvline(0, color="0.2", lw=.9)
    ax.set_xlabel(tx["event_x"]); ax.grid(axis="x", alpha=.4)
    panel_label(ax, tx["event"]); clean_axis(ax)

    ax = axes[2]
    point, lo, hi = float(summary.delta_b2_vs_b1), float(summary.delta_ci_lo), float(summary.delta_ci_hi)
    ax.errorbar(point, 0, xerr=[[point-lo], [hi-point]], fmt="o", ms=8,
                capsize=6, color=PALETTE[2], lw=1.8)
    ax.axvline(0, color="0.2", lw=.9); ax.set_yticks([0], [tx["pooled_label"]])
    pad = max(abs(lo), abs(hi)) * .18; ax.set_xlim(lo-pad, hi+pad); ax.set_ylim(-.65, .65)
    ax.grid(axis="x", alpha=.4)
    ax.text(.5, .19, f"{tx['gate']}\n95% CI [{lo:+.3f}, {hi:+.3f}]\np = {float(summary.permutation_p):.3f}",
            transform=ax.transAxes, ha="center", va="center", fontsize=10.5,
            bbox={"boxstyle": "round,pad=.35", "fc": "#F6E8E8", "ec": "#B85C5C", "lw": .9})
    panel_label(ax, tx["pooled"]); clean_axis(ax)
    fig.suptitle(tx["cal_title"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.82, bottom=.16, left=.075, right=.98, wspace=.48)
    return fig


def fig_attack_sensor_generalization(cfg, tables: Path, lang: str):
    """Direct Experiment-B test: does B2 improve held-out attack measurement over B1?"""
    tx = TEXT[lang]
    d = read(tables, "exp_b_method_sensitivity.csv").copy()
    events = ["E2024_0826_ATTACK", "E2024_0917_SUMY", "E2024_1117_ATTACK",
              "E2024_1128_ATTACK", "E2024_1213_ATTACK", "E2024_1225_ATTACK"]
    d = d[d.event_id.isin(events) & d.sensor_method.isin(["B1", "B2"])]
    wide = d.pivot(index="event_id", columns="sensor_method",
                   values=["max_deficit", "deficit_auc_full", "t90_h"]).reindex(events)
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(1, 3, figsize=MAIN_PAGE, sharey=True,
                             gridspec_kw={"width_ratios": [1.05, 1.05, 1]})
    specs = [("max_deficit", tx["b_peak"]),
             ("deficit_auc_full", tx["b_auc"]),
             ("t90_h", tx["b_t90"])]
    y = np.arange(len(events))
    labels = []
    for event_id in events:
        label = EVENT_SHORT[event_id]
        if event_id == "E2024_0917_SUMY": label += f"  |  {tx['descriptive_short']}"
        labels.append(label)
    for j, (metric, title) in enumerate(specs):
        ax = axes[j]
        b1 = wide[(metric, "B1")].to_numpy(float)
        b2 = wide[(metric, "B2")].to_numpy(float)
        for i, (v1, v2) in enumerate(zip(b1, b2)):
            line_color = "0.70" if events[i] != "E2024_0917_SUMY" else "0.82"
            ax.plot([v1, v2], [i, i], color=line_color, lw=1.8, zorder=1)
            alpha = 1 if events[i] != "E2024_0917_SUMY" else .48
            ax.scatter(v1, i, s=48, marker="o", color=PALETTE[0], alpha=alpha, zorder=3)
            ax.scatter(v2, i, s=54, marker="D", color=PALETTE[1], alpha=alpha, zorder=3)
        ax.set_yticks(y, labels)
        if j > 0:
            ax.tick_params(axis="y", labelleft=False)
        ax.grid(axis="x", alpha=.35); clean_axis(ax)
        panel_label(ax, title)
        if metric != "t90_h": ax.axvline(0, color="0.25", lw=.8)
    axes[0].invert_yaxis()
    axes[0].scatter([], [], color=PALETTE[0], marker="o", label=tx["b1_general"])
    axes[0].scatter([], [], color=PALETTE[1], marker="D", label=tx["b2_power"])
    axes[0].legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -.14), ncol=2)
    fig.text(.98, .055, tx["b_general_note"], ha="right", fontsize=9.2, color="0.38")
    fig.suptitle(tx["b_general_title"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.82, bottom=.21, left=.13, right=.98, wspace=.30)
    return fig


def fig_attack_outcome_profile(cfg, tables: Path, lang: str):
    """Compact, directly comparable overview of the four primary event outcomes."""
    tx = TEXT[lang]
    d = read(tables, "exp_b_main_results.csv").sort_values("anchor_utc").copy()
    d["short"] = d.event_id.map(EVENT_SHORT)
    d.loc[d.inference_admissible.ne(1), "short"] += f"  |  {tx['descriptive_short']}"
    specs = [("immediate_drop", tx["eb_immediate"]), ("max_deficit", tx["eb_maximum"]),
             ("deficit_auc_full", tx["eb_auc"]), ("t90_h", tx["eb_recovery"])]
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(1, 4, figsize=MAIN_PAGE, sharey=True)
    y = np.arange(len(d))
    colors = [PALETTE[0] if ok == 1 else "0.58" for ok in d.inference_admissible]
    for j, (metric, title) in enumerate(specs):
        ax = axes[j]; values = d[metric].to_numpy(float)
        ax.hlines(y, 0, values, color="0.82", lw=1.3)
        ax.scatter(values, y, color=colors, s=48, zorder=3)
        ax.set_yticks(y, d.short)
        if j > 0: ax.tick_params(axis="y", labelleft=False)
        ax.grid(axis="x", alpha=.35); clean_axis(ax); panel_label(ax, title)
        if metric != "t90_h": ax.axvline(0, color="0.25", lw=.8)
    axes[0].invert_yaxis()
    fig.suptitle(tx["eb_profile_title"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.82, bottom=.13, left=.13, right=.98, wspace=.30)
    return fig


def fig_attack_anchor_sensitivity(cfg, tables: Path, lang: str):
    """Show whether Experiment-B magnitude depends on a narrowly chosen anchor."""
    tx = TEXT[lang]
    d = read(tables, "exp_b_anchor_sensitivity.csv")
    events = ["E2024_0826_ATTACK", "E2024_0917_SUMY", "E2024_1117_ATTACK",
              "E2024_1128_ATTACK", "E2024_1213_ATTACK", "E2024_1225_ATTACK"]
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(2, 3, figsize=MAIN_PAGE, sharex=True, sharey=True)
    for ax, event_id in zip(axes.flat, events):
        e = d[d.event_id.eq(event_id)].sort_values("anchor_shift_h")
        color = PALETTE[0] if event_id != "E2024_0917_SUMY" else "0.55"
        ax.plot(e.anchor_shift_h, e.max_deficit, marker="o", color=color, lw=1.7)
        ax.axvline(0, color=PALETTE[1], ls="--", lw=1.1)
        ax.set_title(EVENT_SHORT[event_id] + (f" | {tx['descriptive_short']}" if event_id == "E2024_0917_SUMY" else ""),
                     loc="left", fontsize=10.5, fontweight="bold")
        ax.set_xticks([-6, -4, -2, 0, 2, 4, 6]); ax.grid(True, alpha=.3); clean_axis(ax)
    fig.supylabel(tx["eb_anchor_y"], x=.035, fontsize=11)
    fig.supxlabel(tx["eb_anchor_x"], y=.07, fontsize=11)
    fig.text(.98, .045, tx["eb_anchor_note"], ha="right", fontsize=9.2, color="0.38")
    fig.suptitle(tx["eb_anchor_title"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.85, bottom=.16, left=.09, right=.98, hspace=.34, wspace=.22)
    return fig


def fig_attack_evidence_matrix(cfg, tables: Path, lang: str):
    """Reviewer-readable gate matrix joining design admissibility and external timing."""
    tx = TEXT[lang]
    d = read(tables, "exp_b_main_results.csv").sort_values("anchor_utc").copy()
    ext = read(tables, "sens_ioda_external_validation.csv")
    d = d.merge(ext[["event_id", "temporal_concordant_6h"]], on="event_id", how="left")
    matrix = np.column_stack([d.matching_balance_ok.eq(1), d.pretrend_equivalent.eq(True),
                              d.inference_admissible.eq(1), d.temporal_concordant_6h.eq(1)]).astype(int)
    manuscript_style(cfg, lang)
    fig, ax = plt.subplots(figsize=MAIN_PAGE)
    ax.set_xlim(-.5, 3.5); ax.set_ylim(len(d)-.5, -.5)
    for i in range(len(d)):
        for j in range(4):
            passed = matrix[i, j] == 1
            ax.scatter(j, i, s=620, marker="s", color="#DDEFE3" if passed else "#F6DEDE",
                       edgecolor="#4B8B62" if passed else "#B85C5C", linewidth=1.2)
            ax.text(j, i, tx["eb_pass"] if passed else tx["eb_fail"], ha="center", va="center",
                    fontsize=10.5, fontweight="bold",
                    color="#287044" if passed else "#A33F3F")
    ax.set_xticks(range(4), [tx["eb_balance"], tx["eb_pretrend"], tx["eb_internal"], tx["eb_ioda"]])
    ax.xaxis.tick_top(); ax.tick_params(axis="x", length=0, pad=12)
    ax.set_yticks(np.arange(len(d)), [EVENT_SHORT[x] for x in d.event_id])
    ax.tick_params(axis="y", length=0, pad=10)
    for spine in ax.spines.values(): spine.set_visible(False)
    ax.text(.5, -.12, tx["eb_matrix_note"], transform=ax.transAxes, ha="center", fontsize=10,
            color="#8A3B3B")
    fig.suptitle(tx["eb_gate_title"], fontsize=14, fontweight="bold", y=.965)
    fig.subplots_adjust(top=.77, bottom=.19, left=.19, right=.94)
    return fig


def fig_attack_dynamics(cfg, tables: Path, lang: str):
    tx = TEXT[lang]
    curves = read(tables, "f4_event_study.csv")
    events = ["E2024_0826_ATTACK", "E2024_0917_SUMY", "E2024_1117_ATTACK",
              "E2024_1128_ATTACK", "E2024_1213_ATTACK", "E2024_1225_ATTACK"]
    curves = curves[curves.event_id.isin(events) & curves.rel_h.between(-24, 72)].copy()
    curves["deficit"] = -curves.effect
    curves["deficit_lo"] = -curves.ci_hi
    curves["deficit_hi"] = -curves.ci_lo
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(2, 3, figsize=MAIN_PAGE, sharex=True, sharey=True)
    for ax, event_id in zip(axes.flat, events):
        d = curves[curves.event_id.eq(event_id)].sort_values("rel_h")
        if d.empty:
            ax.set_visible(False); continue
        x = d.rel_h.to_numpy(float); y = d.deficit.to_numpy(float)
        lo = d.deficit_lo.to_numpy(float); hi = d.deficit_hi.to_numpy(float)
        admissible = int(d.inference_admissible.iloc[0]) == 1
        color = PALETTE[0] if admissible else "0.48"
        ax.axvspan(0, 24, color=PALETTE[1], alpha=.08)
        ax.fill_between(x, lo, hi, color=color, alpha=.15, linewidth=0)
        ax.plot(x, y, color=color, lw=1.8)
        ax.axvline(0, color=PALETTE[1], ls="--", lw=1.2)
        ax.axhline(0, color="0.35", ls=":", lw=1)
        status = tx["admissible"] if admissible else tx["descriptive"]
        ax.set_title(f"{EVENT_SHORT[event_id]}  |  {status}", loc="left", fontsize=10.5, fontweight="bold")
        ax.set_xticks([-24, 0, 24, 48, 72]); ax.grid(True, alpha=.3); clean_axis(ax)
    axes[0, 0].text(12, axes[0, 0].get_ylim()[1] * .82, tx["post24"],
                    ha="center", fontsize=8.8, color=PALETTE[1])
    fig.supylabel(tx["dynamics_y"], x=.035, fontsize=11)
    fig.supxlabel(tx["dynamics_x"], y=.055, fontsize=11)
    fig.suptitle(tx["dynamics_title"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.86, bottom=.14, left=.09, right=.98, hspace=.34, wspace=.22)
    return fig


def fig1(cfg, tables: Path, lang: str):
    tx = TEXT[lang]
    events = pd.read_csv(cfg.root / "config/event_registry_v2.csv")
    metrics = read(tables, "exp_a_event_metrics.csv").copy()
    summary = read(tables, "exp_a_summary.csv").iloc[0]
    manuscript_style(cfg, lang)
    fig = plt.figure(figsize=MAIN_PAGE)
    gs = fig.add_gridspec(2, 2, height_ratios=[0.72, 1.28], width_ratios=[1.35, 1],
                          hspace=.48, wspace=.42)
    ax0 = fig.add_subplot(gs[0, :])
    roles = [("planned_train", 2, tx["train"], PALETTE[0], "o"),
             ("planned_valid", 1, tx["valid"], PALETTE[2], "s"),
             ("attack_national|attack_regional|blind_test|stress_test", 0,
              tx["attack"], PALETTE[1], "D")]
    start, end = pd.Timestamp("2024-06-22"), pd.Timestamp("2025-01-09")
    for role_expr, y, label, color, marker in roles:
        mask = events.analysis_role.astype(str).str.contains(role_expr, regex=True)
        d = events[mask].copy()
        d["time"] = pd.to_datetime(d.outage_start_utc)
        d = d[(d.time >= start) & (d.time <= end)]
        ax0.scatter(d.time, np.full(len(d), y), s=42, marker=marker, color=color,
                    edgecolor="white", linewidth=.6, zorder=3, label=label)
        grouped_august = {"E2024_0819_PLANNED", "E2024_0820_PLANNED", "E2024_0821_PLANNED"}
        offsets = [0.18 if i % 2 == 0 else -0.26 for i in range(len(d))]
        for (_, row), off in zip(d.iterrows(), offsets):
            if row.event_id in grouped_august:
                continue
            short = EVENT_SHORT.get(row.event_id, row.time.strftime("%m/%d"))
            if row.event_id == "E2024_1209_PLANNED":
                short += f" ({tx['excluded']})"
            ax0.text(row.time, y + off, short, ha="center",
                     va="bottom" if off > 0 else "top", fontsize=9.2,
                     color="0.25")
        if role_expr == "planned_valid":
            group_label = "08/19-21 (3 events)" if lang == "en" else "08/19-21（3个事件）"
            ax0.annotate(group_label, (pd.Timestamp("2024-08-20"), y), xytext=(0, 12),
                         textcoords="offset points", ha="center", va="bottom",
                         fontsize=9.2, color="0.25")
    ax0.set_xlim(start, end); ax0.set_ylim(-.55, 2.55); ax0.set_yticks([])
    ax0.xaxis.set_major_locator(mdates.MonthLocator())
    ax0.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax0.tick_params(axis="x", labelsize=9.5); ax0.grid(axis="x", alpha=.35)
    ax0.legend(ncol=3, loc="upper center", bbox_to_anchor=(.5, -0.20), frameon=False)
    panel_label(ax0, tx["timeline"]); clean_axis(ax0)

    ax1 = fig.add_subplot(gs[1, 0])
    metrics["short"] = metrics.event_id.map(EVENT_SHORT)
    metrics = metrics.sort_values("delta_b2_vs_b1")
    y = np.arange(len(metrics))
    eligible = metrics.publication_eligible.eq(1)
    colors = [PALETTE[2] if ok else "0.72" for ok in eligible]
    ax1.barh(y, metrics.delta_b2_vs_b1, color=colors, height=.62)
    labels = [s if ok else f"{s} ({tx['excluded']})" for s, ok in zip(metrics.short, eligible)]
    ax1.set_yticks(y, labels); ax1.axvline(0, color="0.2", lw=.9)
    ax1.set_xlabel(tx["event_x"]); ax1.grid(axis="x", alpha=.4)
    panel_label(ax1, tx["event"]); clean_axis(ax1)

    ax2 = fig.add_subplot(gs[1, 1])
    point, lo, hi = float(summary.delta_b2_vs_b1), float(summary.delta_ci_lo), float(summary.delta_ci_hi)
    ax2.errorbar(point, 0, xerr=[[point - lo], [hi - point]], fmt="o", ms=7,
                 capsize=5, color=PALETTE[2], lw=1.5)
    ax2.axvline(0, color="0.2", lw=.9); ax2.set_yticks([0], [tx["pooled_label"]])
    pad = max(abs(lo), abs(hi)) * .18
    ax2.set_xlim(lo - pad, hi + pad); ax2.set_ylim(-.65, .65); ax2.grid(axis="x", alpha=.4)
    ax2.text(.5, .18, f"{tx['gate']}\n95% CI [{lo:+.3f}, {hi:+.3f}]\np = {float(summary.permutation_p):.3f}",
             transform=ax2.transAxes, ha="center", va="center", fontsize=10,
             bbox={"boxstyle": "round,pad=.35", "fc": "#F6E8E8", "ec": "#B85C5C", "lw": .8})
    panel_label(ax2, tx["pooled"]); clean_axis(ax2)
    fig.suptitle(tx["fig1"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.92, bottom=.09, left=.10, right=.98)
    return fig


def fig2(cfg, tables: Path, lang: str):
    tx = TEXT[lang]
    internal = read(tables, "exp_b_main_results.csv").copy()
    external = read(tables, "sens_ioda_external_validation.csv")
    d = internal.merge(external[["event_id", "relative_deficit", "temporal_concordant_6h"]],
                       on="event_id", how="inner").sort_values("anchor_utc")
    d["short"] = d.event_id.map(EVENT_SHORT)
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(1, 2, figsize=MAIN_PAGE, gridspec_kw={"width_ratios": [1.2, 1]})
    ax = axes[0]; y = np.arange(len(d))
    for i, row in d.reset_index(drop=True).iterrows():
        ax.plot([row.immediate_drop, row.max_deficit], [i, i], color="0.72", lw=1.5, zorder=1)
        face = PALETTE[0] if row.inference_admissible == 1 else "white"
        ax.scatter(row.immediate_drop, i, marker="o", s=42, facecolor=face,
                   edgecolor=PALETTE[0], linewidth=1.2, zorder=3)
        ax.scatter(row.max_deficit, i, marker="s", s=46,
                   facecolor=PALETTE[1] if row.inference_admissible == 1 else "white",
                   edgecolor=PALETTE[1], linewidth=1.2, zorder=3)
    suffix = [tx["admissible"] if x == 1 else tx["descriptive"] for x in d.inference_admissible]
    ax.set_yticks(y, [f"{a}  |  {b}" for a, b in zip(d.short, suffix)])
    ax.invert_yaxis(); ax.axvline(0, color="0.2", lw=.8); ax.set_xlabel(tx["impact_x"])
    ax.grid(axis="x", alpha=.4); panel_label(ax, tx["impact"]); clean_axis(ax)
    ax.scatter([], [], marker="o", color=PALETTE[0], label=tx["immediate"])
    ax.scatter([], [], marker="s", color=PALETTE[1], label=tx["maximum"])
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(.5, -.16),
              fontsize=9, ncol=2)

    ax = axes[1]
    for _, row in d.iterrows():
        filled = row.temporal_concordant_6h == 1
        ax.scatter(row.max_deficit, row.relative_deficit, s=55, marker="o",
                   facecolor=PALETTE[2] if filled else "white", edgecolor=PALETTE[2], lw=1.4)
        ax.annotate(row.short, (row.max_deficit, row.relative_deficit), xytext=(4, 4),
                    textcoords="offset points", fontsize=9.2)
    lim = max(d.max_deficit.max(), d.relative_deficit.max()) * 1.12
    ax.plot([0, lim], [0, lim], "--", color="0.65", lw=.8)
    rho, p = spearmanr(d.max_deficit, d.relative_deficit)
    ax.text(.04, .96, f"Spearman ρ = {rho:.2f}\np = {p:.3f}; n = {len(d)}",
            transform=ax.transAxes, va="top", fontsize=10)
    ax.set_xlim(-.005, lim); ax.set_ylim(-.005, lim)
    ax.set_xlabel(tx["internal_x"]); ax.set_ylabel(tx["ioda_y"])
    ax.grid(True, alpha=.35); panel_label(ax, tx["external"]); clean_axis(ax)
    ax.scatter([], [], facecolor=PALETTE[2], edgecolor=PALETTE[2], label=tx["concordant"])
    ax.scatter([], [], facecolor="white", edgecolor=PALETTE[2], label=tx["delayed"])
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(.5, -.16),
              fontsize=9, ncol=2)
    fig.suptitle(tx["fig2"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.86, bottom=.23, left=.13, right=.98, wspace=.35)
    return fig


def fig3(cfg, tables: Path, lang: str):
    tx = TEXT[lang]
    repeat = read(tables, "exp_c_repeatability.csv")
    repeat = repeat[repeat.target.eq("deficit_auc_full")]
    events = ["E2024_0826_ATTACK", "E2024_1117_ATTACK", "E2024_1128_ATTACK",
              "E2024_1213_ATTACK", "E2024_1225_ATTACK"]
    mat = np.full((len(events), len(events)), np.nan)
    np.fill_diagonal(mat, 1.0)
    for _, row in repeat.iterrows():
        if row.event_a in events and row.event_b in events and row.admissible == 1:
            i, j = events.index(row.event_a), events.index(row.event_b)
            mat[i, j] = mat[j, i] = row.spearman_rho
    perf = read(tables, "f8_model_perf.csv")
    perf = perf[(perf.target.eq("deficit_auc_full")) & perf.event_id.eq("EVENT_EQUAL")].copy()
    order = ["M0_global", "M1_admin1", "M2_asn", "M3_group", "M4_ridge_history", "M5_gbdt_history"]
    perf = perf.set_index("model").reindex(order).reset_index()
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(1, 2, figsize=MAIN_PAGE, gridspec_kw={"width_ratios": [1.08, 1]})
    ax = axes[0]
    masked = np.ma.masked_invalid(mat)
    cmap = plt.get_cmap("RdBu_r").copy(); cmap.set_bad("#E7E7E7")
    im = ax.imshow(masked, vmin=-1, vmax=1, cmap=cmap)
    labels = [EVENT_SHORT[e] for e in events]
    ax.set_xticks(np.arange(len(events)), labels, rotation=40, ha="right")
    ax.set_yticks(np.arange(len(events)), labels)
    for i in range(len(events)):
        for j in range(len(events)):
            if np.isfinite(mat[i, j]):
                color = "white" if abs(mat[i, j]) > .55 else "0.15"
                ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=10, color=color)
            else:
                ax.text(j, i, "-", ha="center", va="center", fontsize=10, color="0.55")
    cb = fig.colorbar(im, ax=ax, fraction=.046, pad=.04); cb.set_label(tx["rho"])
    panel_label(ax, tx["repeat"])

    ax = axes[1]; y = np.arange(len(perf))
    colors = [PALETTE[2] if m == "M4_ridge_history" else "0.65" for m in perf.model]
    ax.scatter(perf.mae, y, s=[58 if m == "M4_ridge_history" else 38 for m in perf.model],
               color=colors, zorder=3)
    ax.hlines(y, 0, perf.mae, color="0.82", lw=1)
    ax.set_yticks(y, [m.replace("_", " ") for m in perf.model]); ax.invert_yaxis()
    ax.set_xlim(left=0); ax.set_xlabel(tx["mae"]); ax.grid(axis="x", alpha=.4)
    ax.text(.98, .96, tx["apparent"], transform=ax.transAxes, ha="right", va="top",
            fontsize=10, bbox={"boxstyle": "round,pad=.3", "fc": "#F6E8E8", "ec": "#B85C5C", "lw": .8})
    panel_label(ax, tx["prediction"]); clean_axis(ax)
    fig.suptitle(tx["fig3"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.84, bottom=.16, left=.10, right=.98, wspace=.42)
    return fig


def _coef_panel(ax, data: pd.DataFrame, target: str, tx: dict, title: str) -> None:
    d = data[(data.target.eq(target)) & data.identified.eq(1)].copy()
    order = ["baseline_residualized", "future_debt_placebo"]
    d = d.set_index("analysis").reindex(order).reset_index()
    y = np.arange(len(d)); colors = [PALETTE[2], "0.62"]
    for yi, (_, row), color in zip(y, d.iterrows(), colors):
        ax.errorbar(row.beta, yi, xerr=[[row.beta - row.ci_lo], [row.ci_hi - row.beta]],
                    fmt="o", color=color, ecolor=color, capsize=4, lw=1.5,
                    ms=5.5, zorder=3)
    ax.axvline(0, color="0.2", lw=.8); ax.set_yticks(y, [tx["residual"], tx["future"]])
    ax.invert_yaxis(); ax.set_xlabel(tx["coef"]); ax.grid(axis="x", alpha=.4)
    panel_label(ax, title); clean_axis(ax)


def fig4(cfg, tables: Path, lang: str):
    tx = TEXT[lang]
    recovery = read(tables, "sens_recovery_debt_placebo.csv")
    paths = read(tables, "sens_path_final_review.csv")
    paths = paths[paths.analysis.eq("same_target_BH_FDR")]
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(1, 3, figsize=MAIN_PAGE, gridspec_kw={"width_ratios": [1, 1, 1.05]})
    _coef_panel(axes[0], recovery, "deficit_auc_full", tx, tx["auc"])
    _coef_panel(axes[1], recovery, "t90_h", tx, tx["t90"])
    axes[1].set_yticklabels([])
    axes[1].tick_params(axis="y", length=0)
    ax = axes[2]
    ax.plot(paths.min_trace_per_phase, paths.fdr_significant_n, marker="o", color=PALETTE[0], lw=1.6)
    for _, row in paths.iterrows():
        ax.annotate(f"{int(row.fdr_significant_n)}/{int(row.eligible_n)}",
                    (row.min_trace_per_phase, row.fdr_significant_n), xytext=(0, 7),
                    textcoords="offset points", ha="center", fontsize=9.5)
    ax.set_ylim(0, max(paths.fdr_significant_n) + 2.2)
    ax.set_xlabel(tx["trace"]); ax.set_ylabel(tx["fdr"]); ax.grid(True, alpha=.4)
    ax.text(.5, -.29, tx["conditional"], transform=ax.transAxes, ha="center", fontsize=9, color="0.35")
    panel_label(ax, tx["paths"]); clean_axis(ax)
    fig.suptitle(tx["fig4"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.82, bottom=.24, left=.10, right=.98, wspace=.55)
    return fig


def supp1(cfg, tables: Path, lang: str):
    tx = TEXT[lang]
    cluster = read(tables, "sens_calibration_leave_cluster_out.csv")
    warning = read(tables, "sens_official_heat_warning.csv")
    manuscript_style(cfg, lang)
    fig, axes = plt.subplots(1, 2, figsize=SUPP_PAGE)
    d = cluster.copy()
    labels = {
        "full_event_equal": "Full event-equal" if lang == "en" else "全部事件等权",
        "august_heat": "Leave August out" if lang == "en" else "移除8月事件簇",
        "late_july_replication": "Leave late July out" if lang == "en" else "移除7月末事件簇",
    }
    names = [labels["full_event_equal"] if row.analysis == "full_event_equal" else labels[row.left_out_cluster]
             for _, row in d.iterrows()]
    y = np.arange(len(d)); axes[0].barh(y, d.delta_b2_vs_b1, color=[PALETTE[0], PALETTE[1], PALETTE[2]])
    axes[0].set_yticks(y, names); axes[0].invert_yaxis(); axes[0].axvline(0, color="0.2", lw=.8)
    axes[0].set_xlabel(tx["event_x"]); axes[0].grid(axis="x", alpha=.4); panel_label(axes[0], tx["cluster"]); clean_axis(axes[0])
    wanted = ["all_unadjusted", "exclude_official_heat_warning", "exclude_official_severe_heat_warning"]
    d = warning.set_index("analysis").reindex(wanted)
    names = (["All rows", "Exclude heat warning", "Exclude severe warning"] if lang == "en" else
             ["全部数据", "排除高温预警", "排除严重高温预警"])
    y = np.arange(len(d)); axes[1].barh(y, d.delta_b2_vs_b1, color=[PALETTE[0], PALETTE[2], PALETTE[3]])
    axes[1].set_yticks(y, names); axes[1].invert_yaxis(); axes[1].axvline(0, color="0.2", lw=.8)
    axes[1].set_xlabel(tx["event_x"]); axes[1].grid(axis="x", alpha=.4); panel_label(axes[1], tx["warning"]); clean_axis(axes[1])
    axes[1].text(.5, -.28, tx["warning_note"], transform=axes[1].transAxes, ha="center", fontsize=9, color="0.35")
    fig.suptitle(tx["s1"], fontsize=14, fontweight="bold", y=.985)
    fig.subplots_adjust(top=.82, bottom=.22, left=.13, right=.98, wspace=.48)
    return fig


def supp2(cfg, tables: Path, lang: str):
    tx = TEXT[lang]
    d = read(tables, "exp_g_oblast_falsification_summary.csv").iloc[0]
    manuscript_style(cfg, lang)
    fig, ax = plt.subplots(figsize=SUPP_PAGE)
    point, lo, hi = float(d.effect_did), float(d.ci_lo), float(d.ci_hi)
    ax.errorbar(point, 0, xerr=[[point - lo], [hi - point]], fmt="o", color="0.55", capsize=5, ms=7)
    ax.axvline(0, color="0.2", lw=.9); ax.set_yticks([0], ["Zaporizhzhia - Volyn"])
    ax.set_xlabel(tx["did"]); ax.set_ylim(-.7, .7); ax.grid(axis="x", alpha=.4); clean_axis(ax)
    ax.text(.98, .78, tx["failed"], transform=ax.transAxes, ha="right", fontsize=10,
            bbox={"boxstyle": "round,pad=.35", "fc": "#F3F3F3", "ec": "0.55", "lw": .8})
    ax.text(.98, .62, tx["cycles"], transform=ax.transAxes, ha="right", fontsize=9.5, color="0.35")
    fig.suptitle(tx["s2"], fontsize=14, fontweight="bold", y=.98)
    fig.subplots_adjust(top=.78, bottom=.23, left=.18, right=.98)
    return fig


def supp3(cfg, tables: Path, lang: str):
    fig = fig2(cfg, tables, lang)
    fig.suptitle(TEXT[lang]["s3"], fontsize=14, fontweight="bold", y=.985)
    return fig


def supp4(cfg, tables: Path, lang: str):
    fig = fig4(cfg, tables, lang)
    fig.suptitle(TEXT[lang]["s4"], fontsize=14, fontweight="bold", y=.985)
    return fig


def save_set(cfg, tables: Path, lang: str, out: Path) -> None:
    lang_out = out / lang; lang_out.mkdir(parents=True, exist_ok=True)
    # Remove only generated figure leaves so a reduced main set cannot leave a
    # stale Fig5 behind and silently confuse manuscript assembly.
    for pattern in ["Fig*.png", "Fig*.svg", "Fig*.pdf"]:
        for stale in lang_out.glob(pattern):
            stale.unlink()
    main = [fig_study_design, fig_registered_timeline, fig_calibration,
            fig_attack_sensor_generalization, fig_attack_dynamics, fig3]
    supplement = [supp1, supp2, supp3, supp4]
    with PdfPages(lang_out / f"manuscript_main_figures_{lang}.pdf") as pdf:
        for i, fn in enumerate(main, 1):
            fig = fn(cfg, tables, lang); pdf.savefig(fig, bbox_inches=None)
            fig.savefig(lang_out / f"Fig{i}.png", dpi=300, bbox_inches=None)
            fig.savefig(lang_out / f"Fig{i}.svg", bbox_inches=None)
            fig.savefig(lang_out / f"Fig{i}.pdf", bbox_inches=None)
            plt.close(fig)
    with PdfPages(lang_out / f"manuscript_supplement_figures_{lang}.pdf") as pdf:
        for i, fn in enumerate(supplement, 1):
            fig = fn(cfg, tables, lang); pdf.savefig(fig, bbox_inches=None)
            fig.savefig(lang_out / f"FigS{i}.png", dpi=300, bbox_inches=None)
            fig.savefig(lang_out / f"FigS{i}.svg", bbox_inches=None)
            fig.savefig(lang_out / f"FigS{i}.pdf", bbox_inches=None)
            plt.close(fig)


def save_experiment_b_set(cfg, tables: Path, lang: str, out: Path) -> None:
    """A standalone bilingual Experiment-B figure pack for paper selection."""
    lang_out = out / "experiment_b" / lang
    lang_out.mkdir(parents=True, exist_ok=True)
    for pattern in ["ExpB*.png", "ExpB*.svg", "ExpB*.pdf"]:
        for stale in lang_out.glob(pattern): stale.unlink()
    figures = [fig_attack_sensor_generalization, fig_attack_outcome_profile,
               fig_attack_dynamics, fig_attack_anchor_sensitivity,
               fig_attack_evidence_matrix]
    combined = lang_out / f"experiment_b_figures_{lang}.pdf"
    with PdfPages(combined) as pdf:
        for i, fn in enumerate(figures, 1):
            fig = fn(cfg, tables, lang)
            pdf.savefig(fig, bbox_inches=None)
            fig.savefig(lang_out / f"ExpB{i}.pdf", bbox_inches=None)
            fig.savefig(lang_out / f"ExpB{i}.png", dpi=300, bbox_inches=None)
            fig.savefig(lang_out / f"ExpB{i}.svg", bbox_inches=None)
            plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--run-id", required=True); args = ap.parse_args()
    cfg = load_config(run_id=args.run_id, mode="real")
    tables = cfg.out_dir("results_tables")
    out = cfg.run_base / "results" / "figures_manuscript"
    for lang in ["en", "zh"]:
        save_set(cfg, tables, lang, out)
        save_experiment_b_set(cfg, tables, lang, out)
    manifest = {
        "main_figure_n": 6,
        "supplement_figure_n": 4,
        "selection_rule": "Each main figure answers one link in the frozen inferential chain.",
        "core_rerun": False,
        "languages": ["en", "zh"],
        "experiment_b_figure_n": 5,
    }
    (out / "figure_selection_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
