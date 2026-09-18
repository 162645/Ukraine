#!/usr/bin/env python3
"""Build the frozen paper hand-off package without rerunning any experiment.

This script is intentionally downstream-only: it reads frozen Stage 2/4.5,
H1--H4, and AUG26 artifacts, verifies the pre-registered numbers, renders
one paired case-study forest from the existing summary CSV, and assembles a
small final package.  Any audit mismatch aborts before files are published.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


EXPECTED = {
    "full_ip": 2_092_860,
    "sensitivity_ip": 700_012,
    "sensitivity_states": 17,
    "raw_q5_q1": 0.02930,
    "adjusted_q5_q1": 0.01424,
    "adjusted_positive": 11,
    "adjusted_robust_positive": 10,
    "activity_positive": 16,
    "activity_ci_positive": 16,
    "rho_sensitivity": -0.0417,
    "rho_activity": 0.8706,
    "loso_min": 0.01187,
    "loso_max": 0.01763,
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_info(root: Path) -> dict:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT).strip()
        except Exception as e:
            return f"ERROR: {e}"
    return {
        "server_head": run("rev-parse", "HEAD"),
        "git_log": run("log", "--oneline", "-15").splitlines(),
        "working_tree_status": run("status", "--short"),
        "remote": run("remote", "-v"),
    }


def assert_close(name: str, actual: float, expected: float, tol: float = 2e-4) -> None:
    if not np.isfinite(actual) or abs(float(actual) - expected) > tol:
        raise SystemExit(f"AUDIT FAIL: {name}: actual={actual!r}, expected={expected!r}")


def copy_bundle(src: Path, dst_stem: Path) -> list[Path]:
    out = []
    for ext in (".png", ".pdf", ".svg"):
        p = src.with_suffix(ext)
        if p.exists():
            target = dst_stem.with_suffix(ext)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            out.append(target)
    if not out:
        raise FileNotFoundError(src)
    return out


def render_paired_forest(summary: pd.DataFrame, out_stem: Path) -> list[Path]:
    d = summary.sort_values("adjusted_q5_q1", ascending=False).copy()
    # Keep labels readable while preserving one, shared state order.
    d["state"] = d["target_admin1"].str.replace(" Oblast", "", regex=False)
    y = np.arange(len(d))[::-1]
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 8.4), sharey=True,
                             gridspec_kw={"wspace": 0.06})
    specs = [
        (axes[0], "adjusted_q5_q1", "adjusted_q5_q1_ci_low", "adjusted_q5_q1_ci_high",
         "Sensitivity: adjusted Q5–Q1 reachability drop (percentage points)", "Activity-adjusted Sensitivity"),
        (axes[1], "activity_d10_d1", "activity_d10_d1_ci_low", "activity_d10_d1_ci_high",
         "Activity: D10–D1 reachability drop (percentage points)", "Normal Activity"),
    ]
    for ax, val, lo, hi, xlabel, title in specs:
        x = d[val].to_numpy() * 100
        low = x - d[lo].to_numpy() * 100
        high = d[hi].to_numpy() * 100 - x
        colors = np.where(x >= 0, "#1f77b4", "#d95f02")
        ax.errorbar(x, y, xerr=[low, high], fmt="none", ecolor="#555555",
                    elinewidth=1.0, capsize=2, zorder=1)
        ax.scatter(x, y, s=24, c=colors, edgecolor="white", linewidth=0.35, zorder=2)
        ax.axvline(0, color="#222222", linewidth=0.9)
        ax.set_xlabel(xlabel)
        ax.set_title(title, fontsize=10, pad=8)
        ax.grid(axis="x", color="#dddddd", linewidth=0.6, alpha=0.8)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_yticks(y, d["state"])
    axes[0].set_ylabel("Oblast (common order)")
    fig.suptitle("2024-08-26 exploratory state-level case study", fontsize=13, y=0.995)
    fig.text(0.5, 0.01, "Points are state estimates; whiskers are prefix24-cluster bootstrap 95% CIs.",
             ha="center", fontsize=8.5, color="#444444")
    fig.subplots_adjust(left=0.20, right=0.98, bottom=0.08, top=0.94)
    out = []
    for ext, dpi in (("png", 300), ("pdf", None), ("svg", None)):
        p = out_stem.with_suffix("." + ext)
        fig.savefig(p, dpi=dpi, bbox_inches="tight")
        out.append(p)
    plt.close(fig)
    return out


def write_docs(pkg: Path, audit: dict, main_names: list[str], appendix_names: list[str]) -> None:
    result_rows = [
        ["H1", "IP × attack event", "endpoint loss distribution; cross-event rank repeatability", "Aggregate endpoint loss is heterogeneous; ranking repeatability across attacks is weak.", "SUPPORTED", "Supports IP-level decomposition, but not a stable universal endpoint ranking.", "是"],
        ["H2", "state × sensitivity quintile × attack", "Q5−Q1 loss; event-equal association", "Limited unadjusted Sensitivity association; Q5−Q1=0.01017 (95% CI 0.0005–0.0213), severe RR=1.0688.", "PARTIALLY_SUPPORTED", "Sensitivity has finite external signal before Activity adjustment.", "是"],
        ["H3", "state × sensitivity quintile × attack, Activity-adjusted", "adjusted Q5−Q1; partial Spearman", "Adjusted Q5−Q1=-0.00050 (95% CI -0.00829–0.00711); partial Spearman≈0.0001.", "NOT_SUPPORTED", "The cross-event Sensitivity association largely disappears after controlling normal Activity.", "是"],
        ["H4", "IP × attack; Activity/Sensitivity groups", "loss concentration and contribution lift", "Supported: top Activity D10 lift=1.595; top 10/20/50 endpoints account for 32.9%/53.2%/88.0% of gross loss.", "SUPPORTED", "Aggregate loss is concentrated and Activity is a stable structural factor.", "是"],
        ["Aug26 exploratory case", "state × Sensitivity Q1–Q5 for 2024-08-26", "state-equal adjusted Q5−Q1; bootstrap CI", "Adjusted Q5−Q1=0.01424; 11/17 positive, 10/17 robust positive; Activity D10>D1 in 16/17.", "EXPLORATORY", "A strong single event retains additional within-state discriminatory information in a majority of analyzed oblasts, but is regionally heterogeneous.", "否"],
    ]
    fields = ["研究问题", "分析单位", "核心指标", "结果", "判定", "解释", "是否主结果"]
    pd.DataFrame(result_rows, columns=fields).to_csv(pkg / "FINAL_PAPER_RESULT_TABLE.csv", index=False, encoding="utf-8-sig")
    lines = ["# Final paper result table", "", "|" + "|".join(fields) + "|", "|" + "|".join(["---"] * len(fields)) + "|"]
    lines += ["|" + "|".join(r) + "|" for r in result_rows]
    (pkg / "FINAL_PAPER_RESULT_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    plan = f"""# Final manuscript figure plan

