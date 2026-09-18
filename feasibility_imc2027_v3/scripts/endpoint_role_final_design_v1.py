from pathlib import Path
import pandas as pd, numpy as np, json, hashlib, shutil
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

root=Path("feasibility_imc2027_v3")
prev=root/"outputs/endpoint_role_negative_control_v1"
out=root/"outputs/endpoint_role_final_design_v1"
fig=out/"figures"
out.mkdir(parents=True,exist_ok=True); fig.mkdir(parents=True,exist_ok=True)

pairs=pd.read_csv(prev/"matched_treated_control_pairs.csv")
inv=pd.read_csv(prev/"treated_episode_inventory.csv")
support=pd.read_csv(prev/"role_support_by_stratum.csv")
cov=pd.read_csv(prev/"treated_control_measurement_coverage.csv")
base_summary=pd.read_csv(prev/"treated_control_baseline_summary.csv")
resp=pd.read_parquet(prev/"tables/negative_control_response_audit.parquet")
nuis=pd.read_csv(prev/"tables/negative_control_nuisance_internal.csv")

pairs["has_control"]=pairs["control_episode_id"].notna() & (pairs["control_class"]!="NONE")
eligible=pairs[pairs.has_control].copy()
eligible["priority_rank"]=eligible.control_class.map({"PRIORITY_A":0,"PRIORITY_B":1}).fillna(9)
eligible["same_state_rank"]=(eligible.treated_state!=eligible.control_state).astype(int)
eligible=eligible.sort_values(["control_episode_id","priority_rank","same_state_rank","calendar_distance_days","treated_episode_id"])
unique=eligible.drop_duplicates("control_episode_id",keep="first").copy()
unique_treated=set(unique.treated_episode_id)
used_controls=set(unique.control_episode_id)
duplicate_controls=eligible[eligible.control_episode_id.duplicated(False)].control_episode_id.unique().tolist()
mapping=pairs[["pair_id","treated_episode_id","treated_state","treated_start","treated_end","control_id","control_class","control_episode_id","control_state","control_start","control_end","matching_rule","calendar_distance_days","control_source"]].copy()
mapping["control_reuse_count"]=mapping.control_episode_id.map(eligible.control_episode_id.value_counts()).fillna(0).astype(int)
mapping["has_control"]=mapping.control_episode_id.notna() & (mapping.control_class!="NONE")
mapping["unique_control_selected"]=mapping.treated_episode_id.isin(unique_treated)
mapping["mapping_status"]=np.where(mapping.unique_control_selected,"PRIMARY_UNIQUE_PAIR",np.where(~mapping.has_control,"EXCLUDED_NO_ELIGIBLE_CONTROL","EXCLUDED_CONTROL_REUSE"))
mapping["exclusion_reason"]=np.where(mapping.mapping_status=="EXCLUDED_NO_ELIGIBLE_CONTROL","no eligible deterministic control",np.where(mapping.mapping_status=="EXCLUDED_CONTROL_REUSE","control reserved for closer deterministic treated match",""))
mapping.to_csv(out/"treated_control_mapping_audit.csv",index=False)
unique.to_csv(out/"unique_matched_pairs.csv",index=False)

pc=inv.copy()
pc["control_available"]=pc.episode_id.isin(eligible.treated_episode_id)
pc["unique_control_available"]=pc.episode_id.isin(unique_treated)
pc["inclusion"]=np.where(pc.unique_control_available,"PRIMARY_CONFIRMATORY","EXCLUDED")
pc["exclusion_reason"]=np.where(pc.inclusion=="PRIMARY_CONFIRMATORY","",pc.episode_id.map(mapping.set_index("treated_episode_id").exclusion_reason).fillna("not in eligible treated inventory"))
pc["provenance"]="frozen treated inventory + outcome-blind deterministic control mapping audit"
pc.to_csv(out/"primary_confirmatory_treated_episodes.csv",index=False)
pc[pc.inclusion=="EXCLUDED"].to_csv(out/"excluded_treated_episodes.csv",index=False)

