"""H3: Activity-conditional external validity of frozen Sensitivity labels.

H3 consumes the frozen H2 endpoint panels and the Stage-2 frozen Activity
deciles.  It does not re-estimate Sensitivity, Activity, war outcomes, or
event definitions.  All reported associations are conditional/descriptive,
not causal effects.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

CORE_EVENTS = ["E2024_0826_ATTACK", "E2024_0917_SUMY", "E2024_1117_ATTACK", "E2024_1128_ATTACK", "E2024_1213_ATTACK", "E2024_1225_ATTACK"]
QUINTILES = ["Q1", "Q2", "Q3", "Q4", "Q5"]
DECILES = [f"D{i}" for i in range(1, 11)]
SEED = 20260910
PANELS = {"MAIN": "h2_ip_level_main.parquet", "A": "h2_ip_level_a.parquet", "B": "h2_ip_level_b.parquet", "C": "h2_ip_level_c.parquet", "D": "h2_ip_level_d.parquet"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def load_panel(h2_dir: Path, h1_dir: Path, fname: str) -> pd.DataFrame:
    x = pd.read_parquet(h2_dir / fname)
    x = x[x.event_id.isin(CORE_EVENTS)].copy()
    # H1 is the frozen source for Activity D1--D10.  Never recreate deciles
    # from outcomes here; take the registered label and de-duplicate by IP.
    ad = pd.read_parquet(h1_dir / "h1_ip_level_outcomes.parquet", columns=["dst_ip", "activity_decile"])
    ad = ad.drop_duplicates("dst_ip")
    x = x.drop(columns=["activity_decile"], errors="ignore").merge(ad, on="dst_ip", how="left", validate="many_to_one")
    x = x[x.activity_decile.isin(DECILES)].copy()
    x["reach_drop"] = pd.to_numeric(x["reach_drop"], errors="coerce")
    x = x[x.reach_drop.notna() & x.sensitivity.notna()]
    return x


def _metrics(g: pd.DataFrame) -> dict:
    y = g.reach_drop.to_numpy(dtype=float)
    return {"n": int(len(y)), "mean": float(np.mean(y)), "median": float(np.median(y)),
            "severe025": float(np.mean(y >= .25)), "severe050": float(np.mean(y >= .50))}


def strata(x: pd.DataFrame, bin_col: str = "activity_decile") -> pd.DataFrame:
    rows = []
    for (e, s, d, q), g in x.groupby(["event_id", "target_admin1", bin_col, "quintile"], observed=True):
        m = _metrics(g)
        m.update({"event_id": e, "target_admin1": s, "activity_bin": d, "quintile": q,
                  "activity_mean": float(g.activity_score_smoothed.mean()), "activity_median": float(g.activity_score_smoothed.median()),
                  "sensitivity_mean": float(g.sensitivity.mean())})
        rows.append(m)
    return pd.DataFrame(rows)


def _state_level(se: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Equal-weight valid Activity strata within each state/event."""
    if se.empty:
        return pd.DataFrame(), pd.DataFrame()
    st = se.groupby(["event_id", "target_admin1", "quintile"], observed=True).agg(
        n=("n", "sum"), mean=("mean", "mean"), median=("median", "mean"), severe025=("severe025", "mean"), severe050=("severe050", "mean"),
        activity_mean=("activity_mean", "mean"), activity_median=("activity_median", "mean"), strata_n=("n", "size")).reset_index()
    rows = []
    for (e, s), g in st.groupby(["event_id", "target_admin1"], observed=True):
        m = g.set_index("quintile")
        if not set(["Q1", "Q5"]).issubset(m.index):
            continue
        q1, q5 = m.loc["Q1"], m.loc["Q5"]
        rows.append({"event_id": e, "target_admin1": s, "q1_mean": q1["mean"], "q5_mean": q5["mean"], "q5_q1_effect": q5["mean"] - q1["mean"],
                     "q1_median": q1["median"], "q5_median": q5["median"], "q5_q1_median_effect": q5["median"] - q1["median"],
                     "q1_severe025": q1["severe025"], "q5_severe025": q5["severe025"], "q1_severe050": q1["severe050"], "q5_severe050": q5["severe050"],
                     "severe_rr025": q5["severe025"] / q1["severe025"] if q1["severe025"] > 0 else np.nan,
                     "severe_rr050": q5["severe050"] / q1["severe050"] if q1["severe050"] > 0 else np.nan})
    return st, pd.DataFrame(rows)


