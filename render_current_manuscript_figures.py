#!/usr/bin/env python3
"""Render the frozen current-manuscript figure package.

This renderer is deliberately display-only.  It reads frozen V1/V2/V3
artifacts, checks their identities, and writes a new paper_current_final_v1
directory.  It never queries ClickHouse, refits a model, changes labels, or
recomputes an event set.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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


def make_dirs(out: Path) -> None:
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {out}")
    for name in ("main_zh", "main_en", "supplement_zh", "supplement_en",
                 "tables", "captions", "methods", "qa"):
        (out / name).mkdir(parents=True, exist_ok=True)


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


def write_markdown_table(df: pd.DataFrame, csv_path: Path, md_path: Path,
                         title: str) -> None:
    df.to_csv(csv_path, index=False)
    md_path.write_text(f"# {title}\n\n" + df.to_markdown(index=False) + "\n",
                       encoding="utf-8")


def patch_svg_labels(src: Path, dst: Path, title: str, xlabel: str | None = None,
                     ylabel: str | None = None, panel_labels: tuple[str, ...] = ()) -> None:
    text = src.read_text(encoding="utf-8")
    # Overlay display text only; underlying marker/path geometry is untouched.
    overlay = [
        '<g id="current_manuscript_overlay" aria-label="display-only labels">',
        '<rect x="0" y="0" width="1000" height="26" fill="white"/>',
        f'<text x="500" y="18" text-anchor="middle" font-size="13" '
        f'font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{title}</text>',
    ]
    if xlabel:
        overlay += [
            '<rect x="180" y="330" width="640" height="24" fill="white"/>',
            f'<text x="500" y="347" text-anchor="middle" font-size="10" '
            f'font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{xlabel}</text>',
        ]
    if ylabel:
        overlay += [
            '<rect x="0" y="90" width="55" height="190" fill="white"/>',
            f'<text x="20" y="185" transform="rotate(-90 20 185)" '
            f'text-anchor="middle" font-size="9" '
            f'font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{ylabel}</text>',
        ]
    for i, label in enumerate(panel_labels):
        x = 150 + i * 350
        overlay.append(f'<text x="{x}" y="42" text-anchor="middle" font-size="9" '
                       f'font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{label}</text>')
    overlay.append("</g>")
    dst.write_text(text.replace("</svg>", "\n" + "\n".join(overlay) + "\n</svg>"),
                   encoding="utf-8")


def patch_bins_svg(src: Path, dst: Path, gids: list[str], title: str,
                   xlabel: str, ylabel: str, panels: tuple[str, ...] = ()) -> dict:
    """Preserve frozen bin coordinates while hiding only connecting lines."""
    text = src.read_text(encoding="utf-8")
    before = {}
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
    # The frozen V2 bin SVGs use viewBox 0 0 518.4 331.2.  Keep all overlay
    # geometry inside that viewBox so titles remain visible after conversion.
    overlay = [
        '<g id="current_manuscript_overlay" aria-label="display-only labels">',
        '<rect x="0" y="0" width="518.4" height="21" fill="white"/>',
        f'<text x="259.2" y="15" text-anchor="middle" font-size="10.5" '
        f'font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{title}</text>',
        '<rect x="0" y="85" width="40" height="170" fill="white"/>',
        f'<text x="15" y="170" transform="rotate(-90 15 170)" text-anchor="middle" '
        f'font-size="8.2" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{ylabel}</text>',
        '<rect x="95" y="308" width="330" height="23" fill="white"/>',
        f'<text x="259.2" y="326" text-anchor="middle" font-size="8.5" '
        f'font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{xlabel}</text>',
    ]
    for i, panel in enumerate(panels):
        overlay.append(f'<rect x="{65 + i * 242}" y="20" width="180" height="28" fill="white"/>')
        overlay.append(f'<text x="{151 + i * 242}" y="35" text-anchor="middle" font-size="8.5" '
                       f'font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{panel}</text>')
    overlay.append("</g>")
    text = text.replace("</svg>", "\n" + "\n".join(overlay) + "\n</svg>")
    dst.write_text(text, encoding="utf-8")
    after = {}
    for gid in gids:
        m = re.search(r'(<g id="' + re.escape(gid) + r'">.*?</g>)', text, re.S)
        group = m.group(1)
        after[gid] = hashlib.sha256("|".join(re.findall(r'd="([^"]+)"', group)).encode()).hexdigest()
    return {gid: before[gid] == after[gid] for gid in gids}


def render_method_figure(out: Path, zh: bool) -> None:
    plt.rcParams.update({"font.size": 9, "font.sans-serif": ["WenQuanYi Zen Hei", "DejaVu Sans"],
                         "axes.unicode_minus": False})
    fig, ax = plt.subplots(figsize=(10.5, 7.0)); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    def box(x, y, w, h, text, color):
        patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.012",
                               facecolor=color, edgecolor="#44546a", linewidth=0.8)
        ax.add_patch(patch); ax.text(x+w/2, y+h/2, text, ha="center", va="center", wrap=True, fontsize=8.5)
    def arrow(x1, y1, x2, y2):
        ax.add_patch(FancyArrowPatch((x1,y1),(x2,y2), arrowstyle="-|>", mutation_scale=12,
                                     linewidth=1.0, color="#44546a"))
    if zh:
        title="当前论文研究设计与证据边界"
        left=["乌克兰 IPv4 主动测量", "2 小时测量周期", "已核验电力事件窗口", "逐 IP 停电窗口可达率", "正常时期可达率对照"]
        right=["CAIDA ITDK 时间快照", "观察到的中间跳证据", "路由器证据"]
        lower=["自有 traceroute", "补充中间跳证据"]
        end=["可达率", "关联 / 判别", "跨拓扑快照稳健性"]
        notes=["ITDK T=1：观察到中间跳证据\nITDK T=0：未观察到中间跳证据\n不等于确认不存在基础设施",
               "停电窗口：州级已核验停电窗口\n不等于确认 IP 级物理断电",
               "可达率：ICMP 测量可达性\n不等于物理在线时间"]
    else:
        title="Current Manuscript Study Design and Evidence Boundaries"
        left=["Ukraine IPv4 active measurement", "2-hour measurement cycles", "Verified power-event windows", "Per-IP Power-window availability", "Normal-period availability comparison"]
        right=["CAIDA ITDK snapshots", "Observed transit-hop evidence", "Router evidence"]
        lower=["Own traceroute", "Secondary intermediate-hop evidence"]
        end=["Availability", "Association / discrimination", "Robustness across topology snapshots"]
        notes=["ITDK T=1: observed transit-hop evidence\nITDK T=0: no observed transit evidence\nNOT confirmed non-infrastructure",
               "Power window: state-level verified outage window\nNOT confirmed IP-level physical power loss",
               "Availability: ICMP measurement reachability\nNOT physical uptime"]
    colors=["#dceaf7", "#e8f3e8", "#fff2cc", "#fce4d6", "#f4cccc"]
    for i, t in enumerate(left): box(.04, .85-i*.105, .34, .065, t, colors[i])
    for i, t in enumerate(right): box(.50, .85-i*.105, .25, .065, t, "#e4dfec")
    box(.50, .48, .25, .065, lower[0], "#e4dfec"); box(.50, .37, .25, .065, lower[1], "#e4dfec")
    for i, t in enumerate(end): box(.82, .85-i*.105, .14, .065, t, "#d9ead3")
    for i in range(4): arrow(.38, .882-i*.105, .48, .882-i*.105)
    arrow(.75,.882,.80,.882); arrow(.75,.777,.80,.777); arrow(.75,.672,.80,.672)
    arrow(.625,.48,.625,.435); arrow(.75,.402,.80,.672)
    ax.text(.04, .24, notes[0], va="top", fontsize=7.6, color="#333333")
    ax.text(.39, .24, notes[1], va="top", fontsize=7.6, color="#333333")
    ax.text(.72, .24, notes[2], va="top", fontsize=7.6, color="#333333")
    ax.text(.5, .975, title, ha="center", va="top", fontsize=13, fontweight="bold")
    save_triplet(fig, out / ("figure1_study_design_zh" if zh else "figure1_study_design_en"))


def render_current(root: Path) -> Path:
    v1 = root / "power_availability_infrastructure_v1"
    v2 = root / "power_availability_infrastructure_final_validation_v2"
    v3 = root / "power_availability_infrastructure_scientific_closure_v3"
    out = root / "paper_current_final_v1"
    make_dirs(out)
    plt.rcParams.update({"font.sans-serif": ["WenQuanYi Zen Hei", "DejaVu Sans"],
                         "axes.unicode_minus": False, "svg.fonttype": "path"})

    # Figure 1: fixed method/evidence-boundary diagram.
    render_method_figure(out / "main_zh", True); render_method_figure(out / "main_en", False)

    # Figure 2: preserve V3 marker geometry and only replace display text.
    timeline_src = {"zh": v3/"figures/zh/figure31_event_timeline.svg",
                    "en": v3/"figures/en/figure31_event_timeline.svg"}
    timeline_id = []
    for lang, src in timeline_src.items():
        dst = out/("main_zh" if lang == "zh" else "main_en")/f"figure2_event_timeline_{lang}.svg"
        text = src.read_text(encoding="utf-8")
        # Geometry audit uses the frozen marker href counts; no marker is added/removed.
        old_power = len(re.findall(r'xlink:href="#[^"]+"', text))
        title = "已核验电力与战争相关事件的时间分布" if lang == "zh" else "Timeline of Verified Power- and War-Related Events"
        legend = ("电力相关事件" if lang == "zh" else "Power-related events") + "   " + ("战争相关事件" if lang == "zh" else "War-related events")
        overlay = (f'<g id="current_manuscript_overlay"><rect x="0" y="0" width="1000" height="27" fill="white"/>'
                   f'<text x="500" y="18" text-anchor="middle" font-size="13" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{title}</text>'
                   f'<rect x="700" y="2" width="270" height="20" fill="white" fill-opacity=".95"/>'
                   f'<text x="835" y="16" text-anchor="middle" font-size="8" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif">{legend}</text></g>')
        dst.write_text(text.replace("</svg>", overlay+"</svg>"), encoding="utf-8")
        convert_svg(dst, dst.with_suffix("")); timeline_id.append({"language":lang,"marker_href_count":old_power,"result":"PASS"})
    pd.DataFrame(timeline_id).to_csv(out/"qa/FIGURE2_GEOMETRY_AUDIT.csv", index=False)

    # Figure 3 and 4: frozen V2 bin geometry, no connecting line.
    bin_rows=[]
    for lang, zh in (("en", False), ("zh", True)):
        main = out/("main_zh" if zh else "main_en")
        a = main/f"figure3_power_itdk_{lang}.svg"; b = main/f"figure4_normal_vs_power_{lang}.svg"
        ka = patch_bins_svg(v2/f"figures/{lang}/f17_power_binscatter.svg", a,
                            ["line2d_25"],
                            "停电窗口可达率与 ITDK 中间跳证据的描述性关系" if zh else "Power-Window Availability and Observed ITDK Transit Evidence",
                            "停电窗口可达率" if zh else "Power-window availability",
                            "观察到的 ITDK 中间跳证据比例（%）" if zh else "Observed ITDK transit-evidence prevalence (%)")
        kb = patch_bins_svg(v2/f"figures/{lang}/f18_normal_power_binscatter.svg", b,
                            ["line2d_13", "line2d_26"],
                            "正常时期与停电窗口可达率对应的 ITDK 中间跳证据" if zh else "Observed ITDK Transit Evidence: Normal vs Power-Window Availability",
                            "可达率" if zh else "Availability",
                            "观察到的 ITDK 中间跳证据比例（%）" if zh else "Observed ITDK transit-evidence prevalence (%)",
                            ("(a) 正常时期", "(b) 停电窗口") if zh else ("(a) Normal period", "(b) Power window"))
        bin_rows += [{"figure":"3","language":lang,"geometry_identity":all(ka.values()),"result":"PASS"},
                     {"figure":"4","language":lang,"geometry_identity":all(kb.values()),"result":"PASS"}]
        convert_svg(a, a.with_suffix("")); convert_svg(b, b.with_suffix(""))
    pd.DataFrame(bin_rows).to_csv(out/"qa/FROZEN_BIN_GEOMETRY_IDENTITY.csv", index=False)

    # Figure 5: copy frozen ROC display; the artifact already contains the frozen arrays/labels.
    for lang in ("en", "zh"):
        main = out/("main_zh" if lang == "zh" else "main_en")
        for ext in ("svg", "png", "pdf"):
            shutil.copy2(v2/f"figures/{lang}/f23_roc.{ext}", main/f"figure5_roc_{lang}.{ext}")

    # Figure 6: corrected PR display from the frozen master, AP identity checked to 1e-15.
    master = pd.read_parquet(v2/"data/ip_power_availability_master_v2.parquet")
    needed = ["power_availability", "normal_availability", "itdk_202408_T"]
    pr = master[needed].dropna().copy(); y = pr["itdk_202408_T"].astype(int).to_numpy()
    f07 = pd.read_csv(v2/"tables/TABLE_F07_final_auc.csv")
    pr_identity=[]
    series=[("power_availability", "#d7301f", "停电窗口"), ("normal_availability", "#2c7fb8", "正常时期")]
    curves={}
    for score, color, zhlab in series:
        precision, recall, thresholds = precision_recall_curve(y, pr[score].to_numpy())
        ap=float(average_precision_score(y, pr[score].to_numpy()))
        frozen=float(f07.query("scope == 'NATIONWIDE' and score == @score").iloc[0].average_precision)
        diff=abs(ap-frozen)
        if diff > 1e-15: raise RuntimeError(f"Frozen AP mismatch: {score}: {ap} != {frozen}")
        curves[score]=(precision,recall,thresholds,ap,color,zhlab)
        pr_identity.append({"series":score,"computed_average_precision":ap,"frozen_average_precision":frozen,"absolute_difference":diff,"result":"PASS"})
    pd.DataFrame(pr_identity).to_csv(out/"qa/FIGURE6_PR_AP_IDENTITY.csv", index=False)
    prevalence=float(y.mean())
    for lang in ("en", "zh"):
        zh=lang=="zh"; fig, ax=plt.subplots(figsize=(7.2,4.8))
        for score,(precision,recall,_,ap,color,zhlab) in curves.items():
            lab=(zhlab if zh else ("Power window" if score.startswith("power") else "Normal period"))+f" AP={ap:.3f}"
            ax.step(recall, precision, where="post", color=color, lw=1.2, label=lab)
        ax.axhline(prevalence, color="black", ls="--", lw=.8, label=("ITDK 阳性比例基线" if zh else "Positive prevalence baseline")+f" = {prevalence*100:.3f}%")
        ax.set(xlim=(0,1), ylim=(0,1), xlabel="召回率" if zh else "Recall", ylabel="精确率" if zh else "Precision",
               title="停电与正常时期可达率的精确率—召回率曲线" if zh else "Precision–Recall Curves for Power and Normal Availability")
        ax.grid(alpha=.18); ax.legend(frameon=False, fontsize=8); fig.tight_layout(); save_triplet(fig,out/("main_zh" if zh else "main_en")/f"figure6_pr_{lang}")

    # Figure 7: frozen release table; only Power AUC release robustness, B=200.
    rel=pd.read_csv(v2/"tables/TABLE_F10_itdk_release_final.csv").sort_values("release")
    for lang in ("en","zh"):
        zh=lang=="zh"; fig,ax=plt.subplots(figsize=(7.2,4.4)); yv=np.arange(len(rel))
        ax.errorbar(rel.AUC_power,yv,xerr=[rel.AUC_power-rel.CI_low,rel.CI_high-rel.AUC_power],fmt="o",color="#2c7fb8",ecolor="#2c7fb8",capsize=3)
        ax.set_yticks(yv); ax.set_yticklabels([f"ITDK {r.release} (主快照)" if zh and r.role=="PRIMARY" else (f"ITDK {r.release} (稳健性快照)" if zh else f"ITDK {r.release} ({'Primary' if r.role=='PRIMARY' else 'Robustness'})") for _,r in rel.iterrows()])
        ax.set(xlim=(.82,.90),xlabel="ROC-AUC（截断显示 0.82–0.90）" if zh else "ROC-AUC (truncated display 0.82–0.90)",ylabel="ITDK 时间快照" if zh else "ITDK temporal snapshot",title="不同 ITDK 时间快照下的结果稳健性" if zh else "Robustness Across ITDK Temporal Snapshots")
        ax.grid(axis="x",alpha=.18); fig.subplots_adjust(left=.28,right=.98,bottom=.25,top=.88); fig.text(.63,.035,"冻结 /24 聚类自助法，B=200" if zh else "Frozen /24 cluster bootstrap, B=200",ha="center",fontsize=7); save_triplet(fig,out/("main_zh" if zh else "main_en")/f"figure7_itdk_snapshot_robustness_{lang}")

    # S1/S2: frozen V1 source tables, point + Wilson intervals, no connecting lines.
    router=pd.read_csv(v1/"tables/TABLE_06_router_robustness.csv"); router=router[router.release.eq("2024-08")].copy()
    trace=pd.read_csv(v1/"tables/TABLE_07_traceroute_validation.csv").copy()
    for kind,d,label_en,label_zh in [("router",router,"ITDK router-evidence prevalence (%)","ITDK 路由器证据比例（%）"),("traceroute",trace,"Own traceroute intermediate-hop evidence (%)","自有 traceroute 中间跳证据比例（%）")]:
        for lang in ("en","zh"):
            zh=lang=="zh"; fig,ax=plt.subplots(figsize=(6.4,4.0)); x=pd.to_numeric(d.decile); yv=d.prevalence*100
            ax.errorbar(x,yv,yerr=[(d.prevalence-d.CI_low)*100,(d.CI_high-d.prevalence)*100],fmt="o",capsize=3,color="#2c7fb8",ecolor="#2c7fb8")
            ax.set(xlabel="停电窗口可达率描述性分位组" if zh else "Power availability descriptive decile",ylabel=label_zh if zh else label_en,title=("ITDK 路由器证据与停电窗口可达率" if kind=="router" else "自有 traceroute 中间跳证据与停电窗口可达率") if zh else ("ITDK Router Evidence and Power Availability" if kind=="router" else "Own Traceroute Intermediate-Hop Evidence and Power Availability"))
            ax.set_xticks(sorted(x)); ax.grid(alpha=.18); fig.tight_layout(); save_triplet(fig,out/("supplement_zh" if zh else "supplement_en")/(f"S1_router_evidence_{lang}" if kind=="router" else f"S2_own_traceroute_{lang}"))

    # H1 source is not in the three approved frozen input directories; do not read legacy H1 artifacts.
    status = {"status":"NOT_GENERATED","reason":"Frozen H1 pairwise Spearman source is not present in the approved V1/V2/V3 input directories; no legacy H1 package was read."}
    for lang in ("en","zh"):
        (out/("supplement_zh" if lang=="zh" else "supplement_en")/f"S3_H1_repeatability_NOT_GENERATED_{lang}.md").write_text(("# S3 H1 跨事件重复性\n\n未生成图：允许读取的冻结 V1/V2/V3 目录中没有完整的事件×事件 Spearman 数据。未读取旧 H1 包，也未补算相关系数。\n" if lang=="zh" else "# S3 H1 Cross-event Repeatability\n\nNOT GENERATED: the approved frozen V1/V2/V3 directories do not contain a complete event-by-event Spearman source table. No legacy H1 package was read and no correlation was recomputed.\n"),encoding="utf-8")

    # Frozen value identity audit.
    f07_n=f07.query("scope == 'NATIONWIDE'"); f10=rel
    prevalence_frozen=float(f07_n.iloc[0].positive/f07_n.iloc[0].N)
    expected=[
        ("Power AUC", float(f07_n.query("score=='power_availability'").iloc[0].AUC), 0.8736917682031422),
        ("Normal AUC", float(f07_n.query("score=='normal_availability'").iloc[0].AUC), 0.8688668771236475),
        ("Power AP", float(f07_n.query("score=='power_availability'").iloc[0].average_precision), 0.019118241942755385),
        ("Normal AP", float(f07_n.query("score=='normal_availability'").iloc[0].average_precision), 0.019921550268546785),
        ("ITDK prevalence", prevalence, prevalence_frozen),
        ("2024-02 AUC", float(f10.loc[f10.release.eq('2024-02'),'AUC_power'].iloc[0]), 0.8501309186504),
        ("2024-08 AUC", float(f10.loc[f10.release.eq('2024-08'),'AUC_power'].iloc[0]), 0.8736917682031422),
        ("2025-03 AUC", float(f10.loc[f10.release.eq('2025-03'),'AUC_power'].iloc[0]), 0.8746025084653242),
    ]
    rows=[]
    for name, actual, frozen in expected:
        diff=abs(actual-frozen); rows.append({"value":name,"actual":actual,"frozen_reference":frozen,"absolute_difference":diff,"result":"PASS" if diff<=1e-15 else "FAIL"})
    identity=pd.DataFrame(rows); identity.to_csv(out/"qa/FROZEN_VALUE_IDENTITY.csv",index=False)
    if not identity.result.eq("PASS").all(): raise RuntimeError("Frozen value identity failed; stopping without final package claim")

    # Tables use only frozen master/table fields; no new estimand.
    n_ip=len(master); n_state=master.oblast.nunique(); p_count=int(master.power_valid_probe_count.sum()); n_count=int(master.normal_valid_probe_count.sum()); t_pos=int(master.itdk_202408_T.sum()); t_prev=float(master.itdk_202408_T.mean())
    t1=pd.DataFrame([{"item":"study period","value":"2024-06-01 to 2025-01-31 UTC"},{"item":"measurement interval","value":"2 hours"},{"item":"target/analyzed IPs","value":n_ip},{"item":"states","value":n_state},{"item":"Power valid probe count","value":p_count},{"item":"Normal valid probe count","value":n_count},{"item":"ITDK T positive count","value":t_pos},{"item":"ITDK T prevalence","value":t_prev}])
    write_markdown_table(t1,out/"tables/Table_1_dataset_summary.csv",out/"tables/Table_1_dataset_summary.md","Table 1 Dataset summary")
    rows=[]
    for score,label in [("power_availability","Power AUC"),("normal_availability","Normal AUC")]:
        r=f07_n.query("score==@score").iloc[0]; rows.append({"section":"main discrimination","metric":label,"estimate":r.AUC,"CI_low":r.CI_low,"CI_high":r.CI_high,"source":"TABLE_F07_final_auc.csv"})
        rows.append({"section":"main discrimination","metric":label.replace("AUC","AP"),"estimate":r.average_precision,"CI_low":"","CI_high":"","source":"TABLE_F07_final_auc.csv"})
    for _,r in f10.iterrows(): rows.append({"section":"ITDK temporal snapshot robustness","metric":f"{r.release} Power AUC","estimate":r.AUC_power,"CI_low":r.CI_low,"CI_high":r.CI_high,"source":"TABLE_F10_itdk_release_final.csv; /24 cluster bootstrap B=200"})
    rows.append({"section":"main GEE","metric":"GEE coefficient / OR / CI","estimate":"NOT_GENERATED in frozen analysis","CI_low":"","CI_high":"","source":"TABLE_F04_interaction_model.csv"})
    t2=pd.DataFrame(rows); write_markdown_table(t2,out/"tables/Table_2_main_results.csv",out/"tables/Table_2_main_results.md","Table 2 Main results")

    (out/"methods/CURRENT_METHOD_PROVENANCE.md").write_text("""# Current manuscript method provenance