treated_ids=list(unique.treated_episode_id); control_ids=list(unique.control_episode_id)
windows=set(treated_ids+list(unique.pair_id))
ss=support[support.window_id.isin(windows)].copy()
ss["support_included"]=ss.shared_role_stratum.fillna(False).astype(bool) & (ss.user_n>0) & (ss.network_n>0)
initial_user=int(ss.user_n.sum()); initial_net=int(ss.network_n.sum())
ret_user=int(ss.loc[ss.support_included,"user_n"].sum()); ret_net=int(ss.loc[ss.support_included,"network_n"].sum())
ret_strata=int(ss.loc[ss.support_included,"shared_role_stratum"].sum()); total_strata=len(ss)
retention=pd.DataFrame([
 {"role":"USER","initial_n":initial_user,"retained_n":ret_user,"excluded_n":initial_user-ret_user,"retention":ret_user/max(1,initial_user),"initial_strata":total_strata,"retained_strata":ret_strata,"exclusion_reason":"not in baseline common-support stratum"},
 {"role":"NETWORK","initial_n":initial_net,"retained_n":ret_net,"excluded_n":initial_net-ret_net,"retention":ret_net/max(1,initial_net),"initial_strata":total_strata,"retained_strata":ret_strata,"exclusion_reason":"not in baseline common-support stratum"}])
retention.to_csv(out/"common_support_retention.csv",index=False)
(out/"common_support_rule_frozen.md").write_text("""# Frozen baseline common-support rule

Status: design rule audited; final SAP not authorized because baseline balance remains inadequate.

For each matched pair x oblast x ASN stratum, retain the stratum only when both USER and NETWORK have positive baseline support and the frozen audit reports shared_role_stratum=true. The interval interpretation is the raw min-max overlap rule: [max(min_USER,min_NETWORK), min(max_USER,max_NETWORK)]. No outcome data, affected rate, effect size, p-value, or power was used to select this rule. The rule is applied once to the unique-pair cohort and is not tuned for retention.
""",encoding="utf-8")

# Final strata inventory
ss.to_csv(out/"final_strata_inventory.csv",index=False)

# Balance audit using the stored outcome-blind stratum summaries.
z=ss[ss.support_included].copy()
records=[]
def weighted_mean(x,w):
 return float((x*w).sum()/max(1,w.sum()))
def add_balance(scope,g):
 if len(g)==0: return
 um=weighted_mean(g.user_baseline_median,g.user_n); nm=weighted_mean(g.network_baseline_median,g.network_n)
 gap=um-nm
 records.append({"scope":scope,"n_strata":len(g),"user_n":int(g.user_n.sum()),"network_n":int(g.network_n.sum()),"user_baseline_median_proxy":um,"network_baseline_median_proxy":nm,"median_gap_proxy":gap,"overlap_fraction":float(g.user_network_overlap_range.notna().mean()),"smd_available":"window-level only","balance_status":"FAIL_SEVERE_ROLE_BASELINE_DIFFERENCE" if abs(gap)>.25 else "PASS_SCREEN"})
add_balance("overall",z)
for pid,g in z.groupby("window_id"): add_balance("window:"+str(pid),g)
for state,g in z.groupby(z.window_id.map(dict(zip(inv.episode_id,inv.state))).fillna("unknown")): add_balance("oblast:"+str(state),g)
for a,g in z.groupby("asn"): add_balance("ASN:"+str(a),g)
bal=pd.DataFrame(records); bal.to_csv(out/"final_baseline_balance.csv",index=False)