def _event_summary(st: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if st.empty:
        return pd.DataFrame(), pd.DataFrame()
    q = st.groupby(["event_id", "quintile"], observed=True).agg(mean=("mean", "mean"), median=("median", "mean"), severe025=("severe025", "mean"), severe050=("severe050", "mean"), state_n=("mean", "size")).reset_index()
    e = []
    for event, g in st.groupby("event_id"):
        q1, q5 = g.iloc[0:0], g.iloc[0:0]
        # st is event/state/q; pivot keeps state equality explicit.
        w = g.pivot(index="target_admin1", columns="quintile", values=["mean", "median", "severe025", "severe050"])
        if not all((col in w.columns) for col in [("mean","Q1"),("mean","Q5")]): continue
        a = w["mean"]; md=w["median"]; r25=w["severe025"]; r50=w["severe050"]
        q1m,q5m=a["Q1"].mean(),a["Q5"].mean(); q1med,q5med=md["Q1"].mean(),md["Q5"].mean()
        p1,p5=r25["Q1"].mean(),r25["Q5"].mean(); s1,s5=r50["Q1"].mean(),r50["Q5"].mean()
        eff=q5m-q1m
        e.append({"event_id":event,"q1_mean_drop":q1m,"q5_mean_drop":q5m,"q5_q1_mean_effect":eff,"q1_median_drop":q1med,"q5_median_drop":q5med,"q5_q1_median_effect":q5med-q1med,
                  "q1_severe025":p1,"q5_severe025":p5,"severe_rr025":p5/p1 if p1>0 else np.nan,"q1_severe050":s1,"q5_severe050":s5,"severe_rr050":s5/s1 if s1>0 else np.nan,"state_n":len(w)})
    return q, pd.DataFrame(e)


def bootstrap_effect(st: pd.DataFrame, n_boot=1000):
    rng=np.random.default_rng(SEED); w=st.pivot_table(index=["event_id","target_admin1"],columns="quintile",values="mean").dropna(subset=["Q1","Q5"])
    if w.empty:return np.nan,np.nan,np.nan
    ev=list(w.index.get_level_values(0).unique()); obs=float(w.assign(e=w.Q5-w.Q1).groupby(level=0).e.mean().mean()); vals=[]
    for _ in range(n_boot):
        es=rng.choice(ev,len(ev),replace=True); z=[]
        for e in es:
            g=w.xs(e,level=0); idx=rng.integers(0,len(g),len(g)); z.append(float((g.iloc[idx]["Q5"]-g.iloc[idx]["Q1"]).mean()))
        vals.append(np.mean(z))
    return obs,float(np.quantile(vals,.025)),float(np.quantile(vals,.975))


def bootstrap_rr(st: pd.DataFrame, n_boot=1000):
    rng=np.random.default_rng(SEED+31); w=st.pivot_table(index=["event_id","target_admin1"],columns="quintile",values="severe025").dropna(subset=["Q1","Q5"])
    if w.empty:return np.nan,np.nan,np.nan
    ev=list(w.index.get_level_values(0).unique());
    def f(z):
        den=z.groupby(level=0).Q1.mean().mean(); num=z.groupby(level=0).Q5.mean().mean(); return num/den if den>0 else np.nan
    obs=f(w); vals=[]
    for _ in range(n_boot):
        es=rng.choice(ev,len(ev),replace=True); parts=[]
        for e in es:
            g=w.xs(e,level=0); parts.append(g.iloc[rng.integers(0,len(g),len(g))])
        vals.append(f(pd.concat(parts,keys=range(len(parts)),names=["eb","sb"])))
    vals=np.asarray(vals); vals=vals[np.isfinite(vals)]; return obs,float(np.quantile(vals,.025)),float(np.quantile(vals,.975))


def partial_spearman(x: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for (e,s),g in x.groupby(["event_id","target_admin1"]):
        if len(g)<5 or g.sensitivity.nunique()<2 or g.reach_drop.nunique()<2 or g.activity_score_smoothed.nunique()<2:
            rho=np.nan
        else:
            rS=g.sensitivity.rank(method="average").to_numpy(float); rY=g.reach_drop.rank(method="average").to_numpy(float); rA=g.activity_score_smoothed.rank(method="average").to_numpy(float)
            z=np.column_stack([np.ones(len(g)),rA]); bx=np.linalg.lstsq(z,rS,rcond=None)[0]; by=np.linalg.lstsq(z,rY,rcond=None)[0]
            rx=rS-z@bx; ry=rY-z@by; rho=float(np.corrcoef(rx,ry)[0,1]) if np.std(rx)>0 and np.std(ry)>0 else np.nan
        rows.append({"event_id":e,"target_admin1":s,"valid_ip_n":len(g),"partial_spearman":rho})
    out=pd.DataFrame(rows)
    if not out.empty:
        out=pd.concat([out,pd.DataFrame([{"event_id":"EVENT_EQUAL","target_admin1":"ALL","valid_ip_n":out.valid_ip_n.sum(),"partial_spearman":out.groupby("event_id").partial_spearman.mean().mean()},{"event_id":"STATE_EQUAL","target_admin1":"ALL","valid_ip_n":out.valid_ip_n.sum(),"partial_spearman":out.partial_spearman.mean()}])],ignore_index=True)
    return out


def activity20(x: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    ip=x[["dst_ip","target_admin1","activity_score_smoothed"]].drop_duplicates("dst_ip").copy(); ip["activity20"]=pd.NA
    for s,g in ip.groupby("target_admin1"):
        z=g.sort_values(["activity_score_smoothed","dst_ip"],kind="mergesort"); pos=np.arange(len(z)); ip.loc[z.index,"activity20"]=[f"B{i+1}" for i in np.minimum(19,(pos*20//len(z)).astype(int))]
    y=x.merge(ip[["dst_ip","activity20"]],on="dst_ip",how="left",validate="many_to_one")
    se=strata(y,"activity20"); st,e=_state_level(se); q,ev=_event_summary(st)
    return st,e


def figsave(fig,path:Path):
    fig.savefig(path.with_suffix(".png"),dpi=220,bbox_inches="tight"); fig.savefig(path.with_suffix(".pdf"),bbox_inches="tight"); fig.savefig(path.with_suffix(".svg"),bbox_inches="tight"); plt.close(fig)


def figures(out:Path, q:pd.DataFrame, events:pd.DataFrame, partial:pd.DataFrame, state_eff:pd.DataFrame, h2_eff:float, h3_eff:float):
    fd=out/"figures"; fd.mkdir(parents=True,exist_ok=True)
    # H3-1
    m=q.groupby("quintile",observed=True).mean(numeric_only=True).reindex(QUINTILES); ci=q.groupby("quintile",observed=True)["mean"].quantile([.025,.975]).unstack(); fig,ax=plt.subplots(figsize=(6.5,4.2)); ax.plot(QUINTILES,m["mean"],marker="o",lw=2,color="#2166ac"); ax.fill_between(np.arange(5),ci.reindex(QUINTILES)[.025],ci.reindex(QUINTILES)[.975],color="#9ecae1",alpha=.35,label="event-level 95% interval"); ax.axhline(0,color="0.35",lw=.8); ax.set(xlabel="Frozen Sensitivity quintile",ylabel="Activity-adjusted reach drop",title="Within-Activity reach loss across Sensitivity quintiles"); ax.legend(frameon=False,fontsize=8); ax.grid(axis="y",alpha=.2); fig.tight_layout(); figsave(fig,fd/"H3-1_adjusted_gradient")
    # H3-2
    fig,ax=plt.subplots(figsize=(5.7,4.0)); ax.axhline(0,color="0.35",lw=.8); ax.bar([0,1],[h2_eff,h3_eff],color=["#bdbdbd","#2166ac"],tick_label=["H2\nunadjusted","H3\nActivity-adjusted"]); ax.set_ylabel("Q5 − Q1 mean reach-drop"); ax.set_title("Activity adjustment changes the Q5 − Q1 association"); ax.grid(axis="y",alpha=.2); fig.tight_layout(); figsave(fig,fd/"H3-2_h2_vs_h3")
    # H3-3
    e=events.sort_values("event_id"); y=np.arange(len(e)); fig,ax=plt.subplots(figsize=(7,4.2)); lo=np.maximum(0,e.q5_q1_mean_effect-e.ci_low); hi=np.maximum(0,e.ci_high-e.q5_q1_mean_effect); ax.axvline(0,color="0.35",lw=.8); ax.errorbar(e.q5_q1_mean_effect,y,xerr=np.vstack([lo,hi]),fmt="o",color="#b2182b",capsize=3); ax.set_yticks(y,e.event_id); ax.set_xlabel("Activity-adjusted Q5 − Q1 reach-drop"); ax.set_title("Activity-adjusted effect by held-out attack (95% CI)"); ax.grid(axis="x",alpha=.2); fig.tight_layout(); figsave(fig,fd/"H3-3_event_effects")
    # H3-4
    h=q.pivot_table(index="event_id",columns="quintile",values="mean",aggfunc="mean").reindex(columns=QUINTILES); fig,ax=plt.subplots(figsize=(7.5,4.2)); im=ax.imshow(h.to_numpy(),aspect="auto",cmap="RdBu_r",vmin=np.nanmin(h),vmax=np.nanmax(h)); ax.set_xticks(range(5),QUINTILES); ax.set_yticks(range(len(h)),h.index); ax.set_xlabel("Sensitivity quintile"); ax.set_title("Activity-adjusted reach drop by attack and Sensitivity quintile"); fig.colorbar(im,ax=ax,label="Adjusted reach drop"); fig.tight_layout(); figsave(fig,fd/"H3-4_event_quintile_heatmap")
    # H3-5
    p=partial[partial.event_id.isin(CORE_EVENTS)].copy(); p=p.groupby("event_id").partial_spearman.mean().reindex(CORE_EVENTS); fig,ax=plt.subplots(figsize=(7,4)); ax.axhline(0,color="0.35",lw=.8); ax.bar(np.arange(len(p)),p.to_numpy(),color="#762a83"); ax.set_xticks(range(len(p)),[e.replace("E2024_","24-") for e in p.index],rotation=35,ha="right"); ax.set_ylabel("Partial Spearman ρ"); ax.set_title("Continuous Sensitivity association after Activity adjustment"); ax.grid(axis="y",alpha=.2); fig.tight_layout(); figsave(fig,fd/"H3-5_partial_spearman")
    # H3-6
    vals=state_eff.q5_q1_effect.dropna().to_numpy(); fig,ax=plt.subplots(figsize=(6.2,4)); ax.hist(vals,bins=min(20,max(5,len(vals)//3)),color="#4393c3",edgecolor="white"); ax.axvline(0,color="0.35",lw=.8); ax.set(xlabel="State-event Activity-adjusted Q5 − Q1 effect",ylabel="State-event count",title="State-event effect distribution"); ax.grid(axis="y",alpha=.2); fig.tight_layout(); figsave(fig,fd/"H3-6_state_event_effect_distribution")


def report(out:Path, main:pd.DataFrame, events:pd.DataFrame, partial:pd.DataFrame, robust:pd.DataFrame, comparison:pd.DataFrame, state_eff:pd.DataFrame, verdict:str):
    lines=["# H3 Activity-Conditional Sensitivity Report","", "H3 reuses frozen H1 outcomes, frozen Stage-2 Activity deciles, and frozen Stage-4/4.5 Sensitivity labels. It estimates conditional association, not causation; H4 was not run.","", "## Main panel", f"- Valid endpoint rows: **{len(main):,}**; unique IPs: **{main.dst_ip.nunique():,}**; states: **{main.target_admin1.nunique()}**; events: **{main.event_id.nunique()}**.", f"- H2 unadjusted Q5−Q1: **{comparison.h2_effect.iloc[0]:.4f}**; H3 Activity-adjusted: **{comparison.h3_effect.iloc[0]:.4f}**; retained: **{comparison.retained_pct.iloc[0]:.1f}%**.", f"- Adjusted Q5/Q1 severe-drop RR: **{comparison.h3_rr025.iloc[0]:.3f}** (95% CI {comparison.h3_rr025_low.iloc[0]:.3f}, {comparison.h3_rr025_high.iloc[0]:.3f}).", f"- Q5 > Q1 in **{int((events.direction=='POSITIVE').sum())}/{len(events)}** events; event-equal partial Spearman: **{partial.loc[partial.event_id.eq('EVENT_EQUAL'),'partial_spearman'].iloc[0]:.4f}**.","", "## Event consistency", "", "```", events.to_string(index=False), "```", "", "## Frozen robustness", "", "```", robust.to_string(index=False), "```", "", "## State-event consistency", f"Positive: **{int((state_eff.q5_q1_effect>0).sum())}**; negative: **{int((state_eff.q5_q1_effect<0).sum())}**; near zero: **{int((state_eff.q5_q1_effect.abs()<=1e-12).sum())}**.","", "## H3 verdict", f"**{verdict}**", "", "The verdict uses effect size, cluster bootstrap intervals, event/state consistency, partial association, and frozen robustness—not IP-level naive p-values. Activity was not hard-filtered and pre-attack reach was not controlled in the main analysis.", "", "H4 was not run; no freeze, event registry, outcome definition, Activity, or Sensitivity label was modified.", ""]
    (out/"H3_ACTIVITY_CONDITIONAL_SENSITIVITY_REPORT.md").write_text("\n".join(lines),encoding="utf-8")


def run(run_id:str,root:Path,h2_dir:Path,h1_dir:Path,stage2_manifest:Path,stage45_manifest:Path,h1_manifest:Path,h2_manifest:Path,git_commit:str):
    out=root/"runs"/run_id/"results"/"stages"/"stage_h3_activity_conditional_sensitivity"; out.mkdir(parents=True,exist_ok=True)
    panels={k:load_panel(h2_dir,h1_dir,f) for k,f in PANELS.items()}
    main=panels["MAIN"]; se=strata(main); st, state_eff=_state_level(se); q, events0=_event_summary(st); partial=partial_spearman(main)
    ci=bootstrap_effect(st); rr=bootstrap_rr(st); events=events0.copy(); events["ci_low"]=np.nan; events["ci_high"]=np.nan
    rng=np.random.default_rng(SEED+99)
    for i,row in events.iterrows():
        g=st[st.event_id.eq(row.event_id)].pivot_table(index="target_admin1",columns="quintile",values="mean").dropna(subset=["Q1","Q5"]); vals=[]
        for _ in range(1000):
            z=g.iloc[rng.integers(0,len(g),len(g))]; vals.append(float((z.Q5-z.Q1).mean()))
        events.loc[i,"ci_low"]=np.quantile(vals,.025); events.loc[i,"ci_high"]=np.quantile(vals,.975)
    events["direction"]=np.where(events.q5_q1_mean_effect>1e-12,"POSITIVE",np.where(events.q5_q1_mean_effect< -1e-12,"NEGATIVE","NEUTRAL"))
    se.to_csv(out/"h3_stratum_summary.csv",index=False); st.to_csv(out/"h3_state_level_summary.csv",index=False); q.to_csv(out/"h3_main_adjusted_quintile_summary.csv",index=False); events.to_csv(out/"h3_event_adjusted_effects.csv",index=False); state_eff.to_csv(out/"h3_state_event_adjusted_effects.csv",index=False); partial.to_csv(out/"h3_partial_spearman.csv",index=False)
    h2eff=pd.read_csv(h2_dir/"h2_event_effects.csv"); h2_effect=float(h2eff.q5_q1_mean_effect.mean()); h2_panel=panels["MAIN"].copy(); h2_un= h2_effect
    h2rr=(h2_panel.assign(sev=h2_panel.reach_drop>=.25).groupby(["event_id","target_admin1","quintile"],observed=True).sev.mean().reset_index().pivot_table(index=["event_id","target_admin1"],columns="quintile",values="sev").dropna(subset=["Q1","Q5"])); h2rrv=float((h2rr.groupby(level=0).Q5.mean().mean()/h2rr.groupby(level=0).Q1.mean().mean()))
    h3_effect=ci[0]; retained=100*h3_effect/h2_un if h2_un else np.nan
    comparison=pd.DataFrame({"h2_effect":[h2_un],"h3_effect":[h3_effect],"retained_pct":[retained],"h2_rr025":[h2rrv],"h3_rr025":[rr[0]],"h3_rr025_low":[rr[1]],"h3_rr025_high":[rr[2]]}); comparison.to_csv(out/"h3_h2_vs_h3_comparison.csv",index=False)
    rrows=[]
    for k,z in panels.items():
        if k=="MAIN": continue
        sz=strata(z); zz,ee=_state_level(sz); qq,ev=_event_summary(zz); c=bootstrap_effect(zz); r=bootstrap_rr(zz); ps=partial_spearman(z); rrows.append({"panel":k,"valid_endpoint_rows":len(z),"valid_ip_n":z.dst_ip.nunique(),"state_n":z.target_admin1.nunique(),"event_n":z.event_id.nunique(),"adjusted_effect":c[0],"ci_low":c[1],"ci_high":c[2],"severe_rr025":r[0],"severe_rr025_low":r[1],"severe_rr025_high":r[2],"event_equal_partial_spearman":ps.loc[ps.event_id.eq('EVENT_EQUAL'),'partial_spearman'].iloc[0] if any(ps.event_id.eq('EVENT_EQUAL')) else np.nan,"positive_event_n":int((ev.q5_q1_effect>0).sum()),"event_direction_n":len(ev)})
    robust=pd.DataFrame(rrows); robust.to_csv(out/"h3_frozen_panel_robustness.csv",index=False)
    _,a20=activity20(main); a20.to_csv(out/"h3_activity20_robustness.csv",index=False)
    figures(out,q,events,partial,state_eff,h2_un,h3_effect)
    # Conservative verdict: non-monotonic or mixed events are partial even if effect remains positive.
    qm=q.set_index("quintile").reindex(QUINTILES)["mean"]; monotonic=bool(np.all(np.diff(qm.dropna().to_numpy())>=-1e-12)) if qm.notna().all() else False; pos=int((events.direction=="POSITIVE").sum()); rho=float(partial.loc[partial.event_id.eq('EVENT_EQUAL'),'partial_spearman'].iloc[0])
    robust_pos=int((robust.adjusted_effect>0).sum())
    verdict="SUPPORTED" if h3_effect>0 and ci[1]>0 and pos>=4 and rho>0 and robust_pos>=3 and monotonic else ("PARTIALLY_SUPPORTED" if h3_effect>0 and pos>=3 and robust_pos>=2 else "NOT_SUPPORTED")
    report(out,main,events,partial,robust,comparison,state_eff,verdict)
    for k,z in panels.items(): z.to_parquet(out/f"h3_ip_level_{k.lower()}.parquet",index=False)
    def meta(p): return {"path":str(p),"sha256":sha256(p)} if p.exists() else {"path":str(p),"sha256":None}
    manifest={"stage":"H3_ACTIVITY_CONDITIONAL_SENSITIVITY","run_id":run_id,"git_commit":git_commit,"random_seed":SEED,"main_panel":"AUGMENTED_STRICT_SUPPORT3","main_expected_sensitivity_population":{"ip_n":700012,"state_n":17},"main_valid_ip_n":int(main.dst_ip.nunique()),"main_valid_state_n":int(main.target_admin1.nunique()),"h2_unadjusted_effect":h2_un,"h3_adjusted_effect":h3_effect,"h3_verdict":verdict,"artifacts":{"stage2_manifest":meta(stage2_manifest),"stage45_manifest":meta(stage45_manifest),"h1_manifest":meta(h1_manifest),"h2_manifest":meta(h2_manifest)},"war_event_registry_version":"frozen_core_6_heldout_attacks","h4_run":False,"h1_h2_rerun":False}
    (out/"h3_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return {"output_dir":str(out),"verdict":verdict,"main_ip_n":int(main.dst_ip.nunique()),"main_state_n":int(main.target_admin1.nunique()),"h3_effect":h3_effect,"ci":ci,"rr":rr,"events":events.to_dict("records"),"manifest":manifest}


def main(argv=None):
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--run-id",default="h3_activity_conditional_sensitivity_20260910"); ap.add_argument("--root",default="/home/wsl/XiaoLunWen_doc_complete_20260908"); ap.add_argument("--h2-dir",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/h2_sensitivity_external_validity_20260910/results/stages/stage_h2_sensitivity_external_validity"); ap.add_argument("--h1-dir",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity"); ap.add_argument("--stage2-manifest",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity/stage_manifest.json"); ap.add_argument("--stage45-manifest",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/stage4_5_label_robustness_20260910/results/stages/stage04_5_label_robustness/stage4_5_manifest.json"); ap.add_argument("--h1-manifest",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/h1_manifest.json"); ap.add_argument("--h2-manifest",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/h2_sensitivity_external_validity_20260910/results/stages/stage_h2_sensitivity_external_validity/h2_manifest.json"); ap.add_argument("--git-commit",default=os.environ.get("GIT_COMMIT","unknown")); a=ap.parse_args(); print(json.dumps(run(a.run_id,Path(a.root),Path(a.h2_dir),Path(a.h1_dir),Path(a.stage2_manifest),Path(a.stage45_manifest),Path(a.h1_manifest),Path(a.h2_manifest),a.git_commit),indent=2,default=str))

if __name__ == "__main__": main()