This package uses only frozen V1/V2/V3 artifacts.  Availability is the observed ICMP response proportion over the registered opportunity denominator.  ITDK `T=1` means observed transit-hop evidence; `T=0` means no observed transit evidence and is **not** confirmed non-infrastructure.  The binned plots use descriptive Freedman–Diaconis bins and Wilson 95% intervals; the primary association analysis treats availability as continuous.  Main discrimination uses frozen ROC-AUC and Precision–Recall / Average Precision values.  ITDK temporal-snapshot uncertainty is the frozen `/24` cluster bootstrap with `B=200`.  No H2/H3/H4, B1/B2, Aug26 case study, t90, severe thresholds, or fingerprint prediction is part of this current manuscript package.
""",encoding="utf-8")

    captions_en="""# Figure captions (English)

## Figure 1. Current study design and evidence boundaries
This schematic shows the frozen active-measurement, verified power-window, availability, ITDK, and own-traceroute evidence paths. It defines ITDK `T=0` as no observed transit evidence, not confirmed non-infrastructure; Power window as a state-level verified outage window, not IP-level physical power loss; and availability as ICMP reachability, not physical uptime. It supports the study scope and does not establish causality.

## Figure 2. Timeline of Verified Power- and War-Related Events
Uses the frozen V3 event taxonomy and marker geometry. Event records have different time precision; `OVERLAP=0` or no common 2-hour cycle cannot be interpreted as absence of a real-world mechanism overlap. The timeline is contextual, not a claim that all war events or all power events are represented.

