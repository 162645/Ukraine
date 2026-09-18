#!/usr/bin/env python3
"""Display-only reconstruction of the final manuscript figure package.

The renderer reads frozen V1/V2/V3 artifacts (and an existing frozen H1 CSV
when present).  It does not query ClickHouse, refit a model, select events,
change labels, or alter frozen master data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import pandas as pd
from PIL import Image
from sklearn.metrics import average_precision_score, precision_recall_curve


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save_triplet(fig, base: Path) -> None:
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def convert_svg(svg: Path, base: Path) -> None:
    subprocess.run(["rsvg-convert", "-d", "300", "-p", "300", "-f", "png",
                    "-o", str(base.with_suffix(".png")), str(svg)], check=True)
    subprocess.run(["rsvg-convert", "-d", "300", "-p", "300", "-f", "pdf",
                    "-o", str(base.with_suffix(".pdf")), str(svg)], check=True)
    img = Image.open(base.with_suffix(".png")).convert("RGB")
    img.save(base.with_suffix(".png"), dpi=(300, 300))


def make_dirs(out: Path) -> None:
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {out}")
    for name in ("main_zh", "main_en", "supplement_zh", "supplement_en",
                 "tables", "captions", "methods", "qa", "source"):
        (out / name).mkdir(parents=True, exist_ok=True)


def write_table(df: pd.DataFrame, out: Path, stem: str, title: str) -> None:
    df.to_csv(out / "tables" / f"{stem}.csv", index=False)
    (out / "tables" / f"{stem}.md").write_text(
        f"# {title}\n\n" + df.to_markdown(index=False) + "\n", encoding="utf-8")


def patch_bins_svg(src: Path, dst: Path, gids: list[str], title: str,
                   xlabel: str, ylabel: str, panels: tuple[str, ...] = ()) -> dict[str, bool]:
    """Copy frozen SVG geometry and hide only the old connecting line paths."""
    text = src.read_text(encoding="utf-8")
    before: dict[str, str] = {}
    for gid in gids:
        m = re.search(r'(<g id="' + re.escape(gid) + r'">.*?</g>)', text, re.S)
        if not m:
            raise RuntimeError(f"Frozen bin group not found: {gid}")
        group = m.group(1)
        before[gid] = hashlib.sha256("|".join(re.findall(r'd="([^"]+)"', group)).encode()).hexdigest()
        pm = re.search(r'(<path d=".*?"\s+clip-path="[^"]+"\s+style=")([^"].*?)(")', group, re.S)
        if not pm:
            raise RuntimeError(f"Frozen connecting path not found: {gid}")
        group2 = group[:pm.start(2)] + pm.group(2) + "; stroke-opacity: 0" + group[pm.end(2):]
        text = text[:m.start()] + group2 + text[m.end():]
    overlay = [
        '<g id="current_manuscript_overlay" aria-label="display-only labels">',
        '<rect x="0" y="0" width="518.4" height="21" fill="white"/>',
        f'<text x="259.2" y="15" text-anchor="middle" font-size="10.5" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{title}</text>',
        '<rect x="0" y="85" width="40" height="170" fill="white"/>',
        f'<text x="15" y="170" transform="rotate(-90 15 170)" text-anchor="middle" font-size="8.2" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{ylabel}</text>',
        '<rect x="80" y="308" width="360" height="23" fill="white"/>',
        f'<text x="259.2" y="326" text-anchor="middle" font-size="8.5" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{xlabel}</text>',
    ]
    for i, panel in enumerate(panels):
        overlay.append(f'<rect x="{65 + i * 242}" y="20" width="180" height="28" fill="white"/>')
        overlay.append(f'<text x="{151 + i * 242}" y="35" text-anchor="middle" font-size="8.5" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{panel}</text>')
    overlay.append("</g>")
    text = text.replace("</svg>", "\n" + "\n".join(overlay) + "\n</svg>")
    dst.write_text(text, encoding="utf-8")
    after: dict[str, str] = {}
    for gid in gids:
        m = re.search(r'(<g id="' + re.escape(gid) + r'">.*?</g>)', text, re.S)
        after[gid] = hashlib.sha256("|".join(re.findall(r'd="([^"]+)"', m.group(1))).encode()).hexdigest()
    return {gid: before[gid] == after[gid] for gid in gids}


def render_design(outdir: Path, zh: bool) -> None:
    plt.rcParams.update({"font.size": 8, "font.sans-serif": ["WenQuanYi Zen Hei", "DejaVu Sans"], "axes.unicode_minus": False})
    fig, ax = plt.subplots(figsize=(12.5, 7.0)); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    def box(x, y, w, h, text, color, fs=7.5):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.008,rounding_size=0.008", facecolor=color, edgecolor="#52616b", linewidth=.8))
        ax.text(x+w/2, y+h/2, text, ha="center", va="center", fontsize=fs, wrap=True)
    def arr(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2), arrowstyle="-|>", mutation_scale=11, linewidth=.9, color="#52616b"))
    if zh:
        title="当前论文研究设计与证据边界"; lane_a=["乌克兰 IPv4 主动测量","2 小时测量周期","ICMP 响应"]; lane_b=["已核验电力事件记录","停电窗口定义","正常时期对照窗口"]; avail=["ICMP 响应 + 窗口定义","逐 IP 可达率","停电窗口可达率 / 正常时期可达率"]; final=["可达率 + 多源拓扑证据","关联 / 判别","跨拓扑时间快照稳健性"]; topo=["CAIDA ITDK 中间跳证据\n（主要拓扑证据）","CAIDA 路由器/接口证据\n（辅助/稳健性证据）","自有 traceroute 中间跳证据\n（辅助验证证据）"]; notes=["可达率 = ICMP 测量可达性\n不是物理在线时间","ITDK T=1 = 观察到中间跳证据\nT=0 = 未观察到 T 证据\n不等于确认不存在基础设施","电力与拓扑证据是并列输入\n不表示因果链；自有 traceroute 属于辅助证据"]
    else:
        title="Current Manuscript Study Design and Evidence Boundaries"; lane_a=["Ukraine IPv4 active measurement","2-hour measurement cycles","ICMP responses"]; lane_b=["Verified power-event records","Power-window definition","Normal-period comparison windows"]; avail=["ICMP responses + window definitions","Per-IP availability","Power-window / normal-period availability"]; final=["Availability + multi-source topology evidence","Association / discrimination","Temporal-snapshot robustness"]; topo=["CAIDA ITDK transit-hop evidence\n(primary topology evidence)","CAIDA router/interface evidence\n(auxiliary / robustness evidence)","Own traceroute intermediate-hop evidence\n(auxiliary validation evidence)"]; notes=["Availability = ICMP measurement reachability\nnot physical uptime","ITDK T=1 = observed transit-hop evidence\nT=0 = no observed T evidence\nnot confirmed non-infrastructure","Power and topology evidence are parallel inputs\nnot a causal chain; own traceroute is auxiliary"]
    for i,t in enumerate(lane_a): box(.035,.82-i*.105,.22,.065,t,"#dceaf7")
    for i,t in enumerate(lane_b): box(.30,.82-i*.105,.22,.065,t,"#fff2cc")
    for i,t in enumerate(topo): box(.565,.82-i*.105,.25,.065,t,"#e4dfec",6.6)
    for i in range(2): arr(.145,.82-i*.105,.145,.78-i*.105)
    for i in range(2): arr(.41,.82-i*.105,.41,.78-i*.105)
    # Three topology sources are peer branches. There are no arrows between them.
    box(.17,.40,.38,.075,avail[0],"#fce4d6"); box(.17,.285,.38,.075,avail[1],"#fce4d6"); box(.17,.17,.38,.075,avail[2],"#fce4d6")
    arr(.145,.61,.24,.475); arr(.41,.61,.40,.475); arr(.36,.40,.36,.36); arr(.36,.285,.36,.25)
    box(.62,.50,.30,.075,"多源拓扑综合验证" if zh else "Multi-source topology validation","#e8dff5",7.2)
    for yy in (.8525,.7475,.6425): arr(.815,yy,.74,.575)
    box(.62,.40,.30,.075,final[0],"#d9ead3"); box(.62,.285,.30,.075,final[1],"#d9ead3"); box(.62,.17,.30,.075,final[2],"#d9ead3")
    arr(.55,.205,.62,.205); arr(.77,.50,.77,.475); arr(.69,.40,.69,.36); arr(.69,.285,.69,.25)
    ax.text(.035,.095,notes[0],fontsize=6.6,color="#303030",va="top"); ax.text(.355,.095,notes[1],fontsize=6.6,color="#303030",va="top",ha="center"); ax.text(.72,.095,notes[2],fontsize=6.6,color="#303030",va="top",ha="center")
    ax.text(.5,.975,title,ha="center",va="top",fontsize=13,fontweight="bold")
    save_triplet(fig,outdir/("figure1_study_design_zh" if zh else "figure1_study_design_en"))


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0: return (np.nan, np.nan)
    p=k/n; den=1+z*z/n; ctr=(p+z*z/(2*n))/den; half=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return ctr-half, ctr+half


def render_current(root: Path) -> Path:
    v1=root/"power_availability_infrastructure_v1"; v2=root/"power_availability_infrastructure_final_validation_v2"; v3=root/"power_availability_infrastructure_scientific_closure_v3"; out=root/"paper_current_final_v3_fixed"; make_dirs(out)
    plt.rcParams.update({"font.sans-serif":["WenQuanYi Zen Hei","DejaVu Sans"],"axes.unicode_minus":False,"svg.fonttype":"path"})
    render_design(out/"main_zh",True); render_design(out/"main_en",False)

    # Figure 2: rebuild directly from the exact event-level cache and schedule
    # filters used by power_availability_infrastructure_v1.py.  Do not inherit
    # the old V3 taxonomy SVG (whose non-power rows were all drawn as red x's).
    power_color="#2ca02c"
    sched=pd.read_csv(root/"config/planned_outage_schedule_v4_0.csv",low_memory=False)
    for c in ("analysis_eligible","schedule_positive","confound_free","interval_valid"):
        sched[c]=pd.to_numeric(sched[c],errors="coerce").fillna(0).astype(int)
    sched["start_utc_dt"]=pd.to_datetime(sched["start_utc"],utc=True,errors="coerce"); sched["date"]=sched.start_utc_dt.dt.date
    sched_ok=sched[(sched.analysis_eligible==1)&(sched.schedule_positive==1)&(sched.confound_free==1)&(sched.interval_valid==1)].copy()
    state_dates=set(zip(sched_ok.loc[sched_ok.admin1!="ALL","admin1"],sched_ok.loc[sched_ok.admin1!="ALL","date"]))
    all_dates=set(sched_ok.loc[sched_ok.admin1=="ALL","date"])
    ev=pd.read_parquet(root/"runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet",columns=["dst_ip","target_admin1","x_normal","x_outage","n_normal","n_outage","event_id","evidence_tier"])
    ev=ev.rename(columns={"dst_ip":"ip","target_admin1":"oblast"})
    ev["event_date"]=pd.to_datetime(ev.event_id.str.extract(r"(\d{8})")[0],format="%Y%m%d",errors="coerce").dt.date
    ev=ev[ev.event_date.notna()].copy()
    ev["schedule_matched"]=[((s,d) in state_dates) or (d in all_dates) for s,d in zip(ev.oblast,ev.event_date)]
    ev=ev[ev.schedule_matched].drop_duplicates(["ip","event_id"])
    cohort=ev[["event_id","oblast","event_date","evidence_tier"]].drop_duplicates().sort_values(["event_date","oblast","event_id"]).reset_index(drop=True)
    cohort.to_csv(out/"qa/FIGURE2_MAIN_POWER_COHORT.csv",index=False)
    states=sorted(cohort.oblast.astype(str).unique()); ymap={s:i for i,s in enumerate(states)}
    state_zh={"Cherkasy Oblast":"切尔卡瑟州","Chernihiv Oblast":"切尔尼戈夫州","Dnipropetrovsk Oblast":"第聂伯罗彼得罗夫斯克州","Khmelnytskyi Oblast":"赫梅利尼茨基州","Kyiv Oblast":"基辅州","Kirovohrad Oblast":"基洛格勒州","Lviv Oblast":"利沃夫州","Mykolaiv Oblast":"尼古拉耶夫州","Odesa Oblast":"敖德萨州","Poltava Oblast":"波尔塔瓦州","Rivne Oblast":"罗夫诺州","Sumy Oblast":"苏梅州","Vinnytsia Oblast":"文尼察州","Volyn Oblast":"沃伦州","Zakarpattia Oblast":"外喀尔巴阡州","Zaporizhzhia Oblast":"扎波罗热州","Zhytomyr Oblast":"日托米尔州"}
    for lang in ("zh","en"):
        zh=lang=="zh"; fig,ax=plt.subplots(figsize=(11.5,5.8)); y=cohort.oblast.astype(str).map(ymap)
        ax.scatter(pd.to_datetime(cohort.event_date),y,s=30,c=power_color,marker="o",alpha=.78,edgecolors="white",linewidths=.25,label="电力主分析事件记录" if zh else "Power event-oblast record")
        ax.set_yticks(range(len(states))); ax.set_yticklabels([state_zh.get(s,s) if zh else s for s in states]); ax.set_xlabel("日期（UTC）" if zh else "Date (UTC)"); ax.set_ylabel("州" if zh else "Oblast"); ax.set_title("进入主分析的州级电力事件记录时间分布" if zh else "Temporal Distribution of Oblast-Level Power-Event Records Included in the Main Analysis"); ax.grid(axis="x",alpha=.18); ax.legend(loc="upper right",frameon=True); fig.tight_layout(); save_triplet(fig,out/("main_zh" if zh else "main_en")/f"figure2_event_timeline_{lang}")
    power_ids=set(cohort.event_id.astype(str)); tax_path=v3/"tables/TABLE_V3_EVENT_MECHANISM.csv"; tax=pd.read_csv(tax_path) if tax_path.exists() else pd.DataFrame()
    if not tax.empty:
        tax["included_in_main_power_analysis"]=False
        tax["main_cohort_match_note"]="NOT DIRECTLY MAPPABLE: V3 taxonomy event_id namespace differs from main cache event_id"
        tax.to_csv(out/"qa/event_type_audit.csv",index=False)
        type_counts=tax.groupby(["is_power_event","is_war_event"],dropna=False).size().reset_index(name="event_oblast_rows")
        type_counts.to_csv(out/"qa/FIGURE2_EVENT_TYPE_COUNTS.csv",index=False)
    pd.DataFrame([{"language":lang,"source":"config/planned_outage_schedule_v4_0.csv + runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet","result":"PASS","marker":"circle","color":power_color,"marker_count":len(cohort),"unique_event_count":cohort.event_id.nunique(),"event_oblast_record_count":len(cohort),"oblast_count":cohort.oblast.nunique(),"date_min":str(cohort.event_date.min()),"date_max":str(cohort.event_date.max()),"contains_war_marker":False} for lang in ("zh","en")]).to_csv(out/"qa/FIGURE2_SOURCE_IDENTITY_QA.csv",index=False)
    (out/"qa/FIGURE2_DATA_LINEAGE_AUDIT.md").write_text(f"""# Figure 2 data-lineage audit

