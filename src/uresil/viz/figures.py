"""F1–F15 bilingual manuscript figures with validation-first rendering."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .labels import L
from ..progress import HeartbeatProgress, get_logger
from .style import (COLOR_ATTACK, COLOR_PLANNED, DIVERGING, PALETTE,
                    apply_style, save_fig)


def _p(cfg, name): return cfg.out_dir("results_tables", ensure=False) / name

def _read(cfg, name, required=()):
    p = _p(cfg, name)
    if not p.exists() or p.stat().st_size == 0:
        raise FileNotFoundError(p)
    d = pd.read_csv(p)
    missing = set(required) - set(d.columns)
    if missing:
        raise ValueError(f"{name}: missing {sorted(missing)}")
    return d, p


def _panel(ax, letter):
    ax.text(-0.10, 1.04, letter, transform=ax.transAxes, fontweight="bold", va="bottom")


def _compact_edge_label(value: str) -> str:
    """Keep AS endpoints and destination region readable at column width."""
    parts = str(value).split("=>", 1)
    if len(parts) != 2:
        return str(value)[:42]
    left = parts[0].split("|")
    right = parts[1].split("|")
    left_as = left[0]
    left_country = left[1] if len(left) > 1 else ""
    right_as = right[0]
    right_region = right[-1] if len(right) > 1 else ""
    return f"{left_as} ({left_country}) → {right_as} / {right_region}"


def plot_f1(cfg, lang):
    d, p = _read(cfg, "f1_coverage.csv", ["measure_time", "ping_prefixes", "ping_unique_ips",
                                                    "trace_reached_rate", "as0_path_share",
                                                    "geo_unknown_path_share", "is_complete"])
    d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True)
    apply_style(cfg, lang)
    fig, ax = plt.subplots(3, 1, figsize=(cfg.figures["double_column_width_in"], 5.6), sharex=True)
    bad = d["is_complete"].eq(0)
    ax[0].plot(d.measure_time, d.ping_prefixes, label="/24", color=PALETTE[0])
    ax[0].plot(d.measure_time, d.ping_unique_ips, label="IP", color=PALETTE[1], linestyle="--")
    ax[0].set_ylabel(L(lang, "coverage")); ax[0].legend(frameon=False, ncol=2); _panel(ax[0], "a")
    ax[1].plot(d.measure_time, d.trace_reached_rate, color=PALETTE[2])
    ax[1].set_ylabel(L(lang,"trace_reached")); ax[1].set_ylim(0, 1); _panel(ax[1], "b")
    ax[2].plot(d.measure_time, d.as0_path_share, label="AS0", color=PALETTE[3])
    ax[2].plot(d.measure_time, d.geo_unknown_path_share, label=L(lang,"geo_unknown"), color=PALETTE[4], linestyle="--")
    ax[2].set_ylabel(L(lang, "unknown")); ax[2].set_xlabel(L(lang, "time")); ax[2].legend(frameon=False, ncol=2); _panel(ax[2], "c")
    for a in ax:
        a.grid(True, axis="y")
        for t in d.loc[bad, "measure_time"]:
            a.axvspan(t, t + pd.Timedelta(hours=2), color="0.8", alpha=.25, linewidth=0)
    ax[-1].xaxis.set_major_locator(mdates.MonthLocator())
    ax[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    return save_fig(fig, "F1", cfg, lang, [p],
                    "Measurement coverage, traceroute reachability, and mapping-quality time series.")


def plot_f2(cfg, lang):
    tl, p1 = _read(cfg, "f2_timeline.csv", ["event_id", "kind", "start_utc", "end_utc"])
    sig, p2 = _read(cfg, "f2_signal.csv", ["measure_time", "national_reach"])
    sig["measure_time"] = pd.to_datetime(sig["measure_time"], utc=True)
    apply_style(cfg, lang)
    fig, ax = plt.subplots(2, 1, figsize=(cfg.figures["double_column_width_in"], 4.2), sharex=True,
                           gridspec_kw={"height_ratios": [1, 2]})
    for _, r in tl.iterrows():
        s = pd.to_datetime(r.start_utc, utc=True); e = pd.to_datetime(r.end_utc, utc=True, errors="coerce")
        if pd.isna(e): e = s + pd.Timedelta(hours=2)
        y = 1 if r.kind == "attack" else 0
        ax[0].barh(y, (e-s).total_seconds()/86400, left=mdates.date2num(s), height=.6,
                   color=COLOR_ATTACK if y else COLOR_PLANNED, alpha=.8)
    ax[0].set_yticks([0,1], [L(lang,"planned"), L(lang,"attack")]); _panel(ax[0], "a")
    ax[1].plot(sig.measure_time, sig.national_reach, color=PALETTE[0])
    ax[1].axhline(1, color="0.4", linestyle=":")
    ax[1].set_ylabel(L(lang,"national")); ax[1].set_xlabel(L(lang,"time")); ax[1].grid(True, axis="y"); _panel(ax[1], "b")
    ax[1].xaxis.set_major_locator(mdates.MonthLocator()); ax[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    return save_fig(fig,"F2",cfg,lang,[p1,p2],"Frozen outage/attack timeline aligned with national normalized reachability.")


def plot_f3(cfg, lang):
    pr, p1 = _read(cfg,"f3_pr.csv",["method","recall","precision"])
    au, p2 = _read(cfg,"f3_auprc.csv",["method","auprc"])
    if pr.groupby("method").size().min() < 5:
        raise ValueError("PR curve has fewer than five thresholds per method")
    apply_style(cfg,lang)
    fig, ax = plt.subplots(1,2,figsize=(cfg.figures["double_column_width_in"],3.0))
    styles={"B0":("-","o"),"B1":("--","s"),"B2":("-.","^")}
    for i,(m,g) in enumerate(pr.groupby("method")):
        ls,mk=styles.get(m,("-","o")); ax[0].plot(g.recall,g.precision,label=m,color=PALETTE[i],linestyle=ls,marker=mk,markevery=max(1,len(g)//8))
    ax[0].set_xlabel(L(lang,"recall"));ax[0].set_ylabel(L(lang,"precision"));ax[0].set_xlim(0,1);ax[0].set_ylim(0,1);ax[0].legend(frameon=False);ax[0].grid(True);_panel(ax[0],"a")
    bars=ax[1].bar(au.method,au.auprc,color=PALETTE[:len(au)])
    ax[1].set_ylabel(L(lang,"auprc"));_panel(ax[1],"b")
    for b,v in zip(bars,au.auprc): ax[1].text(b.get_x()+b.get_width()/2,v,f"{v:.3f}",ha="center",va="bottom")
    return save_fig(fig,"F3",cfg,lang,[p1,p2],"Held-out scheduled-outage precision-recall curves and AUPRC by sensor method.")


def plot_f4(cfg, lang):
    d,p=_read(cfg,"f4_event_study.csv",["event_id","rel_h","effect","ci_lo","ci_hi","n_prefix"])
    if "confirmatory" in d: d=d[d.confirmatory.eq(1)]
    if "design_admissible" in d: d=d[d.design_admissible.eq(1)]
    if "analysis_role" in d: d=d[d.analysis_role.isin(["attack_national","attack_regional","blind_test"])]
    pre=float(cfg.figures.get("main_event_plot_pre_h",24)); post=float(cfg.figures.get("main_event_plot_post_h",72))
    d=d[d.rel_h.between(-pre,post)]
    if d.empty: raise ValueError("No design-admissible confirmatory event-study curve")
    apply_style(cfg,lang)
    events=list(d.event_id.unique()); n=len(events)
    fig,axes=plt.subplots(n,1,figsize=(cfg.figures["double_column_width_in"],max(2.2,1.65*n)),sharex=True,squeeze=False)
    max_abs=float(np.nanmax(np.abs(d[["ci_lo","ci_hi"]].to_numpy(float))))
    ylim=max(float(cfg.figures.get("common_event_y_limit",.25)),max_abs*1.05)
    for i,e in enumerate(events):
        a=axes[i,0];g=d[d.event_id.eq(e)].sort_values("rel_h")
        a.plot(g.rel_h,g.effect,color=PALETTE[0],marker="o",markevery=max(1,len(g)//10))
        a.fill_between(g.rel_h,g.ci_lo,g.ci_hi,color=PALETTE[0],alpha=.18)
        if "treatment_start_utc" in g and "anchor_utc" in g:
            t=pd.to_datetime(g.treatment_start_utc.iloc[0],utc=True,errors="coerce")
            anchor=pd.to_datetime(g.anchor_utc.iloc[0],utc=True,errors="coerce")
            if pd.notna(t) and pd.notna(anchor):
                trans=(t-anchor).total_seconds()/3600
                if trans<0: a.axvspan(trans,0,color="0.7",alpha=.18,linewidth=0)
                a.axvline(trans,color=COLOR_ATTACK,linestyle=":",linewidth=1)
        a.axhline(0,color="0.4",linestyle=":");a.axvline(0,color=COLOR_ATTACK,linestyle="--")
        a.set_ylim(-ylim,ylim);a.text(.99,.86,str(e),transform=a.transAxes,ha="right")
        a.grid(True,axis="y");_panel(a,chr(97+i))
    axes[-1,0].set_xlabel(L(lang,"relative"))
    fig.supylabel(L(lang,"effect"), x=0.015)
    fig.subplots_adjust(left=0.13, hspace=0.22)
    return save_fig(fig,"F4",cfg,lang,[p],"Confirmatory event-study estimates. Grey shading marks the attack-to-outage transition excluded from pretrend assessment; all panels share one y scale.")


def plot_f5(cfg, lang):
    d,p=_read(cfg,"f5_state_time.csv",["event_id","admin1","rel_h","reach_dev"])
    if "confirmatory" in d: d=d[d.confirmatory.eq(1)]
    if "design_admissible" in d: d=d[d.design_admissible.eq(1)]
    if "analysis_role" in d: d=d[d.analysis_role.isin(["attack_national","attack_regional","blind_test"])]
    pre=float(cfg.figures.get("main_event_plot_pre_h",24));post=float(cfg.figures.get("main_event_plot_post_h",72))
    d=d[d.rel_h.between(-pre,post)].dropna(subset=["admin1","reach_dev"])
    if d.empty: raise ValueError("No design-admissible confirmatory Admin1 event data")
    events=list(d.event_id.unique());apply_style(cfg,lang)
    fig,axes=plt.subplots(len(events),1,figsize=(cfg.figures["double_column_width_in"],max(2.5,2.0*len(events))),squeeze=False)
    vmax=max(.01,float(d.reach_dev.abs().quantile(.98)));max_rows=int(cfg.figures.get("main_admin1_max",12))
    for i,e in enumerate(events):
        g=d[d.event_id.eq(e)].pivot_table(index="admin1",columns="rel_h",values="reach_dev",aggfunc="mean")
        g=g.loc[g.abs().mean(axis=1).sort_values(ascending=False).head(max_rows).index]
        a=axes[i,0];im=a.imshow(g.values,aspect="auto",cmap=DIVERGING,vmin=-vmax,vmax=vmax)
        a.set_yticks(range(len(g)),g.index);xs=np.arange(len(g.columns));sel=xs[::max(1,len(xs)//8)]
        a.set_xticks(sel,[f"{g.columns[j]:g}" for j in sel]);a.text(.99,1.02,str(e),transform=a.transAxes,ha="right");_panel(a,chr(97+i))
    axes[-1,0].set_xlabel(L(lang,"relative"));fig.supylabel(L(lang,"admin1"),x=0.01)
    fig.colorbar(im,ax=axes.ravel().tolist(),label=L(lang,"effect"),fraction=.02,pad=.02)
    return save_fig(fig,"F5",cfg,lang,[p],"Main-text Admin1 heatmap limited to the largest absolute effects; the full state table remains in the artifact.")


def plot_f6(cfg, lang):
    d,p=_read(cfg,"f6_fingerprint.csv",["rel_h","planned_reach","planned_lo","planned_hi","attack_reach","attack_lo","attack_hi"])
    pre=float(cfg.figures.get("main_event_plot_pre_h",24));post=float(cfg.figures.get("main_event_plot_post_h",72))
    common=d.dropna(subset=["planned_reach","attack_reach"])
    common=common[common.rel_h.between(-pre,post)]
    if len(common)<4: raise ValueError("Insufficient common support between planned and attack curves")
    apply_style(cfg,lang);fig,ax=plt.subplots(figsize=(cfg.figures["single_column_width_in"],2.8))
    for kind,color,ls,mk in [("planned",COLOR_PLANNED,"--","s"),("attack",COLOR_ATTACK,"-","o")]:
        ax.plot(common.rel_h,common[f"{kind}_reach"],color=color,linestyle=ls,marker=mk,markevery=max(1,len(common)//8),label=L(lang,kind))
        ax.fill_between(common.rel_h,common[f"{kind}_lo"],common[f"{kind}_hi"],color=color,alpha=.15)
    ax.axvline(0,color="0.4",linestyle=":");ax.set_xlabel(L(lang,"relative"));ax.set_ylabel(L(lang,"reach"));ax.legend();ax.grid(True)
    return save_fig(fig,"F6",cfg,lang,[p],"Event-equal planned-outage and attack fingerprints restricted to their common supported relative-time interval.")


def plot_f7(cfg, lang):
    d,p=_read(cfg,"f7_heatmap.csv",["group","event_id","auc"]);d=d.dropna(subset=["auc"])
    piv=d.pivot_table(index="group",columns="event_id",values="auc",aggfunc="mean")
    piv=piv.loc[piv.mean(axis=1).sort_values(ascending=False).head(int(cfg.figures.get("main_admin1_max",12))*2).index]
    if piv.empty: raise ValueError("No fingerprint data")
    apply_style(cfg,lang);fig,ax=plt.subplots(figsize=(cfg.figures["double_column_width_in"],max(3.2,len(piv)*.10)))
    im=ax.imshow(piv.values,aspect="auto",cmap="viridis");ax.set_yticks(range(len(piv)),piv.index);ax.set_xticks(range(len(piv.columns)),piv.columns,rotation=35,ha="right");ax.set_ylabel(L(lang,"group"));ax.set_xlabel(L(lang,"event"));fig.colorbar(im,ax=ax,label=L(lang,"auc"),fraction=.025,pad=.02)
    return save_fig(fig,"F7",cfg,lang,[p],"Cross-event resilience fingerprint heatmap for ASN-by-Admin1 groups.")


def plot_f8(cfg, lang):
    pred,p1=_read(cfg,"f8_pred_scatter.csv",["target","model","event_id","pred","actual"])
    perf,p2=_read(cfg,"f8_model_perf.csv",["target","model","event_id","mae"])
    target="deficit_auc_full" if "deficit_auc_full" in set(pred.target) else pred.target.iloc[0]
    z=pred[(pred.target.eq(target))&(pred.model.eq("M4_ridge_history"))]
    if "fit_status" in z:
        z=z[z.fit_status.eq("ok")]
    if z.empty: raise ValueError("No successfully fitted prospective M4 predictions")
    apply_style(cfg,lang);fig,ax=plt.subplots(1,2,figsize=(cfg.figures["double_column_width_in"],3.0))
    for i,(e,g) in enumerate(z.groupby("event_id")):ax[0].scatter(g.actual,g.pred,label=e,alpha=.65,edgecolor="none",color=PALETTE[i%len(PALETTE)])
    lo=min(z.actual.min(),z.pred.min());hi=max(z.actual.max(),z.pred.max());ax[0].plot([lo,hi],[lo,hi],color="0.3",linestyle="--");ax[0].set_xlabel(L(lang,"actual"));ax[0].set_ylabel(L(lang,"pred"));ax[0].legend(frameon=False,fontsize=6);_panel(ax[0],"a")
    q=perf[(perf.target.eq(target))&(perf.event_id.eq("EVENT_EQUAL"))].copy()
    if "fit_failure_n" in q:
        q=q[q.fit_failure_n.eq(0)]
    q=q.sort_values("mae")
    ax[1].barh(q.model,q.mae,color=PALETTE[:len(q)]);ax[1].set_xlabel(L(lang,"event_equal_mae"));_panel(ax[1],"b")
    return save_fig(fig,"F8",cfg,lang,[p1,p2],"Rolling-origin, whole-event-held-out predictions and event-equal model performance.")


def plot_f9(cfg, lang):
    d,p=_read(cfg,"f9_variance.csv",["target","component","frac","status"])
    d=d[(d.status.eq("ok"))&d.frac.notna()]
    if d.empty: raise ValueError("Variance decomposition did not converge")
    apply_style(cfg,lang);fig,ax=plt.subplots(figsize=(cfg.figures["single_column_width_in"],2.8))
    targets=list(d.target.unique());bottom=np.zeros(len(targets))
    component_keys={"event":"event_component","asn":"asn_component","admin1":"admin1_component",
                    "interaction":"interaction_component","residual":"residual_component"}
    for i,c in enumerate(["event","asn","admin1","interaction","residual"]):
        vals=np.array([d[(d.target.eq(t))&(d.component.eq(c))].frac.sum() for t in targets])
        ax.bar(targets,vals,bottom=bottom,label=L(lang,component_keys[c]),color=PALETTE[i]);bottom+=vals
    ax.set_ylim(0,1);ax.set_ylabel(L(lang,"variance"));ax.legend(frameon=False,bbox_to_anchor=(1.02,1),loc="upper left")
    return save_fig(fig,"F9",cfg,lang,[p],"Crossed mixed-model variance components for observed resilience outcomes.")


def plot_f10(cfg, lang):
    dose,p1=_read(cfg,"f10_dose.csv",["exposure_hours","next_auc"]);surv,p2=_read(cfg,"f10_survival.csv",["hours","surv_unrecovered","group_label"])
    if dose.exposure_hours.nunique()<2: raise ValueError("Exposure dose has no variation")
    apply_style(cfg,lang);fig,ax=plt.subplots(1,2,figsize=(cfg.figures["double_column_width_in"],3.0))
    ax[0].scatter(dose.exposure_hours,dose.next_auc,alpha=.25,s=10);ax[0].set_xlabel(L(lang,"exposure"));ax[0].set_ylabel(L(lang,"auc"));_panel(ax[0],"a")
    for i,(g,z) in enumerate(surv.groupby("group_label")):ax[1].step(z.hours,z.surv_unrecovered,where="post",label=g,color=PALETTE[i],linestyle=["-","--","-."][i%3])
    ax[1].set_xlabel(L(lang,"hours_after_event"));ax[1].set_ylabel(L(lang,"survival"));ax[1].set_ylim(0,1);ax[1].legend(frameon=False);_panel(ax[1],"b")
    return save_fig(fig,"F10",cfg,lang,[p1,p2],"Prior outage dose versus subsequent deficit, and recovery survival stratified by exposure.")


def plot_f11(cfg, lang):
    d,p=_read(cfg,"f11_quadrant.csv",["group","event_id","auc","jsd","n_trace_event","quality"])
    d=d.dropna(subset=["auc","jsd"])
    if d.empty: raise ValueError("No path groups pass the preregistered quality gate")
    apply_style(cfg,lang);fig,ax=plt.subplots(figsize=(cfg.figures["single_column_width_in"],3.2))
    size=np.sqrt(d.n_trace_event.clip(lower=1))*3.5
    sig=d.get("asgeo_path_fdr_significant",pd.Series(0,index=d.index)).fillna(0).astype(int).eq(1)
    for i,(event,z) in enumerate(d.groupby("event_id",sort=True)):
        ax.scatter(z.auc,z.jsd,s=size.loc[z.index],alpha=.55,edgecolor="0.25",linewidth=.3,label=event,color=PALETTE[i%len(PALETTE)],marker=["o","s","^"][i%3])
    ax.scatter(d.loc[sig,"auc"],d.loc[sig,"jsd"],s=size.loc[sig]*1.25,facecolors="none",edgecolors="black",linewidths=1.0)
    candidates=d[sig | d.auc.ge(d.auc.quantile(.9))].sort_values(["auc","jsd"],ascending=False).head(int(cfg.path.get("main_figure_max_labels",12)))
    for _,r in candidates.iterrows():
        ax.annotate(str(r["group"]).replace("|Ukraine|"," / "),(r.auc,r.jsd),xytext=(3,3),textcoords="offset points",fontsize=max(5.5,float(cfg.figures["min_font_size_pt"])-1))
    ax.set_xlabel(L(lang,"auc"));ax.set_ylabel(L(lang,"path_jsd"))
    if d.event_id.nunique()>1: ax.legend(fontsize=6,loc="best")
    return save_fig(fig,"F11",cfg,lang,[p],"Functional deficit versus target-specific ASGeo-edge JSD among quality-admissible groups. Open rings mark BH-FDR significant path changes; marker area scales with valid traceroutes.")


def plot_f12(cfg, lang):
    d,p=_read(cfg,"f12_ingress.csv",["event_id","phase","edge","per_1000_trace"])
    d=d.dropna(subset=["per_1000_trace"])
    if d.empty: raise ValueError("No admissible ingress-edge frequencies")
    events=list(d.event_id.dropna().astype(str).drop_duplicates())
    if not events: raise ValueError("No event-specific ingress data")
    apply_style(cfg,lang)
    fig,axes=plt.subplots(1,len(events),figsize=(cfg.figures["double_column_width_in"],max(3.2,2.7)),squeeze=False)
    phases=["baseline","event","recovery"]
    for j,event in enumerate(events):
        ax=axes[0,j];z=d[d.event_id.astype(str).eq(event)]
        q=z.groupby(["phase","edge"],as_index=False).per_1000_trace.mean()
        top=q.groupby("edge").per_1000_trace.max().nlargest(8).index
        piv=q[q.edge.isin(top)].pivot(index="edge",columns="phase",values="per_1000_trace").fillna(0)
        piv=piv.loc[piv.max(axis=1).sort_values().index]
        y=np.arange(len(piv));w=.24
        for i,phase in enumerate(phases):
            ax.barh(y+(i-1)*w,piv.get(phase,pd.Series(0,index=piv.index)),height=w,
                    label=L(lang,phase),color=PALETTE[i])
        ax.set_yticks(y,[_compact_edge_label(x) for x in piv.index],
                      fontsize=max(5.5,float(cfg.figures["min_font_size_pt"])-1))
        ax.set_xlabel(L(lang,"edge_rate"));ax.set_title(event,fontsize=float(cfg.figures["min_font_size_pt"]))
        if j==0: ax.legend(frameon=False,ncol=1,fontsize=6)
        _panel(ax,chr(ord("a")+j))
    fig.tight_layout()
    return save_fig(fig,"F12",cfg,lang,[p],"Event-specific normalized high-confidence foreign-to-Ukraine ingress relations by phase; frequencies are per 1,000 valid traceroutes, not raw counts.")

def plot_f13(cfg, lang):
    d,p=_read(cfg,"f13_external.csv",["event_id","temporal_offset_h","spatial_jaccard","external_time_available","external_space_available"])
    zt=d[d.external_time_available.eq(1)&d.temporal_offset_h.notna()]
    spatial_col="topk_jaccard" if "topk_jaccard" in d.columns else "spatial_jaccard"
    zs=d[d.external_space_available.eq(1)&pd.to_numeric(d[spatial_col],errors="coerce").notna()].copy()
    if zt.empty and zs.empty: raise ValueError("No external network observation is available for concordance")
    apply_style(cfg,lang);fig,ax=plt.subplots(1,2,figsize=(cfg.figures["double_column_width_in"],3.0))
    if not zt.empty:
        y=np.arange(len(zt));ax[0].hlines(y,0,zt.temporal_offset_h,color="0.6");ax[0].scatter(zt.temporal_offset_h,y,color=PALETTE[0]);ax[0].axvline(0,color="0.3",linestyle=":");ax[0].set_yticks(y,zt.event_id);ax[0].set_xlabel(L(lang,"external_time_offset"))
    else: ax[0].text(.5,.5,"N/A",ha="center",va="center",transform=ax[0].transAxes)
    _panel(ax[0],"a")
    if not zs.empty:
        y=np.arange(len(zs));ax[1].barh(y,zs[spatial_col],color=PALETTE[2]);ax[1].set_yticks(y,zs.event_id);ax[1].set_xlim(0,1);ax[1].set_xlabel(L(lang,"spatial_jaccard"))
    else: ax[1].text(.5,.5,"N/A",ha="center",va="center",transform=ax[1].transAxes)
    _panel(ax[1],"b")
    return save_fig(fig,"F13",cfg,lang,[p],"Temporal and spatial concordance between frozen third-party network observations and self-measured anomalies.")

def plot_f14(cfg, lang):
    d,p=_read(cfg,"exp_a_event_metrics.csv",["event_id","delta_b2_vs_b1"])
    d=d.dropna(subset=["delta_b2_vs_b1"])
    if d.empty: raise ValueError("No estimable held-out scheduled-outage events")
    apply_style(cfg,lang)
    fig,ax=plt.subplots(figsize=(cfg.figures["single_column_width_in"],max(2.6,.35*len(d)+1.5)))
    d=d.sort_values("delta_b2_vs_b1")
    y=np.arange(len(d))
    colors=[PALETTE[2] if v>0 else PALETTE[1] for v in d.delta_b2_vs_b1]
    ax.barh(y,d.delta_b2_vs_b1,color=colors)
    ax.axvline(0,color="0.35",linewidth=.8)
    ax.set_yticks(y,d.event_id)
    ax.set_xlabel(L(lang,"delta_auprc"))
    ax.set_ylabel(L(lang,"validation_event"))
    ax.grid(True,axis="x")
    return save_fig(fig,"F14",cfg,lang,[p],
                    "Event-specific held-out calibration gain: AUPRC of scheduled-outage-calibrated B2 sensors minus stable B1 sensors.")


def plot_f15(cfg, lang):
    d,p=_read(cfg,"exp_b_target_universe_sensitivity.csv",
              ["event_id","target_universe","deficit_auc_full","max_deficit","n_analysis_unit"])
    d=d.dropna(subset=["deficit_auc_full","max_deficit"]).copy()
    # U2/U3 comparison is meaningful for national estimands; regional inference
    # is necessarily U3-only because country-only endpoints have no treatment label.
    q=d[d["target_universe"].isin(["U2_ukraine_valid_asn","U3_ukraine_valid_admin1_asn"])].copy()
    counts=q.groupby("event_id")["target_universe"].nunique()
    q=q[q["event_id"].isin(counts[counts>=2].index)]
    if q.empty: raise ValueError("No national event has both U2 and U3 target-universe estimates")
    events=list(q["event_id"].drop_duplicates())
    universes=["U2_ukraine_valid_asn","U3_ukraine_valid_admin1_asn"]
    labels={"U2_ukraine_valid_asn":"U2: UA + ASN",
            "U3_ukraine_valid_admin1_asn":"U3: UA + ASN + Admin1"}
    apply_style(cfg,lang);fig,ax=plt.subplots(1,2,figsize=(cfg.figures["double_column_width_in"],3.0))
    x=np.arange(len(events));markers=["o","s"];styles=["-","--"]
    for i,u in enumerate(universes):
        z=q[q.target_universe.eq(u)].set_index("event_id").reindex(events)
        ax[0].plot(x,z.deficit_auc_full,marker=markers[i],linestyle=styles[i],label=labels[u],color=PALETTE[i])
        ax[1].plot(x,z.max_deficit,marker=markers[i],linestyle=styles[i],label=labels[u],color=PALETTE[i])
    for a,key in zip(ax,["auc","max_deficit"]):
        a.set_xticks(x,events,rotation=30,ha="right");a.set_ylabel(L(lang,key));a.grid(True,axis="y")
    ax[0].legend(frameon=False,fontsize=6);_panel(ax[0],"a");_panel(ax[1],"b")
    return save_fig(fig,"F15",cfg,lang,[p],
                    "National event-effect sensitivity to retaining country-only Ukrainian endpoints (U2) versus requiring valid Admin1 (U3).")


FIGURES={f"F{i}":globals()[f"plot_f{i}"] for i in range(1,16)}


def render_all(cfg, lang):
    logger = get_logger(cfg.out_dir("logs"))
    outputs=[];warnings=[];manifest=[]
    progress = HeartbeatProgress(logger, f"figures.{lang}", total=len(FIGURES),
                                 unit="figure", log_every_n=1, log_every_s=30.0)
    progress.start(language=lang)
    for fig_id,fn in FIGURES.items():
        t0 = time.time()
        logger.info("figure start: lang=%s figure=%s", lang, fig_id)
        try:
            paths=fn(cfg,lang);outputs.extend(paths)
            manifest.append({"figure":fig_id,"language":lang,"status":"rendered","files":"|".join(paths)})
            elapsed_s = time.time() - t0
            logger.info("figure done: lang=%s figure=%s elapsed=%.1fs outputs=%d", lang, fig_id, elapsed_s, len(paths))
            progress.advance(current=fig_id, rendered=len(outputs))
        except Exception as exc:  # Validation failures are explicit; no empty/misleading figure is emitted.
            warnings.append({"figure":fig_id,"language":lang,"error":f"{type(exc).__name__}: {exc}"})
            manifest.append({"figure":fig_id,"language":lang,"status":"skipped","files":""})
            progress.mark_failed()
            logger.warning("figure skipped: lang=%s figure=%s error=%s: %s", lang, fig_id, type(exc).__name__, exc)
            progress.advance(current=fig_id, warnings=len(warnings))
    table_dir=cfg.out_dir("results_tables")
    pd.DataFrame(warnings).to_csv(table_dir/f"figure_warnings_{lang}.csv",index=False)
    pd.DataFrame(manifest).to_csv(table_dir/f"figure_manifest_{lang}.csv",index=False)
    progress.finish(outputs=len(outputs), warnings=len(warnings))
    return {"status":"ok" if not warnings else "warning","outputs":outputs,"warnings":warnings}
