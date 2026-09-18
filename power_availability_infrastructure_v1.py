#!/usr/bin/env python3
"""Independent power-availability / infrastructure-evidence feasibility stage.

This stage deliberately consumes the frozen, auditable event-level response
cache and the frozen time-appropriate target mapping.  It does not reuse any
stable-IP/support threshold or any H1--H4 outcome.
"""
from __future__ import annotations

import argparse, hashlib, json, math, os, shutil, tarfile
from pathlib import Path

import numpy as np
import pandas as pd

RNG_SEED = 20240601
RELEASES = ["2024-02", "2024-08", "2025-03"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def wilson(k, n, z=1.959963984540054):
    if n <= 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def availability(responsive, valid):
    responsive = np.asarray(responsive, dtype=float)
    valid = np.asarray(valid, dtype=float)
    out = np.full(responsive.shape, np.nan, dtype=float)
    np.divide(responsive, valid, out=out, where=valid > 0)
    return out


def deciles(values: pd.Series) -> pd.Series:
    """Deterministic percentile deciles; equal values are never randomly split."""
    v = pd.to_numeric(values, errors="coerce")
    rank = v.rank(method="min", pct=True)
    d = np.ceil(rank * 10).clip(1, 10)
    return d.astype("Int64")


def load_inputs(root: Path):
    target = pd.read_parquet(root / "runs/paper_final_v2_episode_fix_20260910/data_derived/target_ip_universe.parquet")
    target = target[(target.valid_target_admin1 == 1) & (target.target_country == "Ukraine")].copy()
    target = target.rename(columns={"dst_ip": "ip", "target_admin1": "oblast", "target_asn": "asn"})
    target = target[["ip", "prefix24", "oblast", "asn"]].drop_duplicates("ip")

    sched = pd.read_csv(root / "config/planned_outage_schedule_v4_0.csv", low_memory=False)
    for c in ["analysis_eligible", "schedule_positive", "confound_free", "interval_valid"]:
        sched[c] = pd.to_numeric(sched[c], errors="coerce").fillna(0).astype(int)
    sched["start_utc_dt"] = pd.to_datetime(sched["start_utc"], utc=True, errors="coerce")
    sched["date"] = sched["start_utc_dt"].dt.date
    sched_ok = sched[(sched.analysis_eligible == 1) & (sched.schedule_positive == 1) &
                     (sched.confound_free == 1) & (sched.interval_valid == 1)].copy()
    # State/date is the auditable matching key; ALL applies nationwide.
    state_dates = set(zip(sched_ok.loc[sched_ok.admin1 != "ALL", "admin1"],
                          sched_ok.loc[sched_ok.admin1 != "ALL", "date"]))
    all_dates = set(sched_ok.loc[sched_ok.admin1 == "ALL", "date"])

    ev = pd.read_parquet(root / "runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet",
                         columns=["dst_ip", "target_admin1", "x_normal", "x_outage",
                                  "n_normal", "n_outage", "event_id", "evidence_tier"])
    ev = ev.rename(columns={"dst_ip": "ip", "target_admin1": "oblast"})
    ev["event_date"] = pd.to_datetime(ev.event_id.str.extract(r"(\d{8})")[0],
                                       format="%Y%m%d", errors="coerce").dt.date
    ev = ev[ev.event_date.notna()].copy()
    ev["schedule_matched"] = [((s, d) in state_dates) or (d in all_dates)
                               for s, d in zip(ev.oblast, ev.event_date)]
    ev = ev[ev.schedule_matched].copy()
    for c in ["x_normal", "x_outage", "n_normal", "n_outage"]:
        ev[c] = pd.to_numeric(ev[c], errors="coerce").fillna(0.0)
    ev = ev.drop_duplicates(["ip", "event_id"])

    # CAIDA evidence parquet contains release-specific rows plus 2025 flags.
    ca = pd.read_parquet("/home/caida_ukraine_validation/ukraine_filtered/caida_infrastructure_evidence.parquet")
    flags = []
    for rel in ["2024-02", "2024-08"]:
        d = ca[ca.release.eq(rel)].copy()
        t = d.groupby("ip").is_transit_or_middle_hop.max().fillna(0).astype(int)
        r = d.groupby("ip").router_id.apply(lambda x: int(x.notna().any()))
        flags.append(pd.DataFrame({f"itdk_{rel.replace('-', '')}_T": t,
                                   f"itdk_{rel.replace('-', '')}_router": r}))
    d25 = ca[ca.is_transit_202503.notna() | ca.router_id_202503.notna()].copy()
    if len(d25):
        t = d25.groupby("ip").is_transit_202503.max().fillna(0).astype(int)
        r = d25.groupby("ip").router_id_202503.apply(lambda x: int(x.notna().any()))
    else:
        t = pd.Series(dtype=int); r = pd.Series(dtype=int)
    flags.append(pd.DataFrame({"itdk_202503_T": t, "itdk_202503_router": r}))
    ca_flags = pd.concat(flags, axis=1).fillna(0).astype(int).reset_index()

    trace_files = sorted((root / "feasibility_imc2027_v2/data_processed/traceroute").glob("intermediate_ipv4_*.csv"))
    own = set()
    for f in trace_files:
        try:
            own.update(pd.read_csv(f, usecols=["ip"])["ip"].dropna().astype(str))
        except Exception:
            pass
    return target, sched_ok, ev, ca_flags, own


def build_master(root: Path, out: Path, target, sched, ev, ca_flags, own):
    # Opportunity denominator: one complete event opportunity per matched state/event.
    state_event = ev[["oblast", "event_id", "event_date"]].drop_duplicates()
    den = (ev.groupby(["oblast", "event_id"], as_index=False)
             .agg(power_valid_event=("n_outage", "max"), normal_valid_event=("n_normal", "max")))
    state_den = den.groupby("oblast").agg(
        power_valid_probe_count=("power_valid_event", "sum"),
        normal_valid_probe_count=("normal_valid_event", "sum"),
        power_opportunity_event_n=("event_id", "nunique"),
        control_opportunity_event_n=("event_id", "nunique"),
    ).reset_index()
    agg = (ev.groupby("ip", as_index=False)
             .agg(power_responsive_count=("x_outage", "sum"),
                  power_valid_probe_observed=("n_outage", "sum"),
                  normal_responsive_count=("x_normal", "sum"),
                  normal_valid_probe_observed=("n_normal", "sum"),
                  number_of_power_events_observed=("event_id", "nunique"),
                  number_of_control_events_observed=("event_id", "nunique")))
    m = target.merge(state_den, on="oblast", how="left", suffixes=("", "_state"))
    m = m.merge(agg, on="ip", how="left")
    # When a state-level denominator and an observed-cache column have the same
    # name pandas applies the `_state` suffix.  Keep the explicit state
    # opportunity denominator and use the observed event count only as a
    # diagnostic; the denominator is never inferred from missing response rows.
    # Observed cache rows retain numerator; denominator is complete-cycle opportunity count.
    for c in ["power_responsive_count", "normal_responsive_count"]:
        m[c] = m[c].fillna(0.0)
    for c in ["number_of_power_events_observed", "number_of_control_events_observed"]:
        m[c] = m[c].fillna(0).astype(int)
    m["power_valid_probe_count"] = m["power_valid_probe_count"].fillna(0)
    m["normal_valid_probe_count"] = m["normal_valid_probe_count"].fillna(0)
    m["power_availability"] = availability(m.power_responsive_count, m.power_valid_probe_count)
    m["normal_availability"] = availability(m.normal_responsive_count, m.normal_valid_probe_count)
    m = m[m.power_valid_probe_count > 0].copy()
    m = m.merge(ca_flags, on="ip", how="left")
    for c in ["itdk_202402_T", "itdk_202408_T", "itdk_202503_T",
              "itdk_202402_router", "itdk_202408_router", "itdk_202503_router"]:
        m[c] = m[c].fillna(0).astype(int)
    m["own_traceroute_intermediate"] = m.ip.isin(own).astype(int)
    m["power_decile_oblast"] = m.groupby("oblast", group_keys=False).power_availability.apply(deciles).astype("Int64")
    m["power_decile_nationwide"] = deciles(m.power_availability)
    m.to_parquet(out / "data/ip_power_availability_master.parquet", index=False, compression="zstd")
    # Event matching audit is part of the data provenance, not a result filter.
    audit = (ev.groupby(["oblast", "event_id", "event_date", "evidence_tier"], as_index=False)
               .agg(ip_rows=("ip", "nunique"), max_power_cycles=("n_outage", "max"), max_control_cycles=("n_normal", "max")))
    audit.to_csv(out / "data/matched_event_opportunity_audit.csv", index=False)
    return m, audit


def bootstrap_auc(d, score, label, cluster="prefix24", B=100, seed=RNG_SEED):
    d = d[[score, label, cluster]].dropna().copy()
    if d[label].nunique() < 2:
        return np.nan, np.nan, np.nan
    from sklearn.metrics import roc_auc_score
    point = roc_auc_score(d[label], d[score])
    groups = d[cluster].astype(str).unique(); rng = np.random.default_rng(seed); vals=[]
    by = {g: x for g, x in d.groupby(cluster, sort=False)}
    for _ in range(B):
        sampled = rng.choice(groups, size=len(groups), replace=True)
        z = pd.concat([by[g] for g in sampled], ignore_index=True)
        if z[label].nunique() == 2:
            vals.append(roc_auc_score(z[label], z[score]))
    if len(vals) < 20:
        return point, np.nan, np.nan
    return point, float(np.quantile(vals, .025)), float(np.quantile(vals, .975))


def tables_and_models(m: pd.DataFrame, out: Path):
    from sklearn.metrics import roc_auc_score, average_precision_score
    from scipy.stats import spearmanr
    trows=[]
    for oblast, g in m.groupby("oblast"):
        for d, z in g.groupby("power_decile_oblast", dropna=True):
            n=len(z); k=int(z.itdk_202408_T.sum()); lo,hi=wilson(k,n)
            trows.append({"oblast":oblast,"decile":int(d),"n":n,
                          "power_availability_median":z.power_availability.median(),
                          "itdk_T_n":k,"itdk_T_prevalence":k/n,"CI_low":lo,"CI_high":hi})
    for d,z in m.groupby("power_decile_nationwide", dropna=True):
        n=len(z); k=int(z.itdk_202408_T.sum()); lo,hi=wilson(k,n)
        trows.append({"oblast":"NATIONWIDE","decile":int(d),"n":n,
                      "power_availability_median":z.power_availability.median(),
                      "itdk_T_n":k,"itdk_T_prevalence":k/n,"CI_low":lo,"CI_high":hi})
    tab1=pd.DataFrame(trows); tab1.to_csv(out/"tables/TABLE_01_decile_enrichment.csv",index=False)

    arows=[]; prows=[]
    for oblast, g in pd.concat([m, m.assign(oblast="NATIONWIDE")], ignore_index=True).groupby("oblast"):
        r={"oblast":oblast,"N":len(g),"N_positive":int(g.itdk_202408_T.sum()),"N_negative":int((g.itdk_202408_T==0).sum())}
        ap,lo,hi=bootstrap_auc(g,"power_availability","itdk_202408_T")
        an,ln,hn=bootstrap_auc(g,"normal_availability","itdk_202408_T")
        # Paired cluster bootstrap difference.
        valid=g[["power_availability","normal_availability","itdk_202408_T","prefix24"]].dropna()
        diff=ap-an if np.isfinite(ap) and np.isfinite(an) else np.nan; vals=[]
        if len(valid) and valid.itdk_202408_T.nunique()==2:
            rng=np.random.default_rng(RNG_SEED); by={x:z for x,z in valid.groupby("prefix24")}; groups=np.array(list(by))
            for _ in range(100):
                z=pd.concat([by[x] for x in rng.choice(groups,len(groups),replace=True)],ignore_index=True)
                if z.itdk_202408_T.nunique()==2:
                    vals.append(roc_auc_score(z.itdk_202408_T,z.power_availability)-roc_auc_score(z.itdk_202408_T,z.normal_availability))
        dlo,dhi=(np.quantile(vals,[.025,.975]) if len(vals)>=20 else (np.nan,np.nan))
        r.update(AUC_power=ap,CI_low=lo,CI_high=hi,AUC_normal=an,CI_low_normal=ln,CI_high_normal=hn,AUC_difference=diff,difference_CI_low=dlo,difference_CI_high=dhi,p_value_if_supported=np.nan)
        arows.append(r)
        for score,name in [("power_availability","power"),("normal_availability","normal")]:
            z=g[[score,"itdk_202408_T"]].dropna();
            prows.append({"oblast":oblast,"score":name,"N":len(z),"positive_prevalence":z.itdk_202408_T.mean() if len(z) else np.nan,
                          "average_precision":average_precision_score(z.itdk_202408_T,z[score]) if len(z) and z.itdk_202408_T.nunique()==2 else np.nan})
    tab2=pd.DataFrame(arows); tab2.to_csv(out/"tables/TABLE_02_auc_by_oblast.csv",index=False)
    pd.DataFrame(prows).to_csv(out/"tables/TABLE_03_pr_by_oblast.csv",index=False)

    # Primary GEE: continuous availability, prefix24 exchangeable working correlation.
    rows=[]; status="OK"
    try:
        import statsmodels.api as sm
        from statsmodels.genmod.generalized_estimating_equations import GEE
        from statsmodels.genmod.families import Binomial
        z=m[["power_availability","itdk_202408_T","prefix24"]].dropna().copy()
        z["const"]=1.0
        fit=GEE(z.itdk_202408_T, z[["const","power_availability"]], groups=z.prefix24,
                family=Binomial(), cov_struct=sm.cov_struct.Exchangeable()).fit()
        rows=[{"term":"power_availability","estimate_log_odds_per_unit":fit.params["power_availability"],
               "odds_ratio_per_unit":np.exp(fit.params["power_availability"]),"CI_low":np.exp(fit.conf_int().loc["power_availability",0]),
               "CI_high":np.exp(fit.conf_int().loc["power_availability",1]),"p_value":fit.pvalues["power_availability"],
               "cluster_unit":"prefix24","working_correlation":"exchangeable","n":len(z),"cluster_n":z.prefix24.nunique()}]
    except Exception as e:
        status=f"NOT_GENERATED: {e}"; rows=[{"term":"power_availability","status":status,"cluster_unit":"prefix24","working_correlation":"exchangeable"}]
    pd.DataFrame(rows).to_csv(out/"tables/TABLE_04_primary_regression.csv",index=False)

    rr=[]
    for rel, lab in [("2024-02","itdk_202402_T"),("2024-08","itdk_202408_T"),("2025-03","itdk_202503_T")]:
        ap,lo,hi=bootstrap_auc(m,"power_availability",lab); rr.append({"release":rel,"label":lab,"AUC_power":ap,"CI_low":lo,"CI_high":hi,"role":"PRIMARY" if rel=="2024-08" else "ROBUSTNESS"})
    pd.DataFrame(rr).to_csv(out/"tables/TABLE_05_release_robustness.csv",index=False)
    rows=[]
    for rel, lab in [("2024-02","itdk_202402_router"),("2024-08","itdk_202408_router"),("2025-03","itdk_202503_router")]:
        for d,z in m.groupby("power_decile_nationwide"):
            n=len(z); k=int(z[lab].sum()); lo,hi=wilson(k,n); rows.append({"release":rel,"decile":int(d),"n":n,"positive":k,"prevalence":k/n,"CI_low":lo,"CI_high":hi,"label":lab})
    pd.DataFrame(rows).to_csv(out/"tables/TABLE_06_router_robustness.csv",index=False)
    rows=[]
    for d,z in m.groupby("power_decile_nationwide"):
        n=len(z); k=int(z.own_traceroute_intermediate.sum()); lo,hi=wilson(k,n); rows.append({"decile":int(d),"n":n,"positive":k,"prevalence":k/n,"CI_low":lo,"CI_high":hi,"label":"own_traceroute_intermediate"})
    pd.DataFrame(rows).to_csv(out/"tables/TABLE_07_traceroute_validation.csv",index=False)
    return tab1,tab2,status


def figure(figdir: Path, name, lang, draw, xlabel, ylabel, title):
    import matplotlib.pyplot as plt
    # Use an installed CJK font; never download or bundle fonts.
    plt.rcParams.update({"font.size":9,"axes.titlesize":11,"axes.labelsize":9,"figure.dpi":120,
                         "font.sans-serif": ["SimHei", "WenQuanYi Micro Hei", "DejaVu Sans"],
                         "axes.unicode_minus": False})
    fig,ax=plt.subplots(figsize=(7.2,4.4)); draw(ax,lang)
    if ax.figure is None:
        fig.suptitle(title[lang])
    else:
        ax.set_title(title[lang]); ax.set_xlabel(xlabel[lang]); ax.set_ylabel(ylabel[lang]); ax.grid(alpha=.2)
    fig.tight_layout(); base=figdir/lang/name
    base.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(str(base)+".png",dpi=300); fig.savefig(str(base)+".pdf"); fig.savefig(str(base)+".svg"); plt.close(fig)


def make_figures(m, tab1, tab2, out: Path):
    import matplotlib.pyplot as plt
    from sklearn.metrics import roc_curve, precision_recall_curve, roc_auc_score, average_precision_score
    zh={"title":None}; labels={"zh":"zh","en":"en"}
    # Consistent colors and data; only text changes by language.
    titles={
      "f01_coverage":{"zh":"纳入 IP 的州级覆盖","en":"Coverage of Included IPs"},
      "f02_ecdf":{"zh":"电力中断窗口可达率分布","en":"Power-Window Availability ECDF"},
      "f03_normal_power":{"zh":"正常窗口与电力中断窗口可达率","en":"Normal-Window vs Power-Window Availability"},
      "f04_decile":{"zh":"不同停电可达率分位组中的 ITDK 中间跳证据比例","en":"ITDK Transit-Evidence Prevalence Across Power-Availability Deciles"},
      "f06_roc":{"zh":"停电窗口可达率识别 ITDK 中间跳证据的 ROC 曲线","en":"ROC Curves for ITDK Transit Evidence from Availability"},
      "f07_pr":{"zh":"停电窗口可达率识别 ITDK 中间跳证据的 PR 曲线","en":"Precision–Recall Curves for ITDK Transit Evidence"},
      "f08_auc_forest":{"zh":"各州停电可达率对 ITDK 中间跳证据的判别能力","en":"Oblast-Level Discrimination of ITDK Transit Evidence"},
      "f09_auc_diff":{"zh":"停电期与正常期可达率判别能力差异","en":"Difference in Discrimination: Power - Normal"},
      "f11_release":{"zh":"不同 ITDK 时间快照下的结果稳健性","en":"Robustness Across ITDK Releases"},
      "f12_router":{"zh":"不同停电可达率分位组中的 ITDK 路由器证据比例","en":"ITDK Router-Evidence Prevalence Across Deciles"},
      "f13_trace":{"zh":"不同停电可达率分位组中的 Traceroute 中间跳证据比例","en":"Traceroute Intermediate-Hop Evidence Across Deciles"},
      "f14_opportunities":{"zh":"每个 IP 的有效电力中断观测机会分布","en":"Valid Power-Outage Observation Opportunities per IP"},
      "f15_opportunity_scatter":{"zh":"停电窗口可达率与观测机会数量关系","en":"Power Availability vs Observation Opportunities"},
    }
    xlbl={"zh":"电力中断窗口可达率","en":"Power-Window Availability"}; ylbl={"zh":"IP 密度","en":"IP density"}
    # Figure 1
    def cov(ax,l):
        q=m.oblast.value_counts().sort_values(); ax.barh(q.index,q.values,color="#2c7fb8"); ax.tick_params(axis='y',labelsize=7)
    figure(out/"figures", "f01_coverage", "zh", cov,{"zh":"IP 数量","en":"Number of IPs"},{"zh":"州","en":"Oblast"},titles['f01_coverage'])
    figure(out/"figures", "f01_coverage", "en", cov,{"zh":"IP 数量","en":"Number of IPs"},{"zh":"州","en":"Oblast"},titles['f01_coverage'])
    # Figure 2
    def ecdf(ax,l):
        x=np.sort(m.power_availability.dropna().to_numpy()); y=np.arange(1,len(x)+1)/len(x); ax.plot(x,y,color="#d7301f"); ax.set_xlim(0,1); ax.set_ylim(0,1)
    for l in ['zh','en']: figure(out/"figures","f02_ecdf",l,ecdf,{"zh":"电力中断窗口可达率","en":"Power-Window Availability"},{"zh":"累积比例","en":"Cumulative share"},titles['f02_ecdf'])
    # Figure 3
    def scat(ax,l):
        z=m[["normal_availability","power_availability"]].dropna(); ax.hexbin(z.normal_availability,z.power_availability,gridsize=55,bins='log',cmap='viridis'); ax.plot([0,1],[0,1],"k--",lw=.8); ax.set_xlim(0,1); ax.set_ylim(0,1)
    for l in ['zh','en']: figure(out/"figures","f03_normal_power",l,scat,{"zh":"正常窗口可达率","en":"Normal-Window Availability"},{"zh":"电力中断窗口可达率","en":"Power-Window Availability"},titles['f03_normal_power'])
    # Figure 4 nationwide deciles
    def dec(ax,l):
        z=tab1[tab1.oblast.eq('NATIONWIDE')].sort_values('decile'); ax.errorbar(z.decile,z.itdk_T_prevalence*100,yerr=[(z.itdk_T_prevalence-z.CI_low)*100,(z.CI_high-z.itdk_T_prevalence)*100],fmt='o-',color='#2c7fb8'); ax.set_xticks(range(1,11)); ax.set_ylim(bottom=0); ax.set_xlabel({"zh":"停电可达率十分位组（D1 最低，D10 最高）","en":"Power-Availability Decile (D1 lowest, D10 highest)"}[l]); ax.set_ylabel({"zh":"ITDK 中间跳证据 IP 比例（%）","en":"IPs with ITDK Transit Evidence (%)"}[l])
    for l in ['zh','en']: figure(out/"figures","f04_decile",l,dec,{"zh":"十分位组","en":"Decile"},{"zh":"ITDK 中间跳证据比例（%）","en":"ITDK transit evidence prevalence (%)"},titles['f04_decile'])
    # Figure 5: same y-scale in every oblast panel (no result-based state removal).
    def oblast_dec(ax,l):
        states=sorted([x for x in tab1.oblast.unique() if x!='NATIONWIDE'])
        fig=ax.figure; ax.remove(); axes=fig.subplots(math.ceil(len(states)/4),4,sharex=True,sharey=True).ravel()
        ymax=max(1.0,float(tab1.itdk_T_prevalence.max()*100*1.05))
        for a,s in zip(axes,states):
            q=tab1[tab1.oblast.eq(s)].sort_values('decile'); lo=np.maximum(0,(q.itdk_T_prevalence-q.CI_low)*100); hi=np.maximum(0,(q.CI_high-q.itdk_T_prevalence)*100); a.errorbar(q.decile,q.itdk_T_prevalence*100,yerr=[lo,hi],fmt='o-',ms=2,color='#2c7fb8'); a.set_title(s.replace(' Oblast',''),fontsize=7); a.set_ylim(0,ymax); a.set_xticks([1,5,10]); a.grid(alpha=.15)
        for a in axes[len(states):]: a.axis('off')
        fig.supxlabel({"zh":"电力中断窗口可达率十分位组（D1 最低，D10 最高）","en":"Power-Availability Decile (D1 lowest, D10 highest)"}[l]); fig.supylabel({"zh":"ITDK 中间跳证据比例（%）","en":"ITDK transit evidence prevalence (%)"}[l])
    for l in ['zh','en']: figure(out/"figures","f05_oblast_decile",l,oblast_dec,{"zh":"十分位组","en":"Decile"},{"zh":"ITDK 证据比例（%）","en":"ITDK evidence prevalence (%)"},{"zh":"各州停电可达率与 ITDK 基础设施证据富集关系","en":"Oblast-Level Relationship Between Power Availability and ITDK Evidence"})
    # ROC/PR
    z=m[["power_availability","normal_availability","itdk_202408_T"]].dropna(subset=['itdk_202408_T'])
    def roc(ax,l):
        for c,col,lab in [('power_availability','#d7301f',{'zh':'电力中断窗口','en':'Power window'}),('normal_availability','#2c7fb8',{'zh':'正常窗口','en':'Normal window'})]:
            q=z[[c,'itdk_202408_T']].dropna(); f,t,_=roc_curve(q.itdk_202408_T,q[c]); ax.plot(f,t,color=col,label=f"{lab[l]} AUC={roc_auc_score(q.itdk_202408_T,q[c]):.3f}")
        ax.plot([0,1],[0,1],'k--',lw=.8); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.legend(frameon=False,fontsize=8)
    for l in ['zh','en']: figure(out/"figures","f06_roc",l,roc,{"zh":"假阳性率","en":"False Positive Rate"},{"zh":"真阳性率","en":"True Positive Rate"},titles['f06_roc'])
    def pr(ax,l):
        for c,col,lab in [('power_availability','#d7301f',{'zh':'电力中断窗口','en':'Power window'}),('normal_availability','#2c7fb8',{'zh':'正常窗口','en':'Normal window'})]:
            q=z[[c,'itdk_202408_T']].dropna(); rec,pre,_=precision_recall_curve(q.itdk_202408_T,q[c]); ax.plot(rec,pre,color=col,label=f"{lab[l]} AP={average_precision_score(q.itdk_202408_T,q[c]):.3f}")
        ax.axhline(z.itdk_202408_T.mean(),color='k',ls='--',lw=.8,label={"zh":"阳性比例基线","en":"Positive prevalence baseline"}[l]); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.legend(frameon=False,fontsize=8)
    for l in ['zh','en']: figure(out/"figures","f07_pr",l,pr,{"zh":"召回率","en":"Recall"},{"zh":"精确率","en":"Precision"},titles['f07_pr'])
    # Forest and difference
    state=tab2[~tab2.oblast.eq('NATIONWIDE')].sort_values('AUC_power').reset_index(drop=True)
    def forest(ax,l):
        y=np.arange(len(state)); ax.errorbar(state.AUC_power,y,xerr=[state.AUC_power-state.CI_low,state.CI_high-state.AUC_power],fmt='o',color='#d7301f'); ax.axvline(.5,color='k',ls='--',lw=.8); ax.set_yticks(y); ax.set_yticklabels(state.oblast); ax.set_xlim(0,1)
    for l in ['zh','en']: figure(out/"figures","f08_auc_forest",l,forest,{"zh":"ROC-AUC","en":"ROC-AUC"},{"zh":"州","en":"Oblast"},titles['f08_auc_forest'])
    def diff(ax,l):
        q=tab2.sort_values('AUC_difference').reset_index(drop=True); y=np.arange(len(q)); ax.errorbar(q.AUC_difference,y,xerr=[q.AUC_difference-q.difference_CI_low,q.difference_CI_high-q.AUC_difference],fmt='o',color='#54278f'); ax.axvline(0,color='k',ls='--',lw=.8); ax.set_yticks(y); ax.set_yticklabels(q.oblast); ax.set_xlabel({"zh":"AUC 差值（电力中断期 - 正常期）","en":"AUC difference (Power - Normal)"}[l])
    for l in ['zh','en']: figure(out/"figures","f09_auc_diff",l,diff,{"zh":"AUC 差值","en":"AUC difference"},{"zh":"州 / 全国","en":"Oblast / Nationwide"},titles['f09_auc_diff'])
    # Robustness, router and traceroute deciles
    def release(ax,l):
        q=pd.read_csv(out/'tables/TABLE_05_release_robustness.csv'); q=q.sort_values('release'); y=np.arange(len(q)); ax.errorbar(q.AUC_power,y,xerr=[q.AUC_power-q.CI_low,q.CI_high-q.AUC_power],fmt='o'); ax.axvline(.5,color='k',ls='--',lw=.8); ax.set_yticks(y); ax.set_yticklabels(q.release); ax.set_xlim(0,1)
    for l in ['zh','en']: figure(out/"figures","f11_release",l,release,{"zh":"ROC-AUC","en":"ROC-AUC"},{"zh":"ITDK 快照","en":"ITDK release"},titles['f11_release'])
    def router(ax,l):
        q=pd.read_csv(out/'tables/TABLE_06_router_robustness.csv'); q=q[q.release.eq('2024-08')]; ax.plot(q.decile,q.prevalence*100,'o-',color='#31a354'); ax.set_xticks(range(1,11)); ax.set_ylabel({"zh":"路由器证据比例（%）","en":"Router evidence prevalence (%)"}[l])
    for l in ['zh','en']: figure(out/"figures","f12_router",l,router,{"zh":"十分位组","en":"Decile"},{"zh":"路由器证据比例（%）","en":"Router evidence prevalence (%)"},titles['f12_router'])
    def trace(ax,l):
        q=pd.read_csv(out/'tables/TABLE_07_traceroute_validation.csv'); ax.plot(q.decile,q.prevalence*100,'o-',color='#756bb1'); ax.set_xticks(range(1,11)); ax.set_ylabel({"zh":"Traceroute 中间跳证据比例（%）","en":"Traceroute intermediate-hop evidence (%)"}[l])
    for l in ['zh','en']: figure(out/"figures","f13_trace",l,trace,{"zh":"十分位组","en":"Decile"},{"zh":"中间跳证据比例（%）","en":"Intermediate-hop evidence (%)"},titles['f13_trace'])
    def opp(ax,l):
        q=m.power_valid_probe_count.value_counts().sort_index(); ax.bar(q.index,q.values,color='#74a9cf'); ax.set_xlim(left=0)
    for l in ['zh','en']: figure(out/"figures","f14_opportunities",l,opp,{"zh":"有效电力中断观测次数","en":"Valid power-outage observations"},{"zh":"IP 数量","en":"Number of IPs"},titles['f14_opportunities'])
    def oppsc(ax,l):
        q=m[["power_valid_probe_count","power_availability"]].dropna(); ax.scatter(q.power_valid_probe_count,q.power_availability,s=1,alpha=.12,color='#d7301f'); ax.set_ylim(0,1); ax.set_xscale('log')
    for l in ['zh','en']: figure(out/"figures","f15_opportunity_scatter",l,oppsc,{"zh":"有效电力中断观测次数（对数轴）","en":"Valid power-outage observations (log scale)"},{"zh":"电力中断窗口可达率","en":"Power-window availability"},titles['f15_opportunity_scatter'])


def write_docs(out: Path, audit, model_status):
    methods=out/'methods'; methods.mkdir(parents=True,exist_ok=True)
    (methods/'METHOD_PROVENANCE.md').write_text("""# Method provenance\n\n## Primary availability\n`availability = responded probes / valid probes` follows Bhagwan, Savage & Voelker (IPTPS 2003), https://cseweb.ucsd.edu/~voelker/pubs/avail-iptps03.pdf. The current label is named **power-window availability**, not a resilience score.\n\n## Power-window design\nNormal/outage separation follows the design idea in Anderson et al., *PowerPing* (2023), https://pages.cs.wisc.edu/~pb/PowerPing.pdf. The paper's 20-minute/all-probes candidate rule is not imported because this campaign has a different cycle schedule.\n\n## Infrastructure labels\nCAIDA ITDK documentation defines the Interfaces `T` flag as an address observed as a transit hop: https://www.caida.org/catalog/datasets/internet-topology-data-kit/. ITDK 2024-08 is PRIMARY; 2024-02 and 2025-03 are robustness snapshots. Router membership and own traceroute intermediate evidence are separate secondary labels; no composite infrastructure score is constructed.\n\n## Proportion intervals\nDecile prevalence intervals use Wilson binomial intervals (Brown, Cai & DasGupta, 2001, https://doi.org/10.1214/ss/1009213286).\n\n## Continuous primary model\nA binomial GEE with prefix24 clusters and exchangeable working correlation is the pre-registered primary association model, following Liang & Zeger (1986), https://doi.org/10.1093/biomet/73.1.13. The cluster unit is fixed before outcome inspection because IPs sharing a /24 can be correlated.\n\n## Discrimination\nROC interpretation follows Hanley & McNeil (1982), https://doi.org/10.1148/radiology.143.1.7063747. Uncertainty is a deterministic /24 cluster bootstrap (Efron & Tibshirani, 1993) with **100 cluster resamples** in this run; independent-IP DeLong assumptions are not appropriate for clustered address populations. PR curves report average precision and the observed positive-prevalence baseline following Saito & Rehmsmeier (2015), https://doi.org/10.1371/journal.pone.0118432.\n\n## Control-window caveat\nThe matched control windows are inherited from the frozen project registry. Their construction is documented as secondary/descriptive here; no new matching or threshold is invented.\n\n## NOT GENERATED\nThe period×infrastructure interaction is not generated in this run because the cached event table does not carry a separately auditable, frozen paired POWER/CONTROL opportunity registry for this stage. This prevents a post-hoc interaction analysis.\n""",encoding='utf-8')
    (methods/'PRE_REGISTERED_ANALYSIS_PLAN.md').write_text("""# Pre-registered analysis plan\n\nPrimary hypothesis: higher continuous power-window availability is positively associated with CAIDA ITDK 2024-08 transit (`T`) evidence. Primary effect: binomial GEE log-odds per unit availability, /24 exchangeable cluster. Deciles are descriptive only.\n\nNo stable-IP, support, discovery, holdout, availability or AUC cutoffs are used. Equal availability values receive the same deterministic percentile rank.\n\nNormal availability is an explicit comparison, not a replacement primary outcome. ITDK 2024-02/2025-03, router membership and own traceroute are robustness/secondary validation. No H1-H4 or prior outcome is read.\n""",encoding='utf-8')
    (methods/'REFERENCES.bib').write_text("""@inproceedings{bhagwan2003availability,title={Understanding Availability},author={Bhagwan, Ranjita and Savage, Stefan and Voelker, Geoffrey M.},booktitle={IPTPS},year={2003},url={https://cseweb.ucsd.edu/~voelker/pubs/avail-iptps03.pdf}}\n@article{liang1986longitudinal,title={Longitudinal data analysis using generalized linear models},author={Liang, Kung-Yee and Zeger, Scott L.},journal={Biometrika},volume={73},number={1},pages={13--22},year={1986},doi={10.1093/biomet/73.1.13}}\n@article{brown2001interval,title={Interval Estimation for a Binomial Proportion},author={Brown, Lawrence D. and Cai, Tony T. and DasGupta, Anirban},journal={Statistical Science},year={2001},doi={10.1214/ss/1009213286}}\n@article{hanley1982meaning,title={The meaning and use of the area under a ROC curve},author={Hanley, James A. and McNeil, B. J.},journal={Radiology},year={1982},doi={10.1148/radiology.143.1.7063747}}\n@article{saito2015precision,title={The precision-recall plot is more informative than the ROC plot when evaluating binary classifiers on imbalanced datasets},author={Saito, T. and Rehmsmeier, M.},journal={PLoS ONE},year={2015},doi={10.1371/journal.pone.0118432}}\n@article{anderson2023powerping,title={PowerPing: Measuring the Impact of Power Outages on Internet Hosts in the US},author={Anderson, Scott and Bell, Tucker and Egan, Patrick and Weinshenker, Nathan and Barford, Paul},year={2023},url={https://pages.cs.wisc.edu/~pb/PowerPing.pdf}}\n""",encoding='utf-8')
    (methods/'VARIABLE_DICTIONARY.md').write_text("""# Variable dictionary\n\n`power_availability`: power_responsive_count / power_valid_probe_count. `normal_availability`: analogous matched-control ratio. `itdk_202408_T`: CAIDA ITDK 2024-08 Interfaces T flag; 0 means no observed T evidence, not proof of non-infrastructure. `itdk_*_router`: router membership. `own_traceroute_intermediate`: observed as an intermediate IPv4 in the project's traceroute campaign. `power_decile_oblast` and `power_decile_nationwide`: descriptive deterministic percentile deciles; not eligibility thresholds.\n""",encoding='utf-8')
    prov=[]
    for f in sorted((out/'figures').glob('*/*.png')):
        prov.append({"figure":f.stem,"input":"ip_power_availability_master.parquet / TABLE_*","x":"figure-specific","y":"figure-specific","filter":"valid mapped IPs; no stable/support cutoff","ci":"Wilson or /24 cluster bootstrap where applicable","source_script":"power_availability_infrastructure_v1.py"})
    pd.DataFrame(prov).to_csv(out/'methods/FIGURE_PROVENANCE.csv',index=False)
    (out/'methods/FIGURE_PROVENANCE.md').write_text("# Figure provenance\n\nThe CSV next to this file records each bilingual figure's input, transformation, interval method and source script. English and Chinese files are rendered from the same table and plotting arrays.\n",encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='/home/wsl/XiaoLunWen_doc_complete_20260908'); ap.add_argument('--dry-run',action='store_true'); ap.add_argument('--full',action='store_true'); ap.add_argument('--rerender',action='store_true'); args=ap.parse_args()
    root=Path(args.root); out=root/'power_availability_infrastructure_v1';
    if out.exists() and args.full: shutil.rmtree(out)
    for d in ['methods','data','tables','figures/zh','figures/en','logs','scripts','outputs']: (out/d).mkdir(parents=True,exist_ok=True)
    if args.rerender:
        m=pd.read_parquet(out/'data/ip_power_availability_master.parquet'); tab1=pd.read_csv(out/'tables/TABLE_01_decile_enrichment.csv'); tab2=pd.read_csv(out/'tables/TABLE_02_auc_by_oblast.csv'); make_figures(m,tab1,tab2,out); print(json.dumps({"status":"RERENDER_PASS","n_figures":len(list((out/'figures').glob('*/*.png')))})); return
    target,sched,ev,ca,own=load_inputs(root)
    if args.dry_run:
        small=target.sample(min(10000,len(target)),random_state=RNG_SEED); small=small[small.oblast.isin(small.oblast.unique()[:3])]
        pd.DataFrame({"test":"dry_run","target_rows":len(small),"event_rows":min(1000,len(ev)),"caida_rows":len(ca),"own_trace_ips":len(own),"status":"PASS_PIPELINE_SCHEMA_PATHS"},index=[0]).to_csv(out/'logs/dry_run.csv',index=False)
        print(json.dumps({"status":"DRY_RUN_PASS","target_subset":len(small),"event_cache_rows":len(ev)},ensure_ascii=False)); return
    m,audit=build_master(root,out,target,sched,ev,ca,own)
    tab1,tab2,model_status=tables_and_models(m,out)
    make_figures(m,tab1,tab2,out); write_docs(out,audit,model_status)
    # Input/output hashes and run summary.
    inputs=[root/'config/planned_outage_schedule_v4_0.csv',root/'runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet',root/'runs/paper_final_v2_episode_fix_20260910/data_derived/target_ip_universe.parquet',Path('/home/caida_ukraine_validation/ukraine_filtered/caida_infrastructure_evidence.parquet')]
    (out/'methods/INPUT_MANIFEST_SHA256.txt').write_text('\n'.join(f'{sha256(p)}  {p}' for p in inputs if p.exists())+'\n',encoding='utf-8')
    files=[p for p in out.rglob('*') if p.is_file() and p.name!='OUTPUT_MANIFEST_SHA256.txt']; (out/'methods/OUTPUT_MANIFEST_SHA256.txt').write_text('\n'.join(f'{sha256(p)}  {p.relative_to(out)}' for p in files)+'\n',encoding='utf-8')
    release_counts = {r: int(m["itdk_" + r.replace("-", "") + "_T"].sum()) for r in RELEASES}
    summary={"status":"FULL_RUN_COMPLETE","n_states":int(m.oblast.nunique()),"n_ips":int(m.ip.nunique()),"power_rows":int(m.power_valid_probe_count.sum()),"normal_rows":int(m.normal_valid_probe_count.sum()),"itdk_202408_T_positive":int(m.itdk_202408_T.sum()),"itdk_202408_T_prevalence":float(m.itdk_202408_T.mean()),"router_202408_positive":int(m.itdk_202408_router.sum()),"releases":release_counts,"primary_model":model_status,"git_head":os.popen(f'git -C {root} rev-parse HEAD').read().strip()}
    (out/'outputs/FINAL_SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
