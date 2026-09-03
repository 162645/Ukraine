"""Experiment D — accumulated outage exposure and observable recovery debt.

Official outage hours are calculated by interval overlap with the frozen registry.
The complementary ``pre_event_debt`` metric is derived only from measurements
available before the next event and represents incomplete observable recovery; it
is not treated as a physical outage-hour substitute.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from .config import Config
from .geo import Admin1Canonicalizer
from .progress import get_logger, step
from .stats import km_survival

OUTCOMES = ["max_deficit", "deficit_auc_full", "t90_h"]


def _split(x: object) -> set[str]:
    s = str(x or "").strip()
    return {z.strip() for z in s.split("|") if z.strip()}


def prepare_exposure_registry(cfg: Config) -> pd.DataFrame:
    x = cfg.load_exposure_registry().copy()
    canon = Admin1Canonicalizer(cfg.resource_path("admin1_aliases"),
                                cfg.quality["unknown_labels"], cfg.quality["valid_country_aliases"])
    x["affected_set"] = x.apply(
        lambda r: {"ALL"} if str(r["scope_type"]).lower() == "national" or str(r["affected_admin1"]) == "ALL"
        else {canon.canonical_admin1("Ukraine", z) for z in _split(r["affected_admin1"])}, axis=1)
    x["duration_h"] = (x["end_utc"] - x["start_utc"]).dt.total_seconds() / 3600
    return x


def overlap_hours(start_a, end_a, start_b, end_b) -> float:
    lo, hi = max(start_a, start_b), min(end_a, end_b)
    return max(0.0, (hi-lo).total_seconds()/3600.0) if hi > lo else 0.0


def exposure_for_group(anchor: pd.Timestamp, admin1: str, registry: pd.DataFrame,
                       lookback_h: float, exposure_types: set[str] | None = None) -> float:
    lo = anchor - pd.Timedelta(hours=float(lookback_h)); total = 0.0
    for _, r in registry.iterrows():
        if exposure_types and r["exposure_type"] not in exposure_types:
            continue
        if r["start_utc"] >= anchor or r["end_utc"] <= lo:
            continue
        if "ALL" not in r["affected_set"] and admin1 not in r["affected_set"]:
            continue
        total += overlap_hours(lo, anchor, r["start_utc"], r["end_utc"])
    return total


def build_exposure_panel(features: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    reg = prepare_exposure_registry(cfg); d = features.copy()
    d["event_anchor_utc"] = pd.to_datetime(d["event_anchor_utc"], utc=True, errors="coerce")
    for h in map(int, cfg.recovery_debt["lookbacks_hours"]):
        d[f"outage_hours_{h}h"] = [exposure_for_group(a, str(g), reg, h)
                                    for a, g in zip(d["event_anchor_utc"], d["target_admin1"])]
        d[f"scheduled_hours_{h}h"] = [exposure_for_group(a, str(g), reg, h, {"scheduled"})
                                       for a, g in zip(d["event_anchor_utc"], d["target_admin1"])]
        d[f"emergency_hours_{h}h"] = [exposure_for_group(a, str(g), reg, h, {"emergency", "preventive_emergency"})
                                       for a, g in zip(d["event_anchor_utc"], d["target_admin1"])]
    d = d.sort_values(["group", "event_anchor_utc"])
    d["previous_t90_h"] = d.groupby("group")["t90_h"].shift(1)
    d["previous_recovery_censored"] = d.groupby("group")["recovery_censored"].shift(1)
    d["previous_event_utc"] = d.groupby("group")["event_anchor_utc"].shift(1)
    d["hours_since_previous_event"] = (d["event_anchor_utc"]-d["previous_event_utc"]).dt.total_seconds()/3600
    d["previously_unrecovered"] = ((d["previous_recovery_censored"].eq(1)) |
                                    (d["previous_t90_h"] > d["hours_since_previous_event"])).astype(int)
    if "pre_event_debt" not in d:
        d["pre_event_debt"] = np.nan
    return d


def variation_audit(d: pd.DataFrame, exposures: list[str]) -> pd.DataFrame:
    rows=[]
    for x in exposures:
        for event_id,z in d.groupby("event_id"):
            v=pd.to_numeric(z[x],errors="coerce")
            rows.append({"exposure":x,"event_id":event_id,"n":v.notna().sum(),
                         "n_unique":v.nunique(dropna=True),"min":v.min(),"max":v.max(),
                         "sd":v.std(),"within_event_variation":int(v.nunique(dropna=True)>=2)})
    return pd.DataFrame(rows)


def _numpy_fe_fit(z: pd.DataFrame, y: str, exposures: list[str], with_event: bool) -> tuple[np.ndarray,np.ndarray,np.ndarray]:
    """OLS with group/event dummies and group-clustered sandwich covariance."""
    cols = exposures.copy()
    X = z[cols].astype(float).reset_index(drop=True)
    gd = pd.get_dummies(z["group"].astype(str), prefix="g", drop_first=True, dtype=float).reset_index(drop=True)
    parts=[pd.DataFrame({"intercept":np.ones(len(z))}),X,gd]
    if with_event:
        ed=pd.get_dummies(z["event_id"].astype(str),prefix="e",drop_first=True,dtype=float).reset_index(drop=True);parts.append(ed)
    M=pd.concat(parts,axis=1).to_numpy(float); yy=z[y].to_numpy(float)
    beta=np.linalg.pinv(M.T@M)@(M.T@yy); resid=yy-M@beta
    bread=np.linalg.pinv(M.T@M); meat=np.zeros((M.shape[1],M.shape[1]))
    groups=z["group"].astype(str).reset_index(drop=True)
    for _,idx in groups.groupby(groups).groups.items():
        idx=np.asarray(list(idx),int); score=M[idx].T@resid[idx]; meat+=np.outer(score,score)
    G=groups.nunique(); n=len(z); k=M.shape[1]
    correction=(G/(G-1))*((n-1)/max(n-k,1)) if G>1 else 1.0
    cov=correction*bread@meat@bread; se=np.sqrt(np.clip(np.diag(cov),0,np.inf))
    return beta[:1+len(exposures)],se[:1+len(exposures)],resid


def _fit_one(z: pd.DataFrame, y: str, exposures: list[str], with_event: bool) -> dict:
    try:
        import statsmodels.formula.api as smf
        rhs=" + ".join([f"Q('{x}')" for x in exposures]+["C(group)"]+(["C(event_id)"] if with_event else []))
        fit=smf.ols(f"Q('{y}') ~ {rhs}",data=z).fit(cov_type="cluster",cov_kwds={"groups":z["group"]})
        out={}
        for x in exposures:
            term=f"Q('{x}')";out[x]=(float(fit.params[term]),float(fit.bse[term]),float(fit.pvalues[term]))
        return {"engine":"statsmodels","terms":out}
    except Exception as exc:  # fallback is intentionally deterministic and dependency-free
        beta,se,_=_numpy_fe_fit(z,y,exposures,with_event);out={}
        for i,x in enumerate(exposures,1):
            b=float(beta[i]); s=float(se[i]); p=float(2*(1-norm.cdf(abs(b/s)))) if s>0 else np.nan
            out[x]=(b,s,p)
        return {"engine":f"numpy_cluster_fallback_after_{type(exc).__name__}","terms":out}


def fit_exposure_models(d: pd.DataFrame, cfg: Config, exposures: list[str]) -> pd.DataFrame:
    rows=[]
    specs=[([x],f"single:{x}") for x in exposures]
    primary=str(cfg.recovery_debt["primary_exposure"])
    if primary in d and "pre_event_debt" in d:
        specs.append(([primary,"pre_event_debt"],"joint_official_plus_observable_debt"))
    for xs,spec in specs:
        for y in OUTCOMES:
            z=d.dropna(subset=xs+[y,"group","event_id"]).copy()
            within=all(z.groupby("event_id")[x].nunique().gt(1).any() for x in xs) if not z.empty else False
            base={"model_spec":spec,"exposure":"+".join(xs),"target":y,"n_obs":len(z),
                  "n_event":z["event_id"].nunique(),"n_group":z["group"].nunique(),
                  "n_unique_exposure":min((z[x].nunique() for x in xs),default=0),
                  "within_event_variation":int(within)}
            if len(z)<30 or not within:
                rows.append(base|{"term":xs[0],"beta":np.nan,"se":np.nan,"ci_lo":np.nan,"ci_hi":np.nan,
                                  "p_value":np.nan,"identified":0,"model":"not_estimated",
                                  "note":"requires within-event exposure variation"});continue
            try:
                fit=_fit_one(z,y,xs,with_event=True)
                for term,(b,se,p) in fit["terms"].items():
                    rows.append(base|{"term":term,"beta":b,"se":se,"ci_lo":b-1.96*se,"ci_hi":b+1.96*se,
                                      "p_value":p,"identified":1,"model":"group+event FE cluster(group)",
                                      "note":fit["engine"]})
            except Exception as exc:
                rows.append(base|{"term":xs[0],"beta":np.nan,"se":np.nan,"ci_lo":np.nan,"ci_hi":np.nan,
                                  "p_value":np.nan,"identified":0,"model":"failed","note":f"{type(exc).__name__}: {exc}"})
    return pd.DataFrame(rows)


def make_dose_table(d: pd.DataFrame, exposure: str) -> pd.DataFrame:
    return d[["group","event_id","target_asn","target_admin1",exposure,"pre_event_debt",
              "deficit_auc_full","t90_h","max_deficit","recovery_censored","previously_unrecovered"]].rename(
        columns={exposure:"exposure_hours","deficit_auc_full":"next_auc","t90_h":"next_t90"})


def make_survival_table(d: pd.DataFrame, exposure: str, cfg: Config) -> pd.DataFrame:
    z=d.dropna(subset=[exposure]).copy()
    if z.empty:return pd.DataFrame(columns=["hours","surv_unrecovered","group_label","n"])
    if z[exposure].nunique()>=3:
        try:z["exposure_group"]=pd.qcut(z[exposure],3,labels=["low","medium","high"],duplicates="drop")
        except ValueError:z["exposure_group"]=np.where(z[exposure]>0,"positive","zero")
    else:z["exposure_group"]=np.where(z[exposure]>0,"positive","zero")
    end=float(cfg.recovery_debt["observation_end_hours"]);rows=[]
    for label,g in z.groupby("exposure_group",observed=True):
        duration=pd.to_numeric(g["t90_h"],errors="coerce").fillna(end).clip(upper=end)
        event=((g["recovery_censored"].fillna(1).astype(int)==0)&pd.to_numeric(g["t90_h"],errors="coerce").notna()&
               (pd.to_numeric(g["t90_h"],errors="coerce")<=end)).astype(int)
        t,s=km_survival(duration,event)
        rows.extend({"hours":float(tt),"surv_unrecovered":float(ss),"group_label":str(label),"n":len(g)} for tt,ss in zip(t,s))
    return pd.DataFrame(rows)


def run(cfg: Config) -> dict:
    logger=get_logger(cfg.out_dir("logs"));source=cfg.out_dir("data_derived")/"group_event_features.parquet"
    if not source.exists():raise FileNotFoundError(source)
    with step("Experiment D: accumulated exposure and recovery debt",logger):
        f=pd.read_parquet(source)
        attacks=f[f["analysis_role"].isin(["attack_national","attack_regional","blind_test","stress_test"]) & f["is_treated"].eq(1)].copy()
        e=cfg.load_event_registry()[["event_id","confound_weather","confound_holiday","confound_overlap","anchor_precision_h"]]
        attacks=attacks.merge(e,on="event_id",how="left",suffixes=("","_event"));d=build_exposure_panel(attacks,cfg)
        official=[f"outage_hours_{int(h)}h" for h in cfg.recovery_debt["lookbacks_hours"]]
        exposures=official+["pre_event_debt"]
        audit=variation_audit(d,exposures);models=fit_exposure_models(d,cfg,exposures)
        primary=str(cfg.recovery_debt["primary_exposure"])
        identified_official=models[(models["identified"].eq(1))&models["term"].isin(official)]
        selected=primary
        if identified_official.empty or not (identified_official["term"]==primary).any():
            # Exploratory fallback chooses the official lookback with the most within-event variation.
            scores={x:int(audit.loc[(audit.exposure.eq(x))&(audit.within_event_variation.eq(1)),"event_id"].nunique()) for x in official}
            selected=max(scores,key=scores.get) if scores else primary
        dose=make_dose_table(d,selected);survival=make_survival_table(d,selected,cfg)
        td=cfg.out_dir("results_tables");d.to_parquet(cfg.out_dir("data_derived")/"recovery_debt_panel.parquet",index=False)
        audit.to_csv(td/"exp_d_exposure_audit.csv",index=False);models.to_csv(td/"exp_d_models.csv",index=False)
        dose.to_csv(td/"f10_dose.csv",index=False);survival.to_csv(td/"f10_survival.csv",index=False)
        summary=pd.DataFrame([{"n_group_event":len(d),"preregistered_primary_exposure":primary,
                               "selected_plot_exposure":selected,"selected_is_preregistered":int(selected==primary),
                               "primary_nonzero_share":float((d[primary]>0).mean()) if primary in d and len(d) else np.nan,
                               "primary_unique":int(d[primary].nunique()) if primary in d else 0,
                               "n_identified_model":int(models["identified"].sum()) if not models.empty else 0,
                               "n_identified_official_model":int(identified_official.shape[0]),
                               "all_zero_failure":int(primary not in d or d[primary].max()<=0)}])
        summary.to_csv(td/"exp_d_summary.csv",index=False)
    return {"status":"ok" if not summary.iloc[0]["all_zero_failure"] else "failed_zero_exposure",
            "outputs":[str(td/x) for x in ["exp_d_models.csv","f10_dose.csv","f10_survival.csv","exp_d_exposure_audit.csv","exp_d_summary.csv"]]}
