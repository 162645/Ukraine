"""Paper Visualization Refactor: render only frozen Stage 0--3.5 artifacts."""
from __future__ import annotations

import argparse, json, subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

from .paper_visualization import PLOT_LABELS, COLORS, STATE_ZH, configure_theme, save_figure, state_order, zh_name

def _read(p: Path) -> pd.DataFrame:
    return pd.read_csv(p)

def _paths(run: Path):
    s = run / "results" / "stages"
    return {"s0": s/"stage00_quality", "s1": s/"stage01_canonical", "s2": s/"stage02_activity", "s3": s/"stage03_calibration_events", "s35": s/"stage03_5_episode_audit"}

def render_f01(run, out, lang):
    p = _paths(run); ips = _read(p["s1"]/"figure_data/fig_S1_1_ips_oblast_time.csv"); fbs = _read(p["s1"]/"figure_data/fig_S1_2_fbs_oblast_time.csv")
    for d in (ips, fbs): d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True); d["date"] = d.measure_time.dt.floor("D")
    states = state_order(ips.admin1); days = sorted(ips.date.dropna().unique()); daily = []
    for st in states:
        for day in days:
            a, b = ips[(ips.admin1==st)&(ips.date==day)], fbs[(fbs.admin1==st)&(fbs.date==day)]
            valid = a.cycle_complete.fillna(False).astype(bool) & b.cycle_complete.fillna(False).astype(bool)
            if valid.sum() < 9: daily.append((day,st,np.nan,np.nan,valid.sum())); continue
            daily.append((day,st,2*float((a.loc[valid,"IPS_ratio"]<0.90).sum()),2*float((b.loc[valid,"FBS_ratio"]<0.95).sum()),valid.sum()))
    dd = pd.DataFrame(daily, columns=["date","admin1","IPS_outage_hours","FBS_outage_hours","valid_cycle_n"]); dd.to_csv(out/"figure_data/F01_daily_outage_hours.csv", index=False)
    fig, ax = plt.subplots(2,1,figsize=(7.0,4.4),sharex=True,sharey=True,constrained_layout=True)
    for a,col,label in zip(ax,["IPS_outage_hours","FBS_outage_hours"],[PLOT_LABELS[lang]["ips"],PLOT_LABELS[lang]["fbs"]]):
        z=dd.pivot(index="admin1",columns="date",values=col).reindex(states); im=a.imshow(z.values,aspect="auto",interpolation="none",origin="lower",vmin=0,vmax=24,cmap="Reds"); a.set_yticks(range(len(states))); a.set_yticklabels([zh_name(x,lang) for x in states]); a.set_ylabel(PLOT_LABELS[lang]["oblast"]); a.set_title(label,loc="left",fontweight="bold"); a.grid(False)
        for x in np.where(z.isna().all(axis=0))[0]: a.axvline(x,color=COLORS["missing"],lw=1.2)
        reg = run.parent.parent / "config" / "event_registry_v1.csv"
        if reg.exists():
            ev = pd.read_csv(reg); ev["anchor"] = pd.to_datetime(ev.get("primary_anchor_utc"), utc=True, errors="coerce")
            for stamp in ev.anchor.dropna():
                day = stamp.floor("D")
                if day in days: a.axvline(days.index(day), color="#222222", lw=.45, alpha=.65, zorder=3)
    ax[-1].set_xticks(np.linspace(0,len(days)-1,min(8,len(days)),dtype=int)); ax[-1].set_xticklabels([pd.Timestamp(days[i]).strftime("%Y-%m") for i in ax[-1].get_xticks()]); ax[-1].set_xlabel(PLOT_LABELS[lang]["date"])
    c=fig.colorbar(im,ax=ax.ravel().tolist(),fraction=.02,pad=.01); c.set_label(PLOT_LABELS[lang]["outage_hours"]); save_figure(fig,out/f"main/{lang}/F01_canonical_ips_fbs_daily",lang,{"figure":"F01","source":"stage01 canonical ratio tables","aggregation":"2h valid cycles x 2h; day NA if <9/12 valid cycles","missing":"NA; no interpolation","message":"Compare daily IPS and FBS outage hours with common scale."})