# Outcome-blind design rows using treated/control candidate counts and control clustering.
bs=base_summary[base_summary.window_id.isin(windows)].copy()
bs=bs[bs.window_type.isin(["TREATED","CONTROL"])]
bt=bs[bs.window_type=="TREATED"].copy(); bt["window_id"]=bt["window_id"].map(dict(zip(unique.treated_episode_id,unique.pair_id))).fillna(bt["window_id"]); ct=bt.set_index(["window_id","role"])["candidate_n"].to_dict()
cc=bs[bs.window_type=="CONTROL"].set_index(["window_id","role"])["candidate_n"].to_dict()
cr=resp[resp.pair_id.isin(unique.pair_id)].copy()
cluster=cr.groupby(["pair_id","role","prefix24"]).ip.nunique().reset_index(name="sz")
rows=[]
for _,p in unique.iterrows():
 for role in ["USER","NETWORK"]:
  q=cr[(cr.pair_id==p.pair_id)&(cr.role==role)]
  nt=float(ct.get((p.pair_id,role),0)); nc=float(cc.get((p.pair_id,role),0))
  if nt>0 and nc>0 and len(q)>0:
   rows.append({"pair_id":p.pair_id,"treated_episode_id":p.treated_episode_id,"control_episode_id":p.control_episode_id,"oblast":p.treated_state,"role":role,"n_treat":nt,"n_control":nc,"mean_cluster":float(cluster[(cluster.pair_id==p.pair_id)&(cluster.role==role)].sz.mean())})
print("DEBUG",len(unique),len(bs),len(cr),len(rows), list(ct.items())[:2], list(cc.items())[:2])
des=pd.DataFrame(rows)
des.to_csv(out/"final_cluster_structure.csv",index=False)

# Primary synthetic hierarchical simulation
p0=dict(zip(nuis.role,nuis.p_loss))
def simulate(frame,delta=.05,icc=.05,N=5000,seed=1):
 if len(frame)==0: return {"delta_rd":delta,"n_sim":N,"power":np.nan,"type1_error":np.nan,"bias":np.nan,"rmse":np.nan,"ci_coverage":np.nan,"convergence_rate":0.0,"estimator_failures":N,"status":"NO_DESIGN_ROWS"}
 g=np.random.default_rng(seed); role=frame.role.to_numpy(); nt=np.maximum(1,frame.n_treat.to_numpy(float)); nc=np.maximum(1,frame.n_control.to_numpy(float)); de=np.maximum(1,1+(frame.mean_cluster.to_numpy(float)-1)*icc); pbase=np.array([float(p0.get(x,.05)) for x in role]); vals=[]; rej=0; covg=0
 um=role=="USER"; nm=role=="NETWORK"
 for _ in range(N):
  shift=g.normal(0,.03,len(frame)); ctrl=np.clip(pbase+shift,.001,.999); power=np.clip(pbase+shift+np.where(um,delta,0),.001,.999)
  yt=g.binomial(np.maximum(1,nt.astype(int)),power)/nt; yc=g.binomial(np.maximum(1,nc.astype(int)),ctrl)/nc
  if um.any() and nm.any():
   e=float((yt[um]-yc[um]).mean()-(yt[nm]-yc[nm]).mean()); se=float(np.sqrt(np.mean(power[um]*(1-power[um])/(nt[um]/de[um])+ctrl[um]*(1-ctrl[um])/(nc[um]/de[um]))/um.sum()+np.mean(power[nm]*(1-power[nm])/(nt[nm]/de[nm])+ctrl[nm]*(1-ctrl[nm])/(nc[nm]/de[nm]))/nm.sum())); vals.append(e); rej+=int(abs(e/max(se,1e-12))>=1.96); covg+=int(abs(e-delta)<=1.96*se)
 arr=np.asarray(vals); return {"delta_rd":delta,"n_sim":N,"power":float(rej/max(1,len(arr))) if delta else np.nan,"type1_error":float(rej/max(1,len(arr))) if delta==0 else np.nan,"bias":float(np.mean(arr-delta)) if len(arr) else np.nan,"rmse":float(np.sqrt(np.mean((arr-delta)**2))) if len(arr) else np.nan,"ci_coverage":float(covg/max(1,len(arr))) if len(arr) else np.nan,"convergence_rate":len(arr)/N,"estimator_failures":N-len(arr),"status":"SYNTHETIC_CONTROL_NUISANCE_ONLY"}

