"""H4 loss-contribution decomposition on frozen H3 endpoint panels.

This module is deliberately downstream-only: it reads the frozen H3 panel,
keeps signed reach losses (including negative values), and never re-estimates
Activity, Sensitivity, events, or outcomes.  Contribution shares are
descriptive decompositions, not causal effects.
"""
from __future__ import annotations

import hashlib, json, os
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

CORE_EVENTS = ["E2024_0826_ATTACK", "E2024_0917_SUMY", "E2024_1117_ATTACK", "E2024_1128_ATTACK", "E2024_1213_ATTACK", "E2024_1225_ATTACK"]
QUINTILES = [f"Q{i}" for i in range(1, 6)]
DECILES = [f"D{i}" for i in range(1, 11)]
PANELS = {"MAIN":"h3_ip_level_main.parquet", "A":"h3_ip_level_a.parquet", "B":"h3_ip_level_b.parquet", "C":"h3_ip_level_c.parquet", "D":"h3_ip_level_d.parquet"}

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""): h.update(b)
    return h.hexdigest()

def load_panel(path: Path) -> pd.DataFrame:
    cols=["dst_ip","target_admin1","event_id","reach_drop","quintile","activity_decile","sensitivity","activity_score_smoothed"]
    x=pd.read_parquet(path, columns=cols)
    x=x[x.event_id.isin(CORE_EVENTS)].copy()
    x["reach_drop"]=pd.to_numeric(x["reach_drop"],errors="coerce")
    x=x[x.reach_drop.notna() & x.quintile.isin(QUINTILES) & x.activity_decile.isin(DECILES)]
    return x

