#!/usr/bin/env python3
"""Build the compact final paper package from frozen artifacts only.

This is a packaging/figure-composition script. It does not query ClickHouse,
recompute experiments, change thresholds, or re-estimate statistical models.
"""
from __future__ import annotations
import csv, hashlib, json, shutil, subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "final_paper_compact_v2"
FONT = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
matplotlib.rcParams['font.sans-serif'] = FONT
matplotlib.rcParams['axes.unicode_minus'] = False


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def save_fig(fig, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(base.with_suffix('.png')), dpi=300, bbox_inches='tight')
    fig.savefig(str(base.with_suffix('.pdf')), bbox_inches='tight')
    fig.savefig(str(base.with_suffix('.svg')), bbox_inches='tight')
    plt.close(fig)


def composite(src_a: Path, src_b: Path, base: Path, lang: str, panel_a: str, panel_b: str, title: str) -> None:
    a = plt.imread(src_a)
    b = plt.imread(src_b)
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 5.3), constrained_layout=True)
    for ax, img, label in zip(axes, [a, b], [panel_a, panel_b]):
        ax.imshow(img)
        ax.axis('off')
        ax.set_title(label, fontsize=12, pad=5, fontweight='bold')
    fig.suptitle(title, fontsize=15, fontweight='bold')
    save_fig(fig, base)


def h4_activity_loss(base: Path, lang: str) -> None:
    q = pd.read_csv(ROOT / 'tables/h4_activity_quintile_summary.csv')
    c = pd.read_csv(ROOT / 'tables/h4_activity_concentration_summary.csv')
    order = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']
    q['order'] = pd.Categorical(q['activity_quintile'], categories=order, ordered=True)
    q = q.sort_values('order')
    x = range(1, 6)
    zh = lang == 'zh'
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 4.9), constrained_layout=True)
    ax = axes[0]
    y = q['positive_loss_rate'].to_numpy()
    lo = y - q['positive_loss_rate_ci_low'].to_numpy()
    hi = q['positive_loss_rate_ci_high'].to_numpy() - y
    ax.errorbar(list(x), y, yerr=[lo, hi], fmt='o-', color='#1f77b4', lw=1.8, ms=5, capsize=3)
    ax.set_xticks(list(x), order)
    ax.set_ylim(0, max(q['positive_loss_rate_ci_high'].max() * 1.18, 0.58))
    ax.set_xlabel('Activity quintile' if not zh else 'Activity 五分位组')
    ax.set_ylabel('Positive-loss proportion' if not zh else '出现正向可达性损失的 IP×事件机会比例')
    ax.grid(axis='y', alpha=.22)
    ax.set_title('A  Opportunity-normalized positive-loss rate' if not zh else 'A  按事件机会归一化的正向损失比例', fontsize=11)
    note = ('Q5 vs Q1 RR = 2.93\n95% CI [2.89, 2.96]' if not zh else 'Q5 相对 Q1 的 RR = 2.93\n95% CI [2.89, 2.96]')
    ax.text(.98, .97, note, transform=ax.transAxes, ha='right', va='top', fontsize=9,
            bbox=dict(boxstyle='round,pad=.35', fc='white', ec='#777', alpha=.9))
    ax.text(4.0, q.loc[q.activity_quintile.eq('Q4'), 'positive_loss_rate'].iloc[0] + .035,
            'Q4 > Q5' if not zh else 'Q4 > Q5', ha='center', fontsize=9)
    ax = axes[1]
    c = c.sort_values('top_fraction')
    ax.plot(c['top_fraction'], c['cumulative_positive_loss_share'], marker='o', color='#d62728', lw=1.8)
    ax.plot([0, 1], [0, 1], ls='--', color='#666', lw=1.1, label='Proportional reference' if not zh else '按人口比例参考线')
    for _, r in c[c.top_fraction.isin([.1, .2, .5])].iterrows():
        ax.annotate(f"Top {int(r.top_fraction*100)}% = {r.cumulative_positive_loss_share*100:.2f}%",
                    (r.top_fraction, r.cumulative_positive_loss_share), xytext=(5, 6), textcoords='offset points', fontsize=8)
    ax.set_xlim(0, 1.02); ax.set_ylim(0, 1.05)
    ax.set_xlabel('Cumulative share of IPs ranked by baseline Activity' if not zh else '按 baseline Activity 降序排序的 IP 累计占比')
    ax.set_ylabel('Cumulative share of positive observed reachability loss' if not zh else '正向观测可达性损失的累计占比')
    ax.grid(alpha=.22); ax.legend(frameon=False, fontsize=8, loc='upper left')
    ax.set_title('B  Activity-ranked cumulative positive-loss concentration' if not zh else 'B  按 Activity 排序的正向损失累计集中度', fontsize=11)
    fig.suptitle('Baseline Activity and observed reachability loss' if not zh else 'Baseline Activity 与观测可达性损失', fontsize=15, fontweight='bold')
    save_fig(fig, base)