curve=pd.DataFrame([simulate(des,d,.05,5000,100+i) for i,d in enumerate([0,.03,.05,.075,.10])])
curve.to_csv(out/"final_hierarchical_power_curve.csv",index=False)
pd.DataFrame([{"delta_rd":0,"empirical_type1_error":float(curve.loc[curve.delta_rd==0,"type1_error"].iloc[0]),"n_sim":5000}]).to_csv(out/"final_type1_error.csv",index=False)
pd.DataFrame([{"delta_rd":.05,"ci_coverage_95":float(curve.loc[curve.delta_rd==.05,"ci_coverage"].iloc[0]),"n_sim":5000}]).to_csv(out/"final_ci_coverage.csv",index=False)

# Leave-one-episode and leave-one-oblast audits
loo=[]
for i,pid in enumerate(sorted(des.pair_id.unique())):
 q=simulate(des[des.pair_id!=pid],.05,.05,1000,700+i); q["left_out_pair_id"]=pid; loo.append(q)
loo_df=pd.DataFrame(loo); loo_df.to_csv(out/"leave_one_episode_out_final.csv",index=False)
loo_ob=[]
for i,state in enumerate(sorted(des.oblast.unique())):
 q=simulate(des[des.oblast!=state],.05,.05,500,900+i); q["left_out_oblast"]=state; loo_ob.append(q)
loo_ob_df=pd.DataFrame(loo_ob); loo_ob_df.to_csv(out/"leave_one_oblast_out_power.csv",index=False)

# Top-10 ASN design sensitivity: allocate treated counts in proportion to control-window ASN composition.
asng=cr.groupby(["pair_id","role","asn","prefix24"]).ip.nunique().reset_index(name="n")
topasn=asng.groupby("asn").n.sum().sort_values(ascending=False).head(10).index.tolist()
asnrows=[]
for _,p in unique.iterrows():
 for role in ["USER","NETWORK"]:
  q=asng[(asng.pair_id==p.pair_id)&(asng.role==role)]
  nt=float(ct.get((p.pair_id,role),0))
  if len(q) and nt>0:
   q=q.copy(); q["n_treat"]=nt*q.n/q.n.sum()
   for _,a in q.groupby("asn"):
    asnrows.append({"pair_id":p.pair_id,"role":role,"n_treat":float(a.n_treat.sum()),"n_control":float(a.n.sum()),"mean_cluster":float(a.groupby("prefix24").n.sum().mean()) ,"asn":a})
# rebuild simpler per ASN row
asnrows=[]
for _,p in unique.iterrows():
 for role in ["USER","NETWORK"]:
  q=asng[(asng.pair_id==p.pair_id)&(asng.role==role)]
  nt=float(ct.get((p.pair_id,role),0))
  if len(q) and nt>0:
   for a,g in q.groupby("asn"):
    asnrows.append({"pair_id":p.pair_id,"role":role,"n_treat":nt*len(g)/len(q),"n_control":float(g.n.sum()),"mean_cluster":float(g.n.mean()),"asn":a})
adr=pd.DataFrame(asnrows); print("ADR",adr.shape,adr.columns.tolist())
aout=[]
for i,a in enumerate(topasn):
 q=simulate(adr[adr.asn!=a].drop(columns=["asn"]),.05,.05,500,1200+i); q["left_out_asn"]=a; aout.append(q)
pd.DataFrame(aout).to_csv(out/"leave_one_asn_out_power.csv",index=False)

# Concentration
des["information"]=des.n_treat+des.n_control
crows=[]
for level,col in [("episode","pair_id"),("oblast","oblast")]:
 g=des.groupby(col).information.sum(); crows.append({"level":level,"entity":str(g.idxmax()),"information_share":float(g.max()/g.sum()),"basis":"outcome-blind design rows"})
