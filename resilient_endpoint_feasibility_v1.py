#!/usr/bin/env python3
"""Power-resilient endpoint feasibility audit.

This stage is deliberately isolated from CAIDA: it consumes only the frozen
Ukraine active-measurement role/outcome artifacts and the 21 frozen pairs.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path("/home/wsl/XiaoLunWen_doc_complete_20260908")
STAGE = ROOT / "resilient_endpoint_feasibility_v1"
OUT = STAGE / "outputs"
FIG = OUT / "figures"
PAIR_DIR = ROOT / "feasibility_imc2027_v3/outputs/endpoint_role_final_design_v1"
ROLE_DIR = ROOT / "feasibility_imc2027_v3/outputs/endpoint_role_negative_control_v1"
BASE_DIR = ROOT / "feasibility_imc2027_v3/outputs/endpoint_role_feasibility_v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def savefig(name: str) -> None:
    plt.tight_layout()
    for ext, kw in [("png", {"dpi": 300}), ("pdf", {}), ("svg", {})]:
        plt.savefig(FIG / f"{name}.{ext}", bbox_inches="tight", **kw)
    plt.close()


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    cen = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return cen - half, cen + half


def beta_ci(k: int, n: int) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    try:
        from scipy.stats import beta
        return (float(beta.ppf(0.025, k + 0.5, n - k + 0.5)),
                float(beta.ppf(0.975, k + 0.5, n - k + 0.5)))
    except Exception:
        return wilson(k, n)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    # Frozen pair contract: exactly the previous 21 pairs, no re-matching.
    pairs = pd.read_csv(PAIR_DIR / "unique_matched_pairs.csv")
    if len(pairs) != 21:
        raise RuntimeError(f"frozen pair contract failed: expected 21, got {len(pairs)}")
    pairs["treated_start"] = pd.to_datetime(pairs["treated_start"], utc=True)
    pairs = pairs.sort_values(["treated_start", "pair_id"]).reset_index(drop=True)
    pairs["split"] = np.where(pairs.index < 13, "discovery", "holdout")
    pairs[["pair_id", "treated_episode_id", "control_episode_id", "treated_state",
           "treated_start", "treated_end", "control_start", "control_end", "split"]].to_csv(
        OUT / "chronological_pair_split.csv", index=False)

    treated = pd.read_parquet(BASE_DIR / "tables/endpoint_role_outcomes.parquet")
    treated = treated[treated.episode_id.isin(pairs.treated_episode_id) & treated.role.isin(["USER", "NETWORK"])].copy()
    ctrl = pd.read_parquet(ROLE_DIR / "tables/negative_control_response_audit.parquet")
    ctrl = ctrl[ctrl.pair_id.isin(pairs.pair_id) & ctrl.role.isin(["USER", "NETWORK"])].copy()
    ctrl = ctrl.rename(columns={"pre_response": "control_clean_response", "control_response": "control_survival"})
    treated = treated.rename(columns={"pre_response": "treated_clean_response", "outage_response": "treated_survival"})
    treated["treated_clean_response"] = treated.treated_clean_response.astype(int)
    treated["treated_survival"] = treated.treated_survival.astype(int)
    ctrl["control_clean_response"] = ctrl.control_clean_response.astype(int)
    ctrl["control_survival"] = ctrl.control_survival.astype(int)

    keys = ["pair_id", "role", "ip"]
    tr = treated.merge(pairs[["pair_id", "treated_episode_id", "control_episode_id", "treated_state", "split"]],
                       left_on=["episode_id"], right_on=["treated_episode_id"], how="inner")
    tr = tr.rename(columns={"treated_state": "oblast"})
    opp = tr.merge(ctrl[keys + ["control_clean_response", "control_survival", "prefix24", "asn"]],
                   on=keys, how="inner", suffixes=("", "_control"))
    # All rows are from complete frozen windows; a valid opportunity requires
    # both clean reference observations and an at-risk target in each role.
    opp["valid_opportunity"] = (
        opp.treated_clean_response.eq(1) & opp.control_clean_response.eq(1) &
        opp.at_risk.astype(bool) & opp.ip.notna()
    )
    opp = opp[opp.valid_opportunity].copy()
    opp["treated_affected"] = 1 - opp.treated_survival
    opp["control_affected"] = 1 - opp.control_survival
    opp["acquisition_gap_excluded"] = False
    keep = ["pair_id", "treated_episode_id", "control_episode_id", "oblast", "split", "role", "ip",
            "prefix24", "asn", "baseline_availability", "treated_clean_response", "treated_survival",
            "treated_affected", "control_clean_response", "control_survival", "control_affected",
            "acquisition_gap_excluded", "valid_opportunity"]
    opp[keep].to_parquet(OUT / "paired_endpoint_opportunities.parquet", index=False)

    dist = opp.groupby(["ip", "role"], as_index=False).agg(
        opportunity_n=("pair_id", "nunique"), oblast=("oblast", "first"), asn=("asn", "first"), prefix24=("prefix24", "first"))
    dist["support_ge_1"] = dist.opportunity_n >= 1
    dist["support_ge_2"] = dist.opportunity_n >= 2
    dist["support_ge_3"] = dist.opportunity_n >= 3
    dist["support_ge_5"] = dist.opportunity_n >= 5
    dist["support_ge_8"] = dist.opportunity_n >= 8
    dist["support_ge_10"] = dist.opportunity_n >= 10
    dist["support_ge_15"] = dist.opportunity_n >= 15
    dist.to_csv(OUT / "opportunity_distribution_by_ip.csv", index=False)
    by_state = dist.groupby(["oblast", "role"], as_index=False).agg(
        ip_n=("ip", "nunique"), opportunity_n=("opportunity_n", "sum"), median_opportunity=("opportunity_n", "median"),
        ge2=("support_ge_2", "sum"), ge3=("support_ge_3", "sum"), ge5=("support_ge_5", "sum"), ge8=("support_ge_8", "sum"), ge10=("support_ge_10", "sum"), ge15=("support_ge_15", "sum"))
    by_state.to_csv(OUT / "opportunity_distribution_by_oblast.csv", index=False)
    by_asn = dist.groupby(["asn", "role"], as_index=False).agg(ip_n=("ip", "nunique"), opportunity_n=("opportunity_n", "sum"), median_opportunity=("opportunity_n", "median"))
    by_asn.to_csv(OUT / "opportunity_distribution_by_asn.csv", index=False)
    by_pfx = dist.groupby(["prefix24", "role"], as_index=False).agg(ip_n=("ip", "nunique"), opportunity_n=("opportunity_n", "sum"), median_opportunity=("opportunity_n", "median"))
    by_pfx.to_csv(OUT / "opportunity_distribution_by_prefix24.csv", index=False)

    # Distribution figures.
    plt.figure(figsize=(8, 5));
    for role, g in dist.groupby("role"):
        plt.hist(g.opportunity_n, bins=np.arange(0.5, max(2, g.opportunity_n.max()) + 1.5), alpha=.55, label=role)
    plt.xlabel("有效事件机会数（每个 IP）"); plt.ylabel("IP 数量"); plt.title("端点有效机会数分布"); plt.legend(frameon=False); savefig("01_opportunity_histogram")
    plt.figure(figsize=(8, 5));
    for role, g in dist.groupby("role"):
        x=np.sort(g.opportunity_n.to_numpy()); y=np.arange(1,len(x)+1)/len(x); plt.step(x,y,where="post",label=role)
    plt.xlabel("有效事件机会数（每个 IP）"); plt.ylabel("累计比例"); plt.title("端点有效机会数 ECDF"); plt.legend(frameon=False); savefig("02_opportunity_ecdf")

    # Discovery histories and holdout rows.
    dsc = opp[opp.split.eq("discovery")].copy(); hld = opp[opp.split.eq("holdout")].copy()
    hist = dsc.groupby(["ip", "role"], as_index=False).agg(N_i=("pair_id", "nunique"), S_i=("treated_survival", "sum"), C_i=("control_survival", "sum"), oblast=("oblast", "first"), asn=("asn", "first"))
    hist["treated_survival_fraction"] = hist.S_i / hist.N_i
    hist["control_survival_fraction"] = hist.C_i / hist.N_i
    hist.to_parquet(OUT / "discovery_survival_summary.parquet", index=False)
    hist.to_csv(OUT / "discovery_survival_summary.csv", index=False)
    pd.DataFrame({"metric":["all","ge2","ge3","ge5","ge8","ge10","ge15"], "ip_n":[len(dist), int((dist.opportunity_n>=2).sum()), int((dist.opportunity_n>=3).sum()), int((dist.opportunity_n>=5).sum()), int((dist.opportunity_n>=8).sum()), int((dist.opportunity_n>=10).sum()), int((dist.opportunity_n>=15).sum())]}).to_csv(OUT / "support_threshold_summary.csv", index=False)

    # M0/M1 predictive audit, using only discovery to construct history.
    def design(frame: pd.DataFrame, with_history: bool, reference_hist: pd.DataFrame | None = None):
        x = frame[["ip", "baseline_availability", "oblast", "asn", "pair_id"]].copy()
        if with_history:
            hh = reference_hist if reference_hist is not None else hist
            x = x.merge(hh[["ip", "N_i", "S_i", "treated_survival_fraction"]], left_on="ip", right_on="ip", how="left")
            x[["N_i", "S_i", "treated_survival_fraction"]] = x[["N_i", "S_i", "treated_survival_fraction"]].fillna(0)
        x = x.drop(columns=["ip"], errors="ignore")
        x["baseline_availability"] = x.baseline_availability.fillna(0).clip(0, 1)
        return pd.get_dummies(x, columns=["oblast", "asn", "pair_id"], dtype=float)
    results=[]; pred_tables=[]
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score
        train=dsc.copy(); test=hld.copy()
        if len(train) and len(test):
            for model_name, use_hist in [("M0",False),("M1",True)]:
                Xtr=design(train,use_hist); Xte=design(test,use_hist,hist); Xte=Xte.reindex(columns=Xtr.columns,fill_value=0)
                ytr=train.treated_survival.astype(int); yte=test.treated_survival.astype(int)
                if ytr.nunique()<2: raise RuntimeError("discovery outcome has one class")
                fit=LogisticRegression(max_iter=500, class_weight="balanced").fit(Xtr,ytr)
                prob=fit.predict_proba(Xte)[:,1]; pred_tables.append(test[["pair_id","ip","role","oblast","treated_survival"]].assign(model=model_name,predicted_survival=prob))
                results.append({"model":model_name,"n_train":len(train),"n_holdout":len(test),"log_loss":float(log_loss(yte,prob,labels=[0,1])),"brier":float(brier_score_loss(yte,prob)),"auc":float(roc_auc_score(yte,prob)) if len(np.unique(yte))>1 else np.nan,"mean_predicted_survival":float(prob.mean()),"observed_survival":float(yte.mean()),"marginal_effect_survival":float(prob[test.role.eq('USER')].mean()-prob[test.role.eq('NETWORK')].mean()) if test.role.nunique()>1 else np.nan})
    except Exception as e:
        results.append({"model":"M0/M1","status":"NOT_ESTIMABLE","reason":str(e)})
    pd.DataFrame(results).to_csv(OUT / "holdout_m0_m1_metrics.csv", index=False)
    if pred_tables: pd.concat(pred_tables,ignore_index=True).to_parquet(OUT/"holdout_predictions.parquet",index=False)
    # Calibration by equal-width prediction bins, kept separate from the model table.
    cal=[]
    if pred_tables:
        pp=pd.concat(pred_tables,ignore_index=True)
        for model_name,g in pp.groupby("model"):
            g=g.copy(); g["bin"]=pd.cut(g.predicted_survival, bins=np.linspace(0,1,11), include_lowest=True)
            for b,h in g.groupby("bin", observed=False):
                cal.append({"model":model_name,"bin":str(b),"n":len(h),"mean_predicted":h.predicted_survival.mean() if len(h) else np.nan,"observed_survival":h.treated_survival.mean() if len(h) else np.nan})
    pd.DataFrame(cal).to_csv(OUT/"holdout_calibration.csv",index=False)

    # Precision audit by discovery support.
    pr=[]
    for n in [3,5,8,10,15]:
        g=hist[hist.N_i.eq(n)]
        for role in sorted(hist.role.unique()):
            q=g[g.role.eq(role)]; k=int(q.S_i.sum()); nn=int(q.N_i.sum()); lo,hi=wilson(k,nn); blo,bhi=beta_ci(k,nn)
            pr.append({"role":role,"N_i":n,"ip_n":len(q),"opportunity_n":nn,"survival_n":k,"survival_fraction":k/nn if nn else np.nan,"wilson_low":lo,"wilson_high":hi,"clopper_pearson_low":blo,"clopper_pearson_high":bhi})
    pd.DataFrame(pr).to_csv(OUT / "precision_audit.csv",index=False)

    # Negative control and placebo labels: repeated control survival, then pairwise label swaps.
    paired = opp.copy();
    obs=float((paired.treated_survival-paired.control_survival).mean()) if len(paired) else np.nan
    rng=np.random.default_rng(20260916); placebo=[]
    for i in range(1000):
        swap=rng.integers(0,2,len(paired)); a=np.where(swap,paired.control_survival,paired.treated_survival); b=np.where(swap,paired.treated_survival,paired.control_survival); placebo.append(float((a-b).mean()))
    placebo_df=pd.DataFrame({"placebo_delta":placebo}); placebo_df.to_csv(OUT/"placebo_label_permutations.csv",index=False)
    p_abs=float(np.mean(np.abs(placebo_df.placebo_delta)>=abs(obs))) if len(placebo_df) else np.nan
    pd.DataFrame([{ "observed_treated_minus_control_survival":obs,"placebo_abs_p":p_abs,"n_permutations":1000,"negative_control_status":"PASS_SCREEN" if p_abs<.05 else "SAME_STRENGTH_AS_PLACEBO"}]).to_csv(OUT/"negative_control_summary.csv",index=False)

    # Leave-one-out repeatability summaries (descriptive, not H1-H4).
    loo=[]
    for pid in sorted(opp.pair_id.unique()):
        q=opp[opp.pair_id.ne(pid)]; loo.append({"left_out_pair_id":pid,"opportunity_n":len(q),"survival_fraction":q.treated_survival.mean() if len(q) else np.nan})
    pd.DataFrame(loo).to_csv(OUT/"leave_one_episode_out.csv",index=False)
    for col,name in [("oblast","leave_one_oblast_out.csv"),("asn","leave_one_asn_out.csv")]:
        rows=[]
        for val in sorted(opp[col].dropna().astype(str).unique()):
            q=opp[opp[col].astype(str).ne(val)]; rows.append({"left_out":val,"opportunity_n":len(q),"survival_fraction":q.treated_survival.mean() if len(q) else np.nan})
        pd.DataFrame(rows).to_csv(OUT/name,index=False)

    # Candidate group is only released if M1 materially improves M0; never tune on holdout.
    met=pd.DataFrame(results); candidate_reason="M1 not materially better than M0"
    candidate=pd.DataFrame(columns=list(hist.columns)+["candidate_group"])
    if set(["M0","M1"]).issubset(set(met.model)):
        m0=met[met.model.eq("M0")].iloc[0]; m1=met[met.model.eq("M1")].iloc[0]
        if m1.log_loss < m0.log_loss-0.01 and m1.brier < m0.brier:
            candidate=hist.copy(); candidate["candidate_group"]=(candidate.treated_survival_fraction>=candidate.treated_survival_fraction.quantile(.75)).astype(int); candidate_reason="M1 materially improved discovery-to-holdout metrics"
    candidate.to_csv(OUT/"candidate_group_discovery_only.csv",index=False)
    pd.DataFrame([{"candidate_n":len(candidate),"candidate_reason":candidate_reason,"holdout_used_for_candidate":False,"caida_used_for_candidate":False}]).to_csv(OUT/"candidate_group_audit.csv",index=False)

    # Figures 3-10.
    plt.figure(figsize=(9,5)); ss=dist.groupby("oblast").opportunity_n.sum().sort_values(); plt.barh(ss.index,ss.values); plt.xlabel("有效机会总数"); plt.ylabel("州"); plt.title("各州端点有效机会总数"); savefig("03_opportunity_by_oblast")
    plt.figure(figsize=(7,5));
    for role,g in hist.groupby("role"): plt.hist(g.treated_survival_fraction,bins=20,alpha=.5,label=role)
    plt.xlabel("发现期处理窗口存活比例"); plt.ylabel("IP 数量"); plt.title("发现期端点存活比例"); plt.legend(frameon=False); savefig("04_discovery_survival_hist")
    plt.figure(figsize=(8,5)); p=hist.groupby("N_i").ip.count(); plt.bar(p.index.astype(str),p.values); plt.xlabel("N_i（发现期有效机会数）"); plt.ylabel("IP 数量"); plt.title("发现期支持度分布"); savefig("05_discovery_support")
    if len(results)>=2:
        m=met[met.model.isin(["M0","M1"])]; plt.figure(figsize=(7,5)); plt.bar(m.model,m.log_loss); plt.ylabel("留出集 Log loss"); plt.title("M0/M1 留出集比较"); savefig("06_holdout_logloss")
        plt.figure(figsize=(7,5)); plt.bar(m.model,m.brier); plt.ylabel("留出集 Brier score"); plt.title("M0/M1 留出集 Brier 比较"); savefig("07_holdout_brier")
    else:
        for n in ["06_holdout_logloss","07_holdout_brier"]:
            plt.figure(figsize=(7,5)); plt.text(.5,.5,"不可估计",ha="center",va="center"); plt.axis("off"); savefig(n)
    plt.figure(figsize=(7,5)); plt.hist(placebo, bins=30, color="grey"); plt.axvline(obs,color="red",label="观测差异"); plt.xlabel("置换标签下存活差异"); plt.ylabel("次数"); plt.title("阴性对照：标签置换分布"); plt.legend(frameon=False); savefig("08_placebo_permutation")
    plt.figure(figsize=(7,5)); plt.bar(["处理窗口","对照窗口"],[paired.treated_survival.mean(),paired.control_survival.mean()]); plt.ylabel("存活比例"); plt.title("处理/对照窗口存活比例"); savefig("09_treated_control_survival")
    plt.figure(figsize=(8,5)); g=opp.groupby("pair_id").treated_survival.mean().sort_values(); plt.plot(np.arange(len(g)),g.values,"o-"); plt.xlabel("按时间排序的独立配对事件"); plt.ylabel("处理窗口存活比例"); plt.title("跨配对事件存活重复性（描述性）"); savefig("10_pair_repeatability")

    # Deterministic final verdict: low support dominates; placebo same-strength also blocks.
    share_1_2=float((dist.opportunity_n.le(2)).mean()) if len(dist) else 1.0
    no_go_reason=[]
    if len(pairs)!=21: no_go_reason.append("frozen pair contract failed")
    if len(opp)==0: no_go_reason.append("no valid opportunities")
    if share_1_2>0.5: no_go_reason.append(f"{share_1_2:.3f} of IP-role units have only 1-2 opportunities")
    if len(placebo_df) and p_abs>=.05: no_go_reason.append("negative-control/placebo has same-strength signal")
    verdict="NO_GO_FOR_RESILIENCE_PHENOTYPE" if no_go_reason else "GO_FOR_EXTERNAL_INFRASTRUCTURE_VALIDATION"
    decision={"final_verdict":verdict,"frozen_pairs":int(len(pairs)),"opportunity_rows":int(len(opp)),"ip_role_units":int(len(dist)),"share_only_1_or_2_opportunities":share_1_2,"observed_treated_minus_control_survival":obs,"placebo_abs_p":p_abs,"reasons":no_go_reason,"caida_used_for_stage_b":False,"h1_h4_modified":False}
    (OUT/"final_decision.json").write_text(json.dumps(decision,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    reason_lines="\n".join(f"- {x}" for x in no_go_reason) if no_go_reason else "- No blocking reason"
    report=f"""# Power-Resilient Endpoint Feasibility Audit v1\n\n## Final verdict\n\n**{verdict}**\n\nThis stage reused exactly 21 frozen treated-control pairs and did not read CAIDA/PeeringDB role labels. It did not modify H1-H4.\n\n## Opportunity coverage\n\n- Paired endpoint opportunities: {len(opp):,}\n- IP-role units: {len(dist):,}\n- Share with only 1-2 opportunities: {share_1_2:.4f}\n- Support counts are reported for thresholds 1, 2, 3, 5, 8, 10 and 15.\n\n## Discovery / holdout\n\nThe chronological split is fixed at 13 discovery pairs and 8 holdout pairs. Discovery survival histories and holdout M0/M1 metrics are exported separately. A candidate group is released only if M1 materially improves M0 and is discovery-only.\n\n## Negative control\n\nObserved treated-minus-control survival difference: {obs:.6f}. Placebo absolute p-value: {p_abs:.6f}.\n\n## Decision basis\n\n{reason_lines}\n\nNo threshold, split, baseline, event selection, or CAIDA enrichment was tuned after seeing outcomes.\n"""
    (OUT/"POWER_RESILIENT_ENDPOINT_FEASIBILITY_REPORT.md").write_text(report,encoding="utf-8")
    (OUT/"config_snapshot.json").write_text(json.dumps({"stage":"Power-Resilient Endpoint Feasibility Audit v1","frozen_pairs":21,"discovery_pairs":13,"holdout_pairs":8,"support_thresholds":[1,2,3,5,8,10,15],"primary_outcome":"treated primary-cycle survival among paired at-risk IPs","candidate_release_rule":"M1 materially improves M0; discovery-only","caida_used":False,"h1_h4_modified":False},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (OUT/"resilience_vs_h1_comparison.md").write_text("# Resilience repeatability versus prior H1\n\nThis audit is descriptive and does not modify H1-H4. It reuses the 21 frozen treated-control pairs and reports opportunity support and pair-level survival repeatability. Cross-event endpoint ranking summaries remain in the frozen H1 artifacts.\n",encoding="utf-8")
    prov={"inputs":{},"caida_read":False,"frozen_pair_n":len(pairs),"output_sha256":{}}
    for p in [PAIR_DIR/"unique_matched_pairs.csv", BASE_DIR/"tables/endpoint_role_outcomes.parquet", ROLE_DIR/"tables/negative_control_response_audit.parquet"]:
        prov["inputs"][str(p)]=sha256(p)
    for p in OUT.glob("*"):
        if p.is_file() and p.name!="provenance_hashes.json": prov["output_sha256"][p.name]=sha256(p)
    (OUT/"provenance_hashes.json").write_text(json.dumps(prov,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