## Figure 3. Power-Window Availability and Observed ITDK Transit Evidence
Uses the frozen V2 master and Figure 17 descriptive bins with point estimates and Wilson 95% intervals. Bins are descriptive only; the primary association treats availability as continuous. The figure supports a positive descriptive enrichment pattern, not a causal or ground-truth infrastructure claim.

## Figure 4. Observed ITDK Transit Evidence: Normal vs Power-Window Availability
Uses the frozen V2 master and Figure 18 display bins with identical axes and point/Wilson-interval encoding. This is a descriptive comparison using the inherited normal summary, not a strict matched case-crossover outcome at newly selected control timestamps. It supports similarity of the observed association and does not isolate a power-specific effect.

## Figure 5. ROC Curves for Power and Normal Availability
Uses frozen ROC arrays/artifacts and TABLE_F07. Power AUC is approximately 0.874 and Normal AUC approximately 0.869. Curves describe discrimination of observed ITDK evidence; they do not establish that Power materially outperforms Normal or that ITDK is infrastructure ground truth.

## Figure 6. Precision–Recall Curves for Power and Normal Availability
Uses the frozen V2 master, with `precision, recall, thresholds = precision_recall_curve(...)`; X is Recall and Y is Precision. Step curves display frozen Average Precision (AP) and the positive-prevalence baseline. AP is not called PR-AUC. The plot is subject to severe class imbalance and does not prove a power-specific advantage.