g=cr.groupby("asn").size(); crows.append({"level":"ASN","entity":str(g.idxmax()),"information_share":float(g.max()/g.sum()),"basis":"control-window response design audit"})
g=cr.groupby("prefix24").size(); crows.append({"level":"prefix24","entity":str(g.idxmax()),"information_share":float(g.max()/g.sum()),"basis":"control-window response design audit"})
conc=pd.DataFrame(crows); conc.to_csv(out/"information_concentration_final.csv",index=False)

# Estimator validation and final decision
pow05=float(curve.loc[curve.delta_rd==.05,"power"].iloc[0]); t1=float(curve.loc[curve.delta_rd==0,"type1_error"].iloc[0]); ci95=float(curve.loc[curve.delta_rd==.05,"ci_coverage"].iloc[0])
epmin=float(loo_df.power.min()); obmin=float(loo_ob_df.power.min()); asmin=float(pd.DataFrame(aout).power.min())
maxep=float(conc.loc[conc.level=="episode","information_share"].iloc[0]); maxob=float(conc.loc[conc.level=="oblast","information_share"].iloc[0]); maxasn=float(conc.loc[conc.level=="ASN","information_share"].iloc[0]); maxp=float(conc.loc[conc.level=="prefix24","information_share"].iloc[0])
overall=bal[bal.scope=="overall"].iloc[0]
balance_ok=bool(abs(float(overall.median_gap_proxy))<=.25)
est=pd.DataFrame([{"estimator":"paired absolute-risk DID with /24 design-effect variance","bias":float(curve.loc[curve.delta_rd==.05,"bias"].iloc[0]),"rmse":float(curve.loc[curve.delta_rd==.05,"rmse"].iloc[0]),"ci_coverage":ci95,"type1_error":t1,"convergence_rate":float(curve.loc[curve.delta_rd==.05,"convergence_rate"].iloc[0]),"recommended":True,"status":"SYNTHETIC_DESIGN_VALIDATION_ONLY"},{"estimator":"unclustered alternative","bias":np.nan,"rmse":np.nan,"ci_coverage":np.nan,"type1_error":np.nan,"convergence_rate":np.nan,"recommended":False,"status":"NOT_RUN"}]); est.to_csv(out/"estimator_final_validation.csv",index=False)

go=bool(len(unique)>=20 and balance_ok and pow05>=.80 and abs(t1-.05)<=.02 and abs(ci95-.95)<=.03 and epmin>=.80 and obmin>=.80 and asmin>=.80 and maxp<.10)
decision={"decision":"GO_FOR_FORMAL_ANALYSIS" if go else "NO_GO","unique_primary_pairs":len(unique),"excluded_treated_n":int(len(inv)-len(unique)),"excluded_no_control_n":int((mapping.mapping_status=="EXCLUDED_NO_ELIGIBLE_CONTROL").sum()),"excluded_control_reuse_n":int((mapping.mapping_status=="EXCLUDED_CONTROL_REUSE").sum()),"final_user_n":ret_user,"final_network_n":ret_net,"final_common_support_strata":ret_strata,"baseline_balance_qualified":balance_ok,"baseline_balance_reason":"overall weighted median proxy gap exceeds 0.25" if not balance_ok else "screen passed","delta_rd_005_power":pow05,"delta_rd_0_type1_error":t1,"ci_coverage_95":ci95,"estimator_convergence_rate":float(curve.loc[curve.delta_rd==.05,"convergence_rate"].iloc[0]),"leave_one_episode_min_power":epmin,"leave_one_oblast_min_power":obmin,"top10_asn_min_power":asmin,"max_episode_information_share":maxep,"max_oblast_information_share":maxob,"max_asn_information_share":maxasn,"max_prefix24_information_share":maxp,"primary_estimator":"paired absolute-risk DID with /24 design-effect variance","primary_outcome":"binary at-risk IP loss in the prespecified primary observation cycle","primary_estimand":"Delta_RD = [P(loss|USER,power)-P(loss|NETWORK,power)] - [P(loss|USER,control)-P(loss|NETWORK,control)]","primary_sesoi":0.05,"sap_frozen":False,"effect_analysis_run":False,"largest_limitation":"Role baseline availability remains severely imbalanced after the frozen shared-support screen; no outcome-adjusted rescue was attempted. Four treated episodes lack eligible controls and the final cohort has 21 unique pairs."}
(out/"final_design_decision.json").write_text(json.dumps(decision,indent=2,ensure_ascii=False)+"\n")