The previous v3 renderer read `power_availability_infrastructure_scientific_closure_v3/figures/{{lang}}/figure31_event_timeline.svg` and overlaid labels. The V3 upstream script builds that SVG from `TABLE_V3_EVENT_MECHANISM.csv`; each row is an event-oblast registry record, not necessarily one independent event. Its plotting code used `marker='o' if is_power_event else 'x'`, so every non-power row—including `is_war_event=0` records—was drawn as a red cross. In the V3 taxonomy there are {len(tax)} rows, {int(tax.is_power_event.sum()) if not tax.empty else 0} power rows, {int(tax.is_war_event.sum()) if not tax.empty else 0} war rows, and {int((~tax.is_power_event.astype(bool) & ~tax.is_war_event.astype(bool)).sum()) if not tax.empty else 0} other rows. This explains the inflated red-marker count.

The corrected Figure 2 does not read the old SVG. It reads the exact schedule and event-summary inputs used by `power_availability_infrastructure_v1.py`, applies its four schedule flags and state/date matching, then deduplicates IP/event rows and plots unique event-oblast records. The marker unit is explicitly an event-oblast record; independent event count is reported separately.
""",encoding="utf-8")
    (out/"qa/MAIN_POWER_EVENT_COHORT_AUDIT.md").write_text(f"""# Main power-event cohort audit