def render_f02(run, out, lang):
    d=_read(_paths(run)["s1"]/"figure_data/fig_S1_4_0826_signal_curve.csv"); x=d.relative_h; fig,ax=plt.subplots(figsize=(3.35,2.45),constrained_layout=True); ax.plot(x,d.IPS_ratio,color=COLORS["ips"],lw=1.5,label=PLOT_LABELS[lang]["ips"]); ax.plot(x,d.FBS_ratio,color=COLORS["fbs"],lw=.9,label=PLOT_LABELS[lang]["fbs"]); ax.axhline(1,color="#bdbdbd",lw=.7); ax.axhline(.9,color="#d9a3a8",ls="--",lw=.6); ax.axhline(.95,color="#a5c8c4",ls="--",lw=.6); ax.axvline(0,color="black",ls="--",lw=.8); ax.set_xlim(-24,60); ax.set_ylim(0,1.1); ax.set_xlabel(PLOT_LABELS[lang]["time"]+" relative to "+PLOT_LABELS[lang]["attack"]); ax.set_ylabel(PLOT_LABELS[lang]["ips_ratio"]); ax.legend(frameon=False,loc="lower left"); save_figure(fig,out/f"main/{lang}/F02_2024-08-26_event_curve",lang,{"figure":"F02","source":"stage01 fig_S1_4","baseline":"preceding 7-day mean","range":"-24h to +60h","missing":"NA breaks the line; no interpolation","causal_claim":False})