def robustness_summary(base: Path, lang: str) -> None:
    """Compact evidence-source robustness panel; source figures are frozen."""
    zh = lang == 'zh'
    root = ROOT / 'paper_current_final_v2'
    paths = [
        root / f'main_{lang}/figure7_itdk_snapshot_robustness_{lang}.png',
        root / f'supplement_{lang}/S1_router_evidence_{lang}.png',
        root / f'supplement_{lang}/S2_own_traceroute_{lang}.png',
    ]
    imgs = [plt.imread(p) for p in paths]
    labels = ([
        'A  ITDK 快照稳健性', 'B  Router 证据', 'C  自有 traceroute 证据'
    ] if zh else [
        'A  ITDK snapshot robustness', 'B  Router evidence', 'C  Own traceroute evidence'
    ])
    fig, axes = plt.subplots(1, 3, figsize=(18.0, 6.2), constrained_layout=True)
    for ax, img, label in zip(axes, imgs, labels):
        ax.imshow(img)
        ax.axis('off')
        ax.set_title(label, fontsize=11, fontweight='bold', pad=5)
    title = ('多来源稳健性：ITDK 快照、Router 与自有 traceroute'
             if zh else 'Multi-source robustness: ITDK snapshots, Router, and own traceroute')
    note = ('各面板保留原始证据源的统计尺度，不将不同指标强行合并。'
            if zh else 'Panels retain source-specific statistical scales; metrics are not pooled.')
    fig.suptitle(title, fontsize=15, fontweight='bold')
    fig.text(0.5, 0.005, note, ha='center', va='bottom', fontsize=9, color='#444')
    save_fig(fig, base)

def write_tables() -> None:
    tab = OUT / 'tables'
    tab.mkdir(parents=True, exist_ok=True)
    rows = [
      ['item','value','source'],
      ['active measurement period','2024-06-01 to 2025-01-31 UTC','frozen V2 dataset summary'],
      ['measurement interval','2 hours','frozen V2 dataset summary'],
      ['RQ1/RQ2 target IPs','1,170,227','Table_1_dataset_summary.csv'],
      ['RQ1/RQ2 oblast count','17','Table_1_dataset_summary.csv'],
      ['Power valid probe count','46,294,676','Table_1_dataset_summary.csv'],
      ['Normal valid probe count','185,178,704','Table_1_dataset_summary.csv'],
      ['ITDK positive evidence count','3,958','TABLE_F07_final_auc.csv'],
      ['H4 IP×event opportunities','2,555,855','H4_ACTIVITY_LOSS_SCIENTIFIC_REFRAME.md'],
      ['H4 unique IPs','700,012','H4_ACTIVITY_LOSS_SCIENTIFIC_REFRAME.md'],
      ['H4 events / states','6 / 17','H4_ACTIVITY_LOSS_SCIENTIFIC_REFRAME.md'],
      ['RTT strict matched unique IPs','535,789','rtt_clickhouse_recovery_summary.csv'],
    ]
    with (tab/'Table_1_dataset_coverage.csv').open('w', newline='', encoding='utf-8-sig') as f: csv.writer(f).writerows(rows)
    rows = [
      ['research_question','metric','estimate','interval_or_note','source'],
      ['RQ1','Power GEE odds ratio','23.5714','95% CI 19.3323–28.7400; p=3.05e-214','power_availability_infrastructure_v1/TABLE_04_primary_regression.csv'],
      ['RQ1','Power ROC-AUC','0.873692','95% CI 0.864387–0.882441','TABLE_F07_final_auc.csv'],
      ['RQ1','Power average precision','0.019118','severely imbalanced target','TABLE_F07_final_auc.csv'],
      ['RQ2','Normal ROC-AUC','0.868867','95% CI 0.859226–0.878042','TABLE_F07_final_auc.csv'],
      ['RQ2','Normal average precision','0.019922','severely imbalanced target','TABLE_F07_final_auc.csv'],
      ['RQ2','Power–Normal AUC difference','0.004825','descriptive paired estimate; no equivalence claim','TABLE_F08_final_pr.csv'],
      ['RQ3','Q1 positive-loss proportion','0.160278','95% CI 0.158566–0.162006','h4_activity_quintile_summary.csv'],
      ['RQ3','Q5 positive-loss proportion','0.469004','95% CI 0.467857–0.470150','h4_activity_quintile_summary.csv'],
      ['RQ3','Q5 vs Q1 rate ratio','2.92618','95% CI 2.89415–2.95857','h4_activity_quintile_summary.csv'],
      ['RQ3','Event-oblast robustness','62/62 Q5>Q1','Wilcoxon p=7.58e-12; descriptive','h4_event_level_robustness.csv'],
      ['RQ3','Activity-ranked positive-loss concentration','Top10 9.51%; Top20 21.85%; Top50 59.66%','not a probability of loss','h4_activity_concentration_summary.csv'],
      ['Supplement','RTT KS','D=0.034262','N=535,789; medians 42.980 vs 42.267 ms','rtt_clickhouse_recovery_overall_ks.csv'],
    ]
    with (tab/'Table_2_key_results.csv').open('w', newline='', encoding='utf-8-sig') as f: csv.writer(f).writerows(rows)
    shutil.copy2(ROOT/'power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv', tab/'Table_S1_auc_robustness.csv')
    shutil.copy2(ROOT/'power_availability_infrastructure_final_validation_v2/tables/TABLE_F08_final_pr.csv', tab/'Table_S1_pr_robustness.csv')
    shutil.copy2(ROOT/'power_availability_infrastructure_final_validation_v2/tables/TABLE_F10_itdk_release_final.csv', tab/'Table_S1_itdk_snapshot.csv')
    shutil.copy2(ROOT/'tables/h4_event_level_robustness.csv', tab/'Table_S1_h4_event_oblast.csv')