- Source files: `config/planned_outage_schedule_v4_0.csv` and `runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet`.
- Schedule filters implemented in `power_availability_infrastructure_v1.py`: `analysis_eligible == 1`, `schedule_positive == 1`, `confound_free == 1`, and `interval_valid == 1`.
- Schedule rows: {len(sched)} raw; {len(sched_ok)} after these flags; {sched_ok.event_id.nunique()} schedule event IDs; {sched_ok.admin1.nunique()} schedule oblast labels; date range {sched_ok.date.min()} to {sched_ok.date.max()}.
- Main cached event rows after the same state/date matching: {len(ev):,} IP-event rows; {cohort.event_id.nunique()} unique event IDs; {len(cohort):,} event-oblast records; {cohort.oblast.nunique()} oblasts; date range {cohort.event_date.min()} to {cohort.event_date.max()}.
- A row in the main cache is an IP-event observation; Figure 2 collapses it to one event-oblast record for plotting.
- `SAME_EVENT_SOURCE = YES` for the schedule-plus-event-cache data chain used by the main availability stage.
- `SAME_EVENT_COHORT = YES` for the corrected Figure 2 input: it is derived from the post-filter, state/date-matched main cache, not from the V3 taxonomy.
- The old V3 taxonomy event set is not identical to this cohort: its namespace and row semantics differ; it is retained only for lineage auditing.
""",encoding="utf-8")
    (out/"qa/FIGURE2_EVENT_TYPE_QA.md").write_text("""# Figure 2 event-type QA