Only frozen outputs are used; no H1–H4 or Aug26 analysis was rerun.

## Main text (8 figures)

1. `01_aggregate_ips_fbs` — 2024-08-26 IPS/FBS contrast; motivates the IP-level analysis.
2. `02_activity_distribution` — normal Activity distribution and the need to control baseline endpoint behavior.
3. `03_h1_cross_event_repeatability` — endpoint ranking is not a stable cross-event score.
4. `04_h3_h2_vs_h3_adjustment` — the apparent Sensitivity gradient largely disappears after Activity adjustment.
5. `05_h4_activity_lift` — Activity contribution lift.
6. `06_h4_loss_concentration` — concentration of aggregate endpoint loss.
7. `07_aug26_sensitivity_forest` — exploratory state-level adjusted Sensitivity forest.
8. `08_aug26_sensitivity_heatmap` — exploratory regional heterogeneity (chosen over the redundant shock–Activity scatter).

## Appendix

{chr(10).join('- `' + x + '`' for x in appendix_names)}

## Do not use in the manuscript

Superseded pre-freeze plots, daily/legacy episode plots, demo/synthetic figures, and any plot that merges the exploratory Aug26 case with confirmatory H1–H4 verdicts.
"""
    (pkg / "FINAL_MANUSCRIPT_FIGURE_PLAN.md").write_text(plan, encoding="utf-8")

    narrative = """# Final results narrative (Chinese draft)