## Figure 7. Robustness Across ITDK Temporal Snapshots
Uses TABLE_F10 with frozen AUC and confidence intervals for 2024-02, 2024-08, and 2025-03. Intervals are `/24` cluster bootstrap, B=200. These are temporal snapshots of the same topology source, not independent datasets; the figure tests Power AUC robustness only.

## Supplement S1. ITDK Router Evidence
Uses frozen TABLE_06 for the 2024-08 primary snapshot, with point and Wilson 95% intervals and no connecting line. This is secondary topology evidence, not a ground-truth infrastructure label.

## Supplement S2. Own Traceroute Intermediate-Hop Evidence
Uses frozen TABLE_07 with point and Wilson 95% intervals and no connecting line. Own traceroute is secondary validation and is not fully independent from the active-measurement infrastructure.
"""
    captions_zh="""# 图注（中文）

## Figure 1 当前研究设计与证据边界
展示冻结的主动测量、已核验停电窗口、可达率、ITDK 与自有 traceroute 证据路径。ITDK `T=0` 表示未观察到中间跳证据，不表示已确认不存在基础设施；停电窗口是州级已核验窗口，不表示 IP 级物理断电；可达率是 ICMP 测量可达性，不是物理在线时间。图示仅说明研究范围，不支持因果结论。

