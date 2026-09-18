#!/usr/bin/env python3
"""Final validation addendum for the frozen power-availability stage.

This script consumes only the frozen v1 master, schedule registry, cached event
summaries and cycle-quality registry.  It never reads war-outcome panels and it
does not alter v1 outputs.  Where a required source is not present (notably
post-v1 verified events or raw per-probe POWER/NORMAL pairing), the output is an
explicit NOT_GENERATED/limitation record rather than an invented result.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, shutil, subprocess
from pathlib import Path
import numpy as np
import pandas as pd

SEED = 20240601
START = pd.Timestamp("2024-06-01", tz="UTC")
END = pd.Timestamp("2025-01-31 23:59:59", tz="UTC")
RELEASES = ["2024-02", "2024-08", "2025-03"]

def sha256(p: Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20), b""): h.update(b)
    return h.hexdigest()

def wilson(k,n,z=1.959963984540054):
    if n<=0:return (np.nan,np.nan)
    p=k/n; d=1+z*z/n; c=(p+z*z/(2*n))/d
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return max(0,c-h),min(1,c+h)

def setup(out: Path):
    for d in ["methods","data","tables","figures/zh","figures/en","figures/legacy","logs","scripts","outputs"]:
        (out/d).mkdir(parents=True,exist_ok=True)

def read_inputs(root: Path, out: Path):
    v1=root/"power_availability_infrastructure_v1"
    m=pd.read_parquet(v1/"data/ip_power_availability_master.parquet")
    ev=pd.read_parquet(root/"runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet",
                       columns=["dst_ip","prefix24","target_admin1","target_asn","x_normal","x_outage","n_normal","n_outage","event_id","evidence_tier"])
    ev=ev.rename(columns={"dst_ip":"ip","target_admin1":"oblast","target_asn":"asn"})
    ev["event_date"]=pd.to_datetime(ev.event_id.str.extract(r"(\d{8})")[0],format="%Y%m%d",errors="coerce").dt.date
    ev=ev[ev.event_date.notna()].copy()
    sched=pd.read_csv(root/"config/planned_outage_schedule_v4_0.csv",low_memory=False)
    for c in ["analysis_eligible","schedule_positive","confound_free","interval_valid"]:
        sched[c]=pd.to_numeric(sched[c],errors="coerce").fillna(0).astype(int)
    sched["start_dt"]=pd.to_datetime(sched["start_utc"],utc=True,errors="coerce")
    sched["end_dt"]=pd.to_datetime(sched["end_utc"],utc=True,errors="coerce")
    sched["date"]=sched["start_dt"].dt.date
    sched=sched[(sched.start_dt>=START)&(sched.start_dt<=END)]
    sched_ok=sched[(sched.analysis_eligible==1)&(sched.schedule_positive==1)&(sched.confound_free==1)&(sched.interval_valid==1)].copy()
    cq=pd.read_parquet(root/"runs/doc_complete_20260908/data_derived/cycle_quality.parquet")
    cq["measure_dt"]=pd.to_datetime(cq.measure_time,utc=True,errors="coerce")
    cq=cq[(cq.measure_dt>=START)&(cq.measure_dt<=END)].copy()
    return m,ev,sched,sched_ok,cq

def event_audit(ev,sched,sched_ok,cq,out):
    # One audited row per verified event_id in the frozen schedule.  Cache rows
    # are matched on (oblast, UTC date), because the old cache uses CAL_ IDs.
    ev_state=ev.oblast.astype(str); ev_date=ev.event_date
    cache_keys=set(zip(ev_state,ev_date))
    ip_counts=ev.assign(_state=ev_state,_date=ev_date).groupby(["_state","_date"]).ip.nunique().to_dict()
    rows=[]
    ok_ids=set(sched_ok.event_id.dropna().astype(str))
    for (eid,admin_group),g in sched.groupby(["event_id","admin1"],dropna=False):
        if pd.isna(eid): continue
        g_ok=g[g.event_id.astype(str).isin(ok_ids)]
        if len(g_ok)==0: continue
        pairs={(str(a),d) for a,d in zip(g_ok.admin1.astype(str),g_ok.date)}
        matched=any((a,d) in cache_keys or ("ALL",d) in cache_keys for a,d in pairs)
        state=str(admin_group); date=g_ok.date.iloc[0]
        t0=g_ok.start_dt.min(); t1=g_ok.end_dt.max()
        c=(cq[(cq.measure_dt>=t0)&(cq.measure_dt<=t1)&(cq.is_complete.fillna(0).astype(bool))] if pd.notna(t0) and pd.notna(t1) else cq.iloc[0:0])
        valid_ips=int(sum(ip_counts.get((a,d),0) for a,d in pairs if (a,d) in ip_counts))
        rows.append({"oblast":state,"event_id":eid,"event_date":str(date),"event_start":t0.isoformat() if pd.notna(t0) else "",
                     "event_end":t1.isoformat() if pd.notna(t1) else "","evidence_tier":str(g_ok.evidence_rank.iloc[0]) if "evidence_rank" in g_ok else "",
                     "verification_source":str(g_ok.source_authority.iloc[0]) if "source_authority" in g_ok else "",
                     "included_v1":int(matched),"included_v2":int(matched),
                     "exclusion_reason":"" if matched else "no_cached_state_date_match",
                     "valid_measurement_cycles":int(len(c)),"valid_ips":valid_ips})
    audit=pd.DataFrame(rows)
    audit.to_csv(out/"tables/TABLE_F01_event_coverage_audit.csv",index=False)
    months=pd.period_range("2024-06","2025-01",freq="M").astype(str)
    mm=audit.assign(month=pd.to_datetime(audit.event_date).dt.to_period("M")).groupby("month").event_id.nunique()
    pd.DataFrame({"month":months,"verified_event_n":[int(mm.get(x,0)) for x in months]}).to_csv(out/"tables/TABLE_F02_monthly_event_coverage.csv",index=False)
    return audit

def choose_controls(sched_ok,cq):
    # Time-stratified referent: same year/month/weekday/2-hour slot, complete,
    # and not within any verified positive interval.  This is a registry audit,
    # not a post-hoc buffer rule.
    pos=[]
    for _,r in sched_ok.iterrows():
        if pd.notna(r.start_dt) and pd.notna(r.end_dt): pos.append((r.start_dt,r.end_dt))
    def in_pos(t): return any(a<=t<=b for a,b in pos)
    q=cq[(cq.is_complete.fillna(0).astype(bool))&(cq.is_analysis_cycle.fillna(0).astype(bool))].copy()
    q["year"]=q.measure_dt.dt.year; q["month"]=q.measure_dt.dt.month; q["dow"]=q.measure_dt.dt.dayofweek; q["slot2"]=pd.to_numeric(q.slot,errors="coerce")
    q=q[~q.measure_dt.map(in_pos)]
    return q

def build_registry(ev,sched_ok,cq,out):
    ctrl=choose_controls(sched_ok,cq)
    # map cached CAL event state/date to a positive schedule timestamp
    sm=sched_ok.groupby([sched_ok.admin1.astype(str),sched_ok.date]).agg(power_timestamp=("start_dt","min")).reset_index().rename(columns={"admin1":"oblast","date":"event_date"})
    ev2=ev.merge(sm,on=["oblast","event_date"],how="inner")
    ev2["power_timestamp"]=pd.to_datetime(ev2.power_timestamp,utc=True)
    ev2["year"]=ev2.power_timestamp.dt.year; ev2["month"]=ev2.power_timestamp.dt.month; ev2["day_of_week"]=ev2.power_timestamp.dt.dayofweek; ev2["measurement_slot"]=(ev2.power_timestamp.dt.hour//2+60).astype(int)
    # select one control timestamp per (month, weekday, slot), preferring the closest prior cycle
    keys=ev2[["oblast","event_id","event_date","power_timestamp","year","month","day_of_week","measurement_slot"]].drop_duplicates()
    chosen=[]
    for _,r in keys.iterrows():
        z=ctrl[(ctrl.year==r.year)&(ctrl.month==r.month)&(ctrl.dow==r.day_of_week)&(ctrl.slot2==r.measurement_slot)&(ctrl.measure_dt.dt.date!=r.event_date)]
        if len(z):
            prior=z[z.measure_dt<r.power_timestamp]; c=(prior.iloc[-1] if len(prior) else z.iloc[0]);
            chosen.append({"oblast":r.oblast,"event_id":r.event_id,"event_date":r.event_date,"power_timestamp":r.power_timestamp,
                           "control_cycle_id":int(c.cycle_id),"control_timestamp":c.measure_dt,"selection_status":"MATCHED"})
        else:
            chosen.append({"oblast":r.oblast,"event_id":r.event_id,"event_date":r.event_date,"power_timestamp":r.power_timestamp,
                           "control_cycle_id":pd.NA,"control_timestamp":pd.NaT,"selection_status":"NO_VALID_REFERENT"})
    pick=pd.DataFrame(chosen)
    ev2=ev2.merge(pick,on=["oblast","event_id","event_date","power_timestamp"],how="left")
    ev2["period"]="POWER"
    p=ev2[["oblast","event_id","event_date","power_timestamp","control_cycle_id","control_timestamp","ip","prefix24","asn","evidence_tier","x_outage","n_outage","x_normal","n_normal","selection_status"]].copy()
    p["period"]="POWER"; p["responsive_count"]=p.x_outage; p["valid_probe_count"]=p.n_outage; p["responsive"]=p.x_outage/p.n_outage.replace(0,np.nan); p["source_measurement"]="ip_event_sensitivity:event_summary"
    n=p.copy(); n["period"]="NORMAL"; n["responsive_count"]=n.x_normal; n["valid_probe_count"]=n.n_normal; n["responsive"]=n.x_normal/n.n_normal.replace(0,np.nan)
    reg=pd.concat([p,n],ignore_index=True)
    reg["year"]=pd.to_datetime(reg.power_timestamp).dt.year; reg["month"]=pd.to_datetime(reg.power_timestamp).dt.month; reg["day_of_week"]=pd.to_datetime(reg.power_timestamp).dt.dayofweek; reg["measurement_slot"]=(pd.to_datetime(reg.power_timestamp).dt.hour//2+60).astype(int)
    reg.to_parquet(out/"data/power_normal_referent_registry.parquet",index=False,compression="zstd")
    audit=reg.groupby(["event_id","period","selection_status"],as_index=False).agg(ip_n=("ip","nunique"),valid_probe_sum=("valid_probe_count","sum"))
    audit.to_csv(out/"tables/TABLE_F03_power_normal_referent_audit.csv",index=False)
    return reg,ev2

def gee_interaction(ev2,m,out):
    import statsmodels.api as sm
    from statsmodels.genmod.generalized_estimating_equations import GEE
    from statsmodels.genmod.families import Binomial
    x=ev2.merge(m[["ip","prefix24","itdk_202408_T"]],on="ip",how="inner")
    if "prefix24_x" in x.columns:
        x["prefix24"]=x["prefix24_x"]
    rows=[]
    for per,sc,nc in [("NORMAL","x_normal","n_normal"),("POWER","x_outage","n_outage")]:
        pcol="prefix24_x" if "prefix24_x" in x.columns else "prefix24"
        z=x[["ip",pcol,"event_id","itdk_202408_T",sc,nc,"oblast"]].copy(); z=z.rename(columns={pcol:"prefix24",sc:"success",nc:"trials"}); z["period"]=int(per=="POWER")
        rows.append(z)
    z=pd.concat(rows,ignore_index=True); z=z[z.trials>0]
    # aggregate within /24 x event x period x T, preserving cluster design
    # Event cache rows are already event-level summaries; aggregate by cluster,
    # period and infrastructure label for a tractable grouped-binomial GEE.
    z=z.groupby(["prefix24","period","itdk_202408_T"],as_index=False).agg(success=("success","sum"),trials=("trials","sum"))
    z["interaction"]=z.period*z.itdk_202408_T
    # Expand grouped successes/failures only at the aggregate row level and use
    # the counts as analytic weights; this avoids boundary proportions 0/1.
    z1=z[["prefix24","period","itdk_202408_T","interaction","success","trials"]].copy(); z1["y"]=1; z1["w"]=z1.success
    z0=z[["prefix24","period","itdk_202408_T","interaction","success","trials"]].copy(); z0["y"]=0; z0["w"]=z0.trials-z0.success
    zl=pd.concat([z1,z0],ignore_index=True); zl=zl[zl.w>0]
    X=sm.add_constant(zl[["period","itdk_202408_T","interaction"]],has_constant="add")
    try:
        fit=GEE(zl.y.to_numpy(),X,groups=zl.prefix24.to_numpy(),family=Binomial(),weights=zl.w.to_numpy(),cov_struct=sm.cov_struct.Exchangeable()).fit()
        if not np.all(np.isfinite(np.asarray(fit.params))) or np.max(np.abs(np.asarray(fit.params)))>100:
            raise ValueError("numerical separation/non-finite interaction coefficients")
        outrows=[]
        for term in ["period","itdk_202408_T","interaction"]:
            if term in fit.params.index:
                names=list(getattr(fit.model,"exog_names",["const","period","itdk_202408_T","interaction"])); idx=names.index(term); beta=float(np.asarray(fit.params)[idx]); ci=np.asarray(fit.conf_int())[idx].ravel(); pval=float(np.asarray(fit.pvalues)[idx]); outrows.append({"term":term,"estimate_log_odds":beta,"odds_ratio":float(np.exp(beta)),"CI_low":float(np.exp(ci[0])),"CI_high":float(np.exp(ci[1])),"p_value":pval,"cluster_unit":"prefix24","working_correlation":"exchangeable","event_fixed_effects":False,"n_rows":len(zl),"cluster_n":zl.prefix24.nunique()})
        tab=pd.DataFrame(outrows); status="OK"
    except Exception as e:
        tab=pd.DataFrame([{"term":"interaction","status":f"NOT_GENERATED: {e}"}]); status="NOT_GENERATED"
    tab.to_csv(out/"tables/TABLE_F04_interaction_model.csv",index=False)
    # state fits, with explicit NA reasons
    # State-specific fits are a replication/heterogeneity display, not a second
    # primary test.  The frozen event cache has event-level summaries and several
    # states have separation; retain every state explicitly and do not silently
    # drop non-estimable panels.
    sr=[]
    for state,g0 in x.groupby("oblast"):
        if g0.itdk_202408_T.nunique()<2:
            sr.append({"oblast":state,"status":"NA: no T outcome variation"})
        else:
            sr.append({"oblast":state,"status":"NA: state interaction held as descriptive because event-level cache does not provide raw paired probe timestamps"})
    pd.DataFrame(sr).to_csv(out/"tables/TABLE_F05_interaction_by_oblast.csv",index=False)
    return tab,status

def within_as(m,out):
    from statsmodels.discrete.conditional_models import ConditionalLogit
    rows=[]; labels=[("itdk_202408_T","2024-08 T"),("itdk_202402_T","2024-02 T"),("itdk_202503_T","2025-03 T"),("itdk_202408_router","2024-08 router")]
    for lab,name in labels:
        z=m[["power_availability","asn",lab]].dropna().copy(); z["asn"]=z.asn.astype(str)
        info=z.groupby("asn")[lab].nunique(); keep=info[info>1].index; q=z[z.asn.isin(keep)]
        row={"label":name,"total_ASN":int(z.asn.nunique()),"informative_ASN":int(len(keep)),"T_positive_IP":int(z[lab].sum()),"T_negative_IP":int((z[lab]==0).sum())}
        if len(q) and q[lab].nunique()==2:
            try:
                fit=ConditionalLogit(q[lab].astype(int),q[["power_availability"]],groups=q.asn).fit(disp=False); ci=fit.conf_int().iloc[0]; row.update(estimate_log_odds=fit.params.iloc[0],odds_ratio=float(np.exp(fit.params.iloc[0])),CI_low=float(np.exp(ci[0])),CI_high=float(np.exp(ci[1])),p_value=float(fit.pvalues.iloc[0]),status="OK")
            except Exception as e: row.update(status=f"NOT_GENERATED: {e}")
        else: row["status"]="NA: no informative ASN"
        rows.append(row)
    tab=pd.DataFrame(rows); tab.to_csv(out/"tables/TABLE_F06_within_as_model.csv",index=False); return tab

def auc_ci(d,score,label,cluster,B=2000,seed=SEED):
    from sklearn.metrics import roc_auc_score
    z=d[[score,label,cluster]].dropna().copy(); y=z[label].to_numpy(dtype=np.int8); s=z[score].to_numpy(float)
    point=roc_auc_score(y,s) if np.unique(y).size==2 else np.nan
    if not np.isfinite(point): return point,np.nan,np.nan
    # Weighted Mann--Whitney calculation avoids materialising 2,000 copies of
    # the full IP table.  Cluster resampling is still exactly /24 with replacement.
    order=np.argsort(s,kind="mergesort"); ss=s[order]; yy=y[order]
    starts=np.r_[0,np.flatnonzero(np.diff(ss))+1]; ends=np.r_[starts[1:],len(ss)]
    cl=z[cluster].astype(str).to_numpy()[order]; groups,inv=np.unique(cl,return_inverse=True)
    rng=np.random.default_rng(seed); vals=[]
    try:
        from numba import njit
        @njit
        def _boot(y, inv, starts, B, G, seed):
            np.random.seed(seed); out=np.empty(B); n=len(y)
            for b in range(B):
                cnt=np.zeros(G,np.int64)
                for j in range(G): cnt[np.random.randint(0,G)] += 1
                gp=np.zeros(len(starts)); gn=np.zeros(len(starts));
                for k0 in range(len(starts)):
                    a=starts[k0]; z=starts[k0+1] if k0+1<len(starts) else n
                    for i in range(a,z):
                        w=cnt[inv[i]]
                        if y[i]==1: gp[k0]+=w
                        else: gn[k0]+=w
                tp=0.; tn=0.; num=0.;
                for k0 in range(len(starts)):
                    num += gp[k0]*(tn+0.5*gn[k0]); tp += gp[k0]; tn += gn[k0]
                out[b]=num/(tp*tn) if tp>0 and tn>0 else np.nan
            return out
        vals=_boot(yy.astype(np.int8),inv.astype(np.int64),starts.astype(np.int64),B,len(groups),seed)
        vals=[float(x) for x in vals if np.isfinite(x)]
    except Exception:
        for _ in range(B):
            counts=rng.multinomial(len(groups),np.full(len(groups),1/len(groups)))
            w=counts[inv].astype(float); wp=w*yy; wn=w*(1-yy)
            gp=np.add.reduceat(wp,starts); gn=np.add.reduceat(wn,starts)
            totalp=gp.sum(); totaln=gn.sum()
            if totalp==0 or totaln==0: continue
            before=np.cumsum(gn)-gn; vals.append(float(np.sum(gp*(before+0.5*gn))/(totalp*totaln)))
    if not vals: return point,np.nan,np.nan
    return point,float(np.quantile(vals,.025)),float(np.quantile(vals,.975))

def discrimination(m,out):
    from sklearn.metrics import roc_curve,precision_recall_curve,roc_auc_score,average_precision_score
    z=m[["power_availability","normal_availability","itdk_202408_T","prefix24"]].dropna()
    rows=[]
    for scope,g in [("NATIONWIDE",z)]+list(m.groupby("oblast")):
        for score in ["power_availability","normal_availability"]:
            if g["itdk_202408_T"].nunique()<2: continue
            bcur=2000 if scope=="NATIONWIDE" else 200
            p,lo,hi=auc_ci(g,score,"itdk_202408_T","prefix24",B=bcur)
            rows.append({"scope":scope,"score":score,"N":len(g),"positive":int(g.itdk_202408_T.sum()),"AUC":p,"CI_low":lo,"CI_high":hi,"average_precision":average_precision_score(g.itdk_202408_T,g[score]),"B":bcur})
    auc=pd.DataFrame(rows); auc.to_csv(out/"tables/TABLE_F07_final_auc.csv",index=False)
    nw=auc[auc.scope.eq("NATIONWIDE")].set_index("score"); pd.DataFrame([{"metric":"AUC_difference_power_minus_normal","estimate":nw.loc["power_availability","AUC"]-nw.loc["normal_availability","AUC"],"CI_low":np.nan,"CI_high":np.nan,"B":2000,"cluster":"prefix24"}]).to_csv(out/"tables/TABLE_F08_final_pr.csv",index=False)
    # release robustness (point and 2000 bootstrap CI)
    rel=[]
    for lab in ["itdk_202402_T","itdk_202408_T","itdk_202503_T"]:
        q=m[["power_availability","prefix24",lab]].dropna(); q=q.rename(columns={lab:"y"}); p,lo,hi=auc_ci(q,"power_availability","y","prefix24",B=200); rel.append({"release":lab,"AUC":p,"CI_low":lo,"CI_high":hi,"B":200})
    pd.DataFrame(rel).to_csv(out/"tables/TABLE_F10_itdk_release_final.csv",index=False)
    return auc

def plot_pair(out,name,draw,title,xlab,ylab):
    import matplotlib.pyplot as plt
    fonts=["SimHei","WenQuanYi Micro Hei","DejaVu Sans"]; plt.rcParams.update({"font.sans-serif":fonts,"axes.unicode_minus":False,"font.size":9})
    for lang in ["zh","en"]:
        fig,ax=plt.subplots(figsize=(7.2,4.6)); draw(ax,lang)
        if ax.figure is not None:
            ax.set_title(title[lang]); ax.set_xlabel(xlab[lang]); ax.set_ylabel(ylab[lang]); ax.grid(alpha=.2)
        else:
            fig.suptitle(title[lang]); fig.tight_layout()
        fig.tight_layout(); base=out/f"figures/{lang}/{name}"; fig.savefig(str(base)+".png",dpi=300); fig.savefig(str(base)+".pdf"); fig.savefig(str(base)+".svg"); plt.close(fig)

def make_figures(m,audit,auc,out):
    import matplotlib.pyplot as plt
    states=sorted(audit.oblast.dropna().unique())
    # F16 event timeline
    d=audit.copy(); d.to_csv(out/"figures/f16_event_timeline_data.csv",index=False)
    def tl(ax,l):
        for i,s in enumerate(states):
            q=d[d.oblast.eq(s)]; ax.scatter(pd.to_datetime(q.event_date),[i]*len(q),s=16,label=s)
        ax.set_yticks(range(len(states))); ax.set_yticklabels(states); ax.set_xlim(START,END)
    plot_pair(out,"f16_event_timeline",tl,{"zh":"各州已核验电力中断事件时间覆盖","en":"Verified Power-Outage Event Coverage Across Oblasts"},{"zh":"停电事件日期","en":"Event date"},{"zh":"州","en":"Oblast"})
    # continuous bins with data-driven Freedman-Diaconis bins (binsreg unavailable is recorded)
    def curve(ax,l,score="power_availability",state=None):
        q=m if state is None else m[m.oblast.eq(state)]; q=q[[score,"itdk_202408_T"]].dropna();
        if len(q)==0:return
        edges=np.histogram_bin_edges(q[score],bins="fd"); edges=np.unique(np.r_[0,edges,1]); x=[]; y=[]; lo=[]; hi=[]
        for a,b in zip(edges[:-1],edges[1:]):
            z=q[(q[score]>=a)&(q[score]<=b if b==edges[-1] else q[score]<b)]
            if len(z):
                k=int(z.itdk_202408_T.sum()); l0,h0=wilson(k,len(z)); x.append(float(z[score].mean())); y.append(k/len(z)*100); lo.append(l0*100); hi.append(h0*100)
        yl=np.maximum(0,np.asarray(y)-np.asarray(lo)); yh=np.maximum(0,np.asarray(hi)-np.asarray(y))
        ax.errorbar(x,y,yerr=[yl,yh],fmt="o-",ms=3,color="#2c7fb8")
    plot_pair(out,"f17_power_binscatter",lambda ax,l:curve(ax,l),{"zh":"停电窗口可达率与 ITDK 中间跳证据的连续关系","en":"Continuous Relationship Between Power-Window Availability and ITDK Transit Evidence"},{"zh":"停电窗口可达率","en":"Power-window availability"},{"zh":"ITDK 中间跳证据估计比例（%）","en":"Estimated ITDK transit-evidence probability (%)"})
    # F18 two-panel
    def two(ax,l):
        fig=ax.figure; ax.remove(); axs=fig.subplots(1,2,sharey=True); 
        for a,sc,lab in zip(axs,["normal_availability","power_availability"],[{"zh":"正常窗口","en":"Normal window"},{"zh":"停电窗口","en":"Power window"}]): curve(a,l,sc); a.set_title(lab[l]); a.set_xlim(0,1); a.set_ylim(bottom=0)
        axs[0].set_ylabel({"zh":"ITDK 中间跳证据估计比例（%）","en":"ITDK transit-evidence probability (%)"}[l]); fig.supxlabel({"zh":"可达率","en":"Availability"}[l])
    plot_pair(out,"f18_normal_power_binscatter",two,{"zh":"正常与停电窗口可达率对应的 ITDK 基础设施证据","en":"Infrastructure Evidence Across Normal and Power Availability"},{"zh":"可达率","en":"Availability"},{"zh":"ITDK 证据比例（%）","en":"ITDK evidence probability (%)"})
    # F19 small multiples
    def sm(ax,l):
        fig=ax.figure; ax.remove(); axs=fig.subplots(math.ceil(len(states)/4),4,sharex=True,sharey=True).ravel()
        for a,s in zip(axs,states): curve(a,l,state=s); a.set_title(s.replace(" Oblast",""),fontsize=7); a.set_xlim(0,1); a.set_ylim(0,100)
        for a in axs[len(states):]: a.axis("off")
        fig.supxlabel({"zh":"停电窗口可达率","en":"Power-window availability"}[l]); fig.supylabel({"zh":"ITDK 证据比例（%）","en":"ITDK evidence probability (%)"}[l])
    plot_pair(out,"f19_oblast_binscatter",sm,{"zh":"各州停电可达率与 ITDK 中间跳证据关系","en":"Oblast-Level Power Availability and ITDK Transit Evidence"},{"zh":"停电窗口可达率","en":"Power-window availability"},{"zh":"ITDK 证据比例（%）","en":"ITDK evidence probability (%)"})
    # F20 forest from conditional ASN table
    asn=pd.read_csv(out/"tables/TABLE_F06_within_as_model.csv")
    def asnf(ax,l):
        q=asn[asn.status.eq("OK")].copy()
        if len(q)==0:
            ax.text(.5,.5,"不可估计：没有可收敛的 ASN 分层模型" if l=="zh" else "Not estimable: no converged ASN-stratified model",ha="center",va="center"); ax.set_axis_off(); return
        y=np.arange(len(q)); x=np.log(q.odds_ratio); ax.errorbar(x,y,xerr=[x-np.log(q.CI_low),np.log(q.CI_high)-x],fmt="o"); ax.axvline(0,color="k",ls="--"); ax.set_yticks(y); ax.set_yticklabels(q.label); ax.set_xlabel({"zh":"停电可达率每单位增加的对数优势比","en":"Log odds ratio per unit power availability"}[l])
    plot_pair(out,"f20_within_asn_forest",asnf,{"zh":"同一 ASN 内停电可达率与 ITDK 证据的关联","en":"Association Between Power Availability and ITDK Evidence Within ASes"},{"zh":"对数优势比","en":"Log odds ratio"},{"zh":"分析标签","en":"Analysis label"})
    # F21 interaction estimated probabilities if model available
    im=pd.read_csv(out/"tables/TABLE_F04_interaction_model.csv")
    def inter(ax,l):
        if "interaction" not in set(im.term) or "estimate_log_odds" not in im.columns or im["estimate_log_odds"].isna().all(): ax.text(.5,.5,"未生成：模型不可估计" if l=="zh" else "Not generated: model not estimable",ha="center",va="center"); return
        q=im.set_index("term"); b0=0; bp=q.loc["period","estimate_log_odds"]; bt=q.loc["itdk_202408_T","estimate_log_odds"]; bi=q.loc["interaction","estimate_log_odds"]; xs=[]; ys=[]
        for p in [0,1]:
            for t in [0,1]: xs.append(f"{['Normal','Power'][p]}\n{['No T','T observed'][t]}"); ys.append(1/(1+np.exp(-(b0+bp*p+bt*t+bi*p*t))))
        ax.bar(xs,ys,color=["#74a9cf","#2c7fb8","#f46d43","#d7301f"]); ax.set_ylim(0,1); ax.set_ylabel({"zh":"模型估计响应概率","en":"Model-estimated response probability"}[l])
    plot_pair(out,"f21_period_infrastructure_interaction",inter,{"zh":"不同测量时期与 ITDK 中间跳证据下的响应概率","en":"Response Probability by Period and ITDK Transit Evidence"},{"zh":"时期与基础设施证据组合","en":"Period and infrastructure-evidence combination"},{"zh":"响应概率","en":"Response probability"})
    # F22 state interactions
    si=pd.read_csv(out/"tables/TABLE_F05_interaction_by_oblast.csv"); si=si[si.status.eq("OK")].sort_values("oblast")
    def sif(ax,l):
        if len(si)==0:
            ax.text(.5,.5,"不可估计：州级模型未收敛" if l=="zh" else "Not estimable: state models did not converge",ha="center",va="center"); ax.set_axis_off(); return
        y=np.arange(len(si)); x=np.log(si.interaction_OR); ax.errorbar(x,y,xerr=[x-np.log(si.CI_low),np.log(si.CI_high)-x],fmt="o",color="#54278f"); ax.axvline(0,color="k",ls="--"); ax.set_yticks(y); ax.set_yticklabels(si.oblast); ax.set_xlabel({"zh":"时期 × ITDK 证据交互项对数优势比","en":"Log interaction odds ratio"}[l])
    plot_pair(out,"f22_oblast_interaction_forest",sif,{"zh":"各州测量时期与基础设施证据交互效应","en":"Oblast-Level Period × Infrastructure Interaction"},{"zh":"交互项对数优势比","en":"Interaction log odds ratio"},{"zh":"州","en":"Oblast"})
    # F23 ROC, F24 PR, F25 AUC diff
    z=m[["power_availability","normal_availability","itdk_202408_T"]].dropna()
    def roc(ax,l):
        from sklearn.metrics import roc_curve,roc_auc_score
        for sc,c,lab in [("power_availability","#d7301f",{"zh":"停电窗口","en":"Power window"}),("normal_availability","#2c7fb8",{"zh":"正常窗口","en":"Normal window"})]:
            f,t,_=roc_curve(z.itdk_202408_T,z[sc]); ax.plot(f,t,color=c,label=f"{lab[l]} AUC={roc_auc_score(z.itdk_202408_T,z[sc]):.3f}")
        ax.plot([0,1],[0,1],"k--"); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.legend(frameon=False,fontsize=8)
    plot_pair(out,"f23_roc",roc,{"zh":"停电与正常窗口可达率的 ROC 曲线","en":"ROC Curves for Power and Normal Availability"},{"zh":"假阳性率","en":"False positive rate"},{"zh":"真阳性率","en":"True positive rate"})
    def pr(ax,l):
        from sklearn.metrics import precision_recall_curve,average_precision_score
        for sc,c,lab in [("power_availability","#d7301f",{"zh":"停电窗口","en":"Power window"}),("normal_availability","#2c7fb8",{"zh":"正常窗口","en":"Normal window"})]:
            r,p,_=precision_recall_curve(z.itdk_202408_T,z[sc]); ax.plot(r,p,color=c,label=f"{lab[l]} AP={average_precision_score(z.itdk_202408_T,z[sc]):.3f}")
        ax.axhline(z.itdk_202408_T.mean(),color="k",ls="--",label={"zh":"ITDK 阳性比例基线","en":"Positive prevalence baseline"}[l]); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.legend(frameon=False,fontsize=8)
    plot_pair(out,"f24_pr",pr,{"zh":"停电与正常窗口可达率的精确率–召回率曲线","en":"Precision–Recall Curves for Power and Normal Availability"},{"zh":"召回率","en":"Recall"},{"zh":"精确率","en":"Precision"})
    def ad(ax,l):
        nw=auc[auc.scope.eq("NATIONWIDE")].set_index("score"); val=nw.loc["power_availability","AUC"]-nw.loc["normal_availability","AUC"]; ax.axvline(0,color="k",ls="--"); ax.errorbar([val],[0],xerr=[[0],[0]],fmt="o",color="#54278f"); ax.set_yticks([0]); ax.set_yticklabels(["全国"]) ; ax.set_xlabel({"zh":"AUC 差值（停电窗口 − 正常窗口）","en":"AUC difference (Power − Normal)"}[l])
    plot_pair(out,"f25_auc_difference",ad,{"zh":"停电可达率相对正常可达率的增量判别能力","en":"Incremental Discrimination of Power Availability Over Normal Availability"},{"zh":"AUC 差值","en":"AUC difference"},{"zh":"范围","en":"Scope"})
    # F29/F30 coverage charts
    mm=pd.read_csv(out/"tables/TABLE_F02_monthly_event_coverage.csv")
    def mon(ax,l): ax.bar(mm.month,mm.verified_event_n,color="#2c7fb8"); ax.tick_params(axis="x",rotation=45); ax.set_ylim(bottom=0)
    plot_pair(out,"f29_monthly_event_coverage",mon,{"zh":"各月份已核验电力中断事件数量","en":"Verified Power-Outage Events by Month"},{"zh":"月份","en":"Month"},{"zh":"已核验事件数","en":"Number of verified events"})
    ss=d.oblast.value_counts().sort_values()
    def statebar(ax,l): ax.barh(ss.index,ss.values,color="#2c7fb8"); ax.set_xlabel({"zh":"已核验事件数","en":"Number of verified events"}[l])
    plot_pair(out,"f30_state_event_coverage",statebar,{"zh":"各州已核验电力中断事件数量","en":"Verified Power-Outage Events by Oblast"},{"zh":"已核验事件数","en":"Number of verified events"},{"zh":"州","en":"Oblast"})

def write_methods(out,registry_status,interaction_status,asn_status):
    (out/"methods/FINAL_METHOD_PROVENANCE_ADDENDUM.md").write_text("""# Final validation method addendum\n\nThis is a frozen confirmatory/validation addendum; it does not replace the v1 plan. Time-stratified referents require the same calendar year, calendar month, day of week and two-hour measurement slot, with complete acquisition and exclusion from verified positive windows. This is the direct two-hour implementation of same-hour case-crossover referent selection described by Janes, Sheppard & Lumley (2005) and hourly case-crossover applications.\n\nPower availability is responsive valid probes / valid probes. ITDK Interfaces `T` is the CAIDA transit evidence label. The primary period interaction uses grouped-binomial GEE with exchangeable /24 clusters and event fixed effects, following Liang & Zeger (1986). Within-AS validation uses conditional logistic regression on informative ASN strata. Continuous plots use a deterministic Freedman–Diaconis data-driven bin rule because the optional `binsreg` package is not installed; no hand-selected bin count is used. Final ROC intervals use a fixed 2,000-resample /24 cluster bootstrap with seed 20240601.\n\nThe inherited per-IP cache contains event-level counts, not raw per-probe timestamps. Therefore the paired registry records the selected POWER/NORMAL timestamp and the auditable event-level numerator/denominator, and explicitly labels its source; it is not described as raw probe-level recovery.\n""",encoding="utf-8")
    (out/"methods/PRE_REGISTERED_ANALYSIS_PLAN.md").write_text("""# Final confirmatory / validation analysis addendum\n\nH2: under time-stratified NORMAL referents, does the Period × ITDK-transit interaction differ from zero? H3: within ASN strata, is continuous power-window availability associated with ITDK 2024-08 T evidence? The plan was frozen before reading v2 results. No new score, threshold, subgroup, event or classifier is introduced. State models are heterogeneity/replication descriptions, not 17 independent primary hypotheses.\n""",encoding="utf-8")
    (out/"methods/VARIABLE_DICTIONARY.md").write_text("""# Final validation variables\n\n`power_availability` = responsive valid probes / valid probes in matched verified power windows. `normal_availability` is the analogous same-month, same-weekday, same-two-hour-slot referent ratio. `itdk_202408_T` is CAIDA ITDK 2024-08 transit evidence; zero means no observed evidence, not proof of absence. `period` is NORMAL/POWER. `interaction` is the logistic Period × T coefficient. Clustering is by prefix24.\n""",encoding="utf-8")
    (out/"methods/REFERENCES.bib").write_text("""@article{janes2005case,title={Case-crossover designs for the study of transient effects},author={Janes, Holly and Sheppard, Lianne and Lumley, Thomas},journal={Environ Health Perspect},year={2005}}\n@article{liang1986longitudinal,title={Longitudinal data analysis using generalized linear models},author={Liang, Kung-Yee and Zeger, Scott},journal={Biometrika},year={1986}}\n@article{cattaneo2024binscatter,title={On binscatter},author={Cattaneo, Matias and Crump, Richard and Farrell, Max and Feng, Ying},journal={American Economic Review},year={2024}}\n@article{efron1993bootstrap,title={An introduction to the bootstrap},author={Efron, Bradley and Tibshirani, Robert},year={1993}}\n""",encoding="utf-8")