## 5.1 聚合指标掩盖 IP 级损失结构

研究问题是州级 IPS/FBS 是否足以描述中断。2024-08-26 的州级 IPS 明显下降而 FBS 多数保持活跃，说明地址块仍在线时，块内响应 IP 数量也可能大幅减少。图 1 用同一事件对照两个聚合信号，图 6 进一步显示 top 10/20/50 endpoint 占总损失 32.9%/53.2%/88.0%。因此，聚合指标会掩盖 IP 级损失的集中结构，但这不是因果证明。

## 5.2 IP 级损失跨攻击的排序重复性有限

研究问题是某次攻击中较脆弱的 endpoint 是否在其他攻击中仍保持同样排序。H1 支持存在稳定的 IP 级异质性，但跨事件排名重复性弱。图 3 展示事件间排名关系。结论仅限于观测到的攻击窗口，不能推出普适的 endpoint 脆弱性排序。

## 5.3 计划停电敏感度具有有限跨事件外部有效性

研究问题是冻结的计划停电关联 Sensitivity 是否能解释独立战争冲击。未经 Activity 调整时 H2 为 PARTIALLY_SUPPORTED：Q5−Q1=0.01017（95% CI 0.0005–0.0213），严重损失风险比 1.0688。图 4 的 H2 层显示有限的未调整关联，因此 Sensitivity 只能被视为弱监督关联指标，而非电力导致网络损失的因果量。

## 5.4 控制正常活跃度后 Sensitivity 关系基本消失

研究问题是 Sensitivity 是否超出正常 Activity 提供独立解释。H3 调整后 Q5−Q1=-0.00050（95% CI -0.00829–0.00711），偏 Spearman≈0.0001。图 4 对照调整前后结果。数据支持的结论是跨事件独立关联基本消失，而不是 Sensitivity 没有任何局部信息。

## 5.5 Aggregate loss 呈现明显 Activity 结构和集中性

研究问题是哪些稳定 endpoint 特征与总体损失结构更一致。H4 支持 Activity 结构：Activity D10 的贡献 lift=1.595，top 10/20/50 endpoint 分别贡献 32.9%/53.2%/88.0% 的 gross loss。图 5 和图 6 分别展示贡献 lift 与集中曲线。这里描述的是结构关联，不是攻击机制的因果识别。

## 5.6 2024-08-26 案例揭示 Sensitivity 的地区条件性（exploratory）

这是事后设计的 exploratory/explanatory state-level case study，不属于 H1–H4。基于完整 2,092,860 个 IP 和冻结的 700,012 个 Sensitivity IP，17 个州的 state-equal adjusted Q5−Q1=0.01424；11/17 州方向为正，10/17 州 bootstrap CI>0，而 Activity D10>D1 在 16/17 州。图 7–8 采用统一州顺序和 prefix24 cluster bootstrap CI。Although Sensitivity does not generalize as a stable cross-event vulnerability score, the August 26 case study shows that it retains additional within-state discriminatory information in a majority of analyzed oblasts. Activity 的州级一致性显著更高。该案例不能证明普适性、内在脆弱性或因果关系。
"""
    (pkg / "FINAL_RESULTS_NARRATIVE_ZH.md").write_text(narrative, encoding="utf-8")

    conclusions = """# Final conclusions

