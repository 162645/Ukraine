"""Exploratory state-level case study for the 2024-08-26 attack.

This module is intentionally downstream-only.  It reuses frozen H1 outcomes,
Stage-2 Activity deciles and Stage-4.5 Sensitivity/Q labels; it does not
re-estimate any upstream label, window, event, or outcome definition.
"""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

EVENT = "E2024_0826_ATTACK"
QUINTILES = [f"Q{i}" for i in range(1, 6)]
DECILES = [f"D{i}" for i in range(1, 11)]
SEED = 20260912
BOOTSTRAP_N = 1000

def sha256(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def _rank_corr(x,y):
    x=np.asarray(x,float); y=np.asarray(y,float); ok=np.isfinite(x)&np.isfinite(y)
    if ok.sum()<3 or np.unique(x[ok]).size<2 or np.unique(y[ok]).size<2:return np.nan
    return float(spearmanr(x[ok],y[ok]).statistic)

def _partial_spearman(g):
    g=g.dropna(subset=["sensitivity","reach_drop","activity_score_smoothed"])
    if len(g)<5:return np.nan
    rs=g.sensitivity.rank(method="average").to_numpy(float); ry=g.reach_drop.rank(method="average").to_numpy(float); ra=g.activity_score_smoothed.rank(method="average").to_numpy(float)
    z=np.column_stack([np.ones(len(g)),ra]); bx=np.linalg.lstsq(z,rs,rcond=None)[0]; by=np.linalg.lstsq(z,ry,rcond=None)[0]
    x=rs-z@bx; y=ry-z@by
    return float(np.corrcoef(x,y)[0,1]) if np.std(x)>0 and np.std(y)>0 else np.nan

def _state_seed(state: str, offset: int = 0) -> int:
    """Stable per-state seed; Python's built-in hash is process-randomized."""
    digest = hashlib.sha256(str(state).encode("utf-8")).hexdigest()
    return SEED + int(digest[:8], 16) % 10000 + offset

def load_data(h1_path:Path,label_path:Path,h2_path:Path):
    h1=pd.read_parquet(h1_path)
    h1=h1[(h1.event_id==EVENT)&h1.outcome_valid].copy()
    cols=["dst_ip","prefix24","target_admin1","activity_decile","pre_attack_reach","attack_reach","reach_drop"]
    h1=h1[cols].drop_duplicates("dst_ip")
    h1["reach_drop"]=pd.to_numeric(h1.reach_drop,errors="coerce"); h1=h1[h1.reach_drop.notna() & h1.target_admin1.notna() & h1.activity_decile.isin(DECILES)].copy()
    labels=pd.read_parquet(label_path)
    lcols=["dst_ip","prefix24","target_admin1","activity_score_smoothed","s_reach_augmented","support_episode_n_augmented","augmented_estimable"]
    labels=labels[[c for c in lcols if c in labels.columns]].drop_duplicates("dst_ip")
    labels["support_episode_n_augmented"]=pd.to_numeric(labels["support_episode_n_augmented"],errors="coerce")
    labels["s_reach_augmented"]=pd.to_numeric(labels["s_reach_augmented"],errors="coerce")
    a=h1.merge(labels,on="dst_ip",how="left",suffixes=("","_label"),validate="one_to_one")
    a["target_admin1"]=a["target_admin1_label"].fillna(a["target_admin1"]); a["prefix24"]=a["prefix24_label"].fillna(a["prefix24"])
    a["sensitivity"]=a["s_reach_augmented"]
    a["population_type"]="FULL_ACTIVITY_CONTEXT"
    main=(a.support_episode_n_augmented.ge(3)&a.augmented_estimable.fillna(False)&a.s_reach_augmented.notna()).copy()
    a["is_population_a"]=main
    # Frozen H2 Q labels are used only as a consistency check/label source.
    h2=pd.read_parquet(h2_path,columns=["dst_ip","event_id","quintile","panel"])
    h2=h2[(h2.event_id==EVENT)&(h2.panel=="MAIN")].drop_duplicates("dst_ip")[["dst_ip","quintile"]]
    a=a.merge(h2,on="dst_ip",how="left",validate="one_to_one")
    pop_a=a[a.is_population_a & a.quintile.isin(QUINTILES)].copy(); pop_a["population_type"]="SENSITIVITY_CASE_POPULATION"
    pop_b=a.copy()
    # H2's frozen main population must be 700,012 IPs / 17 states.
    assert pop_a.dst_ip.nunique()==700012, f"Frozen Population A changed: {pop_a.dst_ip.nunique()}"
    return pop_a,pop_b

def shock_summary(pop_b):
    rows=[]
    for s,g in pop_b.groupby("target_admin1",observed=True):
        y=g.reach_drop.to_numpy(float); rows.append({"population_type":"FULL_ACTIVITY_CONTEXT","target_admin1":s,"state_ip_n":len(g),"positive_drop_ip_n":int((y>0).sum()),"mean_reach_drop":float(np.mean(y)),"median_reach_drop":float(np.median(y)),"p25":float(np.quantile(y,.25)),"p75":float(np.quantile(y,.75)),"p90":float(np.quantile(y,.90)),"fraction_drop_gt0":float(np.mean(y>0)),"fraction_drop_ge_0_10":float(np.mean(y>=.10)),"fraction_drop_ge_0_25":float(np.mean(y>=.25)),"fraction_drop_ge_0_50":float(np.mean(y>=.50)),"pre_attack_reach_mean":float(g.pre_attack_reach.mean()),"attack_reach_mean":float(g.attack_reach.mean())})
    return pd.DataFrame(rows)

def _raw_table(g):
    rows=[]
    for q,z in g.groupby("quintile",observed=True):
        y=z.reach_drop.to_numpy(float); rows.append({"quintile":q,"ip_n":len(z),"mean_reach_drop":float(y.mean()),"median_reach_drop":float(np.median(y)),"p25":float(np.quantile(y,.25)),"p75":float(np.quantile(y,.75)),"severe025":float(np.mean(y>=.25)),"severe050":float(np.mean(y>=.50))})
    return pd.DataFrame(rows).set_index("quintile").reindex(QUINTILES)

def _adjusted_table(g):
    # Equal weight valid Activity deciles within each state, matching H3.
    z=g.groupby(["activity_decile","quintile"],observed=True).agg(ip_n=("reach_drop","size"),mean_reach_drop=("reach_drop","mean"),severe025=("reach_drop",lambda x:float(np.mean(x>=.25)),),severe050=("reach_drop",lambda x:float(np.mean(x>=.50)),)).reset_index()
    rows=[]
    for q in QUINTILES:
        x=z[z.quintile==q]
        rows.append({"quintile":q,"activity_decile_n":int(x.activity_decile.nunique()),"ip_n":int(x.ip_n.sum()),"mean_reach_drop":float(x.mean_reach_drop.mean()) if len(x) else np.nan,"severe025":float(x.severe025.mean()) if len(x) else np.nan,"severe050":float(x.severe050.mean()) if len(x) else np.nan})
    return pd.DataFrame(rows).set_index("quintile").reindex(QUINTILES),z

def _cluster_arrays(g, group_col, groups):
    g=g.copy(); clusters=sorted(g.prefix24.dropna().unique()); ci={v:i for i,v in enumerate(clusters)}; g["_ci"]=g.prefix24.map(ci)
    sums=np.zeros((len(clusters),len(groups))); counts=np.zeros_like(sums)
    for j,k in enumerate(groups):
        z=g[g[group_col]==k].groupby("_ci").reach_drop.agg(["sum","count"])
        sums[z.index,j]=z["sum"]; counts[z.index,j]=z["count"]
    return clusters,sums,counts

def _cluster_bootstrap(g, group_col, groups, metric, n_boot=BOOTSTRAP_N, seed=SEED):
    clusters,sums,counts=_cluster_arrays(g,group_col,groups)
    if len(clusters)<5:return np.nan,np.nan,len(clusters)
    rng=np.random.default_rng(seed); vals=[]
    for _ in range(n_boot):
        idx=rng.integers(0,len(clusters),len(clusters)); ss=sums[idx].sum(axis=0); cc=counts[idx].sum(axis=0); means=np.divide(ss,cc,out=np.full(len(groups),np.nan),where=cc>0)
        val=metric(means,cc)
        if np.isfinite(val): vals.append(val)
    if len(vals)<100:return np.nan,np.nan,len(clusters)
    return float(np.quantile(vals,.025)),float(np.quantile(vals,.975)),len(clusters)

def _boot_raw(means,counts):return means[4]-means[0]
def _boot_activity(means,counts):return means[9]-means[0]

def _adjusted_bootstrap(g,n_boot=BOOTSTRAP_N,seed=SEED):
    clusters=sorted(g.prefix24.dropna().unique()); ci={v:i for i,v in enumerate(clusters)}; g=g.copy(); g["_ci"]=g.prefix24.map(ci); arrs=[]
    for d in DECILES:
        sums=np.zeros((len(clusters),5)); counts=np.zeros_like(sums)
        for j,q in enumerate(QUINTILES):
            z=g[(g.activity_decile==d)&(g.quintile==q)].groupby("_ci").reach_drop.agg(["sum","count"]); sums[z.index,j]=z["sum"]; counts[z.index,j]=z["count"]
        arrs.append((sums,counts))
    if len(clusters)<5:return np.nan,np.nan,len(clusters)
    rng=np.random.default_rng(seed+11); vals=[]
    for _ in range(n_boot):
        idx=rng.integers(0,len(clusters),len(clusters)); qmeans=[]
        for sums,counts in arrs:
            ss=sums[idx].sum(axis=0); cc=counts[idx].sum(axis=0); qmeans.append(np.divide(ss,cc,out=np.full(5,np.nan),where=cc>0))
        qmeans=np.asarray(qmeans); means=np.nanmean(qmeans,axis=0)
        if np.isfinite(means[[0,4]]).all():vals.append(means[4]-means[0])
    if len(vals)<100:return np.nan,np.nan,len(clusters)
    return float(np.quantile(vals,.025)),float(np.quantile(vals,.975)),len(clusters)

def state_analysis(pop_a,shock):
    rows=[]; qrows=[]; drows=[]
    for s,g in pop_a.groupby("target_admin1",observed=True):
        raw=_raw_table(g); adj,adj_detail=_adjusted_table(g)
        raw_eff=float(raw.loc["Q5","mean_reach_drop"]-raw.loc["Q1","mean_reach_drop"]); adj_eff=float(adj.loc["Q5","mean_reach_drop"]-adj.loc["Q1","mean_reach_drop"])
        raw_lo,raw_hi,prefix_n=_cluster_bootstrap(g,"quintile",QUINTILES,_boot_raw,seed=_state_seed(s)); adj_lo,adj_hi,prefix_n2=_adjusted_bootstrap(g,seed=_state_seed(s,11))
        act=g.groupby("activity_decile",observed=True).agg(ip_n=("reach_drop","size"),mean_reach_drop=("reach_drop","mean"),severe025=("reach_drop",lambda x:float(np.mean(x>=.25)))).reindex(DECILES)
        act_eff=float(act.loc["D10","mean_reach_drop"]-act.loc["D1","mean_reach_drop"]) if act.loc[["D1","D10"],"mean_reach_drop"].notna().all() else np.nan
        act_lo,act_hi,prefix_n3=_cluster_bootstrap(g,"activity_decile",DECILES,_boot_activity,seed=_state_seed(s,31))
        a_q=[]
        for q in QUINTILES:
            qrows.append({"population_type":"SENSITIVITY_CASE_POPULATION","target_admin1":s,"quintile":q,"raw_mean_reach_drop":raw.loc[q,"mean_reach_drop"],"raw_median_reach_drop":raw.loc[q,"median_reach_drop"],"raw_p25":raw.loc[q,"p25"],"raw_p75":raw.loc[q,"p75"],"raw_severe025":raw.loc[q,"severe025"],"raw_severe050":raw.loc[q,"severe050"],"activity_adjusted_mean_reach_drop":adj.loc[q,"mean_reach_drop"],"activity_decile_n":adj.loc[q,"activity_decile_n"]})
        for d in DECILES:
            drows.append({"population_type":"SENSITIVITY_CASE_POPULATION","target_admin1":s,"activity_decile":d,"ip_n":act.loc[d,"ip_n"],"mean_reach_drop":act.loc[d,"mean_reach_drop"],"severe025":act.loc[d,"severe025"]})
        rho=_rank_corr(np.arange(1,6),adj.mean_reach_drop.to_numpy(float)); arho=_rank_corr(np.arange(1,11),act.mean_reach_drop.to_numpy(float)); partial=_partial_spearman(g)
        q1_n=float(raw.loc["Q1","ip_n"]) if "Q1" in raw.index and pd.notna(raw.loc["Q1","ip_n"]) else 0
        q5_n=float(raw.loc["Q5","ip_n"]) if "Q5" in raw.index and pd.notna(raw.loc["Q5","ip_n"]) else 0
        if not np.isfinite(adj_eff) or not np.isfinite(adj_lo) or prefix_n<5 or q1_n==0 or q5_n==0: cls="NOT_ESTIMABLE"
        elif adj_eff>0 and adj_lo>0: cls="ROBUST_POSITIVE"
        elif adj_eff>0: cls="DIRECTIONAL_POSITIVE"
        elif adj_eff<0 and adj_hi<0: cls="ROBUST_NEGATIVE"
        else: cls="DIRECTIONAL_NEGATIVE"
        ratio=adj_eff/raw_eff if np.isfinite(raw_eff) and abs(raw_eff)>1e-12 else np.nan
        direction="preserve" if np.sign(raw_eff)==np.sign(adj_eff) else ("eliminate" if abs(adj_eff)<abs(raw_eff) else "reverse")
        if np.sign(raw_eff)==0 or np.sign(adj_eff)==0: direction="attenuate" if abs(adj_eff)<abs(raw_eff) else "preserve"
        shockrow=shock[shock.target_admin1==s]
        rows.append({"population_type":"SENSITIVITY_CASE_POPULATION","target_admin1":s,"state_shock_severity":float(shockrow.mean_reach_drop.iloc[0]) if len(shockrow) else np.nan,"valid_ip_n_main":len(g),"valid_prefix24_n":prefix_n,"raw_q5_q1":raw_eff,"raw_q5_q1_ci_low":raw_lo,"raw_q5_q1_ci_high":raw_hi,"adjusted_q5_q1":adj_eff,"adjusted_q5_q1_ci_low":adj_lo,"adjusted_q5_q1_ci_high":adj_hi,"sensitivity_class":cls,"raw_effect_sign":np.sign(raw_eff),"adjusted_effect_sign":np.sign(adj_eff),"sensitivity_trend_rho":rho,"strict_monotonic_increasing":bool(np.all(np.diff(adj.mean_reach_drop.dropna())>0)) if adj.mean_reach_drop.notna().all() else False,"activity_d10_d1":act_eff,"activity_d10_d1_ci_low":act_lo,"activity_d10_d1_ci_high":act_hi,"activity_trend_rho":arho,"partial_spearman_sensitivity_reachdrop_given_activity":partial,"q1_severe025":raw.loc["Q1","severe025"],"q5_severe025":raw.loc["Q5","severe025"],"activity_adjustment_ratio":ratio,"activity_adjustment_direction":direction,"prefix24_bootstrap_n":prefix_n,"population_type_note":"Population A; frozen AUGMENTED_STRICT_SUPPORT3"})
    return pd.DataFrame(rows),pd.DataFrame(qrows),pd.DataFrame(drows)

def loso(summary):
    z=summary[summary.sensitivity_class!="NOT_ESTIMABLE"].copy(); vals=[]
    for s in z.target_admin1:
        x=z[z.target_admin1!=s].adjusted_q5_q1.mean(); vals.append({"left_out_state":s,"state_equal_adjusted_q5_q1":float(x),"estimable_state_n":len(z)-1})
    return pd.DataFrame(vals)

def _plot_save(fig,p):
    fig.savefig(p.with_suffix(".png"),dpi=300,bbox_inches="tight"); fig.savefig(p.with_suffix(".pdf"),bbox_inches="tight"); fig.savefig(p.with_suffix(".svg"),bbox_inches="tight"); plt.close(fig)

COLORS={"ROBUST_POSITIVE":"#1b7837","DIRECTIONAL_POSITIVE":"#78c679","DIRECTIONAL_NEGATIVE":"#6baed6","ROBUST_NEGATIVE":"#2166ac","NOT_ESTIMABLE":"#969696"}

def figures(out,summary,qrows,drows):
    fd=out/"figures"; fd.mkdir(parents=True,exist_ok=True); order=summary.sort_values("adjusted_q5_q1",ascending=False).target_admin1.tolist(); s=summary.set_index("target_admin1").loc[order]
    # 1 forest
    fig,ax=plt.subplots(figsize=(9,7)); y=np.arange(len(s));
    for i,(name,r) in enumerate(s.iterrows()):
        if np.isfinite(r.adjusted_q5_q1_ci_low): ax.plot([r.adjusted_q5_q1_ci_low*100,r.adjusted_q5_q1_ci_high*100],[i,i],color=COLORS[r.sensitivity_class],lw=2)
        ax.scatter(r.adjusted_q5_q1*100,i,color=COLORS[r.sensitivity_class],s=35,zorder=3)
        ax.text(max(ax.get_xlim()[1],0)+.02,i,f"N={int(r.valid_ip_n_main):,} /24={int(r.valid_prefix24_n):,}",va="center",fontsize=7)
    from matplotlib.patches import Patch
    ax.axvline(0,color="black",lw=.9); ax.set_yticks(y,order); ax.invert_yaxis(); ax.set_xlabel("Activity-adjusted Q5 − Q1 mean reachability drop (percentage points)"); ax.set_title("2024-08-26: State-level Sensitivity effect"); ax.grid(axis="x",alpha=.2); ax.set_xlim(min(-1,s.adjusted_q5_q1_ci_low.min()*100 if s.adjusted_q5_q1_ci_low.notna().any() else -1),max(1,s.adjusted_q5_q1_ci_high.max()*100 if s.adjusted_q5_q1_ci_high.notna().any() else 1)+8); ax.legend(handles=[Patch(facecolor=c,label=k) for k,c in COLORS.items()],loc="lower right",frameon=False,fontsize=7); _plot_save(fig,fd/"FIG-AUG26-1_sensitivity_forest")
    # 2 adjusted heatmap
    q=qrows.pivot(index="target_admin1",columns="quintile",values="activity_adjusted_mean_reach_drop").reindex(order); h=q.sub(q.Q1,axis=0)*100; lim=max(abs(np.nanmin(h.to_numpy())),abs(np.nanmax(h.to_numpy())),1); fig,ax=plt.subplots(figsize=(6.8,7)); im=ax.imshow(h,aspect="auto",cmap="RdBu_r",vmin=-lim,vmax=lim); ax.set_xticks(range(5),QUINTILES); ax.set_yticks(range(len(order)),order); ax.set_xlabel("Frozen Sensitivity quintile"); ax.set_title("2024-08-26: Activity-adjusted within-state Sensitivity gradient"); fig.colorbar(im,ax=ax,label="Difference from Q1 (percentage points)");
    for i in range(len(h)):
        for j in range(5):
            if np.isfinite(h.iloc[i,j]): ax.text(j,i,f"{h.iloc[i,j]:.1f}",ha="center",va="center",fontsize=7)
    fig.tight_layout(); _plot_save(fig,fd/"FIG-AUG26-2_sensitivity_heatmap")
    # 3 small multiples
    qraw=qrows.pivot_table(index="target_admin1",columns="quintile",values="raw_mean_reach_drop").reindex(order); qadj=qrows.pivot_table(index="target_admin1",columns="quintile",values="activity_adjusted_mean_reach_drop").reindex(order); lo=min(qraw.min().min(),qadj.min().min()); hi=max(qraw.max().max(),qadj.max().max()); fig,axes=plt.subplots(int(np.ceil(len(order)/4)),4,figsize=(13,2.6*int(np.ceil(len(order)/4))),sharex=True,sharey=True); axes=np.asarray(axes).ravel()
    for i,name in enumerate(order):
        ax=axes[i]; ax.plot(range(5),qraw.loc[name].to_numpy(),"--o",color="0.45",ms=3,label="Raw" if i==0 else None); ax.plot(range(5),qadj.loc[name].to_numpy(),"-o",color="#2166ac",ms=3,label="Activity-adjusted" if i==0 else None); ax.set_title(f"{name}\nN={int(s.loc[name].valid_ip_n_main):,}",fontsize=8); ax.set_xticks(range(5),QUINTILES); ax.grid(axis="y",alpha=.2)
    for ax in axes[len(order):]: ax.axis("off")
    axes[0].set_ylabel("Mean reachability drop"); axes[0].legend(frameon=False,fontsize=8); fig.suptitle("2024-08-26: State-wise Sensitivity profiles",y=.995); fig.tight_layout(); _plot_save(fig,fd/"FIG-AUG26-3_state_quintile_small_multiples")
    # 4 activity forest
    fig,ax=plt.subplots(figsize=(9,7)); y=np.arange(len(s));
    for i,(name,r) in enumerate(s.iterrows()):
        ax.plot([r.activity_d10_d1_ci_low*100,r.activity_d10_d1_ci_high*100],[i,i],color="#238b45",lw=2); ax.scatter(r.activity_d10_d1*100,i,color="#238b45",s=35,zorder=3)
    ax.axvline(0,color="black",lw=.9); ax.set_yticks(y,order); ax.invert_yaxis(); ax.set_xlabel("D10 − D1 mean reachability drop (percentage points)"); ax.set_title("2024-08-26: State-level Activity effect"); ax.grid(axis="x",alpha=.2); fig.tight_layout(); _plot_save(fig,fd/"FIG-AUG26-4_activity_forest")
    # 5 activity heatmap
    d=drows.pivot(index="target_admin1",columns="activity_decile",values="mean_reach_drop").reindex(order); dh=d.sub(d.D1,axis=0)*100; lim=max(abs(np.nanmin(dh.to_numpy())),abs(np.nanmax(dh.to_numpy())),1); fig,ax=plt.subplots(figsize=(10,7)); im=ax.imshow(dh,aspect="auto",cmap="RdBu_r",vmin=-lim,vmax=lim); ax.set_xticks(range(10),DECILES); ax.set_yticks(range(len(order)),order); ax.set_xlabel("Frozen Activity decile"); ax.set_title("2024-08-26: Within-state Activity gradient"); fig.colorbar(im,ax=ax,label="Difference from D1 (percentage points)"); fig.tight_layout(); _plot_save(fig,fd/"FIG-AUG26-5_activity_heatmap")
    # 6/7/8 scatter
    def scat(path,ycol,ylabel,title):
        fig,ax=plt.subplots(figsize=(7,5)); x=s.state_shock_severity; yy=s[ycol]; ax.scatter(x,yy,color="#762a83",s=35); ax.axvline(0,color="0.25",lw=.8); ax.axhline(0,color="0.25",lw=.8); ok=x.notna()&yy.notna();
        if ok.sum()>=3: z=np.polyfit(x[ok],yy[ok],1); xx=np.linspace(x[ok].min(),x[ok].max(),100); ax.plot(xx,np.polyval(z,xx),color="#969696",lw=1,ls="--"); rho=_rank_corr(x[ok],yy[ok])
        else: rho=np.nan
        if ok.sum():
            extreme=abs((x[ok]-x[ok].mean())/x[ok].std(ddof=0)+(yy[ok]-yy[ok].mean())/yy[ok].std(ddof=0)).sort_values(ascending=False).head(min(5,ok.sum())).index
            for n in extreme: ax.annotate(n,(x[n],yy[n]),xytext=(4,4),textcoords="offset points",fontsize=7)
        ax.set(xlabel="State shock severity: mean reachability drop",ylabel=ylabel,title=title); ax.text(.02,.97,f"Spearman ρ={rho:.3f}",transform=ax.transAxes,va="top"); ax.grid(alpha=.2); fig.tight_layout(); _plot_save(fig,path)
    scat(fd/"FIG-AUG26-6_shock_vs_sensitivity","adjusted_q5_q1","Activity-adjusted Q5 − Q1 mean reachability drop","Exploratory state-level association: shock severity vs Sensitivity")
    scat(fd/"FIG-AUG26-7_shock_vs_activity","activity_d10_d1","D10 − D1 mean reachability drop","Exploratory state-level association: shock severity vs Activity")
    fig,ax=plt.subplots(figsize=(7,5)); ax.axvline(0,color="0.25",lw=.8); ax.axhline(0,color="0.25",lw=.8); ax.scatter(s.activity_d10_d1,s.adjusted_q5_q1,color="#762a83",s=35); 
    for n,r in s.iterrows(): ax.annotate(n,(r.activity_d10_d1,r.adjusted_q5_q1),xytext=(4,4),textcoords="offset points",fontsize=7)
    ax.set(xlabel="Activity effect: D10 − D1 mean reachability drop",ylabel="Activity-adjusted Sensitivity effect: Q5 − Q1",title="2024-08-26: State-level Activity–Sensitivity effects"); ax.grid(alpha=.2); fig.tight_layout(); _plot_save(fig,fd/"FIG-AUG26-8_activity_sensitivity_quadrants")

def map_figure(out,summary,geojson):
    try:
        # Keep the map dependency-free: draw the frozen GeoJSON ADM1 polygons
        # directly with Matplotlib, so the optional spatial figure is reproducible
        # even when GeoPandas is not installed on the analysis server.
        import json
        from matplotlib.patches import Polygon
        from matplotlib.collections import PatchCollection
        geo=json.loads(Path(geojson).read_text(encoding="utf-8")); classes=dict(zip(summary.target_admin1,summary.sensitivity_class)); patches=[]; colors=[]
        for feat in geo.get("features",[]):
            name=feat.get("properties",{}).get("shapeName"); geom=feat.get("geometry",{}); typ=geom.get("type"); coords=geom.get("coordinates",[])
            polys=coords if typ=="MultiPolygon" else [coords]
            for poly in polys:
                if not poly: continue
                ring=poly[0]; patches.append(Polygon(ring,closed=True)); colors.append(COLORS.get(classes.get(name),"#eeeeee"))
        if not patches:return False
        fig,ax=plt.subplots(figsize=(8,7)); pc=PatchCollection(patches,facecolor=colors,edgecolor="white",linewidth=.4); ax.add_collection(pc); ax.autoscale(); ax.set_aspect("equal"); ax.set_axis_off(); ax.set_title("2024-08-26: Activity-adjusted Q5−Q1 classification"); ax.text(.015,.025,"ROBUST_POSITIVE=green   DIRECTIONAL_POSITIVE=light green   DIRECTIONAL_NEGATIVE=light blue   ROBUST_NEGATIVE=blue   NOT_ESTIMABLE=gray",transform=ax.transAxes,fontsize=7,ha="left",va="bottom",bbox=dict(facecolor="white",edgecolor="0.6",alpha=.9,pad=4)); _plot_save(fig,out/"figures/FIG-AUG26-9_sensitivity_classification_map"); return True
    except Exception:return False

def report(out,pop_a,pop_b,shock,summary,loso,assoc):
    counts=summary.sensitivity_class.value_counts().to_dict(); d10=int((summary.activity_d10_d1>0).sum()); actci=int((summary.activity_d10_d1_ci_low>0).sum()); spos=int((summary.adjusted_q5_q1>0).sum()); sci=int((summary.adjusted_q5_q1_ci_low>0).sum()); raw=float(summary.raw_q5_q1.mean()); adj=float(summary.adjusted_q5_q1.mean());
    if spos==0: verdict="SENSITIVITY_HAS_LITTLE_STATE_LEVEL_SIGNAL"
    elif sci/max(1,len(summary))>=.5: verdict="SENSITIVITY_IS_BROADLY_STATE_CONSISTENT"
    else: verdict="SENSITIVITY_IS_REGION_CONDITIONAL"
    activity_verdict="ACTIVITY_MORE_CONSISTENT_THAN_SENSITIVITY" if actci>d10*0+sci else "SENSITIVITY_COMPARABLE_TO_ACTIVITY"
    lines=["# AUG26_STATE_CASE_STUDY","","This analysis was designed after the six-event H1-H4 analysis and is therefore treated as an exploratory state-level case study. It does not replace the preregistered multi-event conclusions.","","## Scope and frozen inputs","- Event: **E2024_0826_ATTACK** only.",f"- Population A: **{pop_a.dst_ip.nunique():,} IPs**, frozen AUGMENTED_STRICT_SUPPORT3, {pop_a.target_admin1.nunique()} states.",f"- Population B: **{pop_b.dst_ip.nunique():,} valid IPs**, {pop_b.target_admin1.nunique()} states; positive-loss IPs: **{int((pop_b.reach_drop>0).sum()):,}**.","- Bootstrap unit: prefix24; iterations: 1,000; all signed reach_drop values retained.","","## State-level result","",f"- Raw state-equal Q5−Q1: **{raw:.5f}**.",f"- Activity-adjusted state-equal Q5−Q1: **{adj:.5f}**.",f"- Adjusted Q5>Q1: **{spos}/{len(summary)}** states; CI>0: **{sci}/{len(summary)}**.",f"- Activity D10>D1: **{d10}/{len(summary)}** states; CI>0: **{actci}/{len(summary)}**.",f"- Shock severity vs adjusted Sensitivity Spearman ρ: **{assoc['shock_sensitivity_rho']:.4f}**.",f"- Shock severity vs Activity Spearman ρ: **{assoc['shock_activity_rho']:.4f}**.",f"- LOSO adjusted effect range: **{loso.state_equal_adjusted_q5_q1.min():.5f} to {loso.state_equal_adjusted_q5_q1.max():.5f}**.","","## Fixed Sensitivity classification",json.dumps(counts,ensure_ascii=False),"","## Interpretation","",f"Exploratory case-study judgment: **{verdict}**.",f"Activity comparison: **{activity_verdict}**.","This event-level case study can show regional and event-conditional patterns, but cannot replace the six-event H3 conclusion, establish causality, or identify intrinsically vulnerable IPs.","","## Three key reasons","1. The analysis uses the same endpoint population for frozen Sensitivity and Activity, reducing population-composition ambiguity.","2. Activity-adjusted state effects are estimated with equal weighting over valid Activity deciles and prefix24 cluster bootstrap intervals.","3. State-level results are reported for every eligible state, including negative and non-estimable states; no state was selected by effect size.","","## Data and figure outputs","- All state tables and the manifest are in this stage directory.","- Every figure is exported as PNG (300 dpi), PDF, and SVG where applicable.","","The exploratory status is permanent; this output does not create H5 or modify H1-H4."]
    (out/"AUG26_STATE_CASE_STUDY_REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    return verdict,activity_verdict

def run(root:Path,h1_path:Path,label_path:Path,h2_path:Path,h1_manifest:Path,stage2_manifest:Path,stage45_manifest:Path,h2_manifest:Path,h3_manifest:Path,h4_manifest:Path,geojson:Path,server_base_commit:str,github_visible_commit:str,run_id="aug26_state_case_study_20260912"):
    out=root/"runs"/run_id/"results"/"stages"/"stage_aug26_state_case_study"; out.mkdir(parents=True,exist_ok=True)
    pop_a,pop_b=load_data(h1_path,label_path,h2_path); shock=shock_summary(pop_b); summary,qrows,drows=state_analysis(pop_a,shock); los=loso(summary)
    assoc={"shock_sensitivity_rho":_rank_corr(summary.state_shock_severity,summary.adjusted_q5_q1),"shock_activity_rho":_rank_corr(summary.state_shock_severity,summary.activity_d10_d1)}
    shock.to_csv(out/"aug26_state_shock_summary.csv",index=False); qrows.to_csv(out/"aug26_state_sensitivity_summary.csv",index=False); drows.to_csv(out/"aug26_state_activity_summary.csv",index=False); summary.to_csv(out/"aug26_state_sensitivity_activity_summary.csv",index=False); qrows[qrows.columns].to_csv(out/"aug26_state_quintile_adjusted.csv",index=False); drows.to_csv(out/"aug26_state_activity_deciles.csv",index=False); los.to_csv(out/"aug26_leave_one_state_out.csv",index=False); pd.DataFrame([assoc]).to_csv(out/"aug26_state_associations.csv",index=False)
    pop_a.to_parquet(out/"aug26_population_a_endpoint.parquet",index=False)
    figures(out,summary,qrows,drows); map_ok=map_figure(out,summary,geojson) if geojson.exists() else False
    verdict,activity_verdict=report(out,pop_a,pop_b,shock,summary,los,assoc)
    def meta(p):return {"path":str(p),"sha256":sha256(p)} if p.exists() else {"path":str(p),"sha256":None}
    manifest={"stage":"AUG26_STATE_CASE_STUDY","run_id":run_id,"analysis_type":"exploratory_explanatory_case_study","event_id":EVENT,"server_base_commit":server_base_commit,"final_git_commit":server_base_commit,"github_visible_commit":github_visible_commit,"remote_status":"server_newer_than_github_or_github_not_configured","population_a":{"definition":"AUGMENTED_STRICT_SUPPORT3; support_episode_n_augmented >= 3; strict estimable; valid E2024_0826 outcome","ip_n":int(pop_a.dst_ip.nunique()),"state_n":int(pop_a.target_admin1.nunique())},"population_b":{"definition":"all valid E2024_0826 H1 outcomes with frozen Activity","ip_n":int(pop_b.dst_ip.nunique()),"state_n":int(pop_b.target_admin1.nunique())},"bootstrap":{"unit":"prefix24","iterations":BOOTSTRAP_N,"random_seed":SEED},"verdict":verdict,"activity_comparison":activity_verdict,"map_generated":map_ok,"inputs":{"h1_artifact":meta(h1_path),"stage45_labels":meta(label_path),"h2_artifact":meta(h2_path),"h1_manifest":meta(h1_manifest),"stage2_manifest":meta(stage2_manifest),"stage45_manifest":meta(stage45_manifest),"h2_manifest":meta(h2_manifest),"h3_manifest":meta(h3_manifest),"h4_manifest":meta(h4_manifest),"geojson":meta(geojson)}}
    (out/"aug26_case_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return {"output_dir":str(out),"verdict":verdict,"activity_comparison":activity_verdict,"full_valid_ip_n":int(pop_b.dst_ip.nunique()),"full_state_n":int(pop_b.target_admin1.nunique()),"main_ip_n":int(pop_a.dst_ip.nunique()),"main_state_n":int(pop_a.target_admin1.nunique()),"summary":summary.to_dict("records"),"associations":assoc,"loso_range":[float(los.state_equal_adjusted_q5_q1.min()),float(los.state_equal_adjusted_q5_q1.max())]}

def main(argv=None):
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="/home/wsl/XiaoLunWen_doc_complete_20260908"); ap.add_argument("--run-id",default="aug26_state_case_study_20260912"); ap.add_argument("--server-base-commit",default="aab8eaef8e982279ead3d70f1d2a708c0eb3de2c"); ap.add_argument("--github-visible-commit",default="bd66e0c66e78d9aed6c3068aeadd8ac6ce34e9ac")
    defaults={"h1_path":"runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/h1_ip_level_outcomes.parquet","label_path":"runs/stage4_5_label_robustness_20260910/results/tables/b1_full_sensitivity_labels.parquet","h2_path":"runs/h2_sensitivity_external_validity_20260910/results/stages/stage_h2_sensitivity_external_validity/h2_ip_level_main.parquet","h1_manifest":"runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/h1_manifest.json","stage2_manifest":"runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity/stage_manifest.json","stage45_manifest":"runs/stage4_5_label_robustness_20260910/results/stages/stage04_5_label_robustness/stage4_5_manifest.json","h2_manifest":"runs/h2_sensitivity_external_validity_20260910/results/stages/stage_h2_sensitivity_external_validity/h2_manifest.json","h3_manifest":"runs/h3_activity_conditional_sensitivity_20260911/results/stages/stage_h3_activity_conditional_sensitivity/h3_manifest.json","h4_manifest":"runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/h4_manifest.json","geojson":"data_external/geography/geoBoundaries-UKR-ADM1.geojson"}
    for n,d in defaults.items():ap.add_argument("--"+n.replace("_","-"),default=d)
    a=ap.parse_args(); root=Path(a.root); res=lambda x:Path(x) if Path(x).is_absolute() else root/Path(x); kwargs={n:res(getattr(a,n)) for n in defaults}; print(json.dumps(run(root,**kwargs,server_base_commit=a.server_base_commit,github_visible_commit=a.github_visible_commit,run_id=a.run_id),indent=2,default=str))
if __name__=="__main__":main()