def render_f03(run,out,lang):
    d=_read(_paths(run)["s2"]/"tables/ip_activity.csv"); d=d.dropna(subset=["activity_raw","target_admin1"]); d.activity_raw=pd.to_numeric(d.activity_raw,errors="coerce"); d=d.dropna(subset=["activity_raw"]); d.to_csv(out/"figure_data/F03_activity_source.csv",index=False)
    states=state_order(d.target_admin1); fig,(a,b)=plt.subplots(1,2,figsize=(7,3.8),gridspec_kw={"width_ratios":[1.15,1]},constrained_layout=True); vals=np.sort(d.activity_raw.values); step=max(1,len(vals)//20000); a.plot(vals[::step],np.linspace(0,1,len(vals))[::step],color="#4d4d4d",lw=1); med=np.median(vals); a.axvline(med,color=COLORS["primary"],ls="--",lw=.9); a.set_xlabel(PLOT_LABELS[lang]["activity"]); a.set_ylabel("ECDF");
    groups=[d.loc[d.target_admin1==s,"activity_raw"].values for s in states]; meds=[np.median(x) for x in groups]; order=np.argsort(meds); b.boxplot([groups[i] for i in order],vert=False,showfliers=False,patch_artist=True,boxprops={"facecolor":"#d9e6e5","edgecolor":"#4d4d4d"},medianprops={"color":COLORS["ips"]}); b.set_yticks(range(1,len(order)+1)); b.set_yticklabels([zh_name(states[i],lang) for i in order]); b.set_xlabel(PLOT_LABELS[lang]["activity"]); save_figure(fig,out/f"main/{lang}/F03_activity_distribution",lang,{"figure":"F03","source":"stage02 ip_activity.csv","sample_n":int(len(d)),"panels":"ECDF and common-scale horizontal boxplots by Oblast; outliers hidden for readability","summary":"p25/median/p75 are retained in source CSV"})

def render_f04(run,out,lang):
    p=_paths(run); c=_read(p["s35"]/"tables/episode_count_comparison_by_oblast.csv"); c=c[c.panel.isin(["primary","augmented"])].copy(); c["n"] = c.audit_episode_n; c.to_csv(out/"figure_data/F04_episode_counts.csv",index=False); states=state_order(c.geo_name)
    fig,(a,b)=plt.subplots(1,2,figsize=(7,3.8),gridspec_kw={"width_ratios":[1.25,1]},constrained_layout=True); piv=c.pivot(index="geo_name",columns="panel",values="n").reindex(states).fillna(0); y=np.arange(len(states)); a.hlines(y,piv.get("primary",0),piv.get("augmented",0),color="#777",lw=1); a.scatter(piv.get("primary",0),y,color=COLORS["primary"],s=16,label=PLOT_LABELS[lang]["primary"]); a.scatter(piv.get("augmented",0),y,color=COLORS["augmented"],s=16,label=PLOT_LABELS[lang]["augmented"]); a.axvline(3,color="#333",ls="--",lw=.7); a.set_yticks(y); a.set_yticklabels([zh_name(s,lang) for s in states]); a.set_xlabel("修订后的独立 episode 数" if lang=="zh" else "Revised independent episode count"); a.legend(frameon=False)
    events=_read(p["s3"]/"tables/calibration_events.csv"); events["month"]=events.event_date.astype(str).str[:7]; events["episode_v2"]=events.episode_id_v2_augmented.fillna(events.episode_id_v2_main); m=events.groupby(["geo_name","month"])["episode_v2"].nunique().unstack(fill_value=0).reindex(states); b.imshow(m.values,aspect="auto",interpolation="none",cmap="Purples",vmin=0); b.set_yticks(y); b.set_yticklabels([zh_name(s,lang) for s in states]); b.set_xticks(range(len(m.columns))); b.set_xticklabels(m.columns,rotation=45,ha="right"); b.set_xlabel("月份" if lang=="zh" else "Month"); b.set_title("修订后的 episode 覆盖" if lang=="zh" else "Revised episode coverage",loc="left"); save_figure(fig,out/f"main/{lang}/F04_calibration_evidence_coverage",lang,{"figure":"F04","source":"stage03 and stage03.5 revised registry","episode_rule":"episode_id_v2; at least one clean 2h cycle separates episodes","reference":"x=3 support line","old_registry":"not used for main counts"})

def render_appendix(run,out,lang):
    p=_paths(run); s0=p["s0"]; outdir=out/f"appendix/{lang}"; outdir.mkdir(parents=True,exist_ok=True)
    # A01: three quality views from frozen figure-data tables.
    files=[s0/"figure_data/fig_S0_1_measurement_response_timeline.csv",s0/"figure_data/fig_S0_2_daily_cycle_completeness.csv",s0/"figure_data/fig_S0_3_cycle_completeness_matrix.csv"]; fig,ax=plt.subplots(1,3,figsize=(7,2.4),constrained_layout=True)
    for a,f in zip(ax,files):
        d=_read(f); num=d.select_dtypes(include=[np.number]); a.imshow(num.values if not num.empty else np.zeros((1,1)),aspect="auto",interpolation="none",cmap="Greys"); a.set_xticks([]); a.set_yticks([]); a.set_title(f.stem.replace("fig_S0_","S0."),fontsize=8)
    save_figure(fig,outdir/"A01_measurement_quality",lang,{"figure":"A01","source":"stage00 quality figure-data","missing":"retained as missing, never recoded to zero"})
    for fid,fn,title in [("A02","fig_S1_1_ips_oblast_time.csv","Raw IPS ratio heatmap"),("A03","fig_S1_3_ips_fbs_binary.csv","IPS/FBS binary outage raster")]:
        d=_read(p["s1"]/f"figure_data/{fn}"); d.to_csv(out/"figure_data"/(fid+"_source.csv"),index=False); col="IPS_ratio" if fid=="A02" else "ips_outage"; d.measure_time=pd.to_datetime(d.measure_time,utc=True); mat=d.pivot(index="admin1",columns="measure_time",values=col).reindex(state_order(d.admin1)); fig,ax=plt.subplots(figsize=(7,3.5),constrained_layout=True); arr=mat.astype(float).values if fid=="A02" else mat.astype(float).values; ax.imshow(arr,aspect="auto",interpolation="none",cmap="Reds" if fid=="A02" else ListedColormap(["#f7f7f7",COLORS["ips"]])); ax.set_yticks(range(len(mat))); ax.set_yticklabels([zh_name(x,lang) for x in mat.index]); ax.set_xlabel(PLOT_LABELS[lang]["time"]); ax.set_ylabel(PLOT_LABELS[lang]["oblast"]); ax.set_title(title,loc="left",fontweight="bold"); save_figure(fig,outdir/(fid+"_"+("raw_ratio_heatmap" if fid=="A02" else "binary_outage_raster")),lang,{"figure":fid,"source":fn,"missing":"NA shown in light gray; no fill or interpolation"})
    d=_read(p["s2"]/"tables/ip_activity.csv"); d.activity_raw=pd.to_numeric(d.activity_raw,errors="coerce"); fig,ax=plt.subplots(figsize=(3.35,2.4),constrained_layout=True); ax.hist(d.activity_raw.dropna(),bins=30,weights=np.ones(d.activity_raw.notna().sum())/d.activity_raw.notna().sum()*100,color="#7f8c8d",edgecolor="white"); ax.set_xlabel(PLOT_LABELS[lang]["activity"]); ax.set_ylabel("IP share (%)"); save_figure(fig,outdir/"A04_activity_histogram",lang,{"figure":"A04","source":"stage02 ip_activity.csv","denominator":"mapped IPs with valid Activity"})
    c=_read(p["s35"]/"tables/episode_count_comparison_by_oblast.csv"); c=c[c.panel=="primary"]; fig,ax=plt.subplots(figsize=(3.35,2.5),constrained_layout=True); x=np.arange(len(c)); ax.plot(x,c.frozen_episode_n,"o-",color="#999",label="legacy/frozen"); ax.plot(x,c.audit_episode_n,"o-",color=COLORS["primary"],label="revised v2"); ax.set_ylabel("Independent episodes"); ax.set_xlabel(PLOT_LABELS[lang]["oblast"]); ax.set_xticks(x); ax.set_xticklabels([zh_name(s,lang) for s in c.geo_name],rotation=60,ha="right",fontsize=6); ax.legend(frameon=False); save_figure(fig,outdir/"A05_episode_audit_old_vs_revised",lang,{"figure":"A05","source":"stage03.5 episode_count_comparison_by_oblast.csv","focus":"revised episode_id_v2; Volyn and Poltava remain auditable"})

    cal=_read(p["s1"]/"figure_data/fig_S1_5_power_internet_calendar.csv"); cal.date=pd.to_datetime(cal.date,utc=True); cal["month_label"]=cal.date.dt.strftime("%Y-%m"); cal["day_num"]=cal.date.dt.day; months=list(dict.fromkeys(cal.month_label)); mat=cal.pivot(index="month_label",columns="day_num",values="ips_outage_hours").reindex(months).reindex(columns=range(1,32)); fig,ax=plt.subplots(figsize=(7,2.6),constrained_layout=True); im=ax.imshow(mat.values,aspect="auto",interpolation="none",cmap="Reds",vmin=0,vmax=24); ax.set_xlabel("Day of month (UTC)"); ax.set_ylabel("Month (UTC)"); ax.set_xticks([0,4,9,14,19,24,29]); ax.set_xticklabels([1,5,10,15,20,25,30]); ax.set_yticks(range(len(months))); ax.set_yticklabels(months); cbar=fig.colorbar(im,ax=ax,fraction=.02,pad=.01); cbar.set_label("Observed IPS outage hours"); save_figure(fig,outdir/"P_calendar_power_internet_provisional",lang,{"figure":"P_calendar","role":"PROVISIONAL","source":"stage01 fig_S1_5","wording":"observed/covered, not causal; x is day of month and y is month label"})

def build_audit(run,out):
    rows=[]; stages=[("stage00_quality","Stage 0"),("stage01_canonical","Stage 1"),("stage02_activity","Stage 2"),("stage03_calibration_events","Stage 3"),("stage03_5_episode_audit","Stage 3.5")]
    for dirname,label in stages:
        for f in sorted((run/"results/stages"/dirname/"figures").glob("*.png")):
            n=f.name.lower(); role="APPENDIX"; decision="supporting diagnostic"
            if "s1_1" in n or "s1_2" in n or "s1_4" in n or "s2_1" in n or "s2_4" in n or "s3_1" in n or "s3_2" in n or "s3_3" in n: role="MAIN/APPENDIX"
            if "s1_5" in n: role="PROVISIONAL"; decision="descriptive calendar; no causal claim"
            if "s2_3" in n or "s2_6" in n: role="DIAGNOSTIC_ONLY"; decision="within-Oblast decile bookkeeping"
            rows.append(f"| {label} | `{f.name}` | {role} | {decision} |")
    text="# Paper Figure Audit\n\nExisting Stage 0--3.5 PNGs are classified below. This is an audit of frozen artifacts only; it does not run or modify science stages.\n\n| Stage | Existing figure | Role | Decision / limitation |\n|---|---|---|---|\n"+"\n".join(rows)+"\n\nMissing cycles remain NA (never zero/interpolate/connect). The revised `episode_id_v2` is used for F04/A05; legacy IDs are retained only for audit.\n"
    (out/"audit/PAPER_FIGURE_AUDIT.md").write_text(text,encoding="utf-8")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--run-dir",required=True); ap.add_argument("--out-dir",default=None); args=ap.parse_args(); run=Path(args.run_dir).resolve(); out=Path(args.out_dir or run/"results/paper_visualization").resolve(); out.mkdir(parents=True,exist_ok=True); (out/"figure_data").mkdir(exist_ok=True); (out/"metadata").mkdir(exist_ok=True); (out/"captions").mkdir(exist_ok=True); (out/"audit").mkdir(exist_ok=True)
    build_audit(run,out)
    for lang in ("en","zh"):
        configure_theme(lang); render_f01(run,out,lang); render_f02(run,out,lang); render_f03(run,out,lang); render_f04(run,out,lang); render_appendix(run,out,lang)
    index=[("F01","Stage 1","MAIN","F01_canonical_ips_fbs_daily","Daily IPS/FBS outage hours; shared scale; NA incomplete days."),("F02","Stage 1","MAIN","F02_2024-08-26_event_curve","Event-relative ratios; descriptive, not causal."),("F03","Stage 2","MAIN","F03_activity_distribution","Activity heterogeneity by mapped IP and Oblast."),("F04","Stage 3/3.5","MAIN","F04_calibration_evidence_coverage","Revised independent episode support; x=3 reference."),("A01","Stage 0","APPENDIX","A01_measurement_quality","Measurement coverage diagnostics."),("A02","Stage 1","APPENDIX","A02_raw_ratio_heatmap","Raw 2h ratio detail."),("A03","Stage 1","APPENDIX","A03_binary_outage_raster","Binary thresholds with missing gray."),("A04","Stage 2","APPENDIX","A04_activity_histogram","Activity distribution, percent denominator."),("A05","Stage 3.5","APPENDIX","A05_episode_audit_old_vs_revised","Legacy versus revised episode audit.")]
    lines=["# PAPER_FIGURE_INDEX\n\nAll language variants use the same source CSVs (`same_source_data=true`).\n\n| ID | Source | Role | English | 中文 | Message / limitation |\n|---|---|---|---|---|---|"]
    for fid,src,role,name,msg in index: lines.append(f"| {fid} | {src} | {role} | `main/en/{name}.png` or `appendix/en/{name}.png` | `main/zh/{name}.png` or `appendix/zh/{name}.png` | {msg} |")
    (out/"PAPER_FIGURE_INDEX.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    (out/"captions/captions_en.md").write_text("# Captions (English)\n\nF01--F04 captions are generated from frozen Stage 0--3.5 tables; all ratios use the preceding seven-day mean, missing cycles are NA, and adjacency is not a causal claim.\n",encoding="utf-8")
    (out/"captions/captions_zh.md").write_text("# 图注（中文）\n\nF01--F04 均来自冻结的 Stage 0--3.5 表；比率使用此前七天均值，缺失周期保留为 NA，相邻变化不构成因果证据。\n",encoding="utf-8")
    (out/"metadata/run_metadata.json").write_text(json.dumps({"run_dir":str(run),"source_stages":"0-3.5","same_source_data":True,"stage4_used":False,"generated_by":"paper_figures_current.py"},indent=2),encoding="utf-8")

if __name__ == "__main__": main()