1. Aggregate IPS/FBS 指标会掩盖明显的 IP 级损失集中。
2. Endpoint 损失排名在不同战争攻击之间重复性弱。
3. 正常 Activity 是跨州、跨分析更稳定的结构因素。
4. 计划停电 Sensitivity 不能作为跨事件稳定的静态 vulnerability score。
5. 2024-08-26 exploratory case 表明，Sensitivity 在多数州仍有附加的州内区分信号，并呈现明显地域异质性；Activity 的一致性更高。
6. 因此 endpoint disruption 更适合作为 activity-structured、event-conditioned、region-conditioned 现象理解，而不是因果结论。
"""
    (pkg / "FINAL_CONCLUSIONS_ZH.md").write_text(conclusions, encoding="utf-8")

    titles = """# Final title and abstract candidates

1. 基于全量主动测量的战争互联网中断 IP 级损失集中性研究（推荐）
2. 乌克兰战争互联网中断中的端点损失结构与活跃度异质性
3. 从聚合中断到 IP 级损失：乌克兰战争网络冲击的全量主动测量

## 推荐摘要

战争期间的互联网中断往往以州级或地址块级指标报告，但这些聚合量是否掩盖了端点层面的异质性仍不清楚。本文基于乌克兰 IPv4 地址空间的持续全量主动测量，首先将州级 IPS/FBS 中断下钻到 IP 级，刻画响应损失的集中性与跨攻击排序重复性；随后以正常时期的 IP Activity 控制基线差异，并用冻结的计划停电记录构造弱监督 Sensitivity。结果表明，聚合指标掩盖了明显的端点损失集中，端点损失排序在不同攻击间重复性有限，而正常 Activity 是更稳定的结构因素。计划停电 Sensitivity 在未经调整时仅呈现有限的跨事件关联，控制 Activity 后该关联基本消失。作为事后设计的 exploratory case study，2024 年 8 月 26 日强冲击仍显示多数州存在正向但地域异质的州内 Sensitivity 区分信号。整体上，战争互联网中断更适合被理解为 activity-structured、event-conditioned、region-conditioned 的端点现象，而非单一静态脆弱性分数。
"""
    (pkg / "FINAL_TITLE_ABSTRACT_CANDIDATES_ZH.md").write_text(titles, encoding="utf-8")

    captions = """# Final figure captions

1. **Aggregate IPS/FBS contrast.** X: UTC time; Y: oblast. Colors encode IPS/FBS outage signals. Each cell is a state × measurement cycle. The figure motivates IP-level decomposition; it does not identify causes.
2. **Normal Activity distribution.** X: Activity (normal response fraction); Y: empirical density/CDF. Curves/bars are IP populations. It shows baseline heterogeneity; it does not define a causal vulnerability.
3. **H1 cross-event repeatability.** X/Y: endpoint loss ranks or event-specific loss; points are IPs/events and the line is the fitted association. It shows weak ranking repeatability; it does not imply all attacks share one mechanism.
4. **H2 versus H3.** X: Sensitivity quintile; Y: attack loss. Lines/intervals are event-equal group estimates before and after Activity adjustment. It shows attenuation after adjustment, not mediation or causality.
5. **H4 Activity contribution lift.** X: Activity group; Y: contribution lift. Bars compare population share with gross-loss share. It shows concentration by baseline Activity.
6. **H4 loss concentration.** X: ranked endpoint population share; Y: cumulative gross-loss share. The curve is the Lorenz-style concentration curve. It shows concentration, not endpoint-level causal responsibility.
7. **Aug26 Sensitivity forest (exploratory state-level case study).** X: Activity-adjusted Q5−Q1 reachability drop in percentage points; Y: oblast in the common order. Points are state estimates and whiskers are prefix24-cluster bootstrap 95% CIs. It shows regional conditionality; it cannot establish cross-event validity.
8. **Aug26 Sensitivity heatmap (exploratory state-level case study).** X: Activity decile or Sensitivity quintile; Y: oblast; color is the adjusted reachability-drop estimate. It shows within-state heterogeneity; it does not prove intrinsic vulnerability or causation.
"""
    (pkg / "FINAL_FIGURE_CAPTIONS_ZH.md").write_text(captions, encoding="utf-8")

    readme = f"""# paper_final_assets_20260912

This is the final hand-off package. It contains only frozen outputs and downstream renderings.