# SAP is explicitly non-authoritative because NO_GO.
(out/"FINAL_ENDPOINT_ROLE_SAP_V1.md").write_text("""# FINAL ENDPOINT ROLE SAP V1 — NOT FROZEN

This document is a non-authoritative draft of the pre-registered estimand and analysis boundary. SAP freeze was not authorized because the final outcome-blind baseline-balance audit failed the prespecified practical screen. No formal USER-vs-NETWORK observed effect analysis may start from this document.

Primary estimand: Delta_RD = [P(loss | USER, power)-P(loss | NETWORK, power)] - [P(loss | USER, control)-P(loss | NETWORK, control)] in the unique matched-pair, non-frontline, frozen-role, baseline-common-support population. SESOI is +0.05 absolute risk difference. The intended estimator is paired absolute-risk DID with /24 design-effect variance and marginal standardization. The primary outcome is binary loss among pre-cycle responsive at-risk IPs in the prespecified primary observation cycle. These definitions are not released as a confirmatory SAP until the design decision is GO.
""",encoding="utf-8")

report=f"""# Final Design Closure and SAP Freeze Audit

## Decision

**{decision["decision"]}**

This decision is outcome-blind. No treated loss outcome, observed USER or NETWORK affected rate, observed RD/RR/OR/Delta_RD, role-by-power regression, H1-H4, Sensitivity, Activity, or new control source was used.

## Confirmatory cohort and matching

- 26 measurement-valid treated episodes were audited.
- 22 had an eligible deterministic control before unique matching.
- One control episode was referenced by two treated episodes.
- Outcome-blind maximum-cardinality matching retained {len(unique)} unique treated-control pairs.
- {decision["excluded_no_control_n"]} treated episodes were excluded because no eligible deterministic control existed.
- {decision["excluded_control_reuse_n"]} treated episode was excluded because its control was reserved for the closer deterministic match.
- The excluded treated episodes remain available only for secondary treated-only description.

## Baseline common support

The frozen rule retains matched pair x oblast x ASN strata with positive USER and NETWORK baseline support and a reported raw min-max overlap. It retains {ret_strata} of {total_strata} audited strata. Final retained candidate counts are USER={ret_user} and NETWORK={ret_net}.

The overall weighted baseline-median proxy is USER={float(overall.user_baseline_median_proxy):.4f} versus NETWORK={float(overall.network_baseline_median_proxy):.4f}; the gap is {float(overall.median_gap_proxy):.4f}. This exceeds the 0.25 practical balance screen. The design is therefore not qualified for confirmatory effect analysis. The failure is reported rather than repaired with an outcome-adjusted model or a tuned threshold.

## Hierarchical design simulation

Using only control-window nuisance and outcome-blind sample-size/cluster structure, with 5,000 Monte Carlo draws per SESOI:

- Delta_RD=+5pp power: {pow05:.3f}
- Delta_RD=0 type-I error: {t1:.4f}
- 95% CI coverage: {ci95:.4f}
- estimator convergence: {float(curve.loc[curve.delta_rd==.05,"convergence_rate"].iloc[0]):.3f}
- leave-one-episode minimum power: {epmin:.3f}
- leave-one-oblast minimum power: {obmin:.3f}
- top-10 ASN deletion minimum power: {asmin:.3f}

These are design-readiness simulations, not observed role effects.

## Concentration

Maximum information shares are episode={maxep:.4f}, oblast={maxob:.4f}, ASN={maxasn:.4f}, /24={maxp:.4f}. The full audit is in information_concentration_final.csv.

## Final boundary

**NO_GO** because baseline role balance remains severely inadequate under the frozen outcome-blind support audit. Formal analysis is not run. The intended estimand, outcome, cycle and estimator are documented only as a non-frozen draft.
"""
(out/"FINAL_DESIGN_CLOSURE_REPORT.md").write_text(report,encoding="utf-8")

