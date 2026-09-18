#!/usr/bin/env python3
"""Display-only final paper figure packaging; no analytical data are read."""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

FIGS={
 17:{"stage":"V2","stem":"f17_power_binscatter","source":"power_availability_infrastructure_final_validation_v2","name":"power_itdk","title_zh":"停电窗口可达率与 ITDK 中间跳证据的关系","title_en":"Power-Window Availability and ITDK Transit Evidence"},
 18:{"stage":"V2","stem":"f18_normal_power_binscatter","source":"power_availability_infrastructure_final_validation_v2","name":"normal_vs_power","title_zh":"正常时期与停电时期可达率对应的基础设施证据关系","title_en":"Infrastructure Evidence Across Normal and Power Availability"},
 23:{"stage":"V2","stem":"f23_roc","source":"power_availability_infrastructure_final_validation_v2","name":"roc_power_normal","title_zh":"停电时期与正常时期可达率的 ROC 曲线","title_en":"ROC Curves for Power and Normal Availability"},
 24:{"stage":"V2","stem":"f24_pr","source":"power_availability_infrastructure_final_validation_v2","name":"pr_power_normal","title_zh":"停电时期与正常时期可达率的精确率—召回率曲线","title_en":"Precision–Recall Curves for Power and Normal Availability"},
 27:{"stage":"V2","stem":"f27_release_robustness","source":"power_availability_infrastructure_final_validation_v2","name":"release_robustness","title_zh":"不同 ITDK 时间快照下结果的稳健性","title_en":"Robustness Across ITDK Releases"},
 31:{"stage":"V3","stem":"figure31_event_timeline","source":"power_availability_infrastructure_scientific_closure_v3","name":"verified_event_timeline","title_zh":"已核验电力与战争相关事件时间线","title_en":"Timeline of Verified Power and War-Related Events"},
 12:{"stage":"V1","stem":"f12_router","source":"power_availability_infrastructure_v1","name":"router_evidence_deciles","title_zh":"不同稳定程度下的 ITDK 路由器证据比例","title_en":"ITDK Router Evidence Across Stability Deciles"},
 13:{"stage":"V1","stem":"f13_trace","source":"power_availability_infrastructure_v1","name":"traceroute_evidence_deciles","title_zh":"不同稳定程度下的自有 traceroute 中间跳证据比例","title_en":"Own Traceroute Intermediate-Hop Evidence Across Stability Deciles"},
 9:{"stage":"V1","stem":"f09_auc_diff","source":"power_availability_infrastructure_v1","name":"auc_difference","title_zh":"各州及全国 Power 相对 Normal 的 AUC 差值","title_en":"Power versus Normal AUC Difference by Oblast and Nationwide"},
 4:{"stage":"V1","stem":"f04_decile","source":"power_availability_infrastructure_v1","name":"power_decile_itdk","title_zh":"不同停电可达率分组下的 ITDK 中间跳证据比例","title_en":"ITDK Transit-Evidence Prevalence Across Power-Availability Deciles"},
}
AXES={
17:("停电窗口可达率","ITDK 中间跳证据估计比例（%）","Power-window availability","Estimated ITDK transit-evidence probability (%)"),
18:("可达率","ITDK 中间跳证据估计比例（%）","Availability","Estimated ITDK transit-evidence probability (%)"),
23:("假阳性率","真阳性率","False positive rate","True positive rate"),
24:("召回率","精确率","Recall","Precision"),
27:("ROC-AUC","ITDK 快照","ROC-AUC","ITDK release"),
31:("日期（UTC）","州","Date (UTC)","Oblast"),
12:("分位组","路由器证据比例（%）","Decile","Router evidence prevalence (%)"),
13:("分位组","中间跳证据比例（%）","Decile","Intermediate-hop evidence (%)"),
9:("AUC 差值","州 / 全国","AUC difference","Oblast / Nationwide"),
4:("分位组","ITDK 中间跳证据比例（%）","Decile","ITDK transit-evidence prevalence (%)"),
}
CAP_ZH={
17:"展示停电窗口可达率与观察到的 ITDK 中间跳证据比例之间的连续关系。横轴为停电窗口可达率，纵轴为估计的 ITDK 中间跳证据比例（含不确定性）。该图支持描述性关联，不证明停电造成基础设施身份或因果关系。",
18:"并列比较正常时期与停电时期可达率对应的 ITDK 证据关系。两面板共享数据口径和纵轴范围，便于比较；它不能单独证明 Power 相对于一般长期稳定性提供独立信息。",
23:"比较停电时期与正常时期可达率对观察到的 ITDK 中间跳证据的 ROC 判别曲线。曲线、颜色和 AUC 沿用冻结 V2 结果；它描述判别能力，不等于因果效应。",
24:"比较停电时期与正常时期可达率的精确率—召回率曲线，并显示 ITDK 阳性比例基线。精确率受类别不平衡影响，不能把曲线面积直接解释为基础设施真值概率。",
27:"展示 2024-02、2024-08 和 2025-03 ITDK 快照下同一冻结分析的稳健性。该图用于验证结果对快照的敏感性，不消除 ITDK 观测偏差。",
31:"按州展示已核验电力事件与战争相关事件的时间分布；点和叉号分别表示事件类型。日期级事件只作事件层面的时间标记，没有被扩展成全天周期，也不表示确定没有其他事件。",
12:"展示不同稳定程度分位组中的 ITDK 路由器证据比例及区间。它是辅助拓扑证据验证，不是完整基础设施真值，也不代表没有路由器证据的 IP 一定不是基础设施。",
13:"展示不同稳定程度分位组中的自有 traceroute 中间跳证据比例。该图是独立测量来源的稳健性补充，受 traceroute 可见性和共享观测偏差限制。",
9:"展示各州及全国 Power 相对 Normal 的 ROC-AUC 差值和区间。差值沿用冻结 V1 计算，零线仅为参考；图中关联差异不能解释为电力特异因果效应。",
4:"展示停电窗口可达率分位组与 ITDK 中间跳证据比例的关系。分位组用于描述分布，不是人为筛选阈值；该图不能证明 IP 的物理基础设施属性。",
}
CAP_EN={
17:"This figure shows the continuous relationship between power-window availability and observed ITDK transit evidence. It is an association plot and does not establish that an outage caused infrastructure status.",
18:"The two panels compare the same ITDK evidence relationship for normal and power windows. The common scale supports visual comparison, but the figure alone does not establish power-specific information beyond general stability.",
23:"ROC curves compare the discrimination of power-window and normal availability for observed ITDK transit evidence. They describe discrimination, not a causal effect or a ground-truth infrastructure probability.",
24:"Precision–recall curves compare power-window and normal availability and show the observed-positive prevalence baseline. Precision is prevalence-sensitive and is not a physical infrastructure truth.",
27:"This figure reports robustness across the 2024-02, 2024-08 and 2025-03 ITDK snapshots under the same frozen analysis. It does not remove ITDK observation bias.",
31:"The timeline shows verified power and war-related events by oblast. Date-level events are plotted as event-level context and are not expanded to full-day cycles; absence of a marker does not mean no event occurred.",
12:"This figure reports router-evidence prevalence across stability deciles. It is a secondary topology validation and not a complete infrastructure ground truth.",
13:"This figure reports observed own-traceroute intermediate-hop evidence across stability deciles. It is a secondary validation subject to traceroute visibility and shared-observability bias.",
9:"This forest plot reports frozen Power-minus-Normal ROC-AUC differences by oblast and nationwide. The zero line is a reference; the differences are not causal power-specific effects.",
4:"This figure reports observed ITDK transit-evidence prevalence across power-availability deciles. Deciles are descriptive and are not an eligibility threshold or a proof of physical infrastructure role.",
}