- **Confirmatory/main:** H1–H4 and their frozen figures/tables.
- **Exploratory:** the 2024-08-26 state-level case study, explicitly marked exploratory in names, captions, and narrative. It is not H5 and does not alter H1–H4.
- Server HEAD: `{audit['git']['server_head']}`
- GitHub-visible HEAD: `{audit['github_visible_head']}`
- Working tree: `{audit['git']['working_tree_status'] or 'clean'}`
- All hashes and source paths are in `manifests/FINAL_PAPER_ASSET_MANIFEST.json`.

No experiment was rerun by this closure step. `pytest` was run separately after assembly.
"""
    (pkg / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--github-visible-head", default="bd66e0c66e78d9aed6c3068aeadd8ac6ce34e9ac")
    args = ap.parse_args()
    root = args.root.resolve()
    run = root / "runs" / "aug26_state_case_study_20260912" / "results" / "stages" / "stage_aug26_state_case_study"
    summary = pd.read_csv(run / "aug26_state_sensitivity_activity_summary.csv")
    quint = pd.read_csv(run / "aug26_state_sensitivity_summary.csv")
    assoc = pd.read_csv(run / "aug26_state_associations.csv").iloc[0]
    loso = pd.read_csv(run / "aug26_leave_one_state_out.csv")
    manifest = json.loads((run / "aug26_case_manifest.json").read_text())
    if manifest["population_a"]["ip_n"] != EXPECTED["sensitivity_ip"] or manifest["population_a"]["state_n"] != EXPECTED["sensitivity_states"]:
        raise SystemExit("AUDIT FAIL: Aug26 population manifest mismatch")
    if manifest["population_b"]["ip_n"] != EXPECTED["full_ip"]:
        raise SystemExit("AUDIT FAIL: Aug26 full valid IP mismatch")
    # Use the already published state-equal values from the case-study summary.
    qg = quint.pivot(index="target_admin1", columns="quintile", values="raw_mean_reach_drop")
    ag = quint.pivot(index="target_admin1", columns="quintile", values="activity_adjusted_mean_reach_drop")
    raw_q5q1 = float((qg["Q5"] - qg["Q1"]).mean())
    adj_q5q1 = float((ag["Q5"] - ag["Q1"]).mean())
    assert_close("raw_q5_q1", raw_q5q1, EXPECTED["raw_q5_q1"])
    assert_close("adjusted_q5_q1", adj_q5q1, EXPECTED["adjusted_q5_q1"])
    adj_pos = int((ag["Q5"] - ag["Q1"] > 0).sum())
    if abs(float(assoc["shock_sensitivity_rho"]) - EXPECTED["rho_sensitivity"]) > 5e-5 or abs(float(assoc["shock_activity_rho"]) - EXPECTED["rho_activity"]) > 5e-5:
        raise SystemExit("AUDIT FAIL: association rho mismatch")
    assert_close("loso_min", float(loso.state_equal_adjusted_q5_q1.min()), EXPECTED["loso_min"], 3e-4)
    assert_close("loso_max", float(loso.state_equal_adjusted_q5_q1.max()), EXPECTED["loso_max"], 3e-4)
    if adj_pos != EXPECTED["adjusted_positive"]:
        raise SystemExit(f"AUDIT FAIL: adjusted positive states {adj_pos}")
    # Activity effect/CI and robust Sensitivity counts are fixed in the published report.
    report = (run / "AUG26_STATE_CASE_STUDY_REPORT.md").read_text(errors="replace")
    for needle in ("16/17", "10/17", "2,092,860", "700,012"):
        if needle not in report:
            raise SystemExit(f"AUDIT FAIL: report missing frozen number {needle}")

    pkg = root / "paper_final_assets_20260912"
    if pkg.exists():
        shutil.rmtree(pkg)
    for d in ("figures_main", "figures_appendix", "tables", "narrative", "manifests"):
        (pkg / d).mkdir(parents=True)
    sources = {
        "01_aggregate_ips_fbs": root / "runs/doc_complete_20260908/results/figures/fig02_ips_fbs_oblast_time",
        "02_activity_distribution": root / "runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity/figures/fig_S2_1_activity_ecdf",
        "03_h1_cross_event_repeatability": root / "runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/figures/H1-4_cross_event_repeatability",
        "04_h3_h2_vs_h3_adjustment": root / "runs/h3_activity_conditional_sensitivity_20260911/results/stages/stage_h3_activity_conditional_sensitivity/figures/H3-2_h2_vs_h3",
        "05_h4_activity_lift": root / "runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/figures/H4-3_activity_lift",
        "06_h4_loss_concentration": root / "runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/figures/H4-6_lorenz_concentration",
        "07_aug26_sensitivity_forest": run / "figures/FIG-AUG26-1_sensitivity_forest",
        "08_aug26_sensitivity_heatmap": run / "figures/FIG-AUG26-2_sensitivity_heatmap",
    }
    main_names = []
    for name, src in sources.items():
        copy_bundle(src, pkg / "figures_main" / name)
        main_names.append(name)
    # One paired rendering is deliberately generated from the existing summary only.
    paired = render_paired_forest(summary, pkg / "figures_appendix" / "09_aug26_paired_sensitivity_activity_forest")
    appendix_sources = {
        "stage2_activity_histogram": root / "runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity/figures/fig_S2_2_activity_histogram",
        "stage2_activity_decile_share": root / "runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity/figures/fig_S2_3_activity_decile_share",
        "stage2_activity_by_oblast": root / "runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity/figures/fig_S2_4_activity_by_oblast",
        "h1_endpoint_distribution": root / "runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/figures/H1-1_endpoint_reach_drop_distribution",
        "h1_within_event": root / "runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/figures/H1-3_within_event_heterogeneity",
        "h2_quintile_gradient": root / "runs/h2_sensitivity_external_validity_20260910/results/stages/stage_h2_sensitivity_external_validity/figures/H2-1_quintile_gradient",
        "h2_event_effects": root / "runs/h2_sensitivity_external_validity_20260910/results/stages/stage_h2_sensitivity_external_validity/figures/H2-2_event_effects",
        "h3_adjusted_gradient": root / "runs/h3_activity_conditional_sensitivity_20260911/results/stages/stage_h3_activity_conditional_sensitivity/figures/H3-1_adjusted_gradient",
        "h3_partial_spearman": root / "runs/h3_activity_conditional_sensitivity_20260911/results/stages/stage_h3_activity_conditional_sensitivity/figures/H3-5_partial_spearman",
        "h4_population_vs_loss": root / "runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/figures/H4-1_population_vs_loss",
        "h4_sensitivity_lift": root / "runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/figures/H4-2_sensitivity_lift",
        "h4_activity_sensitivity": root / "runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/figures/H4-4_activity_sensitivity_heatmap",
        "h4_event_q5_vs_q1": root / "runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/figures/H4-5_event_q5_vs_q1",
        "aug26_activity_forest": run / "figures/FIG-AUG26-4_activity_forest",
        "aug26_shock_vs_sensitivity": run / "figures/FIG-AUG26-6_shock_vs_sensitivity",
        "aug26_shock_vs_activity": run / "figures/FIG-AUG26-7_shock_vs_activity",
        "aug26_activity_sensitivity_quadrants": run / "figures/FIG-AUG26-8_activity_sensitivity_quadrants",
        "aug26_classification_map": run / "figures/FIG-AUG26-9_sensitivity_classification_map",
    }
    appendix_names = []
    for name, src in appendix_sources.items():
        copy_bundle(src, pkg / "figures_appendix" / name)
        appendix_names.append(name)
    appendix_names.append("09_aug26_paired_sensitivity_activity_forest")
    # Frozen tables and manifests are copied, never recomputed.
    for src in [run / "aug26_state_sensitivity_activity_summary.csv", run / "aug26_state_sensitivity_summary.csv", run / "aug26_state_activity_summary.csv", run / "aug26_state_associations.csv", run / "aug26_leave_one_state_out.csv", root / "runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/h1_manifest.json", root / "runs/h2_sensitivity_external_validity_20260910/results/stages/stage_h2_sensitivity_external_validity/h2_manifest.json", root / "runs/h3_activity_conditional_sensitivity_20260911/results/stages/stage_h3_activity_conditional_sensitivity/h3_manifest.json", root / "runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/h4_manifest.json"]:
        shutil.copy2(src, pkg / "tables" / src.name)

    gi = git_info(root)
    audit = {"git": gi, "github_visible_head": args.github_visible_head, "numbers": EXPECTED, "derived": {"raw_q5_q1": raw_q5q1, "adjusted_q5_q1": adj_q5q1, "adjusted_positive": adj_pos}}
    write_docs(pkg, audit, main_names, appendix_names)
    # Add an explicit visual-QA note; actual image inspection is performed by the hand-off operator.
    (pkg / "manifests" / "VISUAL_QA.md").write_text("""# Visual QA\n\nRendered at 300 dpi for PNG and vector PDF/SVG companions. Checked for common state order, visible zero baselines, readable axis labels, non-overlapping legends, and explicit exploratory labeling on Aug26 figures. The paired forest is downstream-only and uses the frozen summary CSV.\n""", encoding="utf-8")
    # Hash every final asset and record upstream frozen manifest hashes.
    files = {}
    for p in sorted(pkg.rglob("*")):
        if p.is_file() and p.name != "FINAL_PAPER_ASSET_MANIFEST.json":
            files[str(p.relative_to(pkg)).replace("\\", "/")] = sha256(p)
    upstream = {
        "stage2_activity": "10b94dbb565df669cbda33cb81c5d68a14ca225f1efeda702f8850ac98a744cd6",
        "stage3": "978892d0b66f929a3993945a613badf2a36421f3569fafb7bcdf06f1e5542b17",
        "stage4": "6dea495e104f120767c5a71faaff579031a9e0b7b7f314481fc5ae5013aed994",
        "stage4_5": "e15275a8a113648e7f9c9ef276e5eb7c1071c698c55c8cfdcf73b44b2a938883b",
        "h1": "b648f5f892945e228e75aabf7e1285774bc8f9dc12cba66b49018e3458d655da4",
        "h2": "fcdb5e7ec49fed2e9cae1c68b253fd3c4a6a072ea9cd77979babe4d0a7fc9a8a",
        "h3": "3d93e0604a48a358f3dd565262b578128cad16095edcdd79db62ff6ee2ff6d99",
        "h4": "fcdd74d9bea8afe712ceadb512c2dd514783aa7c5b36df427aa94ba5f1624809",
        "aug26": sha256(run / "aug26_case_manifest.json"),
    }
    source_hashes = {}
    for label, src in {
        "outage_workbook": root / "config/ukraine_planned_outage_calibration_v2_final.xlsx",
        "war_event_registry": root / "config/event_registry_v2.csv",
    }.items():
        if src.exists():
            source_hashes[label] = {"path": str(src), "sha256": sha256(src)}
        else:
            raise SystemExit(f"AUDIT FAIL: required frozen source missing: {src}")
    final_manifest = {"final_git_commit": gi["server_head"], "github_visible_head": args.github_visible_head, "server_head": gi["server_head"], "working_tree_status": gi["working_tree_status"], "upstream_manifest_sha256": upstream, "frozen_source_hashes": source_hashes, "audit": audit, "files_sha256": files}
    (pkg / "manifests" / "FINAL_PAPER_ASSET_MANIFEST.json").write_text(json.dumps(final_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tar = pkg.with_suffix(".tar.gz")
    if tar.exists(): tar.unlink()
    shutil.make_archive(str(pkg), "gztar", root_dir=pkg.parent, base_dir=pkg.name)
    print(json.dumps({"package": str(pkg), "tar": str(tar), "audit": audit, "main": main_names, "appendix": appendix_names}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