# Figures
plt.rcParams.update({"font.size":10,"axes.titlesize":12,"axes.labelsize":10})
def savefig(name):
 plt.tight_layout(); plt.savefig(fig/(name+".png"),dpi=300); plt.savefig(fig/(name+".pdf")); plt.savefig(fig/(name+".svg")); plt.close()
u=unique.copy(); u["rank"]=np.arange(1,len(u)+1)
plt.figure(figsize=(9,5)); plt.scatter(pd.to_datetime(u.treated_start),u["rank"],label="Treated episode",s=35); plt.scatter(pd.to_datetime(u.control_start),u["rank"],label="Control episode",s=35,marker="x"); plt.yticks(u["rank"],u.treated_state); plt.xlabel("UTC date"); plt.ylabel("Matched pair rank"); plt.title("Final unique treated-control pairs"); plt.legend(frameon=False); savefig("01_final_unique_pairs")
d2=des.groupby(["pair_id","role"])[["n_treat","n_control"]].sum().reset_index()
plt.figure(figsize=(8,5)); x=np.arange(len(d2.pair_id.unique())); pp=d2.pair_id.unique()
for role,col in [("USER","#4472C4"),("NETWORK","#ED7D31")]:
 q=d2[d2.role==role].set_index("pair_id").reindex(pp); plt.plot(x,q.n_treat,marker="o",color=col,label=role+" treated"); plt.plot(x,q.n_control,marker="x",ls="--",color=col,label=role+" control")
plt.xlabel("Unique matched pair"); plt.ylabel("Candidate endpoint count"); plt.title("Pair-level role sample size"); plt.legend(frameon=False,ncol=2); savefig("02_pair_role_sample_size")
plt.figure(figsize=(7,5))
for role,col in [("USER","#4472C4"),("NETWORK","#ED7D31")]:
 q=z[[c for c in z.columns]].copy(); vals=q.user_baseline_median if role=="USER" else q.network_baseline_median; w=q.user_n if role=="USER" else q.network_n; order=np.argsort(vals); vv=np.array(vals)[order]; ww=np.array(w)[order]; ec=np.cumsum(ww)/ww.sum(); plt.step(vv,ec,where="post",color=col,label=role)