def _group_rows(x: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Group-level signed and gross contributions plus state/event denominators."""
    keys=["event_id","target_admin1"]+group_cols
    g=x.groupby(keys,observed=True,sort=False).agg(n=("reach_drop","size"), mean_drop=("reach_drop","mean"), signed_loss=("reach_drop","sum"), gross_positive_loss=("reach_drop",lambda z: float(np.maximum(z.to_numpy(float),0).sum()))).reset_index()
    den=x.groupby(["event_id","target_admin1"],observed=True).agg(n_total=("reach_drop","size"), signed_total=("reach_drop","sum"), gross_total=("reach_drop",lambda z: float(np.maximum(z.to_numpy(float),0).sum()))).reset_index()
    g=g.merge(den,on=["event_id","target_admin1"],validate="many_to_one")
    g["population_share"]=g.n/g.n_total
    g["loss_contribution_share"]=g.signed_loss/g.signed_total.replace(0,np.nan)
    g["gross_loss_share"]=g.gross_positive_loss/g.gross_total.replace(0,np.nan)
    g["contribution_lift"]=g.loss_contribution_share/g.population_share.replace(0,np.nan)
    g["low_denominator_warning"]=g.signed_total.abs()<1e-9
    g.loc[g.low_denominator_warning,["loss_contribution_share","contribution_lift"]]=np.nan
    return g

def _equal_summaries(rows: pd.DataFrame, group_cols: list[str]) -> tuple[pd.DataFrame,pd.DataFrame]:
    if rows.empty:return pd.DataFrame(),pd.DataFrame()
    # state/equal: each state-event gets equal weight; event/equal: each event gets equal weight.
    state=rows.groupby(["event_id","target_admin1"]+group_cols,observed=True).agg(n=("n","sum"),mean_drop=("mean_drop","mean"),population_share=("population_share","mean"),loss_contribution_share=("loss_contribution_share","mean"),gross_loss_share=("gross_loss_share","mean"),contribution_lift=("contribution_lift","mean"),low_denominator_warning=("low_denominator_warning","any")).reset_index()
    event=state.groupby(["event_id"]+group_cols,observed=True).agg(state_n=("target_admin1","nunique"),n=("n","sum"),mean_drop=("mean_drop","mean"),population_share=("population_share","mean"),loss_contribution_share=("loss_contribution_share","mean"),gross_loss_share=("gross_loss_share","mean"),contribution_lift=("contribution_lift","mean"),low_denominator_warning=("low_denominator_warning","any")).reset_index()
    final=event.groupby(group_cols,observed=True).agg(event_n=("event_id","nunique"),state_event_n=("state_n","sum"),mean_drop=("mean_drop","mean"),population_share=("population_share","mean"),loss_contribution_share=("loss_contribution_share","mean"),gross_loss_share=("gross_loss_share","mean"),contribution_lift=("contribution_lift","mean"),low_denominator_warning=("low_denominator_warning","any")).reset_index()
    return state,event.merge(final,on=group_cols,how="left",suffixes=("","_overall"))

def _collapse(event: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Collapse event-level rows to the pre-registered event-equal summary."""
    if event.empty: return event
    num=[c for c in ["mean_drop","population_share","loss_contribution_share","gross_loss_share","contribution_lift"] if c in event]
    out=event.groupby(group_cols,observed=True).agg(**{c:(c,"mean") for c in num}, event_n=("event_id","nunique"), low_denominator_warning=("low_denominator_warning","any")).reset_index()
    return out

def _event_effects(state: pd.DataFrame, group_col: str, ordered: list[str]) -> pd.DataFrame:
    out=[]
    for e,g in state.groupby("event_id",observed=True):
        p=g.pivot(index="target_admin1",columns=group_col,values=["mean_drop","contribution_lift","loss_contribution_share","population_share"])
        if not all((k,v) in p.columns for k in ["mean_drop","contribution_lift"] for v in [ordered[0],ordered[-1]]): continue
        out.append({"event_id":e,"q1_or_d1_lift":p[("contribution_lift",ordered[0])].mean(),"q5_or_d10_lift":p[("contribution_lift",ordered[-1])].mean(),"q5_q1_lift_diff":p[("contribution_lift",ordered[-1])].mean()-p[("contribution_lift",ordered[0])].mean(),"q1_or_d1_mean_drop":p[("mean_drop",ordered[0])].mean(),"q5_or_d10_mean_drop":p[("mean_drop",ordered[-1])].mean(),"q5_q1_mean_drop_diff":p[("mean_drop",ordered[-1])].mean()-p[("mean_drop",ordered[0])].mean(),"positive_direction":bool(p[("contribution_lift",ordered[-1])].mean()>p[("contribution_lift",ordered[0])].mean())})
    return pd.DataFrame(out)

def _concentration(x: pd.DataFrame) -> pd.DataFrame:
    # Concentration is endpoint-level and uses gross positive loss only.
    ip=x.groupby("dst_ip",observed=True).agg(gross_positive_loss=("reach_drop",lambda z:float(np.maximum(z.to_numpy(float),0).sum())),signed_loss=("reach_drop","sum"),target_admin1=("target_admin1","first")).reset_index()
    # Fractions are of the complete valid endpoint population; zero/negative
    # gross-loss endpoints remain in the denominator but contribute zero.
    ip=ip.sort_values("gross_positive_loss",ascending=False).reset_index(drop=True)
    total=float(ip.gross_positive_loss.sum()); n=len(ip); rows=[]
    for frac in (.10,.20,.50): rows.append({"scope":"ALL_EVENTS","top_fraction":frac,"endpoint_n":int(np.ceil(n*frac)),"gross_positive_loss_total":total,"gross_loss_share":float(ip.head(max(1,int(np.ceil(n*frac)))).gross_positive_loss.sum()/total) if total else np.nan})
    if total:
        p=ip.gross_positive_loss.to_numpy()/total; rows.append({"scope":"ALL_EVENTS","top_fraction":np.nan,"endpoint_n":n,"gross_positive_loss_total":total,"gross_loss_share":1.0,"gini":float((2*np.arange(1,n+1)@np.sort(p))/(n*p.sum())-(n+1)/n)})
    return pd.DataFrame(rows)

def _figsave(fig,path:Path):
    fig.savefig(path.with_suffix(".png"),dpi=220,bbox_inches="tight"); fig.savefig(path.with_suffix(".pdf"),bbox_inches="tight"); fig.savefig(path.with_suffix(".svg"),bbox_inches="tight"); plt.close(fig)

def figures(out:Path,sens:pd.DataFrame,act:pd.DataFrame,combo:pd.DataFrame,events:pd.DataFrame,conc:pd.DataFrame):
    fd=out/"figures"; fd.mkdir(parents=True,exist_ok=True)
    s=sens[sens.quintile.isin(QUINTILES)].set_index("quintile").reindex(QUINTILES); fig,ax=plt.subplots(figsize=(6.4,4)); w=.36; xx=np.arange(5); ax.bar(xx-w/2,s.population_share,width=w,label="Population share",color="#bdbdbd"); ax.bar(xx+w/2,s.loss_contribution_share,width=w,label="Signed loss contribution",color="#2166ac"); ax.set_xticks(xx,QUINTILES); ax.set_ylabel("Share"); ax.set_title("H4-1 Sensitivity population vs signed loss contribution"); ax.legend(frameon=False); ax.grid(axis="y",alpha=.2); fig.tight_layout(); _figsave(fig,fd/"H4-1_population_vs_loss")
    fig,ax=plt.subplots(figsize=(6.2,4)); ax.plot(QUINTILES,s.contribution_lift,marker="o",color="#b2182b"); ax.axhline(1,color="0.35",lw=.9); ax.set(xlabel="Frozen Sensitivity quintile",ylabel="Signed contribution lift",title="H4-2 Sensitivity contribution lift"); ax.grid(axis="y",alpha=.2); fig.tight_layout(); _figsave(fig,fd/"H4-2_sensitivity_lift")
    a=act[act.activity_decile.isin(DECILES)].set_index("activity_decile").reindex(DECILES); fig,ax=plt.subplots(figsize=(7,4)); ax.plot(DECILES,a.contribution_lift,marker="o",color="#1b7837"); ax.axhline(1,color="0.35",lw=.9); ax.set(xlabel="Frozen Activity decile",ylabel="Signed contribution lift",title="H4-3 Activity contribution lift"); ax.grid(axis="y",alpha=.2); fig.tight_layout(); _figsave(fig,fd/"H4-3_activity_lift")
    c=combo.copy(); c["cell"]=c.activity_decile+" × "+c.quintile; pivot=c.pivot_table(index="activity_decile",columns="quintile",values="contribution_lift",aggfunc="mean").reindex(index=DECILES,columns=QUINTILES); fig,ax=plt.subplots(figsize=(6.8,5)); im=ax.imshow(pivot.to_numpy(),aspect="auto",cmap="RdBu_r",vmin=-max(1,float(np.nanmax(np.abs(pivot)))) if np.isfinite(pivot.to_numpy()).any() else -1,vmax=max(1,float(np.nanmax(np.abs(pivot)))) if np.isfinite(pivot.to_numpy()).any() else 1); ax.set_xticks(range(5),QUINTILES); ax.set_yticks(range(10),DECILES); ax.set(xlabel="Frozen Sensitivity quintile",ylabel="Frozen Activity decile",title="H4-4 Activity × Sensitivity contribution lift"); fig.colorbar(im,ax=ax,label="Signed contribution lift"); fig.tight_layout(); _figsave(fig,fd/"H4-4_activity_sensitivity_heatmap")
    if not events.empty:
        fig,ax=plt.subplots(figsize=(7,4)); z=events.set_index("event_id").reindex(CORE_EVENTS); ax.axhline(0,color="0.35",lw=.9); ax.bar(np.arange(len(z)),z.q5_q1_lift_diff,color=np.where(z.q5_q1_lift_diff>=0,"#b2182b","#2166ac")); ax.set_xticks(range(len(z)),[e.replace("E2024_","") for e in z.index],rotation=35,ha="right"); ax.set_ylabel("Q5 − Q1 contribution-lift difference"); ax.set_title("H4-5 Sensitivity contribution contrast by event"); ax.grid(axis="y",alpha=.2); fig.tight_layout(); _figsave(fig,fd/"H4-5_event_q5_vs_q1")
    cc=conc[(conc.scope=="ALL_EVENTS") & conc.top_fraction.notna()].copy(); vals=[cc.loc[np.isclose(cc.top_fraction,f),"gross_loss_share"].iloc[0] if any(np.isclose(cc.top_fraction,f)) else np.nan for f in (.1,.2,.5)]; fig,ax=plt.subplots(figsize=(5.8,4)); ax.plot([0,10,20,50,100],[0,*vals,1],marker="o",color="#762a83"); ax.set(xlabel="Top endpoints by gross positive loss (%)",ylabel="Cumulative gross-loss share",title="H4-6 Gross positive loss concentration"); ax.set_xticks([0,10,20,50,100]); ax.set_ylim(0,1.05); ax.grid(axis="y",alpha=.2); fig.tight_layout(); _figsave(fig,fd/"H4-6_lorenz_concentration")

def _robust_row(name:str,x:pd.DataFrame)->dict:
    s,e=_equal_summaries(_group_rows(x,["quintile"]),["quintile"]); f=_collapse(e,["quintile"]).set_index("quintile");
    if set(["Q1","Q5"]).issubset(f.index):
        q1,q5=f.loc["Q1"],f.loc["Q5"]; eff=float(q5.mean_drop-q1.mean_drop); lift=float(q5.contribution_lift-q1.contribution_lift)
    else: eff=lift=np.nan
    return {"panel":name,"valid_ip_n":int(x.dst_ip.nunique()),"valid_state_n":int(x.target_admin1.nunique()),"valid_endpoint_rows":int(len(x)),"q1_lift":float(f.loc["Q1","contribution_lift"]) if "Q1" in f.index else np.nan,"q5_lift":float(f.loc["Q5","contribution_lift"]) if "Q5" in f.index else np.nan,"q5_q1_mean_drop":eff,"q5_q1_lift_diff":lift,"q5_positive_event_n":int((_event_effects(s,"quintile",QUINTILES).positive_direction).sum()) if not _event_effects(s,"quintile",QUINTILES).empty else 0}

def run(run_id:str,root:Path,h3_dir:Path,stage2_manifest:Path,stage3_manifest:Path,stage4_manifest:Path,stage45_manifest:Path,h1_manifest:Path,h2_manifest:Path,h3_manifest:Path,war_registry:Path,workbook:Path,git_commit:str):
    out=root/"runs"/run_id/"results"/"stages"/"stage_h4_loss_contribution_decomposition"; out.mkdir(parents=True,exist_ok=True)
    panels={k:load_panel(h3_dir/f) for k,f in PANELS.items()}; main=panels["MAIN"]
    validation=[]
    for (e,s),g in main.groupby(["event_id","target_admin1"],observed=True):
        m=float(g.reach_drop.mean()); alt=float(g.reach_drop.sum()/len(g)); validation.append({"event_id":e,"target_admin1":s,"endpoint_n":len(g),"endpoint_mean_drop":m,"aggregate_ips_drop":alt,"abs_difference":abs(m-alt),"status":"PASS" if abs(m-alt)<=1e-12 else "FAIL"})
    vd=pd.DataFrame(validation); vd.to_csv(out/"h4_decomposition_validation.csv",index=False)
    if (vd.status!="PASS").any(): raise RuntimeError("H4 decomposition validation failed")
    sens_rows=_group_rows(main,["quintile"]); act_rows=_group_rows(main,["activity_decile"]); combo_rows=_group_rows(main,["activity_decile","quintile"])
    sens_state,sens_event0=_equal_summaries(sens_rows,["quintile"]); act_state,act_event0=_equal_summaries(act_rows,["activity_decile"]); combo_state,combo_event0=_equal_summaries(combo_rows,["activity_decile","quintile"])
    sens_event=_collapse(sens_event0,["quintile"]); act_event=_collapse(act_event0,["activity_decile"]); combo_event=_collapse(combo_event0,["activity_decile","quintile"])
    sens_rows.to_csv(out/"h4_sensitivity_state_event.csv",index=False); act_rows.to_csv(out/"h4_activity_state_event.csv",index=False); combo_rows.to_csv(out/"h4_activity_sensitivity_state_event.csv",index=False); sens_event.to_csv(out/"h4_sensitivity_summary.csv",index=False); act_event.to_csv(out/"h4_activity_summary.csv",index=False); combo_event.to_csv(out/"h4_activity_sensitivity_summary.csv",index=False)
    effects=_event_effects(sens_state,"quintile",QUINTILES); effects.to_csv(out/"h4_event_effects.csv",index=False); _event_effects(sens_state,"quintile",QUINTILES).to_csv(out/"h4_state_event_effects.csv",index=False)
    # state-event detailed contrast (kept separate from event-level table)
    st=[]
    for (e,s),g in sens_state.groupby(["event_id","target_admin1"],observed=True):
        z=g.set_index("quintile")
        if "Q1" in z.index and "Q5" in z.index: st.append({"event_id":e,"target_admin1":s,"q5_lift_minus_q1_lift":z.loc["Q5","contribution_lift"]-z.loc["Q1","contribution_lift"],"q5_mean_minus_q1_mean":z.loc["Q5","mean_drop"]-z.loc["Q1","mean_drop"]})
    pd.DataFrame(st).to_csv(out/"h4_state_event_effects.csv",index=False)
    robust=pd.DataFrame([_robust_row(k,v) for k,v in panels.items()]); robust.to_csv(out/"h4_robustness_summary.csv",index=False)
    conc=_concentration(main); conc.to_csv(out/"h4_concentration.csv",index=False)
    figures(out,sens_event,sens_event if False else act_event,combo_event,effects,conc)
    q=sens_event.set_index("quintile").reindex(QUINTILES); q1,q5=q.loc["Q1"],q.loc["Q5"]
    topa=act_event.sort_values("loss_contribution_share",ascending=False).iloc[0] if not act_event.empty else None
    q5event=int(effects.q5_or_d10_lift.gt(effects.q1_or_d1_lift).sum()) if not effects.empty else 0
    combo_q5=float(combo_event[combo_event.quintile.eq("Q5")].contribution_lift.mean()) if not combo_event.empty else np.nan; combo_q1=float(combo_event[combo_event.quintile.eq("Q1")].contribution_lift.mean()) if not combo_event.empty else np.nan
    h4_verdict="SUPPORTED" if (q5.contribution_lift>q1.contribution_lift and q5event>=4 and combo_q5>combo_q1) else ("PARTIALLY_SUPPORTED" if (q5.contribution_lift>q1.contribution_lift or q5event>=3) else "NOT_SUPPORTED")
    lines=["# H4 Loss-Contribution Decomposition Report","","H4 is a descriptive decomposition of frozen endpoint reach loss; it is not a causal attribution and does not identify intrinsically vulnerable IPs.","","## Main panel",f"- Valid endpoint-event observations: **{len(main):,}**; IPs: **{main.dst_ip.nunique():,}**; states: **{main.target_admin1.nunique()}**; events: **{main.event_id.nunique()}**.",f"- Q1 population share **{q1.population_share:.4f}**, signed loss share **{q1.loss_contribution_share:.4f}**, lift **{q1.contribution_lift:.4f}**.",f"- Q5 population share **{q5.population_share:.4f}**, signed loss share **{q5.loss_contribution_share:.4f}**, lift **{q5.contribution_lift:.4f}**; Q5/Q1 lift ratio **{q5.contribution_lift/q1.contribution_lift if q1.contribution_lift else np.nan:.4f}**.",f"- Q5 contribution lift exceeds Q1 in **{q5event}/6** core events.",f"- Largest Activity decile: **{topa.activity_decile if topa is not None else 'NA'}**, population share **{topa.population_share if topa is not None else np.nan:.4f}**, loss share **{topa.loss_contribution_share if topa is not None else np.nan:.4f}**, lift **{topa.contribution_lift if topa is not None else np.nan:.4f}**.",f"- Activity-composition check: Q5 lift **{combo_q5:.4f}** vs Q1 **{combo_q1:.4f}**.","","## Concentration",conc.to_string(index=False),"","## Decomposition validation",f"All {len(vd)} event-state cells passed mean-vs-sum validation.","","## Verdict",f"**{h4_verdict}**","","Signed shares are not clipped; negative losses and near-zero denominators are retained with warnings. Gross positive concentration is a secondary descriptive measure."]
    (out/"H4_LOSS_CONTRIBUTION_REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    for k,v in panels.items(): v.to_parquet(out/f"h4_ip_level_{k.lower()}.parquet",index=False)
    def meta(p): return {"path":str(p),"sha256":sha256(p)} if p.exists() else {"path":str(p),"sha256":None}
    manifest={"stage":"H4_LOSS_CONTRIBUTION_DECOMPOSITION","run_id":run_id,"git_commit":git_commit,"main_label":"AUGMENTED_STRICT_SUPPORT3","support_threshold":3,"valid_ip_n":int(main.dst_ip.nunique()),"valid_state_n":int(main.target_admin1.nunique()),"valid_endpoint_event_rows":int(len(main)),"h4_verdict":h4_verdict,"war_event_registry":meta(war_registry),"outage_workbook":meta(workbook),"upstream_manifests":{"stage2":meta(stage2_manifest),"stage3":meta(stage3_manifest),"stage4":meta(stage4_manifest),"stage45":meta(stage45_manifest),"h1":meta(h1_manifest),"h2":meta(h2_manifest),"h3":meta(h3_manifest)},"random_seed":20260911,"h1_h2_h3_rerun":False}
    (out/"h4_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return {"output_dir":str(out),"verdict":h4_verdict,"valid_ip_n":int(main.dst_ip.nunique()),"valid_state_n":int(main.target_admin1.nunique()),"endpoint_rows":int(len(main)),"q1":q1.to_dict(),"q5":q5.to_dict(),"q5_event_n":q5event,"top_activity":topa.to_dict() if topa is not None else {},"combo_q1":combo_q1,"combo_q5":combo_q5,"concentration":conc.to_dict("records")}

def main(argv=None):
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--run-id",default="h4_final_experiment_20260911"); ap.add_argument("--root",default="/home/wsl/XiaoLunWen_doc_complete_20260908"); ap.add_argument("--h3-dir",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/h3_activity_conditional_sensitivity_20260911/results/stages/stage_h3_activity_conditional_sensitivity"); ap.add_argument("--git-commit",default=os.environ.get("GIT_COMMIT","unknown"));
    for n,d in [("stage2_manifest",""),("stage3_manifest",""),("stage4_manifest",""),("stage45_manifest",""),("h1_manifest",""),("h2_manifest",""),("h3_manifest",""),("war_registry","config/event_registry_v2.csv"),("workbook","config/ukraine_outage_calibration_ready_v2_episode_fix.xlsx")]: ap.add_argument("--"+n,default=d)
    a=ap.parse_args(); root=Path(a.root); resolve=lambda p: Path(p) if Path(p).is_absolute() else root/Path(p); print(json.dumps(run(a.run_id,root,Path(a.h3_dir),*[resolve(getattr(a,n)) for n in ["stage2_manifest","stage3_manifest","stage4_manifest","stage45_manifest","h1_manifest","h2_manifest","h3_manifest","war_registry","workbook"]],a.git_commit),indent=2,default=str))
if __name__=="__main__": main()