def h(p):
 x=hashlib.sha256(); x.update(p.read_bytes()); return x.hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); a=ap.parse_args(); root,out=a.root,a.out
 for d in ['en','zh','appendix_en','appendix_zh']:(out/d).mkdir(parents=True,exist_ok=True)
 rows=[]; main_no=[17,18,23,24,27]; app_no=[31,12,13,9,4]
 for n,meta in FIGS.items():
  src=root/meta['source']/'figures'; valid=True; reason=''
  for lang in ['en','zh']:
   srcdir=src/lang
   for ext in ['png','pdf','svg']:
    f=srcdir/f"{meta['stem']}.{ext}"
    if not f.exists(): valid=False; reason=f'MISSING {f}'; continue
    destdir=out/('en' if n in main_no else 'appendix_en') if lang=='en' else out/('zh' if n in main_no else 'appendix_zh')
    prefix=('main_figure_'+str(main_no.index(n)+1) if n in main_no else 'appendix_figure_'+str(app_no.index(n)+1))
    dest=destdir/f"{prefix}_{meta['name']}_{lang}.{ext}"; shutil.copy2(f,dest)
    rows.append({'figure':n,'stage':meta['stage'],'language':lang,'format':ext,'source':str(f.relative_to(root)),'output':str(dest.relative_to(out)),'sha256':h(dest),'valid':True})
  meta['valid']=valid; meta['reason']=reason
 (out/'FIGURE_LANGUAGE_INDEX.csv').write_text('figure,stage,language,format,source,output,sha256,valid\n'+'\n'.join(','.join('"'+str(r[k]).replace('"','""')+'"' for k in ['figure','stage','language','format','source','output','sha256','valid']) for r in rows)+'\n',encoding='utf-8')
 def captions(lang):
  lines=[('# 论文图注（中文）' if lang=='zh' else '# Figure captions (English)'),'', '本图包只复制并本地化冻结 V1/V2/V3 图像；没有重新计算任何数值。','']
  for n in (main_no+app_no):
   m=FIGS[n]; ax=AXES[n]
   if lang=='zh': lines += [f"## Figure {n}：{m['title_zh']}",f"- 横轴：{ax[0]}",f"- 纵轴：{ax[1]}",f"- 说明：{CAP_ZH[n]}",'']
   else: lines += [f"## Figure {n}: {m['title_en']}",f"- X-axis: {ax[2]}",f"- Y-axis: {ax[3]}",f"- Caption: {CAP_EN[n]}",'']
  return '\n'.join(lines)
 (out/'FIGURE_CAPTIONS_ZH.md').write_text(captions('zh'),encoding='utf-8'); (out/'FIGURE_CAPTIONS_EN.md').write_text(captions('en'),encoding='utf-8')
 plan='''# PAPER FIGURE PLAN（中文）\n\n## 一、正文推荐图\n\n1. Figure 17：停电窗口可达率与 ITDK 中间跳证据的连续关系，作为 Power availability 与独立 ITDK 证据的主结果。\n2. Figure 18：正常时期与停电时期的对应关系，用于说明 Power 与一般稳定性的比较口径。\n3. Figure 23：Power/Normal ROC 判别曲线。\n4. Figure 24：Power/Normal 精确率—召回率曲线。\n5. Figure 27：不同 ITDK 快照下的稳健性。\n\n## 二、附录推荐图\n\n- Figure 31：已核验电力与战争相关事件时间线，属于方法/背景图。\n- Figure 12：ITDK 路由器证据。\n- Figure 13：自有 traceroute 中间跳证据。\n- Figure 9：各州及全国 AUC 差值。\n- Figure 4：停电可达率分组与 ITDK 证据比例。\n\n## 三、展示限制\n\n本阶段没有发现目标图为 NOT_GENERATED 或占位图；V3 的其它 Figure 32–42 本来就未生成，未纳入。所有目标图保持原始数值、CI、排序、坐标范围和颜色。\n'''
 (out/'PAPER_FIGURE_PLAN_ZH.md').write_text(plan,encoding='utf-8')
 short='''# 导师汇报版图清单\n\n## Figure 17\n看停电窗口可达率与 ITDK 中间跳证据的连续关系。它是 Power availability 主结果。只能说存在观察到的关联，不能说停电造成了基础设施属性。\n\n## Figure 18\n看正常时期和停电时期两条关系是否相近。它帮助判断 Power 信号是否超出一般长期稳定性，但不能单凭图得出独立增量效应。\n\n## Figure 23\n看 Power 与 Normal 的 ROC 判别能力。它适合比较判别曲线，不应被讲成因果效应。\n\n## Figure 24\n看类别不平衡下的精确率—召回率表现。精确率受 ITDK 阳性比例影响，不能直接等同真实基础设施概率。\n\n## Figure 27\n看 ITDK 时间快照变化时结果是否保持方向。它是稳健性检查，不会消除共享观测偏差。\n'''
 (out/'ADVISOR_FIGURE_SHORTLIST_ZH.md').write_text(short,encoding='utf-8')
 (out/'README.md').write_text('# paper_final_figures\n\nDisplay-only package from frozen V1/V2/V3 outputs. No analysis code, data, metric, CI, ordering, or statistical method was changed. Main figures are in en/zh; appendix figures are in appendix_en/appendix_zh.\n',encoding='utf-8')
 print(json.dumps({'generated_figures':sorted([n for n,m in FIGS.items() if m['valid']]),'rows':len(rows)},ensure_ascii=False))
if __name__=='__main__': main()