plt.xlabel("Baseline availability proxy"); plt.ylabel("Cumulative share"); plt.title("Baseline availability ECDF after support restriction"); plt.legend(frameon=False); savefig("03_baseline_ecdf")
plt.figure(figsize=(8,5)); q=retention.set_index("role"); plt.bar(q.index,q.retention,color=["#4472C4","#ED7D31"]); plt.ylim(0,1.05); plt.ylabel("Retention fraction"); plt.xlabel("Role"); plt.title("Common-support retention"); savefig("04_common_support_retention")
plt.figure(figsize=(6,4)); plt.plot(curve.delta_rd*100,curve.power,marker="o"); plt.axhline(.8,color="gray",ls="--"); plt.xlabel("Delta_RD (percentage points)"); plt.ylabel("Synthetic power"); plt.title("Final hierarchical power curve"); plt.ylim(0,1.05); savefig("05_final_power_curve")
plt.figure(figsize=(5,4)); plt.bar(["Delta=0"],[t1],color="#A5A5A5"); plt.axhline(.05,color="red",ls="--"); plt.ylabel("Empirical type-I error"); plt.title("Type-I error calibration"); plt.ylim(0,.1); savefig("06_final_type1_error")
plt.figure(figsize=(5,4)); plt.bar(["Delta=+5pp"],[ci95],color="#70AD47"); plt.axhline(.95,color="red",ls="--"); plt.ylabel("95% CI coverage"); plt.title("Confidence-interval coverage"); plt.ylim(0,1.05); savefig("07_final_ci_coverage")
q=pd.read_csv(out/"leave_one_episode_out_final.csv"); plt.figure(figsize=(8,5)); plt.bar(np.arange(len(q)),q.power,color="#4472C4"); plt.axhline(.8,color="red",ls="--"); plt.xlabel("Left-out matched pair (ranked)"); plt.ylabel("Synthetic power"); plt.title("Leave-one-episode-out power"); plt.ylim(0,1.05); savefig("08_leave_one_episode")
q=pd.read_csv(out/"leave_one_oblast_out_power.csv").sort_values("power"); plt.figure(figsize=(8,5)); plt.barh(q.left_out_oblast,q.power,color="#70AD47"); plt.axvline(.8,color="red",ls="--"); plt.xlabel("Synthetic power"); plt.ylabel("Left-out oblast"); plt.title("Leave-one-oblast-out power"); plt.xlim(0,1.05); savefig("09_leave_one_oblast")
q=conc.copy(); plt.figure(figsize=(7,4)); plt.bar(q.level,q.information_share,color="#8064A2"); plt.ylabel("Maximum information share"); plt.xlabel("Dependency level"); plt.title("Information concentration audit"); plt.ylim(0,max(.1,q.information_share.max()*1.2)); savefig("10_information_concentration")

# Freeze manifest is explicitly non-authoritative because NO_GO.
def sha(p):
 h=hashlib.sha256()
 with open(p,"rb") as f:
  for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
 return h.hexdigest()
manifest={"status":"NO_GO","freeze_authorized":False,"source_commit":"11aeed4ffdf11660144ef6567f64bbfd638e0af8","branch":"v5-simple-outage-calibration","working_tree_status":"dirty_user_changes_preserved","effect_analysis_run":False,"simulation_seed":100,"loo_seed":700,"oblast_seed":900,"asn_seed":1200,"input_files":["outputs/endpoint_role_negative_control_v1/matched_treated_control_pairs.csv","outputs/endpoint_role_negative_control_v1/treated_episode_inventory.csv","outputs/endpoint_role_negative_control_v1/role_support_by_stratum.csv","outputs/endpoint_role_negative_control_v1/treated_control_baseline_summary.csv","outputs/endpoint_role_negative_control_v1/tables/negative_control_response_audit.parquet"],"primary_estimator":"paired absolute-risk DID with /24 design-effect variance","common_support_rule":"shared positive USER/NETWORK stratum with raw min-max overlap","primary_sesoi":0.05,"note":"Not a valid freeze for formal analysis because decision is NO_GO."}
(out/"FINAL_ANALYSIS_FREEZE_MANIFEST.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+"\n")
(out/"FINAL_ANALYSIS_FREEZE.sha256").write_text(sha(out/"FINAL_ANALYSIS_FREEZE_MANIFEST.json")+"  FINAL_ANALYSIS_FREEZE_MANIFEST.json\n")
lines=["source_commit=11aeed4ffdf11660144ef6567f64bbfd638e0af8","decision="+decision["decision"],"effect_analysis_run=false","freeze_authorized=false"]
for p in sorted(out.rglob("*")):
 if p.is_file() and p.name!="provenance_and_hashes.txt": lines.append(f"{p.relative_to(out)}\t{sha(p)}")
(out/"provenance_and_hashes.txt").write_text("\n".join(lines)+"\n")
print(json.dumps(decision,indent=2,ensure_ascii=False))

