"""Experiment A: scheduled-outage weak supervision with correct response denominators.

The decisive correction from v1 is that validation reach is responder_count / total_sensor_count.
The previous implementation averaged only returned rows, which cannot represent non-response.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import sqlutil as S
from .config import Config
from .db import CHClient
from .events import Events
from .progress import get_logger, pbar, step
from .stats import cluster_bootstrap_metric

METHODS = ["B0", "B1", "B2"]


def _prefix_batches(xs, n):
    xs=list(xs)
    for i in range(0,len(xs),n):yield xs[i:i+n], i//n


def _posterior_mean_var(x, n, a=0.5, b=0.5):
    aa=np.asarray(x,float)+a;bb=np.asarray(n,float)-np.asarray(x,float)+b;s=aa+bb
    return aa/s,(aa*bb)/(s*s*(s+1))


def score_endpoints(raw: pd.DataFrame, cfg: Config, stable_rate: float | None = None) -> pd.DataFrame:
    d=raw.copy(); stable=float(stable_rate if stable_rate is not None else cfg.baseline["stable_ip_resp_rate"])
    mN,vN=_posterior_mean_var(d["x_normal"],d["n_normal"])
    mP,vP=_posterior_mean_var(d["x_planned"],d["n_planned"])
    d["pN"]=mN;d["pP"]=mP;d["S"]=mN-mP;d["S_lo"]=d["S"]-norm.ppf(.975)*np.sqrt(vN+vP)
    d["in_B0"]=(d["x_normal"]+d["x_planned"]>0)
    configured_min=int(cfg.baseline["min_exposure_cycles"])
    available_normal=int(pd.to_numeric(d.get("n_normal"), errors="coerce").fillna(0).max()) if len(d) else 0
    effective_min=max(1, min(configured_min, available_normal))
    d["effective_min_exposure_cycles"] = effective_min
    d["exposure_support_downgraded"] = int(effective_min < configured_min)
    d["in_B1"]=d["in_B0"]&(d["pN"]>=stable)&(d["n_normal"]>=effective_min)
    d["in_B2"]=d["in_B1"]&(d["S_lo"]>0)
    return d



def matched_training_normal_cycles(grid: pd.DataFrame, ev: Events, cfg: Config) -> tuple[list[int], pd.DataFrame]:
    """Choose clean normal cycles with the same DOW×2h slot distribution as training outages.

    Sensor construction is prospective: normal cycles must occur before the first
    held-out scheduled-outage anchor.  Within each slot, choose the closest clean
    cycles to the training-outage cycles, with a frozen normal:planned ratio.
    """
    planned_ids = ev.planned_train_cycles(grid)
    if not planned_ids:
        return [], pd.DataFrame()
    planned = grid[grid["cycle_id"].isin(planned_ids)][["cycle_id","measure_time","slot"]].copy()
    # Freeze every endpoint feature before the first held-out outage. Clean
    # normal cycles after a training outage are allowed because they contain no
    # held-out label, but no cycle at or after the first validation anchor may
    # enter sensor construction.
    validation_anchors = [Events.anchor_time(r) for _, r in ev.planned_valid.iterrows()]
    validation_anchors = [x for x in validation_anchors if pd.notna(x)]
    cutoff = min(validation_anchors) if validation_anchors else planned["measure_time"].max() + pd.Timedelta(hours=1)
    clean = grid[ev.clean_baseline_mask(grid) & (grid["measure_time"] < cutoff)][["cycle_id","measure_time","slot"]].copy()
    ratio = int(cfg.calibration.get("normal_cycles_per_planned_cycle", 4))
    selected=[];audit=[]
    for slot, pg in planned.groupby("slot"):
        cand=clean[clean["slot"].eq(slot)].copy()
        need=int(len(pg)*ratio)
        if cand.empty:
            audit.append({"slot":int(slot),"planned_cycles":len(pg),"normal_candidates":0,
                          "normal_selected":0,"cutoff_utc":cutoff})
            continue
        # Minimum distance to any training outage in the same slot; deterministic tie-break by time.
        pt=pg["measure_time"].astype("int64").to_numpy()
        ct=cand["measure_time"].astype("int64").to_numpy()
        cand["distance_ns"]=[int(np.min(np.abs(pt-x))) for x in ct]
        take=cand.sort_values(["distance_ns","measure_time"]).head(need)
        selected.extend(take["cycle_id"].astype(int).tolist())
        audit.append({"slot":int(slot),"planned_cycles":len(pg),"normal_candidates":len(cand),
                      "normal_selected":len(take),"cutoff_utc":cutoff})
    return sorted(set(selected)), pd.DataFrame(audit)


def matched_validation_cycles(grid: pd.DataFrame, event: pd.Series, ev: Events,
                              cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return outage cycles and clean, slot-matched pre-event controls.

    Validation never labels post-outage recovery cycles as negatives.  Each positive
    outage cycle is compared with a frozen number of complete, clean cycles from the
    same day-of-week × two-hour slot and strictly before the held-out event.
    """
    pos_ids = ev.outage_cycles(grid, event)
    pos = grid[grid["cycle_id"].isin(pos_ids) & grid["is_complete"].eq(1)][
        ["cycle_id", "measure_time", "slot"]].drop_duplicates("cycle_id").copy()
    if pos.empty:
        return pd.DataFrame(), pd.DataFrame()
    cutoff = pd.to_datetime(event.get("outage_start_utc"), utc=True, errors="coerce")
    if pd.isna(cutoff):
        cutoff = Events.anchor_time(event)
    clean = grid[ev.clean_baseline_mask(grid) & (grid["measure_time"] < cutoff)][
        ["cycle_id", "measure_time", "slot"]].drop_duplicates("cycle_id").copy()
    zero_ids = ev.schedule_cycles(grid, event, positive=False, end_before=cutoff)
    same_day_zero = grid[grid["cycle_id"].isin(zero_ids)][
        ["cycle_id", "measure_time", "slot"]].drop_duplicates("cycle_id").copy()
    same_day_zero["control_source"] = "same_day_registered_zero"
    clean["control_source"] = "historical_clean_same_slot"
    ratio = int(cfg.calibration.get("validation_normal_cycles_per_planned_cycle", 4))
    controls, audit = [], []
    for slot, pg in pos.groupby("slot"):
        cand = pd.concat([same_day_zero[same_day_zero["slot"].eq(slot)],
                          clean[clean["slot"].eq(slot)]], ignore_index=True).drop_duplicates("cycle_id")
        need = int(len(pg) * ratio)
        if cand.empty:
            audit.append({"event_id": event["event_id"], "slot": int(slot),
                          "positive_cycles": len(pg), "control_candidates": 0,
                          "control_selected": 0, "cutoff_utc": cutoff})
            continue
        pt = pg["measure_time"].astype("int64").to_numpy()
        ct = cand["measure_time"].astype("int64").to_numpy()
        cand["distance_ns"] = [int(np.min(np.abs(pt - x))) for x in ct]
        cand["source_rank"] = cand["control_source"].map(
            {"same_day_registered_zero": 0, "historical_clean_same_slot": 1}).fillna(1)
        take = cand.sort_values(["source_rank", "distance_ns", "measure_time"]).head(need)
        controls.append(take[["cycle_id", "measure_time", "slot"]])
        audit.append({"event_id": event["event_id"], "slot": int(slot),
                      "positive_cycles": len(pg), "control_candidates": len(cand),
                      "control_selected": len(take),
                      "same_day_zero_selected": int(take["control_source"].eq("same_day_registered_zero").sum()),
                      "cutoff_utc": cutoff})
    neg = pd.concat(controls, ignore_index=True) if controls else pd.DataFrame(
        columns=["cycle_id", "measure_time", "slot"])
    dose = ev.schedule_cycle_dose(grid, event)
    pos = pos.merge(dose, on="cycle_id", how="left")
    pos["queue_count"] = pos["queue_count"].fillna(1.0)
    pos["control_source"] = "registered_positive_segment"
    neg["queue_count"] = 0.0
    if "control_source" not in neg:
        neg["control_source"] = "historical_clean_same_slot"
    pos["label"] = 1
    neg["label"] = 0
    selected = pd.concat([pos, neg], ignore_index=True).sort_values(
        ["cycle_id", "label"], ascending=[True, False]).drop_duplicates("cycle_id")
    selected["event_id"] = event["event_id"]
    return selected, pd.DataFrame(audit)