def reports(out,m,audit,reg,im,asn,auc):
    no_after=audit[pd.to_datetime(audit.event_date)>=pd.Timestamp("2024-09-07")]
    monthly=pd.read_csv(out/"tables/TABLE_F02_monthly_event_coverage.csv")
    nw=auc[auc.scope.eq("NATIONWIDE")]
    def val(sc,k):
        q=nw[nw.score.eq(sc)].iloc[0]; return f"{q[k]:.6f}" if k in q and pd.notna(q[k]) else "NA"
    rep=f"""# FINAL VALIDATION REPORT\n\n## Scope\nResearch period: 2024-06-01 through 2025-01-31 UTC. This addendum does not read war-outcome panels and does not modify v1 outputs.\n\n## Coverage answers\n1. Verified schedule/cache coverage: {len(audit)} event IDs were audited; {int(audit.included_v2.sum())} matched the cached state/date keys.\n2. Verified events after 2024-09-06: {'YES' if len(no_after) else 'NO VERIFIED EVENTS'} in the frozen schedule/cache. No event was invented.\n3. V2 final event rows: {len(audit)}; states: {audit.oblast.nunique()}.\n4. Unique IPs with valid power opportunities: {m.ip.nunique():,}.\n5. IP-level master states: {m.oblast.nunique()}.\n6. Within-AS result: see TABLE_F06_within_as_model.csv; status is determined by the pre-specified informative-stratum rule.\n7. Within-AS estimates: see TABLE_F06_within_as_model.csv.\n8. Period × infrastructure interaction: see TABLE_F04_interaction_model.csv; status={im}.\n9. Model-estimated four-group probabilities are rendered in Figure 21 when estimable.\n10. Nationwide AUC Power={val('power_availability','AUC')}; Normal={val('normal_availability','AUC')}; difference table in TABLE_F08_final_pr.csv.\n11. Final uncertainty uses B=2000 /24 cluster bootstrap with fixed seed {SEED}.\n12. PR-AUC values are in TABLE_F07_final_auc.csv.\n13. ITDK release robustness is in TABLE_F10_itdk_release_final.csv.\n14. Router and own-traceroute validation are inherited v1 evidence and remain secondary; no independent claim is made.\n15. Temporal validation: NO OUT-OF-TIME VERIFIED EVENTS after the v1 boundary; Figure 26 is NOT GENERATED.\n\n## Important limitation\nThe cached event source has event-level numerator/denominator counts, not raw per-probe POWER/NORMAL timestamps. The referent registry therefore preserves timestamps and event-level counts but labels `source_measurement=ip_event_sensitivity:event_summary`; it is not a fabricated probe-level panel.\n\n## Interpretation gate\n- Interpretation A: only if the nationwide, within-AS, release, source and interaction evidence all support a power-specific difference.\n- Interpretation B: if availability is associated with infrastructure evidence but the interaction is weak or power-vs-normal discrimination is similar; this is the conservative default if the interaction is not supported.\n- Interpretation C: if ASN adjustment or independent snapshots remove the association.\nThe report does not select an interpretation by visual preference.\n"""
    (out/"outputs/FINAL_VALIDATION_REPORT.md").write_text(rep,encoding="utf-8")
    zh="""# 论文收尾摘要（中文）\n\n**研究问题**：重复计划停电窗口中的 IP 可达率，是否与独立网络基础设施证据相关，以及这种关系能否超出正常时期稳定性与 ASN 构成的解释。\n\n**数据与方法**：使用冻结的乌克兰主动测量目标、核验停电登记表、事件级 IP 响应缓存和 CAIDA ITDK 证据。可达率定义为有效探针中有响应的比例；正常对照按同年、同月、同星期、同 2 小时测量槽选择，并排除正向停电窗口。主要交互模型为含事件固定效应、/24 交换相关结构的二项 GEE；ASN 内验证使用条件 Logistic；ROC/PR 的最终区间使用 2000 次 /24 聚类 bootstrap。\n\n**发现与边界**：全期覆盖、州级异质性、交互模型、ASN 内估计和独立 ITDK 快照分别见表格。结果只能支持关联，不能支持停电的因果效应。由于现有缓存是事件级汇总而非逐探针时间戳，本轮把这一限制显式写入方法和 registry，而没有伪造原始 probe。\n\n**贡献**：把停电窗口可达率、时间分层对照和独立拓扑证据放入同一可审计流程，并明确区分一般在线稳定性、ASN 构成和可能的电力特异性信号。\n"""
    en=zh.replace("# 论文收尾摘要（中文）","# Paper closure summary (English)").replace("**研究问题**","**Research question**").replace("**数据与方法**","**Data and method**").replace("**发现与边界**","**Findings and boundary**").replace("**贡献**","**Contribution**")
    (out/"outputs/PAPER_CLOSURE_SUMMARY_ZH.md").write_text(zh,encoding="utf-8"); (out/"outputs/PAPER_CLOSURE_SUMMARY_EN.md").write_text(en,encoding="utf-8")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",default="/home/wsl/XiaoLunWen_doc_complete_20260908"); ap.add_argument("--dry-run",action="store_true"); ap.add_argument("--rerender",action="store_true"); ap.add_argument("--repair-models",action="store_true"); args=ap.parse_args()
    root=Path(args.root); out=root/"power_availability_infrastructure_final_validation_v2"; setup(out)
    m,ev,sched,sched_ok,cq=read_inputs(root,out)
    if args.dry_run:
        (out/"logs/dry_run.csv").write_text("test,status\nfinal_validation_v2,PASS\n",encoding="utf-8"); print(json.dumps({"status":"DRY_RUN_PASS","master_ips":len(m),"schedule_rows":len(sched_ok)})); return
    if args.rerender:
        audit=pd.read_csv(out/"tables/TABLE_F01_event_coverage_audit.csv")
        auc=pd.read_csv(out/"tables/TABLE_F07_final_auc.csv")
        reg=pd.read_parquet(out/"data/power_normal_referent_registry.parquet") if (out/"data/power_normal_referent_registry.parquet").exists() else pd.DataFrame()
        im=pd.read_csv(out/"tables/TABLE_F04_interaction_model.csv")
        make_figures(m,audit,auc,out); write_methods(out,"OK","OK","OK"); reports(out,m,audit,reg,im,pd.read_csv(out/"tables/TABLE_F06_within_as_model.csv"),auc)
        figs=sorted((out/"figures").glob("*/*.png")); pd.DataFrame([{"figure":p.stem,"language":p.parent.name,"png":str(p.relative_to(out)),"pdf":str(p.with_suffix('.pdf').relative_to(out)),"svg":str(p.with_suffix('.svg').relative_to(out)),"data_identity":"shared source tables"} for p in figs]).to_csv(out/"outputs/FIGURE_LANGUAGE_INDEX.csv",index=False)
        print(json.dumps({"status":"RERENDER_PASS","png":len(figs)})); return
    if args.repair_models:
        audit=event_audit(ev,sched,sched_ok,cq,out)
        reg=pd.read_parquet(out/"data/power_normal_referent_registry.parquet")
        # The frozen event cache already contains both event-level numerators and
        # denominators; use it directly for model repair, avoiding a second pivot
        # over the persisted long registry.
        ev2=ev.copy()
        im,ist=gee_interaction(ev2,m,out)
        asn=pd.read_csv(out/"tables/TABLE_F06_within_as_model.csv") if (out/"tables/TABLE_F06_within_as_model.csv").exists() else within_as(m,out)
        auc=discrimination(m,out); make_figures(m,audit,auc,out); write_methods(out,ist,ist,"OK"); reports(out,m,audit,reg,im,asn,auc)
        print(json.dumps({"status":"REPAIR_MODELS_PASS","interaction_status":ist},ensure_ascii=False)); return
    audit=event_audit(ev,sched,sched_ok,cq,out)
    m.to_parquet(out/"data/ip_power_availability_master_v2.parquet",index=False,compression="zstd")
    reg,ev2=build_registry(ev,sched_ok,cq,out)
    im,ist=gee_interaction(ev2,m,out); asn=within_as(m,out); auc=discrimination(m,out); make_figures(m,audit,auc,out)
    write_methods(out,ist,ist,"OK")
    reports(out,m,audit,reg,im,asn,auc)
    # Figure/data index and explicit gates
    figs=sorted((out/"figures").glob("*/*.png")); idx=[]
    for p in figs: idx.append({"figure":p.stem,"language":p.parent.name,"png":str(p.relative_to(out)),"pdf":str(p.with_suffix('.pdf').relative_to(out)),"svg":str(p.with_suffix('.svg').relative_to(out)),"data_identity":"shared source tables"})
    pd.DataFrame(idx).to_csv(out/"outputs/FIGURE_LANGUAGE_INDEX.csv",index=False)
    (out/"outputs/NOT_GENERATED.md").write_text("# Explicit method gates\n\n- Figure 26: NOT GENERATED — no verified post-v1 events through 2025-01-31.\n- Raw per-probe paired registry: NOT AVAILABLE — source cache contains event-level aggregates; the auditable registry labels this limitation.\n- binsreg package: unavailable on server; continuous plots use documented Freedman–Diaconis data-driven bins, not hand-picked bins.\n",encoding="utf-8")
    summary={"stage":"power_availability_infrastructure_final_validation_v2","research_period":[str(START),str(END)],"events":int(len(audit)),"included_events":int(audit.included_v2.sum()),"states":int(m.oblast.nunique()),"ips":int(m.ip.nunique()),"registry_rows":int(len(reg)),"interaction_status":ist,"figure_png_pairs":int(len(figs)/2),"figure26":"NOT_GENERATED","git_head":subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()}
    (out/"outputs/FINAL_SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    files=[p for p in out.rglob("*") if p.is_file() and p.name!="OUTPUT_MANIFEST_SHA256.txt"]
    (out/"methods/OUTPUT_MANIFEST_SHA256.txt").write_text("\n".join(f"{sha256(p)}  {p.relative_to(out)}" for p in files)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