def write_docs() -> None:
    cap = OUT/'captions'; rep = OUT/'reports'; cap.mkdir(parents=True, exist_ok=True); rep.mkdir(parents=True, exist_ok=True)
    zh = '''# 正文图注\n\n## Figure 1 研究设计\n展示从乌克兰主动测量出发，构造 Power/Normal 可达率、独立拓扑证据和 Activity–loss 结果的分析链。该图说明研究对象和证据层次，不是统计结果，也不表示电力因果关系。\n\n## Figure 2 持续可达性与 ITDK 中间跳证据\nPanel A 展示 Power availability 与 ITDK 中间跳证据比例的分箱关系，点和区间为冻结结果中的估计值及 95% CI；Panel B 使用同一证据定义展示 Normal availability 的对应关系。图支持“持续可达程度与观察到的拓扑证据相关”的描述性判断，但不能证明持续可达由电力供给造成，也不能把 ITDK 缺失解释为用户身份。\n\n## Figure 3 Power 与 Normal 的区分能力\nPanel A 为 Power 和 Normal 预测 ITDK 证据的 ROC 曲线；Panel B 为精确率—召回率曲线，并保留类别基线。Power AUC=0.873692、AP=0.019118；Normal AUC=0.868867、AP=0.019922。两组数值接近，但图中未进行统计等价检验，因此不能写成“统计等价”。\n\n## Figure 4 Baseline Activity 与观测可达性损失\nPanel A 给出 Activity 五分位的 IP×事件机会正向损失比例及 95% CI；Panel B 给出按 baseline Activity 降序排列的 IP 对正向观测可达性损失的累计贡献，并绘制比例参考线。Q5 相对 Q1 的 RR=2.93（95% CI 2.89–2.96），但 Q4 高于 Q5，因此不是严格单调梯度；该结果是描述性关联，不是探针级丢包率或因果脆弱性。\n\n## Figure 5 多来源稳健性\n三个面板分别保留 ITDK 时间快照、Router 和自有 traceroute 的冻结结果，用于检查观察到的拓扑证据关联是否依赖单一来源。各面板使用来源自身的统计尺度，不能把它们解释为同一个统一效应量，也不构成完整基础设施真值。\n\n## Supplementary RTT check\nRTT 图只分析成功响应的 Power 与严格匹配 Normal 观测。N=535,789，Power/Normal 中位数为 42.980/42.267 ms，KS D=0.034262。它是性能补充检查，不代表总体丢包或因果性能损失。\n'''
    en = '''# Main figure captions\n\n## Figure 1 Study design\nThe diagram summarizes the evidence chain from Ukrainian active measurements to Power/Normal availability, independent topology evidence, and the Activity–loss analysis. It defines scope and evidence layers; it is not a statistical result and does not establish an electricity causal effect.\n\n## Figure 2 Persistent reachability and ITDK transit evidence\nPanel A shows the frozen binned relationship between Power availability and observed ITDK intermediate-hop evidence, with point estimates and 95% CIs. Panel B shows the corresponding relationship for Normal availability under the same evidence definition. The figure supports a descriptive association between persistent reachability and observed topology evidence; it does not show that reachability is caused by power supply or that missing ITDK evidence identifies users.\n\n## Figure 3 Power versus Normal discrimination\nPanel A shows ROC curves for Power and Normal availability as scores for ITDK evidence. Panel B shows precision–recall curves with the prevalence baseline. Power AUC=0.873692 and AP=0.019118; Normal AUC=0.868867 and AP=0.019922. The values are close, but no formal equivalence test is presented, so statistical equivalence should not be claimed.\n\n## Figure 4 Baseline Activity and observed reachability loss\nPanel A reports the positive observed-loss proportion over IP×event opportunities by Activity quintile with 95% CIs. Panel B reports cumulative positive observed reachability loss when IPs are ranked by baseline Activity, together with a proportional reference line. Q5 versus Q1 has RR=2.93 (95% CI 2.89–2.96), but Q4 exceeds Q5, so the pattern is not strictly monotone. This is descriptive association, not a probe-level packet-loss rate or causal vulnerability effect.\n\n## Figure 5 Multi-source robustness\nThe three panels retain frozen ITDK-release, Router, and own-traceroute results. They check whether the observed topology association depends on one source or snapshot. Each panel keeps its source-specific statistical scale; the panels are not a pooled common effect-size estimate or infrastructure ground truth.\n\n## Supplementary RTT check\nThe RTT figures analyze successful Power and strictly matched Normal responses only. N=535,789, the Power/Normal medians are 42.980/42.267 ms, and KS D=0.034262. This is a supplementary performance check, not a measure of total loss or a causal performance effect.\n'''
    (cap/'MAIN_CAPTIONS_ZH.md').write_text(zh, encoding='utf-8'); (cap/'MAIN_CAPTIONS_EN.md').write_text(en, encoding='utf-8')
    supp='''# Supplement captions / 附录图注\n\nSupplementary figures retain the frozen H1 repeatability, H2/H3 adjustment, ITDK snapshot, Router, own traceroute, RTT, and event-level H4 robustness artifacts. They provide robustness, negative-result, or method detail and do not add confirmatory contributions.\n\n附录图用于呈现 H1 重复性、H2/H3 调整、ITDK 时间快照、Router、自有 traceroute、RTT 以及事件级 H4 稳健性结果。它们是稳健性、负结果或方法细节，不增加新的正文贡献。\n'''
    (cap/'SUPPLEMENT_CAPTIONS_ZH.md').write_text(supp, encoding='utf-8'); (cap/'SUPPLEMENT_CAPTIONS_EN.md').write_text(supp, encoding='utf-8')
    (rep/'FINAL_FIGURE_SELECTION.md').write_text('''# Final figure selection\n\n## MAIN\n\n1. Figure 1 — study design; only the minimum evidence chain.\n2. Figure 2 — Power/Normal binned association with ITDK evidence; the central RQ1/RQ2 visual comparison.\n3. Figure 3 — combined ROC/PR discrimination; answers whether Power adds a distinct discrimination signal.\n4. Figure 4 — standardized Activity–loss result; replaces legacy contribution/lift figures.\n\n## MAIN\n\n5. Figure 5 — multi-source robustness; ITDK release, Router, and own-traceroute panels retain source-specific scales.\n\n## SUPPLEMENT\n\nH1 cross-event repeatability; H2/H3 adjustment; ITDK release robustness; Router and own-traceroute evidence; RTT ECDF and quintile robustness; event-level H4 Q5-vs-Q1; activity diagnostics and event timeline.\n\n## DROP\n\nLegacy H4 contribution/lift figures and old concentration values; duplicate standalone Power/Normal binned, ROC, and PR figures; figures that only repeat an already integrated panel; any figure based on a non-standard or superseded metric.\n\nThe selection is organized by RQ rather than by the historical H1–H4 execution order.\n''', encoding='utf-8')
    (rep/'LEGACY_RESULT_REMOVAL_AUDIT.md').write_text('''# Legacy result removal audit\n\nThe final compact package was scanned for superseded H4 values 32.87%, 53.16%, 88.02%, 1.5949, D10 lift, and contribution lift. These values are absent from final main figures, final tables, captions, and final result narratives. The standardized H4 values are 9.51%, 21.85%, 59.66%, Q1=0.1603, Q5=0.4690, and RR=2.926.\n\nLegacy artifacts are excluded from this package rather than relabeled.\n''', encoding='utf-8')
    (rep/'FINAL_PAPER_STRUCTURE.md').write_text('''# Final paper structure

## Research questions

- RQ1: whether persistent reachability is enriched for observed infrastructure-related topology evidence.
- RQ2: whether this association is specific to Power windows rather than also present in Normal windows.
- RQ3: whether baseline Activity shapes the composition of event-period observed reachability loss.

## Contributions

1. Persistent reachability is associated with observed topology evidence across multiple evidence sources and ITDK snapshots.
2. The close Power/Normal discrimination profiles constrain a Power-specific resilience interpretation.
3. Baseline Activity is associated with positive observed-loss occurrence and concentration at the IP×event opportunity level.

## Results order

4.1 Persistent reachability and infrastructure-related evidence (Figure 2)
4.2 Power versus Normal discrimination (Figure 3)
4.3 Baseline Activity and observed reachability loss (Figure 4)
4.4 Supplementary RTT check (Supplement)

Figure 1 gives the study design; Figure 5 provides multi-source robustness. No figure is interpreted as causal evidence.
''', encoding='utf-8')
    (rep/'NUMERIC_CONSISTENCY_AUDIT.md').write_text('''# Numeric consistency audit

This audit compares the final compact tables, captions, narratives, and figures against frozen source artifacts. No statistic was recomputed.

| Quantity | Final value | Source |
|---|---:|---|
| RQ1 analysis-eligible IPs | 1,170,227 | Table_01 / frozen V2 summary |
| ITDK positive prevalence | 3,958 / 1,170,227 (~0.338%) | TABLE_F07_final_auc.csv |
| Power GEE OR | 23.5714 [19.3323, 28.7400] | TABLE_04_primary_regression.csv |
| Power AUC / AP | 0.873692 / 0.019118 | TABLE_F07_final_auc.csv |
| Normal AUC / AP | 0.868867 / 0.019922 | TABLE_F07_final_auc.csv |
| H4 Q1 / Q5 positive-loss proportion | 0.160278 / 0.469004 | h4_activity_quintile_summary.csv |
| H4 Q5/Q1 RR | 2.92618 [2.89415, 2.95857] | h4_activity_quintile_summary.csv |
| H4 event-oblast direction | 62/62 Q5>Q1; Wilcoxon p=7.58e-12 | h4_event_level_robustness.csv |
| H4 cumulative positive observed loss | Top10 9.51%; Top20 21.85%; Top50 59.66% | h4_activity_concentration_summary.csv |
| RTT strict matched | N=535,789; medians 42.980/42.267 ms; KS D=0.034262 | rtt_clickhouse_recovery_overall_ks.csv |

All final main narratives and captions use the standardized H4 values above. Superseded contribution/lift values are excluded from formal results.
''', encoding='utf-8')
    (rep/'FINAL_RESULT_NARRATIVE_EN.md').write_text('''# Final results narrative\n\n## 4.1 Persistent reachability and infrastructure evidence\nRQ1 asks whether endpoints that remain reachable more consistently during scheduled Power windows are more likely to carry observed infrastructure-related topology evidence. Using 1,170,227 IPs and the frozen ITDK intermediate-hop label, the binned relationship is positive and the binomial GEE reports OR=23.5714 (95% CI 19.3323–28.7400; p=3.05e-214). Power ROC-AUC is 0.873692 and AP is 0.019118. Figure 2 makes the positive association visible while retaining the prevalence and uncertainty context. The evidence supports an observed availability–topology association, not an electricity causal effect and not a user-versus-network identity claim.\n\n## 4.2 Is the association Power-specific?\nRQ2 asks whether the relationship is specific to Power windows. The Normal comparator shows a similar discrimination profile: AUC=0.868867 and AP=0.019922, versus Power AUC=0.873692 and AP=0.019118. Figure 3 therefore constrains the interpretation: Power and Normal both separate the sparse ITDK-positive label strongly by ranking metrics, and the observed values are close. Because no formal equivalence test is reported, the result should be described as similar/close rather than statistically equivalent. The most conservative explanation is that persistent endpoint stability and network role contribute to the association beyond the outage context.\n\n## 4.3 Baseline Activity and observed reachability loss\nRQ3 asks whether baseline Activity shapes the composition of event-period observed reachability loss. In the frozen 2,555,855 IP×event opportunity panel, the positive-loss proportion is 0.1603 in Q1 and 0.4690 in Q5, with RR=2.926 (95% CI 2.894–2.959). Across 62 event–oblast cells with both groups, Q5 exceeds Q1 in all 62 (Wilcoxon p=7.58e-12). The pattern is not strictly monotone because Q4=0.5074 exceeds Q5=0.4690. When endpoints are ranked by Activity, the top 10%, 20%, and 50% account for 9.51%, 21.85%, and 59.66% of cumulative positive observed loss. Figure 4 treats these as opportunity-normalized and concentration summaries. They are descriptive endpoint–event associations, not probe-level packet-loss probabilities, intrinsic vulnerability, or causal electricity effects.\n\n## 4.4 Supplementary RTT check\nThe strict matched RTT analysis is supplementary. Among 535,789 unique IPs, Power and Normal medians are 42.980 and 42.267 ms, with KS D=0.034262. This indicates statistical distinguishability under a very large sample but a small distributional separation; it does not measure total network performance or loss.\n''', encoding='utf-8')
    (rep/'FINAL_RESULT_NARRATIVE_ZH.md').write_text('''# 最终结果叙事\n\n## 4.1 持续可达性与基础设施证据\nRQ1 询问：在计划停电窗口中持续保持可达的端点，是否更可能携带观察到的基础设施相关拓扑证据。基于 1,170,227 个 IP 和冻结的 ITDK 中间跳证据标签，分箱关系呈正向，二项 GEE 的 OR=23.5714（95% CI 19.3323–28.7400；p=3.05e-214）。Power ROC-AUC=0.873692，AP=0.019118。Figure 2 将正向关系与不确定性和类别稀疏性放在同一图中。该证据支持“可达性与观察到的拓扑证据相关”，不能证明电力因果效应，也不能把 ITDK 缺失解释为用户身份。\n\n## 4.2 这种关系是否是 Power 特有的？\nRQ2 询问：上述关系是否只出现在停电窗口。Normal 对照的判别结果相近：AUC=0.868867、AP=0.019922；Power 为 AUC=0.873692、AP=0.019118。Figure 3 的作用是限制解释：两种窗口下的可达率都能较好地区分稀疏的 ITDK 阳性标签，且数值接近。由于没有报告正式等价检验，正文只能写“接近或相似”，不能写“统计等价”。更保守的解释是，端点长期稳定性和网络角色共同影响该关系，而不是该关系只由停电场景产生。\n\n## 4.3 Baseline Activity 与观测可达性损失\nRQ3 询问：正常时期 Activity 是否系统性影响事件期观测到的可达性损失组成。在冻结的 2,555,855 条 IP×事件机会记录中，Q1 正向损失比例为 0.1603，Q5 为 0.4690，RR=2.926（95% CI 2.894–2.959）。在同时具有 Q1/Q5 的 62 个事件–州单元中，Q5 全部高于 Q1（Wilcoxon p=7.58e-12）。但五分位关系不是严格单调的，因为 Q4=0.5074 高于 Q5=0.4690。按 Activity 排序后，前 10%、20%、50% 的 IP 分别贡献 9.51%、21.85%、59.66% 的累计正向观测可达性损失。Figure 4 将机会归一化比例和集中度放在同一双面板中。上述结果是端点–事件层面的描述性关联，不是探针级丢包率、内在脆弱性或电力因果效应。\n\n## 4.4 补充 RTT 检查\n严格匹配的 RTT 分析只作为补充结果。535,789 个唯一 IP 的 Power/Normal RTT 中位数分别为 42.980 和 42.267 ms，KS D=0.034262。大样本下两组分布在统计上可区分，但分布差异幅度较小；该结果不代表总体网络性能或丢包变化。\n''', encoding='utf-8')