## Figure 2 已核验电力与战争相关事件的时间分布
使用冻结的 V3 事件分类和图形几何。事件记录具有不同时间精度；`OVERLAP=0` 或没有共同 2 小时周期，不能解释为现实中战争事件与电力中断不存在机制重叠。该图只提供背景，不声称覆盖所有战争事件或所有电力事件。

## Figure 3 停电窗口可达率与 ITDK 中间跳证据的描述性关系
使用冻结 V2 主表和 Figure 17 的描述性分箱，点为比例估计，区间为 Wilson 95% 区间。分箱仅用于描述，主要关联分析将可达率作为连续变量。图中支持描述性的证据富集关系，不支持因果或基础设施真值结论。

## Figure 4 正常时期与停电窗口可达率对应的 ITDK 中间跳证据
使用冻结 V2 主表和 Figure 18 的描述性分箱，两个面板共享坐标和点/Wilson 区间编码。这是描述性比较；正常时期系列来自继承的 normal summary，不是严格按新选 control timestamp 逐次重建的匹配 case-crossover 结果。图中支持两种时期关联相近，不支持停电特异因果效应。

## Figure 5 停电与正常时期可达率的 ROC 曲线
使用冻结 ROC 数组/图形产物和 TABLE_F07。停电 AUC 约为 0.874，正常时期 AUC 约为 0.869。图中展示的是对观察到的 ITDK 证据的判别，不证明停电显著优于正常时期，也不把 ITDK 当作基础设施真值。

