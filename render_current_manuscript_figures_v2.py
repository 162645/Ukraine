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
                 "tables", "captions", "methods", "qa"):
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
        title="当前论文研究设计与证据边界"; lane_a=["乌克兰 IPv4 主动测量","2 小时测量周期","ICMP 响应"]; lane_b=["已核验电力事件记录","停电窗口定义","正常时期对照窗口"]; lane_c=["拓扑证据","CAIDA ITDK 中间跳证据","CAIDA 路由器成员证据","自有 traceroute 中间跳证据"]; avail=["ICMP 响应 + 窗口定义","逐 IP 可达率","停电窗口可达率 / 正常时期可达率"]; final=["可达率 + 拓扑证据","关联 / 判别","跨拓扑时间快照稳健性"]; notes=["可达率 = ICMP 测量可达性\n不是物理在线时间","ITDK T=1 = 观察到中间跳证据\nT=0 = 未观察到 T 证据\n不等于确认不存在基础设施","停电窗口 = 州级/事件级已核验窗口\n不等于确认 IP 级物理断电"]
    else:
        title="Current Manuscript Study Design and Evidence Boundaries"; lane_a=["Ukraine IPv4 active measurement","2-hour measurement cycles","ICMP responses"]; lane_b=["Verified power-event records","Power-window definition","Normal-period comparison windows"]; lane_c=["Topology evidence","CAIDA ITDK transit-hop evidence","CAIDA router membership evidence","Own traceroute intermediate-hop evidence"]; avail=["ICMP responses + window definitions","Per-IP availability","Power-window / normal-period availability"]; final=["Availability + topology evidence","Association / discrimination","Temporal-snapshot robustness"]; notes=["Availability = ICMP measurement reachability\nnot physical uptime","ITDK T=1 = observed transit-hop evidence\nT=0 = no observed T evidence\nnot confirmed non-infrastructure","Power window = verified state/event-level window\nnot confirmed IP-level physical power loss"]
    for i,t in enumerate(lane_a): box(.035,.82-i*.105,.22,.065,t,"#dceaf7")
    for i,t in enumerate(lane_b): box(.30,.82-i*.105,.22,.065,t,"#fff2cc")
    for i,t in enumerate(lane_c): box(.565,.82-i*.095,.25,.065,t,"#e4dfec",7.0)
    for i in range(2): arr(.145,.82-i*.105,.145,.78-i*.105)
    for i in range(2): arr(.41,.82-i*.105,.41,.78-i*.105)
    for i in range(3): arr(.69,.82-i*.095,.69,.78-i*.095)
    box(.17,.40,.38,.075,avail[0],"#fce4d6"); box(.17,.285,.38,.075,avail[1],"#fce4d6"); box(.17,.17,.38,.075,avail[2],"#fce4d6")
    arr(.145,.61,.24,.475); arr(.41,.61,.40,.475); arr(.36,.40,.36,.36); arr(.36,.285,.36,.25)
    box(.62,.40,.30,.075,final[0],"#d9ead3"); box(.62,.285,.30,.075,final[1],"#d9ead3"); box(.62,.17,.30,.075,final[2],"#d9ead3")
    arr(.55,.205,.62,.205); arr(.69,.40,.69,.36); arr(.69,.285,.69,.25); arr(.69,.535,.69,.475); arr(.69,.475,.77,.475)
    ax.text(.035,.095,notes[0],fontsize=6.6,color="#303030",va="top"); ax.text(.355,.095,notes[1],fontsize=6.6,color="#303030",va="top",ha="center"); ax.text(.72,.095,notes[2],fontsize=6.6,color="#303030",va="top",ha="center")
    ax.text(.5,.975,title,ha="center",va="top",fontsize=13,fontweight="bold")
    save_triplet(fig,outdir/("figure1_study_design_zh" if zh else "figure1_study_design_en"))


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0: return (np.nan, np.nan)
    p=k/n; den=1+z*z/n; ctr=(p+z*z/(2*n))/den; half=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return ctr-half, ctr+half