def _metrics(obs: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    from sklearn.metrics import average_precision_score, precision_recall_curve
    pr=[];au=[]
    for method,g in obs.groupby("method"):
        y=g["label"].astype(int).to_numpy();s=g["score"].astype(float).to_numpy()
        if len(np.unique(y))<2:
            au.append({"method":method,"auprc":np.nan,"n_obs":len(y),"prevalence":y.mean() if len(y) else np.nan});continue
        val=float(average_precision_score(y,s));au.append({"method":method,"auprc":val,"n_obs":len(y),"prevalence":float(y.mean())})
        p,r,t=precision_recall_curve(y,s)
        thresholds=np.r_[t,np.nan]
        pr.extend({"method":method,"recall":float(rr),"precision":float(pp),"threshold":float(tt) if np.isfinite(tt) else np.nan}
                  for pp,rr,tt in zip(p,r,thresholds))
    return pd.DataFrame(pr),pd.DataFrame(au)


def _delta_auprc(df: pd.DataFrame) -> float:
    from sklearn.metrics import average_precision_score
    vals={}
    for m in ("B1","B2"):
        g=df[df["method"].eq(m)]
        if g.empty or g["label"].nunique()<2:return np.nan
        vals[m]=average_precision_score(g["label"],g["score"])
    return float(vals["B2"]-vals["B1"])


def weather_sensitivity(obs: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, dict]:
    """Prespecified robustness checks; never changes the frozen B1/B2 choice."""
    wcfg = cfg.calibration.get("weather_sensitivity", {})
    path = cfg.root / str(wcfg.get("data_path", "data_derived/weather_admin1_2h.parquet"))
    empty = {"weather_sensitivity_ready": 0, "weather_robust_positive": 0,
             "weather_path": str(path), "weather_coverage": 0.0}
    if not path.exists():
        return pd.DataFrame([{"analysis": "not_available", "delta_b2_vs_b1": np.nan}]), empty
    weather = pd.read_parquet(path)
    required = set(wcfg.get("required_columns", []))
    if required - set(weather.columns):
        return pd.DataFrame([{"analysis": "missing_columns", "delta_b2_vs_b1": np.nan}]), empty
    z = obs.copy()
    z["weather_bin"] = pd.to_datetime(z["measure_time"], utc=True).dt.floor("2h")
    weather["weather_bin"] = pd.to_datetime(weather["measure_time"], utc=True).dt.floor("2h")
    weather = weather.rename(columns={"admin1": "target_admin1"}).drop(columns=["measure_time"])
    z = z.merge(weather, on=["weather_bin", "target_admin1"], how="left", validate="many_to_one")
    coverage = float(z["t2m_mean_c"].notna().mean()) if len(z) else 0.0
    rows = []
    rows.append({"analysis": "all_unadjusted", "delta_b2_vs_b1": _delta_auprc(z)})
    no_aug = z[~z["independence_cluster"].eq("august_heat")]
    rows.append({"analysis": "exclude_august_heat_cluster", "delta_b2_vs_b1": _delta_auprc(no_aug)})
    for flag, group in z.dropna(subset=["official_heat_warning"]).groupby("official_heat_warning"):
        rows.append({"analysis": f"official_heat_warning_{int(flag)}",
                     "delta_b2_vs_b1": _delta_auprc(group)})
    # Residualize each method's score against weather among negative controls,
    # then evaluate the held-out labels. This removes smooth weather-associated
    # reach variation without learning from outage labels.
    covars = [c for c in wcfg.get("primary_covariates", []) if c in z]
    adjusted = []
    if covars and coverage >= 0.9:
        for method, group in z.groupby("method"):
            g = group.dropna(subset=covars + ["score"]).copy()
            controls = g[g["label"].eq(0)]
            if len(controls) <= len(covars) + 2:
                continue
            x0 = np.column_stack([np.ones(len(controls)), controls[covars].to_numpy(float)])
            beta = np.linalg.lstsq(x0, controls["score"].to_numpy(float), rcond=None)[0]
            xa = np.column_stack([np.ones(len(g)), g[covars].to_numpy(float)])
            g["score"] = g["score"].to_numpy(float) - xa @ beta
            adjusted.append(g)
    adjusted_delta = _delta_auprc(pd.concat(adjusted, ignore_index=True)) if adjusted else np.nan
    rows.append({"analysis": "negative-control_weather_residualized",
                 "delta_b2_vs_b1": adjusted_delta})
    result = pd.DataFrame(rows)
    decisive = result[result["analysis"].isin(
        ["exclude_august_heat_cluster", "negative-control_weather_residualized"]
    )]["delta_b2_vs_b1"].dropna()
    status = {"weather_sensitivity_ready": int(coverage >= 0.9 and len(decisive) == 2),
              "weather_robust_positive": int(len(decisive) == 2 and (decisive > 0).all()),
              "weather_path": str(path), "weather_coverage": coverage}
    return result, status


def run(cfg: Config) -> dict:
    logger=get_logger(cfg.out_dir("logs"));dd=cfg.out_dir("data_derived");rt=cfg.out_dir("results_tables")
    cq=pd.read_parquet(dd/"cycle_quality.parquet");grid=Events(cfg).build_cycle_grid(cq);ev=Events(cfg)
    planned=ev.planned_train_cycles(grid)
    normal, training_cycle_audit = matched_training_normal_cycles(grid, ev, cfg)
    if not normal or not planned:raise RuntimeError("Experiment A requires slot-matched prospective normal and planned training cycles")
    training_cycle_audit.to_csv(rt/"exp_a_training_cycle_audit.csv",index=False)
    # Endpoint-level frozen mapping is the primary contract.  Country-only
    # Ukrainian endpoints are valid for national planned-outage calibration,
    # but will be excluded from regional attack inference downstream.
    targets=pd.read_parquet(dd/"target_ip_universe.parquet")
    targets=targets[targets.national_eligible.eq(1)].copy()
    prefixes=targets.prefix24.drop_duplicates().astype(str).tolist(); batch_n=int(cfg.runtime["prefix_batch"])
    raw_dir=dd/"ip_sensor_scores_parts";raw_dir.mkdir(exist_ok=True)
    h=int(cfg.study["expected_cycle_interval_hours"]);all_ids=sorted(set(normal)|set(planned))
    outputs=[]
    with step("A1 score endpoints",logger):
        with CHClient(cfg) as ch:
            for pb,bi in pbar(list(_prefix_batches(prefixes,batch_n)),desc="sensor batches",unit="batch"):
                p=raw_dir/f"part_{bi:05d}.parquet"
                if p.exists():continue
                q=S.render("04_ip_scores",ping=cfg.table("ping"),dc=cfg.study["data_center"],
                           prefix_in=S.str_list(pb),normal_cids=S.int_list(normal),planned_cids=S.int_list(planned),
                           all_cids=S.int_list(all_ids),cycle_seconds=h*3600)
                d=ch.query_df(q)
                if d.empty:continue
                # Target identity/geography is inherited only from the frozen target-IP mapping
                # audit.  Do not parse ASGeo path text or ISP fields and do not rely on stale
                # denormalised labels in the response table.
                d=d.drop(columns=[c for c in ["target_asn_raw","target_country_raw","target_admin1_raw"] if c in d], errors="ignore")
                d=d.merge(targets[["dst_ip","prefix24","target_asn","target_country","target_admin1",
                                     "regional_eligible","country_only_admin1","group","analysis_unit_id"]],
                          on=["dst_ip","prefix24"], how="inner", validate="many_to_one")
                d=d[(d.target_country=="Ukraine")&(d.target_asn>0)]
                d["n_normal"]=len(normal);d["n_planned"]=len(planned)
                d=score_endpoints(d,cfg)
                d.to_parquet(p,index=False)
    parts=sorted(glob.glob(str(raw_dir/"part_*.parquet")))
    if not parts:raise RuntimeError("No endpoint scores were produced")
    # Sensor denominators and expected normal response mass.
    denom=[]
    for p in parts:
        d=pd.read_parquet(p)
        for m in METHODS:
            x=d[d[f"in_{m}"]]
            if not x.empty:
                denom.append(x.groupby("target_admin1").agg(
                    sensor_n=("dst_ip","nunique"), expected_response_n=("pN","sum")
                ).reset_index().assign(method=m))
    if not denom:
        raise RuntimeError("No B0/B1/B2 validation denominators")
    denom=(pd.concat(denom).groupby(["method","target_admin1"]).agg(
        sensor_n=("sensor_n","sum"), expected_response_n=("expected_response_n","sum")
    ).reset_index())

    # Freeze held-out positives and slot-matched pre-event controls before querying responses.
    validation_cycles={}
    validation_audits=[]
    for _,event in ev.planned_valid.iterrows():
        selected,audit=matched_validation_cycles(grid,event,ev,cfg)
        if not audit.empty: validation_audits.append(audit)
        if not selected.empty: validation_cycles[str(event.event_id)]=selected
    cycle_audit=(pd.concat(validation_audits,ignore_index=True) if validation_audits else pd.DataFrame())
    cycle_audit.to_csv(rt/"exp_a_validation_cycle_audit.csv",index=False)
    if len(validation_cycles)<int(cfg.calibration["min_validation_events"]):
        raise RuntimeError("Too few held-out scheduled-outage events have matched validation cycles")

    numer=[]
    with step("A2 held-out scheduled-outage validation",logger):
        with CHClient(cfg) as ch:
            for _,event in pbar(list(ev.planned_valid.iterrows()),total=len(ev.planned_valid),desc="validation events",unit="event"):
                selected=validation_cycles.get(str(event.event_id))
                if selected is None or selected.empty: continue
                cycle_ids=selected["cycle_id"].astype(int).tolist()
                for p in parts:
                    sensors=pd.read_parquet(p,columns=["dst_ip","prefix24","target_admin1","pN","in_B0","in_B1","in_B2"])
                    pb=sensors.prefix24.drop_duplicates().astype(str).tolist()
                    q=S.render("10_ping_response_cycles",ping=cfg.table("ping"),dc=cfg.study["data_center"],
                               prefix_in=S.str_list(pb),cycle_ids=S.int_list(cycle_ids),cycle_seconds=h*3600)
                    resp=ch.query_df(q)
                    if resp.empty: continue
                    resp=resp.merge(sensors,on=["dst_ip","prefix24"],how="inner")
                    for m in METHODS:
                        x=resp[resp[f"in_{m}"]]
                        if x.empty: continue
                        a=x.groupby(["cycle_id","target_admin1"])["dst_ip"].nunique().rename("responders").reset_index()
                        a["method"]=m;a["event_id"]=event.event_id;numer.append(a)
    if not numer: raise RuntimeError("No held-out validation responses; check event cycles and sensor mapping")
    num=pd.concat(numer).groupby(["event_id","cycle_id","target_admin1","method"])["responders"].sum().reset_index()
    rows=[]
    for event_id,c in validation_cycles.items():
        x=denom.merge(c[["cycle_id","measure_time","slot","label","queue_count","control_source"]],how="cross")
        x["event_id"]=event_id;rows.append(x)
    val=pd.concat(rows,ignore_index=True).merge(num,on=["event_id","cycle_id","target_admin1","method"],how="left")
    val["responders"]=val.responders.fillna(0)
    val["reach"]=val.responders/val.sensor_n.replace(0,np.nan)
    val["normalized_reach"]=val.responders/val.expected_response_n.replace(0,np.nan)
    val["score"]=1-val.normalized_reach
    meta = {str(eid): ev.schedule_event_metadata(str(eid)) for eid in validation_cycles}
    val["independence_cluster"] = val["event_id"].astype(str).map(
        lambda x: meta[x]["independence_cluster"])
    val["publication_eligible"] = val["event_id"].astype(str).map(
        lambda x: meta[x]["publication_eligible"]).astype(int)
    val["max_queue_count"] = val["event_id"].astype(str).map(
        lambda x: meta[x].get("max_queue_count", np.nan))
    # Bootstrap at the independently registered episode, not at the nominal
    # date, so consecutive August schedules cannot masquerade as replication.
    val["block"]=val.independence_cluster.astype(str)+"|"+val.target_admin1.astype(str)
    obs=val.dropna(subset=["score"])[["event_id","cycle_id","measure_time","slot","target_admin1","method",
                                      "score","label","sensor_n","expected_response_n","responders",
                                      "reach","normalized_reach","independence_cluster",
                                      "publication_eligible","max_queue_count","queue_count",
                                      "control_source","block"]]
    weather_table, weather_status = weather_sensitivity(obs, cfg)
    weather_table.to_csv(rt/"exp_a_weather_sensitivity.csv", index=False, encoding="utf-8-sig")
    pr,au=_metrics(obs)
    delta,lo,hi,boots=cluster_bootstrap_metric(obs,"block",_delta_auprc,n_boot=int(cfg.runtime["n_bootstrap"]),ci=float(cfg.inference["ci_level"]),seed=int(cfg.runtime["random_seed"]))
    # Permutation null: shuffle labels within each held-out event/Admin1 block.
    rng=np.random.default_rng(int(cfg.runtime["random_seed"]));null=[]
    for _ in range(int(cfg.calibration["permutation_repetitions"])):
        z=obs.copy();z["label"]=z.groupby("block")["label"].transform(lambda s:rng.permutation(s.values));null.append(_delta_auprc(z))
    perm_p=float((np.sum(np.asarray(null)>=delta)+1)/(len(null)+1)) if np.isfinite(delta) else np.nan

    # Event-specific consistency gate prevents one held-out event from carrying the result.
    from sklearn.metrics import average_precision_score
    event_rows=[]
    for event_id,g in obs.groupby("event_id"):
        vals={}
        for method,m in g.groupby("method"):
            vals[method]=(float(average_precision_score(m["label"],m["score"]))
                          if m["label"].nunique()>=2 else np.nan)
        event_rows.append({"event_id":event_id,
                           "independence_cluster":str(g["independence_cluster"].iloc[0]),
                           "publication_eligible":int(g["publication_eligible"].max()),
                           "max_queue_count":float(g["max_queue_count"].max()),
                           "auprc_B0":vals.get("B0",np.nan),
                           "auprc_B1":vals.get("B1",np.nan),
                           "auprc_B2":vals.get("B2",np.nan),
                           "delta_b2_vs_b1":vals.get("B2",np.nan)-vals.get("B1",np.nan),
                           "n_cycle":g["cycle_id"].nunique(),
                           "n_admin1":g["target_admin1"].nunique()})
    event_metrics=pd.DataFrame(event_rows)
    estimable=event_metrics["delta_b2_vs_b1"].dropna() if not event_metrics.empty else pd.Series(dtype=float)
    eligible_metrics = event_metrics[(event_metrics["publication_eligible"].eq(1)) &
                                     event_metrics["delta_b2_vs_b1"].notna()].copy()
    cluster_metrics = (eligible_metrics.groupby("independence_cluster", as_index=False)
                       .agg(delta_b2_vs_b1=("delta_b2_vs_b1", "mean"),
                            n_event=("event_id", "nunique")))
    n_publication_clusters = int(len(cluster_metrics))
    positive_cluster_fraction = float((cluster_metrics["delta_b2_vs_b1"] > 0).mean()) if len(cluster_metrics) else 0.0
    positive_fraction=float((estimable>0).mean()) if len(estimable) else 0.0
    b2_n=int(denom.loc[denom.method.eq("B2"),"sensor_n"].sum())
    success=(len(estimable)>=int(cfg.calibration["min_validation_events"]) and
             b2_n>=int(cfg.calibration["min_b2_ip"]) and np.isfinite(lo) and
             (lo>0 if cfg.calibration["require_ci_lower_gt_zero"] else delta>0) and
             positive_fraction>=float(cfg.calibration.get("min_positive_validation_event_fraction",0)))
    publication_min_events=int(cfg.calibration.get("min_publication_validation_events",2))
    publication_min_clusters=int(cfg.calibration.get("min_publication_validation_clusters",2))
    configured_exposure_ok = effective_min_exposure_ok = True  # filled after reading the immutable score parts below
    if parts:
        _sample = pd.read_parquet(parts[0], columns=["effective_min_exposure_cycles"])
        if not _sample.empty:
            effective_min_exposure_ok = int(_sample["effective_min_exposure_cycles"].iloc[0]) >= int(cfg.baseline["min_exposure_cycles"])
    configured_exposure_ok = (effective_min_exposure_ok or
                              not bool(cfg.calibration.get("publication_requires_configured_exposure", True)))
    publication_closed=bool(success and len(estimable)>=publication_min_events and
                            n_publication_clusters>=publication_min_clusters and
                            positive_cluster_fraction>=float(cfg.calibration.get("min_positive_validation_event_fraction",0)) and
                            configured_exposure_ok)
    if publication_closed:
        evidence_grade="publication_grade_multi_event_holdout"
    elif success and not effective_min_exposure_ok:
        evidence_grade="provisional_reduced_exposure_support"
    elif success:
        evidence_grade="provisional_single_event_holdout"
    else:
        evidence_grade="negative_or_inconclusive_calibration"
    summary=au.merge(denom.groupby("method")["sensor_n"].sum().rename("n_ip"),on="method",how="left")
    effective_min_exposure = 0
    if parts:
        sample = pd.read_parquet(parts[0], columns=["effective_min_exposure_cycles"])
        if not sample.empty:
            effective_min_exposure = int(sample["effective_min_exposure_cycles"].iloc[0])
    summary["effective_min_exposure_cycles"] = effective_min_exposure
    summary["configured_min_exposure_cycles"] = int(cfg.baseline["min_exposure_cycles"])
    summary["exposure_support_downgraded"] = int(effective_min_exposure < int(cfg.baseline["min_exposure_cycles"]))
    summary["training_label_quality"] = str(cfg.calibration.get("primary_label_quality", "L3_national_time"))
    summary["validation_label_quality"] = str(cfg.calibration.get("primary_label_quality", "L3_national_time"))
    summary["claim_scope"] = "national_time_window_weak_supervision_not_ip_level_power_truth"
    summary["delta_b2_vs_b1"]=delta;summary["delta_ci_lo"]=lo;summary["delta_ci_hi"]=hi
    summary["permutation_p"]=perm_p;summary["positive_validation_event_fraction"]=positive_fraction
    summary["n_estimable_validation_event"]=len(estimable);summary["calibration_success"]=success
    summary["n_publication_validation_cluster"] = n_publication_clusters
    summary["min_publication_validation_clusters"] = publication_min_clusters
    summary["positive_validation_cluster_fraction"] = positive_cluster_fraction
    summary["publication_calibration_closed"]=publication_closed
    summary["min_publication_validation_events"]=publication_min_events
    summary["calibration_evidence_grade"]=evidence_grade
    for key, value in weather_status.items():
        summary[key] = value
    summary["interpretation"]=np.where(
        publication_closed,
        "Scheduled-outage calibration adds multi-event held-out predictive value",
        np.where(success,
                 "B2 passed an operational weak-label gate but lacks multi-event/configured-exposure publication support; treat it as provisional",
                 "Calibration did not beat the stable-IP baseline under the preregistered gate"))
    # Exploratory sensor-count sensitivity only.  This does not replace the frozen
    # S_lo>0 B2 definition and is never used to choose a post-hoc primary threshold.
    sens_rows=[]
    qvals=[float(x) for x in cfg.calibration.get("threshold_sensitivity_quantiles", [])]
    for part in parts:
        _d=pd.read_parquet(part, columns=["S","S_lo","in_B1"])
        _d=_d[_d["in_B1"]]
        if _d.empty: continue
        for qv in qvals:
            thr=float(_d["S"].quantile(qv))
            sens_rows.append({"quantile":qv,"threshold_S":thr,"selected_ip_n":int((_d["S"]>=thr).sum()),"part":Path(part).name})
    if sens_rows:
        _sens=pd.DataFrame(sens_rows).groupby("quantile").agg(threshold_S_median=("threshold_S","median"),selected_ip_n=("selected_ip_n","sum")).reset_index()
    else:
        _sens=pd.DataFrame(columns=["quantile","threshold_S_median","selected_ip_n"])
    _sens.to_csv(rt/"exp_a_sensor_threshold_sensitivity.csv",index=False,encoding="utf-8-sig")
    event_metrics.to_csv(rt/"exp_a_event_metrics.csv",index=False,encoding="utf-8-sig")
    cluster_metrics.to_csv(rt/"exp_a_cluster_metrics.csv",index=False,encoding="utf-8-sig")
    dose_table = (obs.groupby(["event_id", "independence_cluster", "method", "queue_count"], as_index=False)
                  .agg(mean_normalized_reach=("normalized_reach", "mean"),
                       n_cycle=("cycle_id", "nunique"),
                       n_admin1=("target_admin1", "nunique")))
    dose_table["mean_deficit"] = 1 - dose_table["mean_normalized_reach"]
    dose_table.to_csv(rt/"exp_a_queue_dose.csv",index=False,encoding="utf-8-sig")
    # Do not concatenate millions of IP rows into RAM. Keep the immutable part files and
    # write a small manifest plus selected B1/B2 partitions for downstream inspection.
    selected_dir=dd/"ip_sensor_selected_parts";selected_dir.mkdir(exist_ok=True)
    manifest_rows=[]
    for i,part in enumerate(parts):
        d=pd.read_parquet(part)
        sel=d[d["in_B1"]|d["in_B2"]].copy()
        sp=selected_dir/f"part_{i:05d}.parquet"
        if not sel.empty: sel.to_parquet(sp,index=False)
        manifest_rows.append({"part":str(Path(part).name),"n_all":len(d),"n_B1":int(d.in_B1.sum()),
                              "n_B2":int(d.in_B2.sum()),"selected_part":str(sp.name) if not sel.empty else ""})
    pd.DataFrame(manifest_rows).to_csv(rt/"ip_sensor_score_parts_manifest.csv",index=False)
    obs.to_csv(rt/"exp_a_validation_long.csv",index=False,encoding="utf-8-sig");pr.to_csv(rt/"f3_pr.csv",index=False,encoding="utf-8-sig");au.to_csv(rt/"f3_auprc.csv",index=False,encoding="utf-8-sig");summary.to_csv(rt/"exp_a_summary.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame({"bootstrap_delta":boots}).to_csv(rt/"exp_a_bootstrap_delta.csv",index=False)
    pd.DataFrame({"permutation_delta":null}).to_csv(rt/"exp_a_permutation_null.csv",index=False)
    return {"status":"ok","calibration_success":bool(success),
            "publication_calibration_closed":publication_closed,
            "calibration_evidence_grade":evidence_grade,
            "outputs":[str(raw_dir),str(selected_dir),str(rt/"exp_a_summary.csv"),str(rt/"f3_pr.csv"),str(rt/"f3_auprc.csv"),str(rt/"exp_a_training_cycle_audit.csv"),str(rt/"exp_a_validation_cycle_audit.csv"),str(rt/"exp_a_event_metrics.csv"),str(rt/"exp_a_sensor_threshold_sensitivity.csv"),str(rt/"exp_a_weather_sensitivity.csv")]}