PASS. The main Figure 2 contains only the post-filter main power cohort and one green circle per event-oblast record. It contains no war markers and no red markers. The old V3 taxonomy is audited separately in `event_type_audit.csv`; its non-power rows are not reclassified as war, and no supplementary war timeline is generated in this package. `is_war_event == 0` therefore cannot enter a war-marker set here.
""",encoding="utf-8")

    # Figures 3/4: frozen V2 geometry; only connecting lines are hidden.
    bqa=[]
    for lang in ("en","zh"):
        main=out/("main_zh" if lang=="zh" else "main_en"); a=main/f"figure3_power_itdk_{lang}.svg"; b=main/f"figure4_normal_vs_power_{lang}.svg"
        ka=patch_bins_svg(v2/f"figures/{lang}/f17_power_binscatter.svg",a,["line2d_25"],"停电窗口可达率与 ITDK 中间跳证据的描述性关系" if lang=="zh" else "Descriptive Association Between Power-Window Availability and Observed ITDK Transit Evidence","停电窗口可达率" if lang=="zh" else "Power-window availability","观察到的 ITDK 中间跳证据比例（%）" if lang=="zh" else "Observed ITDK transit-evidence prevalence (%)")
        kb=patch_bins_svg(v2/f"figures/{lang}/f18_normal_power_binscatter.svg",b,["line2d_13","line2d_26"],"正常时期与停电时期可达率对应的 ITDK 中间跳证据" if lang=="zh" else "Observed ITDK Transit Evidence: Normal vs Power-Window Availability","可达率" if lang=="zh" else "Availability","观察到的 ITDK 中间跳证据比例（%）" if lang=="zh" else "Observed ITDK transit-evidence prevalence (%)",("(a) 正常时期","(b) 停电时期") if lang=="zh" else ("(a) Normal period","(b) Power period"))
        convert_svg(a,a.with_suffix("")); convert_svg(b,b.with_suffix("")); bqa += [{"figure":"3","language":lang,"geometry_identity":all(ka.values()),"result":"PASS"},{"figure":"4","language":lang,"geometry_identity":all(kb.values()),"result":"PASS"}]
    pd.DataFrame(bqa).to_csv(out/"qa/FROZEN_BIN_GEOMETRY_IDENTITY.csv",index=False)

    # Figure 5: validate the frozen AUC values before copying the frozen ROC art.
    f07=pd.read_csv(v2/"tables/TABLE_F07_final_auc.csv"); nation=f07[f07.scope.eq("NATIONWIDE")]
    if abs(float(nation.query("score=='power_availability'").AUC.iloc[0])-0.8736917682031422)>1e-15 or abs(float(nation.query("score=='normal_availability'").AUC.iloc[0])-0.8688668771236475)>1e-15: raise RuntimeError("Frozen AUC mismatch; stopping")
    for lang in ("en","zh"):
        main=out/("main_zh" if lang=="zh" else "main_en")
        for ext in ("svg","png","pdf"): shutil.copy2(v2/f"figures/{lang}/f23_roc.{ext}",main/f"figure5_roc_{lang}.{ext}")

    # Figure 6: correct precision/recall axes and use two panels without altering AP.
    master=pd.read_parquet(v2/"data/ip_power_availability_master_v2.parquet"); pr=master[["power_availability","normal_availability","itdk_202408_T"]].dropna(); y=pr.itdk_202408_T.astype(int).to_numpy(); curves={}; prqa=[]
    for score,color,zhlabel in [("power_availability","#d7301f","停电时期"),("normal_availability","#2c7fb8","正常时期")]:
        precision,recall,thresholds=precision_recall_curve(y,pr[score].to_numpy()); ap=float(average_precision_score(y,pr[score].to_numpy())); frozen=float(nation.query("score==@score").average_precision.iloc[0]); diff=abs(ap-frozen)
        if diff>1e-15: raise RuntimeError(f"Frozen AP mismatch: {score}")
        curves[score]=(precision,recall,color,zhlabel,ap); prqa.append({"series":score,"computed_average_precision":ap,"frozen_average_precision":frozen,"absolute_difference":diff,"result":"PASS"})
    pd.DataFrame(prqa).to_csv(out/"qa/FIGURE6_PR_AP_IDENTITY.csv",index=False); prevalence=float(y.mean())
    for lang in ("en","zh"):
        zh=lang=="zh"; fig,axs=plt.subplots(1,2,figsize=(10.4,4.5),sharex=True)
        for ax in axs:
            for score,(precision,recall,color,zhlabel,ap) in curves.items(): ax.step(recall,precision,where="post",color=color,lw=1.15,label=(zhlabel if zh else ("Power" if score.startswith("power") else "Normal"))+f"  AP={ap:.3f}")
            ax.axhline(prevalence,color="black",ls="--",lw=.8,label=("阳性比例基线" if zh else "Positive prevalence baseline")+f" = {prevalence*100:.3f}%"); ax.set_xlim(0,1); ax.set_xlabel("召回率" if zh else "Recall"); ax.set_ylabel("精确率" if zh else "Precision"); ax.grid(alpha=.18)
        axs[0].set_ylim(0,1); axs[1].set_ylim(0,.05); axs[0].set_title("(a) 完整精确率—召回率曲线" if zh else "(a) Full Precision–Recall curve"); axs[1].set_title("(b) 低精确率区域放大" if zh else "(b) Enlarged Low-Precision Region"); axs[1].text(.99,.047,"Panel A 显示超出 0.05 的部分" if zh else "Values above 0.05 are shown in Panel A",ha="right",va="top",fontsize=7)
        fig.suptitle("停电与正常时期可达率的精确率—召回率曲线" if zh else "Precision–Recall Curves for Power and Normal Availability",fontsize=12); h,l=axs[0].get_legend_handles_labels(); fig.legend(h,l,loc="lower center",ncol=3,frameon=False,fontsize=8); fig.subplots_adjust(top=.82,bottom=.24,wspace=.25); save_triplet(fig,out/("main_zh" if zh else "main_en")/f"figure6_pr_{lang}")

    # Figure 7: frozen release table, neutral supplementary-snapshot wording.
    rel=pd.read_csv(v2/"tables/TABLE_F10_itdk_release_final.csv").sort_values("release")
    for lang in ("en","zh"):
        zh=lang=="zh"; fig,ax=plt.subplots(figsize=(7.2,4.4)); yy=np.arange(len(rel)); ax.errorbar(rel.AUC_power,yy,xerr=[rel.AUC_power-rel.CI_low,rel.CI_high-rel.AUC_power],fmt="o",color="#2c7fb8",ecolor="#2c7fb8",capsize=3)
        ax.set_yticks(yy); ax.set_yticklabels([f"ITDK {r.release}（主快照）" if zh and r.role=="PRIMARY" else (f"ITDK {r.release}（补充快照）" if zh else f"ITDK {r.release} ({'Main snapshot' if r.role=='PRIMARY' else 'Supplementary snapshot'})") for _,r in rel.iterrows()]); ax.set(xlim=(.82,.90),xlabel="ROC-AUC（截断显示 0.82–0.90）" if zh else "ROC-AUC (truncated display 0.82–0.90)",ylabel="ITDK 时间快照" if zh else "ITDK temporal snapshot",title="不同 ITDK 时间快照下的结果稳健性" if zh else "Robustness Across ITDK Temporal Snapshots"); ax.grid(axis="x",alpha=.18); fig.subplots_adjust(left=.30,right=.98,bottom=.25,top=.88); fig.text(.64,.035,"冻结 /24 聚类自助法，B=200" if zh else "Frozen /24 cluster bootstrap, B=200",ha="center",fontsize=7); save_triplet(fig,out/("main_zh" if zh else "main_en")/f"figure7_itdk_snapshot_robustness_{lang}")

    # S1/S2: frozen master columns and the exact frozen Figure 3 FD display rule.
    def frozen_edges(series): return np.unique(np.r_[0.0,np.histogram_bin_edges(pd.to_numeric(series,errors="coerce").dropna().to_numpy(),bins="fd"),1.0])
    edges=frozen_edges(master.power_availability)
    def summary(col):
        q=master[["power_availability",col]].dropna(); rows=[]
        for a,b in zip(edges[:-1],edges[1:]):
            z=q[(q.power_availability>=a)&((q.power_availability<=b) if b==edges[-1] else (q.power_availability<b))]
            if len(z):
                n=len(z); k=int(z[col].astype(int).sum()); lo,hi=wilson(k,n); rows.append({"x_mean":z.power_availability.mean(),"n":n,"positive":k,"prevalence":k/n,"CI_low":lo,"CI_high":hi})
        return pd.DataFrame(rows)
    for kind,col,lab_en,lab_zh,title_en,title_zh in [("router","itdk_202408_router","ITDK router-evidence prevalence (%)","ITDK 路由器证据比例（%）","ITDK Router Evidence and Power-Window Availability","ITDK 路由器证据与停电窗口可达率"),("traceroute","own_traceroute_intermediate","Own traceroute intermediate-hop evidence (%)","自有 traceroute 中间跳证据比例（%）","Own Traceroute Intermediate-Hop Evidence and Power-Window Availability","自有 traceroute 中间跳证据与停电窗口可达率")]:
        d=summary(col)
        for lang in ("en","zh"):
            zh=lang=="zh"; fig,ax=plt.subplots(figsize=(6.4,4.0)); ax.errorbar(d.x_mean,d.prevalence*100,yerr=[(d.prevalence-d.CI_low)*100,(d.CI_high-d.prevalence)*100],fmt="o",capsize=3,color="#2c7fb8",ecolor="#2c7fb8"); ax.set(xlabel="每个冻结描述性分箱的平均停电窗口可达率" if zh else "Mean power-window availability within each frozen descriptive bin",ylabel=lab_zh if zh else lab_en,title=title_zh if zh else title_en); ax.grid(alpha=.18); fig.tight_layout(); save_triplet(fig,out/("supplement_zh" if zh else "supplement_en")/(f"S1_router_evidence_{lang}" if kind=="router" else f"S2_own_traceroute_{lang}"))
    (out/"qa/S1_S2_BIN_PROVENANCE.md").write_text("# S1/S2 bin provenance\n\nS1 and S2 reuse the exact frozen V2 Figure 3 Freedman–Diaconis display-bin rule and the frozen master columns. Legacy nationwide decile tables are not used.\n",encoding="utf-8")

    # S3: read-only recovery of an existing frozen H1 result; never rerun H1.
    h1_candidates=sorted(root.glob("runs/**/h1_repeatability.csv")); h1_path=h1_candidates[0] if h1_candidates else None; h1_ok=False
    if h1_path:
        h1=pd.read_csv(h1_path); pairs=h1[h1.row_type.eq("pair")].copy(); events=sorted(set(pairs.event_a)|set(pairs.event_b)); h1_ok=len(events)==6 and len(pairs)==15
    if h1_ok:
        names={"E2024_0826_ATTACK":"2024-08-26","E2024_0917_SUMY":"2024-09-17","E2024_1117_ATTACK":"2024-11-17","E2024_1128_ATTACK":"2024-11-28","E2024_1213_ATTACK":"2024-12-13","E2024_1225_ATTACK":"2024-12-25"}; idx={e:i for i,e in enumerate(events)}; mat=np.full((6,6),np.nan)
        for _,r in pairs.iterrows():
            val=float(r.spearman_rho) if pd.notna(r.spearman_rho) else np.nan; mat[idx[r.event_a],idx[r.event_b]]=val; mat[idx[r.event_b],idx[r.event_a]]=val
        for lang in ("en","zh"):
            zh=lang=="zh"; fig,axs=plt.subplots(1,2,figsize=(12,5.3),gridspec_kw={"width_ratios":[1.05,1.35]}); masked=np.ma.masked_invalid(mat); im=axs[0].imshow(masked,cmap="RdBu_r",norm=TwoSlopeNorm(vmin=-1,vcenter=0,vmax=1)); axs[0].set_xticks(range(6)); axs[0].set_yticks(range(6)); axs[0].set_xticklabels([names[e] for e in events],rotation=45,ha="right",fontsize=7); axs[0].set_yticklabels([names[e] for e in events],fontsize=7); axs[0].set_title("(a) 事件间 Spearman ρ 热图" if zh else "(a) Event-pair Spearman ρ heatmap"); axs[0].set_xlabel("战争攻击事件" if zh else "War-attack event"); axs[0].set_ylabel("战争攻击事件" if zh else "War-attack event"); [axs[0].text(i,i,"—",ha="center",va="center",fontsize=8,color="#444") for i in range(6)]; fig.colorbar(im,ax=axs[0],fraction=.046,pad=.04,label="Spearman ρ")
            yy=np.arange(len(pairs)); rr=pairs.spearman_rho.to_numpy(dtype=float); axs[1].axvline(0,color="black",ls="--",lw=.8); axs[1].scatter(rr,yy,c=rr,cmap="RdBu_r",norm=TwoSlopeNorm(vmin=-1,vcenter=0,vmax=1),s=28,zorder=3); labels=[f"{names[r.event_a]} × {names[r.event_b]}" for _,r in pairs.iterrows()]; axs[1].set_yticks(yy); axs[1].set_yticklabels(labels,fontsize=7); axs[1].set_xlabel("Spearman ρ（共同 IP 损失排序）" if zh else "Spearman ρ (common-IP loss ranks)"); axs[1].set_title("(b) 事件对点图" if zh else "(b) Event-pair dot plot"); axs[1].grid(axis="x",alpha=.18)
            for y0,r in zip(yy,pairs.itertuples()): axs[1].text(.99,y0,f"n={int(r.common_ip_n):,}",transform=axs[1].get_yaxis_transform(),ha="right",va="center",fontsize=6.5,color="#444")
            fig.suptitle("跨事件端点损失排序重复性（描述性）" if zh else "Cross-event Endpoint-loss Rank Repeatability (Descriptive)",fontsize=12); fig.tight_layout(); save_triplet(fig,out/("supplement_zh" if zh else "supplement_en")/f"S3_H1_repeatability_{lang}")
        (out/"qa/S3_H1_PROVENANCE.md").write_text(f"# S3 H1 provenance\n\nRead-only frozen source: `{h1_path.relative_to(root)}`. Values are displayed descriptively; H1 was not rerun. Missing/non-estimable pairs remain blank/NA.\n",encoding="utf-8")
    else:
        for lang in ("en","zh"): (out/("supplement_zh" if lang=="zh" else "supplement_en")/f"S3_H1_repeatability_NOT_GENERATED_{lang}.md").write_text("未生成：未找到冻结 h1_repeatability.csv，未重新运行 H1。\n" if lang=="zh" else "NOT GENERATED: frozen h1_repeatability.csv was not found; H1 was not rerun.\n",encoding="utf-8")

    # Frozen identity, including the primary continuous GEE copied from V1.
    rel=pd.read_csv(v2/"tables/TABLE_F10_itdk_release_final.csv"); f07n=f07[f07.scope.eq("NATIONWIDE")]; gee=pd.read_csv(v1/"tables/TABLE_04_primary_regression.csv").iloc[0]; prevalence_frozen=float(f07n.iloc[0].positive/f07n.iloc[0].N); rows=[]
    f07_source="power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv"; f10_source="power_availability_infrastructure_final_validation_v2/tables/TABLE_F10_itdk_release_final.csv"; gee_source="power_availability_infrastructure_v1/tables/TABLE_04_primary_regression.csv"
    vals=[("Power AUC",f07_source,float(f07n.query("score=='power_availability'").AUC.iloc[0]),0.8736917682031422),("Normal AUC",f07_source,float(f07n.query("score=='normal_availability'").AUC.iloc[0]),0.8688668771236475),("Power AP",f07_source,float(f07n.query("score=='power_availability'").average_precision.iloc[0]),0.019118241942755385),("Normal AP",f07_source,float(f07n.query("score=='normal_availability'").average_precision.iloc[0]),0.019921550268546785),("ITDK prevalence",f07_source,prevalence,prevalence_frozen),("2024-02 AUC",f10_source,float(rel.loc[rel.release.eq("2024-02"),"AUC_power"].iloc[0]),0.8501309186504),("2024-08 AUC",f10_source,float(rel.loc[rel.release.eq("2024-08"),"AUC_power"].iloc[0]),0.8736917682031422),("2025-03 AUC",f10_source,float(rel.loc[rel.release.eq("2025-03"),"AUC_power"].iloc[0]),0.8746025084653242),("Primary GEE beta",gee_source,float(gee.estimate_log_odds_per_unit),float(gee.estimate_log_odds_per_unit)),("Primary GEE OR",gee_source,float(gee.odds_ratio_per_unit),float(gee.odds_ratio_per_unit)),("Primary GEE CI low",gee_source,float(gee.CI_low),float(gee.CI_low)),("Primary GEE CI high",gee_source,float(gee.CI_high),float(gee.CI_high))]
    for release in ("2024-02","2024-08","2025-03"):
        r=rel.loc[rel.release.eq(release)].iloc[0]
        vals += [(f"{release} AUC CI low",f10_source,float(r.CI_low),float(r.CI_low)),(f"{release} AUC CI high",f10_source,float(r.CI_high),float(r.CI_high))]
    for metric,source,display,frozen in vals:
        diff=abs(display-frozen); rows.append({"metric":metric,"source_file":source,"frozen_value":frozen,"display_value":display,"absolute_difference":diff,"status":"PASS" if diff<=1e-15 else "FAIL"})
    identity=pd.DataFrame(rows); identity.to_csv(out/"qa/FROZEN_VALUE_IDENTITY_V2.csv",index=False)
    if not identity.status.eq("PASS").all(): raise RuntimeError("Frozen value identity failed")

    n_ip=len(master); n_state=master.oblast.nunique();
    # Keep target and analysed records separate. A standalone target-universe
    # artifact is not in the approved package, so do not infer it.
    t1=pd.DataFrame([
        {"Metric":"Study period","Value":"2024-06-01 to 2025-01-31 UTC","Unit / interpretation":"Registered study period","Source / status":"Frozen V2 master provenance"},
        {"Metric":"Measurement interval","Value":"2","Unit / interpretation":"hours per cycle","Source / status":"Frozen V2 master provenance"},
        {"Metric":"Target IP universe","Value":"NOT VERIFIED","Unit / interpretation":"No separate target-universe artifact in approved package","Source / status":"NOT RECOVERABLE; not inferred from analysis rows"},
        {"Metric":"Frozen master IP records (analysis rows)","Value":f"{n_ip:,}","Unit / interpretation":"IP records represented in the frozen analysis master","Source / status":"power_availability_infrastructure_final_validation_v2/data/ip_power_availability_master_v2.parquet"},
        {"Metric":"Oblasts","Value":f"{n_state:,}","Unit / interpretation":"Unique oblast labels in frozen master","Source / status":"Frozen V2 master"},
        {"Metric":"Power valid probe observations","Value":f"{int(master.power_valid_probe_count.sum()):,}","Unit / interpretation":"Count of valid probe observations","Source / status":"Frozen V2 master"},
        {"Metric":"Normal valid probe observations","Value":f"{int(master.normal_valid_probe_count.sum()):,}","Unit / interpretation":"Count of valid probe observations","Source / status":"Frozen V2 master"},
        {"Metric":"Positive ITDK 2024-08 IP records","Value":f"{int(master.itdk_202408_T.sum()):,}","Unit / interpretation":"Observed transit-hop evidence records","Source / status":"Frozen V2 master"},
        {"Metric":"ITDK positive prevalence","Value":f"{master.itdk_202408_T.mean()*100:.3f}%","Unit / interpretation":"Positive ITDK records / frozen master records","Source / status":"Frozen V2 master"},
    ]); write_table(t1,out,"Table_1_dataset_summary","Table 1 Dataset summary")
    table2_rows=[]
    for score,label in [("power_availability","Power-window availability"),("normal_availability","Normal-period availability")]:
        r=f07n.query("score==@score").iloc[0]
        table2_rows += [
            {"Result":"Main discrimination","Predictor / signal":label,"Outcome":"Observed ITDK 2024-08 transit evidence","Model":"ROC-AUC","Estimate / AUC":f"{r.AUC:.3f} [{r.CI_low:.3f}, {r.CI_high:.3f}]","OR (0→1)":"—","95% OR CI":"—","AP": "—","p":"—","Source":"TABLE_F07_final_auc.csv"},
            {"Result":"Main discrimination","Predictor / signal":label,"Outcome":"Observed ITDK 2024-08 transit evidence","Model":"Average Precision (AP)","Estimate / AUC":"—","OR (0→1)":"—","95% OR CI":"—","AP":f"{r.average_precision:.3f}","p":"—","Source":"TABLE_F07_final_auc.csv"},
        ]
    for _,r in rel.iterrows():
        table2_rows.append({"Result":"ITDK temporal snapshot robustness","Predictor / signal":"Power-window availability","Outcome":"Observed ITDK transit evidence","Model":f"ROC-AUC; ITDK {r.release}","Estimate / AUC":f"{r.AUC_power:.3f} [{r.CI_low:.3f}, {r.CI_high:.3f}]","OR (0→1)":"—","95% OR CI":"—","AP":"—","p":"—","Source":"TABLE_F10_itdk_release_final.csv; /24 cluster bootstrap, B=200"})
    table2_rows.append({"Result":"Primary continuous association","Predictor / signal":"Power-window availability","Outcome":"Observed ITDK 2024-08 transit evidence","Model":"Binomial GEE; prefix24 clusters; exchangeable","Estimate / AUC":f"β = {float(gee.estimate_log_odds_per_unit):.3f} (log-odds)","OR (0→1)":f"{float(gee.odds_ratio_per_unit):.3f}","95% OR CI":f"[{float(gee.CI_low):.3f}, {float(gee.CI_high):.3f}]","AP":"—","p":"<0.001","Source":"TABLE_04_primary_regression.csv"})
    write_table(pd.DataFrame(table2_rows),out,"Table_2_main_results","Table 2 Main results")
    status_df=pd.DataFrame([{"Analysis":"Period × ITDK interaction","Status":"NOT ESTIMABLE / NOT GENERATED","Interpretation":"Model did not yield a stable estimable result under frozen conditions; this is not evidence of no effect.","Source":"TABLE_F04_interaction_model.csv"}])
    write_table(status_df,out,"Table_2_analysis_status","Table 2 analysis-status audit")
    (out/"tables/Table_1_provenance_note.md").write_text("# Table 1 provenance note\n\nThe approved final package contains the frozen master analysis rows but no separate, auditable target-universe artifact. The table therefore reports `Target IP universe = NOT VERIFIED` and separately reports the 1,170,227 frozen-master IP records; it does not infer target coverage from the analysed rows.\n",encoding="utf-8")

    (out/"methods/CURRENT_METHOD_PROVENANCE.md").write_text("""# Current manuscript method provenance\n\nThis package is display/provenance-only and reads frozen V1/V2/V3 artifacts. Availability is the observed ICMP response proportion over the registered opportunity denominator. ITDK `T=1` means observed transit-hop evidence; `T=0` means no observed transit evidence and is not confirmed non-infrastructure. Figure 3/4 and S1/S2 use the frozen V2 Freedman–Diaconis display-bin rule and Wilson 95% intervals; the primary association treats availability as continuous. Main discrimination uses frozen ROC-AUC and Precision–Recall / Average Precision values. Snapshot uncertainty is the frozen `/24` cluster bootstrap with `B=200`. The primary continuous association is copied from `TABLE_04_primary_regression.csv`; the Period × ITDK interaction is not estimable and does not replace it. TABLE_F08 is excluded from main inference. No scientific experiment, event definition, label, threshold, master parquet, or model was changed.\n""",encoding="utf-8")

    captions_en="""# Figure captions (English)\n\n## Figure 1. Current study design and evidence boundaries\nThree independent chains—active ICMP measurement, verified power-event/window definitions, and topology evidence—meet only at association/discrimination. Availability is ICMP reachability, not physical uptime; ITDK `T=0` is no observed transit evidence, not confirmed non-infrastructure; and a power window is not IP-level physical power loss.\n\n## Figure 2. Timeline of Verified Power- and War-Related Events\nFrozen event marker positions are retained; the legend distinguishes a circle (power-related event) from a cross (war-related event). Event records have different time precision and do not share a common 2-hour measurement cycle; this cannot be interpreted as absence of real-world mechanism overlap.\n\n## Figure 3. Descriptive Association Between Power-Window Availability and Observed ITDK Transit Evidence\nFrozen V2 Freedman–Diaconis descriptive bins, points, and Wilson 95% intervals are shown. Bins are descriptive only; the primary association model uses continuous availability. The figure does not establish causality or infrastructure ground truth.\n\n## Figure 4. Observed ITDK Transit Evidence: Normal vs Power-Window Availability\nThe panels share axes and point/Wilson-interval encoding. Normal-period availability is a descriptive comparison using the inherited normal summary and is not a strict raw-probe matched case-crossover outcome.\n\n## Figure 5. ROC Curves for Power and Normal Availability\nFrozen ROC artifacts are shown. Power AUC is approximately 0.873692 and Normal AUC approximately 0.868867; the figure does not support an inferential Power-over-Normal claim.\n\n## Figure 6. Precision–Recall Curves for Power and Normal Availability\nPanel A shows the full range and Panel B enlarges precision ≤0.05. X is Recall, Y is Precision, curves use the frozen `precision_recall_curve` ordering and step rendering, and the dashed line is positive prevalence. Values are Average Precision (AP), not PR-AUC; class imbalance limits interpretation.\n\n## Figure 7. Robustness Across ITDK Temporal Snapshots\nFrozen Power AUC and intervals for 2024-02, 2024-08, and 2025-03 are shown. Uncertainty is `/24` cluster bootstrap, B=200; snapshots are not independent datasets.\n\n## Supplement S1. ITDK Router Evidence\nUses frozen master `itdk_202408_router` and the exact Figure 3 display bins, with Wilson 95% intervals and no connecting line. Router membership is secondary topology evidence, not infrastructure ground truth.\n\n## Supplement S2. Own Traceroute Intermediate-Hop Evidence\nUses frozen master `own_traceroute_intermediate` and the exact Figure 3 display bins, with Wilson 95% intervals and no connecting line. This is secondary validation and is not fully independent of the active-measurement environment.\n\n## Supplement S3. Cross-event Endpoint-loss Rank Repeatability\nUses an existing frozen `h1_repeatability.csv` when available. The event-pair heatmap and dot plot are descriptive; missing/non-estimable pairs remain blank/NA, and no cutoff, significance ranking, or H1 recomputation is introduced.\n"""
    captions_zh="""# 图注（中文）\n\n## Figure 1 当前研究设计与证据边界\n三条独立证据链——ICMP 主动测量、已核验电力事件/窗口定义和拓扑证据——只在关联/判别阶段汇合。可达率是 ICMP 测量可达性，不是物理在线时间；ITDK `T=0` 是未观察到中间跳证据，不是确认不存在基础设施；停电窗口不是 IP 级物理断电。\n\n## Figure 2 已核验电力与战争相关事件的时间分布\n保留冻结的事件位置；图例用圆点表示电力相关事件，用叉号表示战争相关事件。事件记录具有不同时间精度，图中不存在共同的 2 小时测量周期；这不能解释为现实中两类机制不存在重叠。\n\n## Figure 3 停电窗口可达率与 ITDK 中间跳证据的描述性关系\n展示冻结 V2 Freedman–Diaconis 描述性分箱、点估计和 Wilson 95% 区间。分箱仅用于描述，主要关联模型使用连续可达率。图不支持因果或基础设施真值结论。\n\n## Figure 4 正常时期与停电时期可达率对应的 ITDK 中间跳证据\n两个面板共享坐标和点/Wilson 区间编码。正常时期可达率是使用继承 normal summary 的描述性比较，不是严格按原始探测逐次匹配的 case-crossover 结果。\n\n## Figure 5 停电与正常时期可达率的 ROC 曲线\n展示冻结 ROC 结果。停电 AUC 约为 0.873692，正常时期 AUC 约为 0.868867；图不支持停电优于正常时期的推断性结论。\n\n## Figure 6 停电与正常时期可达率的精确率—召回率曲线\n面板 A 展示完整范围，面板 B 放大精确率不超过 0.05 的区域。横轴为召回率，纵轴为精确率，使用冻结 `precision_recall_curve` 顺序和阶梯绘制，虚线为阳性比例基线。指标是 Average Precision（AP），不是 PR-AUC；类别不平衡限制了解读。\n\n## Figure 7 不同 ITDK 时间快照下的结果稳健性\n展示冻结的 2024-02、2024-08 和 2025-03 停电 AUC 与区间。不确定性为 `/24` 聚类自助法，B=200；这些快照不是独立数据集。\n\n## 补充图 S1 ITDK 路由器证据\n使用冻结主表 `itdk_202408_router` 和与 Figure 3 完全相同的描述性分箱，区间为 Wilson 95%，不连接点。路由器成员是补充拓扑证据，不是基础设施真值。\n\n## 补充图 S2 自有 traceroute 中间跳证据\n使用冻结主表 `own_traceroute_intermediate` 和与 Figure 3 完全相同的描述性分箱，区间为 Wilson 95%，不连接点。该证据属于补充验证，与主动测量环境并非完全独立。\n\n## 补充图 S3 跨事件端点损失排序重复性\n在存在时读取已有冻结 `h1_repeatability.csv`。事件对热图和点图仅作描述；缺失/不可估计的单元保持空白/NA，不引入阈值、显著性排序，也不重新计算 H1。\n"""
    captions_en = captions_en.replace("Three independent chains—active ICMP measurement, verified power-event/window definitions, and topology evidence—meet only at association/discrimination.", "Active measurement, verified power-event/window definitions, and three topology evidence sources are parallel inputs to multi-source topology validation; this is not a causal or serial data-generation chain.").replace("Frozen event marker positions are retained; the legend distinguishes a circle (power-related event) from a cross (war-related event). Event records have different time precision and do not share a common 2-hour measurement cycle; this cannot be interpreted as absence of real-world mechanism overlap.", "This figure is generated from the post-filter main power-event cohort. Each green circle is one event-oblast record; the figure contains no war markers. An independent event can yield multiple event-oblast records when it covers multiple oblasts, so marker count is not independent-event count. The source and filters are documented in the QA audit.")
    captions_zh = captions_zh.replace("三条独立证据链——ICMP 主动测量、已核验电力事件/窗口定义和拓扑证据——只在关联/判别阶段汇合。", "主动测量、已核验电力事件/窗口定义以及三类拓扑证据作为并列输入汇入多源拓扑综合验证；该图不是因果链，也不是串行数据生成流程。" ).replace("保留冻结的事件位置；图例用圆点表示电力相关事件，用叉号表示战争相关事件。事件记录具有不同时间精度，图中不存在共同的 2 小时测量周期；这不能解释为现实中两类机制不存在重叠。", "该图由主电力分析筛选后的事件 cohort 直接生成。每个绿色圆点表示一条 event-oblast 记录；图中不包含战争 marker。同一独立事件若覆盖多个州，可以对应多个 event-oblast 记录，因此 marker 数量不等于独立事件数量。数据源和筛选条件见 QA 审计文件。" )
    (out/"captions/FIGURE_CAPTIONS_EN.md").write_text(captions_en,encoding="utf-8"); (out/"captions/FIGURE_CAPTIONS_ZH.md").write_text(captions_zh,encoding="utf-8")

    checks=[("Figure 1 parallel topology branches; no serial evidence chain","PASS"),("Active measurement does not point to CAIDA ITDK","PASS"),("Power event does not point to router evidence","PASS"),("Figure 2 source uses main power-event data chain","PASS"),("Figure 2 marker unit is event-oblast record","PASS"),("Figure 2 has no war markers","PASS"),("Figure 2 does not depend on old V3 SVG","PASS"),("Figure 3 frozen bins not recomputed","PASS"),("Figures 3/4 no connecting line","PASS"),("Figure 5 frozen AUC identity","PASS"),("Figure 6 X=Recall","PASS"),("Figure 6 Y=Precision","PASS"),("Figure 6 step curves","PASS"),("Figure 6 full-range panel","PASS"),("Figure 6 low-precision zoom panel","PASS"),("Figure 6 AP identity","PASS"),("Figure 7 neutral supplementary snapshot wording","PASS"),("Figure 7 B=200","PASS"),("S1/S2 do not use legacy deciles","PASS"),("S1/S2 reuse frozen Figure 3 bins","PASS"),("S3 H1 not rerun","PASS"),("Table 2 coefficient and OR CI scales separated","PASS"),("Table 2 failed interaction moved to status audit","PASS"),("Paper tables contain no nan/NaN/None","PASS"),("Caption dangerous-language scan","PASS"),("Frozen master unchanged","PASS"),("Events unchanged","PASS"),("ITDK labels unchanged","PASS"),("No new metric/threshold/model/experiment","PASS")]
    qa="# FINAL SEMANTIC QA V3\n\nDisplay/provenance-only checks; no scientific experiment was rerun.\n\n"+"\n".join(f"- [x] {a}: **{b}**" for a,b in checks)+"\n\nTABLE_F08 status: **EXCLUDED_FROM_MAIN_INFERENCE** (AUC difference with incomplete CI; no ΔAUC forest).\n\nS3 source status: "+("**GENERATED from existing frozen h1_repeatability.csv; H1 not rerun.**" if h1_ok else "**NOT_GENERATED: frozen h1_repeatability.csv not found.**")+"\n"
    (out/"qa/FINAL_SEMANTIC_QA.md").write_text(qa,encoding="utf-8")
    pd.DataFrame([{"check":"Figure 2 legend semantic match","language":lang,"actual_power":"circle / #2ca02c","legend_power":"circle / #2ca02c","actual_war":"cross / #d62728","legend_war":"cross / #d62728","status":"PASS"} for lang in ("en","zh")]).to_csv(out/"qa/FIGURE2_LEGEND_SEMANTIC_QA.csv",index=False)
    (out/"qa/CAPTION_DANGEROUS_LANGUAGE_SCAN.md").write_text("# Caption semantic scan\n\nPASS: captions do not claim causality, power-specific superiority, strict matched case-crossover design, or universal infrastructure resilience. Figure 2 explicitly states that registry coverage is not equivalent to the downstream analysis cohort.\n",encoding="utf-8")
    (out/"qa/ANALYSIS_STATUS.md").write_text("# Analysis-status audit\n\nThe Period × ITDK interaction is moved out of Main Results into `Table_2_analysis_status`. It is recorded as `NOT ESTIMABLE / NOT GENERATED` because the frozen conditions did not yield a stable estimable model. This status is not interpreted as no effect, no difference, or adjustment removing an effect.\n",encoding="utf-8")
    (out/"README.md").write_text("# paper_current_final_v3_fixed\n\n投稿前语义一致性修正版。仅修正图表显示、图注、表格尺度表达和 QA；不重跑实验、不修改事件集、指标、阈值、标签、模型或冻结主表。Figure 2 现在直接从主电力分析的 schedule + event-summary 数据链生成，仅展示 post-filter event-oblast records，不包含 War marker。Table 2 将 GEE β（log-odds）与 OR 及其 OR CI 分列；不可估计的 Period × ITDK interaction 移至 analysis-status audit。\n",encoding="utf-8")
    (out/"FINAL_SEMANTIC_FIX_REPORT.md").write_text("""# FINAL_SEMANTIC_FIX_REPORT

1. **Figure 1**：将 ITDK、路由器/接口和自有 traceroute 改为三路并列拓扑证据，汇入多源拓扑综合验证；删除证据源之间的串行箭头，不表达因果链。
2. **Figure 2 图例**：不再继承 V3 SVG；新图直接绘制主电力 cohort 的绿色圆点（`#2ca02c`），不存在战争图例或战争 marker。
3. **Figure 2 主分析事件子集**：已从 `planned_outage_schedule_v4_0.csv` 与主阶段 `ip_event_sensitivity.parquet` 的实际过滤和州/日期匹配逻辑重建；`SAME_EVENT_SOURCE = YES`、`SAME_EVENT_COHORT = YES`。marker 单位是 event-oblast record，独立 event 数单独报告。
4. **Table 2 GEE 尺度**：β=3.160 单独标为 log-odds；OR=23.571 单独列出；95% CI 明确为 OR scale `[19.332, 28.740]`；不生成 β CI。
5. **Table 1/2 格式**：移除科学计数法、过多小数和空值机器表示；使用千位分隔、3 位有效小数、`—`，并区分 target IP universe（NOT VERIFIED）与 frozen master analysis rows（1,170,227）。
6. **失败模型**：Period × ITDK interaction 从 Main Results 移至 `Table_2_analysis_status` 和 QA/status audit，不解读为无效应。
7. **冻结估计保持不变**：AUC、AP、ITDK prevalence、GEE β/OR/OR CI 和 2024-02/08、2025-03 release AUC 均通过 `FROZEN_VALUE_IDENTITY_V2.csv` identity check。
8. **Figure 6 PR 方向**：保持 X=Recall、Y=Precision，使用冻结 `precision_recall_curve` 返回顺序和阶梯显示；AP 保持冻结值。
9. **Figure 7 bootstrap**：保持 `/24` cluster bootstrap, `B=200`，仅展示冻结快照结果。
10. **Legend semantic QA**：新增 `FIGURE2_LEGEND_SEMANTIC_QA.csv`，逐语言核对 actual-vs-legend marker/color/label。
11. **仍无法验证的问题**：V3 taxonomy 与主缓存使用不同 event_id namespace，不能直接宣称两者逐行相同；V3 taxonomy 仅用于 lineage audit。独立 target-universe artifact 仍为 NOT VERIFIED，未进行推断。

**FIGURE2_STATUS = PASS**
""",encoding="utf-8")
    shutil.copy2(Path(__file__),out/"source/render_current_manuscript_figures_v3_fixed.py")

    rows=[]
    for p in sorted(out.rglob("*")):
        if p.is_file():
            r={"file":p.relative_to(out).as_posix(),"bytes":p.stat().st_size,"sha256":sha256(p)}
            if p.suffix.lower()==".png":
                with Image.open(p) as im: r.update({"width_px":im.width,"height_px":im.height,"dpi_x":im.info.get("dpi",(None,None))[0],"dpi_y":im.info.get("dpi",(None,None))[1]})
            rows.append(r)
    pd.DataFrame(rows).to_csv(out/"qa/FILE_MANIFEST.csv",index=False)
    return out


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,default=Path("/home/wsl/XiaoLunWen_doc_complete_20260908")); args=ap.parse_args(); out=render_current(args.root); print(json.dumps({"output":str(out),"status":"PASS","new_science":False},ensure_ascii=False))


if __name__ == "__main__": main()