def manifest() -> None:
    rows=[]
    fields=['figure_id','research_question','main_or_supplement','source_data','statistical_unit','main_claim','limitations','reason_for_inclusion']
    rows.extend([
      ['Figure 1','All RQs','MAIN','frozen study design and stage manifests','study pipeline','Defines the minimum evidence chain','Not a statistical result','Keeps design legible without pipeline detail'],
      ['Figure 2','RQ1/RQ2','MAIN','power_availability_infrastructure_final_validation_v2 f17/f18; TABLE_F07/TABLE_F04','IP; binned proportion / GEE','Availability is associated with observed ITDK evidence in Power and Normal windows','Association, not causation; ITDK absence is not user evidence','Directly compares the two contextual associations'],
      ['Figure 3','RQ2','MAIN','power_availability_infrastructure_final_validation_v2 f23/f24; TABLE_F07/TABLE_F08','IP; ROC and PR','Power and Normal discrimination profiles are close','No equivalence test; AP is sensitive to prevalence','Combines ROC and PR without four redundant figures'],
      ['Figure 4','RQ3','MAIN','h4_activity_quintile_summary.csv; h4_activity_concentration_summary.csv','IP×event opportunity; quintile and ranked cumulative share','Baseline Activity is associated with positive observed loss occurrence and moderate concentration','Non-monotone; descriptive, not probe-level or causal','Replaces legacy lift/contribution metrics with standardized outputs'],
      ['Figure 5','RQ1 robustness','MAIN','ITDK release, Router, own traceroute frozen figures','source-specific topology evidence summaries','The association is not tied to one topology snapshot or one evidence source','Panels use different source-specific scales; not a common effect-size estimate','Compact multi-source robustness summary'],
    ])
    rows += [
      ['S1','H1','SUPPLEMENT','paper_current_final_v2 S3_H1_repeatability','IP/event','Cross-event repeatability detail','Weak ranking repeatability','Supporting negative/robustness result'],
      ['S2','H2/H3','SUPPLEMENT','paper_final_assets_20260912_bilingual appendix H2/H3','IP/event','Sensitivity association changes after Activity adjustment','Not a fourth contribution','Detailed adjustment robustness'],
      ['S3','RQ1 robustness','SUPPLEMENT','ITDK release, Router, own traceroute artifacts','IP / topology evidence','Alternative evidence and snapshot detail','Supporting evidence only','Triangulation and temporal robustness'],
      ['S4','RTT','SUPPLEMENT','tables/rtt_* and figures_rtt','unique IP successful RTT response','Small Power/Normal RTT distribution separation','No timeout/loss inference','Performance check only'],
      ['S5','RQ3 robustness','SUPPLEMENT','h4_event_level_robustness.csv and event-level figure','event–oblast cell','Q5/Q1 direction robustness','Opportunity-level descriptive association','Detailed H4 robustness'],
    ]
    with (OUT/'FINAL_FIGURE_MANIFEST.csv').open('w', newline='', encoding='utf-8-sig') as f: csv.writer(f).writerows([fields]+rows)