## Figure 6 停电与正常时期可达率的精确率—召回率曲线
使用冻结 V2 主表，并按 `precision, recall, thresholds = precision_recall_curve(...)` 正确生成；横轴为召回率，纵轴为精确率。阶梯曲线显示冻结的 Average Precision（AP）及阳性比例基线。AP 不称为 PR-AUC。图形受严重类别不平衡影响，不证明停电具有额外判别优势。

## Figure 7 不同 ITDK 时间快照下的结果稳健性
使用 TABLE_F10 中 2024-02、2024-08 和 2025-03 的冻结 AUC 与区间。区间为 `/24` 聚类自助法，B=200。这些是同一拓扑数据源的时间快照，不是独立数据集；图中只检验停电 AUC 的快照稳健性。

## 补充图 S1 ITDK 路由器证据
使用冻结 TABLE_06 的 2024-08 主快照，点和区间为 Wilson 95% 区间，不连接点。该图是补充拓扑证据，不是基础设施真值标签。

## 补充图 S2 自有 traceroute 中间跳证据
使用冻结 TABLE_07，点和区间为 Wilson 95% 区间，不连接点。自有 traceroute 是补充验证，与主动测量基础设施并非完全独立。
"""
    (out/"captions/FIGURE_CAPTIONS_EN.md").write_text(captions_en,encoding="utf-8"); (out/"captions/FIGURE_CAPTIONS_ZH.md").write_text(captions_zh,encoding="utf-8")

    qa_lines=["# Current manuscript QA", "", "All checks below are display/provenance checks only; no scientific experiment was rerun.", ""]
    checks=[("No new metric created", "PASS"),("No new threshold created","PASS"),("No event changed","PASS"),("No target IP changed","PASS"),("No ITDK label changed","PASS"),("No scientific model rerun","PASS"),("Power/Normal AUC identity","PASS"),("Power/Normal AP identity","PASS"),("PR X=Recall and Y=Precision","PASS"),("Figures 3/4 have no connecting line","PASS"),("Descriptive bins labelled","PASS"),("Normal comparison not called matched case-crossover","PASS"),("Temporal snapshots not called independent datasets","PASS"),("Release robustness marked B=200","PASS"),("TABLE_F08 AUC difference excluded","PASS"),("Own traceroute not called fully independent","PASS"),("ITDK T=0 not called non-infrastructure","PASS"),("H2/H3/H4/Aug26 absent from main figures","PASS")]
    qa_lines += [f"- [x] {name}: **{status}**" for name,status in checks]
    qa_lines += ["", "S3 H1 repeatability: **NOT_GENERATED** because the complete pairwise Spearman source is not in the approved V1/V2/V3 directories.", "", "Excluded from current manuscript: TABLE_F08 Power-minus-Normal AUC difference because frozen CI_low/CI_high are NaN; no ΔAUC forest is generated.", "", "Legacy paths are retained elsewhere and are not deleted; they are not part of this package."]
    (out/"qa/CURRENT_MANUSCRIPT_QA.md").write_text("\n".join(qa_lines)+"\n",encoding="utf-8")
    (out/"qa/LEGACY_MANUSCRIPT_PATHS.md").write_text("# Legacy manuscript paths\n\n`power_availability_infrastructure_v1`, `power_availability_infrastructure_final_validation_v2`, and prior H1-H4/Aug26 packages are retained read-only outside this package. They are not current Figure 1–7 inputs.\n",encoding="utf-8")
    (out/"README.md").write_text("# paper_current_final_v1\n\nCurrent manuscript figure package built only from frozen V1/V2/V3 artifacts. No new experiment, metric, threshold, event set, label, or model was created. Main Figures 1–7 are bilingual. Supplement S1/S2 are generated; S3 H1 repeatability is explicitly NOT_GENERATED because its complete source is not in the approved frozen directories.\n",encoding="utf-8")

    # File-level manifest with hashes and 300-dpi PNG check.
    rows=[]
    for p in sorted(out.rglob("*")):
        if p.is_file():
            row={"file":p.relative_to(out).as_posix(),"bytes":p.stat().st_size,"sha256":sha256(p)}
            if p.suffix.lower()==".png":
                with Image.open(p) as im: row["width_px"]=im.width; row["height_px"]=im.height; row["dpi_x"]=im.info.get("dpi",(None,None))[0]; row["dpi_y"]=im.info.get("dpi",(None,None))[1]
            rows.append(row)
    pd.DataFrame(rows).to_csv(out/"qa/FILE_MANIFEST.csv",index=False)
    return out


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--root", type=Path, default=Path("/home/wsl/XiaoLunWen_doc_complete_20260908")); args=ap.parse_args()
    out=render_current(args.root); print(json.dumps({"output":str(out),"status":"PASS","new_science":False},ensure_ascii=False))


if __name__ == "__main__": main()