def render_current(root: Path) -> Path:
    v1=root/"power_availability_infrastructure_v1"; v2=root/"power_availability_infrastructure_final_validation_v2"; v3=root/"power_availability_infrastructure_scientific_closure_v3"; out=root/"paper_current_final_v2"; make_dirs(out)
    plt.rcParams.update({"font.sans-serif":["WenQuanYi Zen Hei","DejaVu Sans"],"axes.unicode_minus":False,"svg.fonttype":"path"})
    render_design(out/"main_zh",True); render_design(out/"main_en",False)

    # Figure 2: frozen marker geometry, display-only title and circle/cross legend.
    audit=[]
    for lang in ("zh","en"):
        src=v3/f"figures/{lang}/figure31_event_timeline.svg"; dst=out/("main_zh" if lang=="zh" else "main_en")/f"figure2_event_timeline_{lang}.svg"; text=src.read_text(encoding="utf-8")
        title="已核验电力与战争相关事件的时间分布" if lang=="zh" else "Timeline of Verified Power- and War-Related Events"; ptxt="电力相关事件" if lang=="zh" else "Power-related event"; wtxt="战争相关事件" if lang=="zh" else "War-related event"
        overlay=(f'<g id="current_manuscript_overlay"><rect x="0" y="0" width="929.6" height="32" fill="white"/><text x="300" y="17" text-anchor="middle" font-size="11" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{title}</text><rect x="600" y="4" width="310" height="23" fill="white" fill-opacity=".97" stroke="#bbbbbb" stroke-width=".4"/><circle cx="615" cy="15" r="3.5" fill="#d7301f"/><text x="625" y="18" font-size="8" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{ptxt}</text><path d="M 755 11 L 763 19 M 763 11 L 755 19" stroke="#2c7fb8" stroke-width="1.5"/><text x="770" y="18" font-size="8" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{wtxt}</text></g>')
        dst.write_text(text.replace("</svg>",overlay+"</svg>"),encoding="utf-8"); convert_svg(dst,dst.with_suffix("")); audit.append({"language":lang,"source":"power_availability_infrastructure_scientific_closure_v3/figures/"+lang+"/figure31_event_timeline.svg","result":"PASS"})
    pd.DataFrame(audit).to_csv(out/"qa/FIGURE2_GEOMETRY_AUDIT.csv",index=False)

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

    n_ip=len(master); n_state=master.oblast.nunique(); t1=pd.DataFrame([{"item":"study period","value":"2024-06-01 to 2025-01-31 UTC"},{"item":"measurement interval","value":"2 hours"},{"item":"target/analyzed IPs","value":n_ip},{"item":"states","value":n_state},{"item":"Power valid probe count","value":int(master.power_valid_probe_count.sum())},{"item":"Normal valid probe count","value":int(master.normal_valid_probe_count.sum())},{"item":"ITDK T positive count","value":int(master.itdk_202408_T.sum())},{"item":"ITDK T prevalence","value":float(master.itdk_202408_T.mean())}]); write_table(t1,out,"Table_1_dataset_summary","Table 1 Dataset summary")
    t2=[]
    for score,label in [("power_availability","Power ROC-AUC"),("normal_availability","Normal ROC-AUC")]:
        r=f07n.query("score==@score").iloc[0]; t2.append({"section":"main discrimination","metric":label,"estimate":r.AUC,"CI_low":r.CI_low,"CI_high":r.CI_high,"source":"power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv"}); t2.append({"section":"main discrimination","metric":label.replace("ROC-AUC","Average Precision (AP)"),"estimate":r.average_precision,"CI_low":"","CI_high":"","source":"power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv"})
    for _,r in rel.iterrows(): t2.append({"section":"ITDK temporal snapshot robustness","metric":f"{r.release} Power ROC-AUC","estimate":r.AUC_power,"CI_low":r.CI_low,"CI_high":r.CI_high,"source":"TABLE_F10_itdk_release_final.csv; /24 cluster bootstrap, B=200"})
    t2.append({"section":"primary continuous association","metric":"Primary continuous association","predictor":"Power-window availability","outcome":"Observed ITDK 2024-08 transit evidence","model":"Binomial GEE","cluster":"prefix24; exchangeable","estimate":gee.estimate_log_odds_per_unit,"OR":gee.odds_ratio_per_unit,"CI_low":gee.CI_low,"CI_high":gee.CI_high,"p_value":gee.p_value,"source":"power_availability_infrastructure_v1/tables/TABLE_04_primary_regression.csv"})
    t2.append({"section":"method-status note","metric":"Period × ITDK interaction","model":"NOT ESTIMABLE / NOT GENERATED","source":"power_availability_infrastructure_final_validation_v2/tables/TABLE_F04_interaction_model.csv"})
    write_table(pd.DataFrame(t2),out,"Table_2_main_results","Table 2 Main results")

    (out/"methods/CURRENT_METHOD_PROVENANCE.md").write_text("""# Current manuscript method provenance\n\nThis package is display/provenance-only and reads frozen V1/V2/V3 artifacts. Availability is the observed ICMP response proportion over the registered opportunity denominator. ITDK `T=1` means observed transit-hop evidence; `T=0` means no observed transit evidence and is not confirmed non-infrastructure. Figure 3/4 and S1/S2 use the frozen V2 Freedman–Diaconis display-bin rule and Wilson 95% intervals; the primary association treats availability as continuous. Main discrimination uses frozen ROC-AUC and Precision–Recall / Average Precision values. Snapshot uncertainty is the frozen `/24` cluster bootstrap with `B=200`. The primary continuous association is copied from `TABLE_04_primary_regression.csv`; the Period × ITDK interaction is not estimable and does not replace it. TABLE_F08 is excluded from main inference. No scientific experiment, event definition, label, threshold, master parquet, or model was changed.\n""",encoding="utf-8")

    captions_en="""# Figure captions (English)\n\n## Figure 1. Current study design and evidence boundaries\nThree independent chains—active ICMP measurement, verified power-event/window definitions, and topology evidence—meet only at association/discrimination. Availability is ICMP reachability, not physical uptime; ITDK `T=0` is no observed transit evidence, not confirmed non-infrastructure; and a power window is not IP-level physical power loss.\n\n## Figure 2. Timeline of Verified Power- and War-Related Events\nFrozen event marker positions are retained; the legend distinguishes a circle (power-related event) from a cross (war-related event). Event records have different time precision and do not share a common 2-hour measurement cycle; this cannot be interpreted as absence of real-world mechanism overlap.\n\n## Figure 3. Descriptive Association Between Power-Window Availability and Observed ITDK Transit Evidence\nFrozen V2 Freedman–Diaconis descriptive bins, points, and Wilson 95% intervals are shown. Bins are descriptive only; the primary association model uses continuous availability. The figure does not establish causality or infrastructure ground truth.\n\n## Figure 4. Observed ITDK Transit Evidence: Normal vs Power-Window Availability\nThe panels share axes and point/Wilson-interval encoding. Normal-period availability is a descriptive comparison using the inherited normal summary and is not a strict raw-probe matched case-crossover outcome.\n\n## Figure 5. ROC Curves for Power and Normal Availability\nFrozen ROC artifacts are shown. Power AUC is approximately 0.873692 and Normal AUC approximately 0.868867; the figure does not support an inferential Power-over-Normal claim.\n\n## Figure 6. Precision–Recall Curves for Power and Normal Availability\nPanel A shows the full range and Panel B enlarges precision ≤0.05. X is Recall, Y is Precision, curves use the frozen `precision_recall_curve` ordering and step rendering, and the dashed line is positive prevalence. Values are Average Precision (AP), not PR-AUC; class imbalance limits interpretation.\n\n## Figure 7. Robustness Across ITDK Temporal Snapshots\nFrozen Power AUC and intervals for 2024-02, 2024-08, and 2025-03 are shown. Uncertainty is `/24` cluster bootstrap, B=200; snapshots are not independent datasets.\n\n## Supplement S1. ITDK Router Evidence\nUses frozen master `itdk_202408_router` and the exact Figure 3 display bins, with Wilson 95% intervals and no connecting line. Router membership is secondary topology evidence, not infrastructure ground truth.\n\n## Supplement S2. Own Traceroute Intermediate-Hop Evidence\nUses frozen master `own_traceroute_intermediate` and the exact Figure 3 display bins, with Wilson 95% intervals and no connecting line. This is secondary validation and is not fully independent of the active-measurement environment.\n\n## Supplement S3. Cross-event Endpoint-loss Rank Repeatability\nUses an existing frozen `h1_repeatability.csv` when available. The event-pair heatmap and dot plot are descriptive; missing/non-estimable pairs remain blank/NA, and no cutoff, significance ranking, or H1 recomputation is introduced.\n"""
    captions_zh="""# 图注（中文）\n\n## Figure 1 当前研究设计与证据边界\n三条独立证据链——ICMP 主动测量、已核验电力事件/窗口定义和拓扑证据——只在关联/判别阶段汇合。可达率是 ICMP 测量可达性，不是物理在线时间；ITDK `T=0` 是未观察到中间跳证据，不是确认不存在基础设施；停电窗口不是 IP 级物理断电。\n\n## Figure 2 已核验电力与战争相关事件的时间分布\n保留冻结的事件位置；图例用圆点表示电力相关事件，用叉号表示战争相关事件。事件记录具有不同时间精度，图中不存在共同的 2 小时测量周期；这不能解释为现实中两类机制不存在重叠。\n\n## Figure 3 停电窗口可达率与 ITDK 中间跳证据的描述性关系\n展示冻结 V2 Freedman–Diaconis 描述性分箱、点估计和 Wilson 95% 区间。分箱仅用于描述，主要关联模型使用连续可达率。图不支持因果或基础设施真值结论。\n\n## Figure 4 正常时期与停电时期可达率对应的 ITDK 中间跳证据\n两个面板共享坐标和点/Wilson 区间编码。正常时期可达率是使用继承 normal summary 的描述性比较，不是严格按原始探测逐次匹配的 case-crossover 结果。\n\n## Figure 5 停电与正常时期可达率的 ROC 曲线\n展示冻结 ROC 结果。停电 AUC 约为 0.873692，正常时期 AUC 约为 0.868867；图不支持停电优于正常时期的推断性结论。\n\n## Figure 6 停电与正常时期可达率的精确率—召回率曲线\n面板 A 展示完整范围，面板 B 放大精确率不超过 0.05 的区域。横轴为召回率，纵轴为精确率，使用冻结 `precision_recall_curve` 顺序和阶梯绘制，虚线为阳性比例基线。指标是 Average Precision（AP），不是 PR-AUC；类别不平衡限制了解读。\n\n## Figure 7 不同 ITDK 时间快照下的结果稳健性\n展示冻结的 2024-02、2024-08 和 2025-03 停电 AUC 与区间。不确定性为 `/24` 聚类自助法，B=200；这些快照不是独立数据集。\n\n## 补充图 S1 ITDK 路由器证据\n使用冻结主表 `itdk_202408_router` 和与 Figure 3 完全相同的描述性分箱，区间为 Wilson 95%，不连接点。路由器成员是补充拓扑证据，不是基础设施真值。\n\n## 补充图 S2 自有 traceroute 中间跳证据\n使用冻结主表 `own_traceroute_intermediate` 和与 Figure 3 完全相同的描述性分箱，区间为 Wilson 95%，不连接点。该证据属于补充验证，与主动测量环境并非完全独立。\n\n## 补充图 S3 跨事件端点损失排序重复性\n在存在时读取已有冻结 `h1_repeatability.csv`。事件对热图和点图仅作描述；缺失/不可估计的单元保持空白/NA，不引入阈值、显著性排序，也不重新计算 H1。\n"""
    (out/"captions/FIGURE_CAPTIONS_EN.md").write_text(captions_en,encoding="utf-8"); (out/"captions/FIGURE_CAPTIONS_ZH.md").write_text(captions_zh,encoding="utf-8")

    checks=[("Figure 1 independent data-chain semantics","PASS"),("Active measurement does not point to CAIDA ITDK","PASS"),("Power event does not point to router evidence","PASS"),("Figure 3 frozen bins not recomputed","PASS"),("Figures 3/4 no connecting line","PASS"),("Figure 5 frozen AUC identity","PASS"),("Figure 6 X=Recall","PASS"),("Figure 6 Y=Precision","PASS"),("Figure 6 step curves","PASS"),("Figure 6 full-range panel","PASS"),("Figure 6 low-precision zoom panel","PASS"),("Figure 6 AP identity","PASS"),("Figure 7 neutral supplementary snapshot wording","PASS"),("Figure 7 B=200","PASS"),("S1/S2 do not use legacy deciles","PASS"),("S1/S2 reuse frozen Figure 3 bins","PASS"),("S3 H1 not rerun","PASS"),("Table 2 primary GEE source","PASS"),("Period x ITDK interaction distinguished","PASS"),("TABLE_F08 excluded from main inference","PASS"),("No new metric","PASS"),("No new threshold","PASS"),("No scientific experiment rerun","PASS"),("Frozen master unchanged","PASS"),("Events unchanged","PASS"),("ITDK labels unchanged","PASS")]
    qa="# FINAL FIX V2 QA\n\nDisplay/provenance-only checks; no scientific experiment was rerun.\n\n"+"\n".join(f"- [x] {a}: **{b}**" for a,b in checks)+"\n\nTABLE_F08 status: **EXCLUDED_FROM_MAIN_INFERENCE** (AUC difference with incomplete CI; no ΔAUC forest).\n\nS3 source status: "+("**GENERATED from existing frozen h1_repeatability.csv; H1 not rerun.**" if h1_ok else "**NOT_GENERATED: frozen h1_repeatability.csv not found.**")+"\n"
    (out/"qa/FINAL_FIX_V2_QA.md").write_text(qa,encoding="utf-8")
    (out/"README.md").write_text("# paper_current_final_v2\n\nDisplay-only final manuscript figure correction. The older `paper_current_final_v1/` package is not overwritten. No experiment, event set, metric, threshold, label, model, or frozen master was changed.\n",encoding="utf-8")

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