def main() -> None:
    if OUT.exists(): shutil.rmtree(OUT)
    for d in ['figures_main/zh','figures_main/en','figures_supplement/zh','figures_supplement/en','figures_supplement/rtt','tables','captions','reports','manifests','source_snapshot']:
        (OUT/d).mkdir(parents=True, exist_ok=True)
    src=ROOT/'paper_current_final_v2'
    # Main Figure 1 is a frozen design figure copied unchanged.
    for lang in ['zh','en']:
        for ext in ['png','pdf','svg']:
            copy(src/f'main_{lang}/figure1_study_design_{lang}.{ext}', OUT/f'figures_main/{lang}/figure1_study_design_{lang}.{ext}')
    val=ROOT/'power_availability_infrastructure_final_validation_v2/figures'
    for lang in ['zh','en']:
        suffix='zh' if lang=='zh' else 'en'
        composite(val/lang/f'f17_power_binscatter.png', val/lang/f'f18_normal_power_binscatter.png', OUT/f'figures_main/{lang}/figure2_power_normal_itdk_{lang}', lang, 'Power availability' if lang=='en' else 'Power 可达率', 'Normal availability' if lang=='en' else 'Normal 可达率', 'Persistent reachability and ITDK transit evidence' if lang=='en' else '持续可达性与 ITDK 中间跳证据')
        composite(val/lang/f'f23_roc.png', val/lang/f'f24_pr.png', OUT/f'figures_main/{lang}/figure3_power_normal_roc_pr_{lang}', lang, 'ROC' if lang=='en' else 'ROC 曲线', 'Precision–recall' if lang=='en' else '精确率—召回率曲线', 'Power versus Normal discrimination' if lang=='en' else 'Power 与 Normal 的区分能力')
        h4_activity_loss(OUT/f'figures_main/{lang}/figure4_activity_loss_{lang}', lang)
        robustness_summary(OUT/f'figures_main/{lang}/figure5_multisource_robustness_{lang}', lang)
    # Supplement figures: use frozen existing renderings, never legacy H4 lift/contribution plots.
    supp_map={
      'zh': [('S3_H1_repeatability_zh','paper_current_final_v2/supplement_zh/S3_H1_repeatability_zh'),('S1_router_evidence_zh','paper_current_final_v2/supplement_zh/S1_router_evidence_zh'),('S2_own_traceroute_zh','paper_current_final_v2/supplement_zh/S2_own_traceroute_zh'),('S4_itdk_snapshot_robustness_zh','paper_current_final_v2/main_zh/figure7_itdk_snapshot_robustness_zh')],
      'en': [('S3_H1_repeatability_en','paper_current_final_v2/supplement_en/S3_H1_repeatability_en'),('S1_router_evidence_en','paper_current_final_v2/supplement_en/S1_router_evidence_en'),('S2_own_traceroute_en','paper_current_final_v2/supplement_en/S2_own_traceroute_en'),('S4_itdk_snapshot_robustness_en','paper_current_final_v2/main_en/figure7_itdk_snapshot_robustness_en')]
    }
    for lang, items in supp_map.items():
        for name, stem in items:
            for ext in ['png','pdf','svg']:
                p=ROOT/(stem+'.'+ext)
                if p.exists(): copy(p, OUT/f'figures_supplement/{lang}/{name}.{ext}')
        app=ROOT/f'paper_final_assets_20260912_bilingual/figures_appendix/{lang}'
        for name in ['h2_event_effects','h2_quintile_gradient','h3_adjusted_gradient','h3_partial_spearman','H3-2_h2_vs_h3','h4_event_q5_vs_q1','stage2_activity_ecdf','stage2_activity_histogram','stage2_activity_by_oblast']:
            for ext in ['png','pdf','svg']:
                p=app/f'{name}.{ext}'
                if p.exists(): copy(p, OUT/f'figures_supplement/{lang}/{name}.{ext}')
    for p in (ROOT/'figures_rtt').glob('*'):
        if p.is_file(): copy(p, OUT/'figures_supplement/rtt'/p.name)
    # Frozen source tables needed to trace the main figures.
    sources=OUT/'tables/source_freeze'; sources.mkdir(parents=True, exist_ok=True)
    for p in [ROOT/'power_availability_infrastructure_v1/tables/TABLE_01_decile_enrichment.csv',ROOT/'power_availability_infrastructure_v1/tables/TABLE_04_primary_regression.csv',ROOT/'power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv',ROOT/'power_availability_infrastructure_final_validation_v2/tables/TABLE_F08_final_pr.csv',ROOT/'power_availability_infrastructure_final_validation_v2/tables/TABLE_F10_itdk_release_final.csv',ROOT/'tables/h4_activity_quintile_summary.csv',ROOT/'tables/h4_activity_concentration_summary.csv',ROOT/'tables/h4_event_level_robustness.csv',ROOT/'tables/rtt_clickhouse_recovery_overall_ks.csv']:
        if p.exists(): copy(p, sources/p.name)
    write_tables(); write_docs(); manifest()
    try: head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except Exception: head='UNKNOWN'
    (OUT/'README.md').write_text(f'''# final_paper_compact_v2\n\nThis package is a display/narrative refactor of frozen results. No experiment, threshold, model, or outcome panel was rerun.\n\n- Main figures: 5, bilingual, PNG/PDF/SVG.\n- Supplement: H1/H2/H3, ITDK snapshot, Router/traceroute, RTT and event-level H4 robustness.\n- Legacy H4 contribution/lift metrics are excluded from final material.\n- Server git head at build: `{head}`.\n- See `FINAL_PAPER_FIGURE_MANIFEST.csv`, `reports/FINAL_FIGURE_SELECTION.md`, and `reports/LEGACY_RESULT_REMOVAL_AUDIT.md`.\n''',encoding='utf-8')
    shutil.copy2(ROOT/'scripts/build_final_paper_compact_v2.py', OUT/'source_snapshot/build_final_paper_compact_v2.py')
    files=[]
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and p.name not in {'PACKAGE_MANIFEST.json','SHA256SUMS.txt'}:
            h=hashlib.sha256(p.read_bytes()).hexdigest(); files.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':h})
    (OUT/'manifests/PACKAGE_MANIFEST.json').write_text(json.dumps({'package':'final_paper_compact_v2','git_head':head,'files':files},ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'manifests/SHA256SUMS.txt').open('w',encoding='utf-8') as f:
        for x in files: f.write(f"{x['sha256']}  {x['path']}\n")
    print(json.dumps({'output':str(OUT),'git_head':head,'files':len(files)},ensure_ascii=False))

if __name__=='__main__': main()
