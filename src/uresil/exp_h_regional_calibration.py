"""Experiment H: oblast-specific power-sensitivity calibration and LOO validation."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from . import sqlutil as S
from .config import Config, file_sha256
from .db import CHClient
from .events import Events
from .exp_a_calibration import _prefix_batches, score_endpoints
from .label_precision import package_root
from .progress import get_logger, pbar, step
from .regional_calibration import (apply_conflict_masks, build_regional_event_registry,
                                   leave_one_event_out_splits, membership_stability,
                                   regional_event_cycles, select_repeated_sensitive)


def _matched_controls(grid, positives, events: Events, cfg: Config) -> pd.DataFrame:
    clean = grid[events.clean_baseline_mask(grid)].copy()
    cutoff = positives.measure_time.min()
    clean = clean[clean.measure_time < cutoff]
    ratio = int(cfg.calibration.get("validation_normal_cycles_per_planned_cycle", 4))
    rows = []
    for slot, pos in positives.groupby("slot"):
        c = clean[clean.slot.eq(slot)].copy()
        if c.empty:
            continue
        ptime = pos.measure_time.astype("int64").to_numpy()
        c["distance"] = [int(np.min(np.abs(ptime - x))) for x in c.measure_time.astype("int64")]
        rows.append(c.sort_values(["distance", "measure_time"]).head(len(pos) * ratio))
    return pd.concat(rows, ignore_index=True).drop_duplicates("cycle_id") if rows else pd.DataFrame()


def _load_inputs(cfg: Config):
    norm = package_root(cfg.root) / "normalized"
    updates = pd.read_csv(norm / "oblast_execution_updates_official.csv")
    queues = pd.read_csv(norm / "khmelnytskyi_published_queue_schedule.csv")
    national = pd.read_csv(norm / "national_dispatch_segments_official.csv")
    conflicts = pd.read_csv(norm / "published_schedule_vs_final_dispatch_conflicts.csv")
    queues = apply_conflict_masks(queues, conflicts, national)
    return build_regional_event_registry(updates, queues), [norm / x for x in (
        "oblast_execution_updates_official.csv", "khmelnytskyi_published_queue_schedule.csv",
        "national_dispatch_segments_official.csv", "published_schedule_vs_final_dispatch_conflicts.csv")]


def _query_event(ch, cfg, targets, normal, planned, score_path, response_path):
    prefixes = targets.prefix24.drop_duplicates().astype(str).tolist()
    h = int(cfg.study["expected_cycle_interval_hours"]); all_ids = sorted(set(normal) | set(planned))
    scores=[]; responses=[]
    for pb, _ in pbar(list(_prefix_batches(prefixes, int(cfg.runtime["prefix_batch"]))),
                      desc=f"regional {score_path.stem}", unit="batch"):
        q=S.render("04_ip_scores", ping=cfg.table("ping"), dc=cfg.study["data_center"],
                   prefix_in=S.str_list(pb), normal_cids=S.int_list(normal),
                   planned_cids=S.int_list(planned), all_cids=S.int_list(all_ids),
                   cycle_seconds=h*3600)
        d=ch.query_df(q)
        if not d.empty:
            d=d.merge(targets[["dst_ip","prefix24","target_admin1"]],
                      on=["dst_ip","prefix24"], how="inner", validate="many_to_one")
            d["n_normal"]=len(normal); d["n_planned"]=len(planned)
            scores.append(score_endpoints(d,cfg))
        qr=S.render("10_ping_response_cycles", ping=cfg.table("ping"), dc=cfg.study["data_center"],
                    prefix_in=S.str_list(pb), cycle_ids=S.int_list(all_ids), cycle_seconds=h*3600)
        r=ch.query_df(qr)
        if not r.empty:
            r=r.merge(targets[["dst_ip","prefix24"]],on=["dst_ip","prefix24"],how="inner")
            responses.append(r)
    if not scores:
        raise RuntimeError(f"no regional endpoint scores for {score_path.stem}")
    pd.concat(scores,ignore_index=True).to_parquet(score_path,index=False)
    (pd.concat(responses,ignore_index=True) if responses else
     pd.DataFrame(columns=["cycle_id","dst_ip","prefix24","rtt_ms"])).to_parquet(response_path,index=False)


def _evaluate_loo(all_scores, artifacts, splits, cfg):
    rows=[]
    for split in splits:
        admin1=split["target_admin1"]; hold=split["holdout_event_id"]
        train=all_scores[(all_scores.target_admin1.eq(admin1)) &
                         (all_scores.event_id.isin(split["train_event_ids"]))]
        selected=select_repeated_sensitive(train,
            min_events=int(cfg.regional_calibration["min_train_events"]),
            min_positive_fraction=float(cfg.regional_calibration["min_positive_event_fraction"]))
        # Missing from any training event is itself endpoint instability, not
        # evidence that may be silently ignored by groupby.
        complete = selected.training_event_n.eq(len(split["train_event_ids"]))
        selected["in_B1_region"] &= complete
        selected["in_B2_region"] &= complete
        pnorm=(train.groupby("dst_ip",as_index=False).pN.median().rename(columns={"pN":"expected"}))
        selected=selected.merge(pnorm,on="dst_ip",how="left")
        cycles=artifacts[hold]["cycles"]; resp=pd.read_parquet(artifacts[hold]["responses"])
        metric={}
        for method,col in (("B1_region","in_B1_region"),("B2_region","in_B2_region")):
            sensor=selected[selected[col]].copy(); ids=set(sensor.dst_ip)
            expected_values=pd.to_numeric(sensor.expected,errors="coerce").replace([np.inf,-np.inf],np.nan).dropna()
            expected=float(expected_values.sum()) if not expected_values.empty else np.nan
            n=len(sensor)
            count=resp[resp.dst_ip.isin(ids)].groupby("cycle_id").dst_ip.nunique()
            z=cycles.copy(); z["responders"]=z.cycle_id.map(count).fillna(0)
            if np.isfinite(expected) and expected > 0:
                z["score"]=1-z.responders/expected
            else:
                z["score"]=np.nan
            labels=pd.to_numeric(z["label"],errors="coerce")
            scores=pd.to_numeric(z["score"],errors="coerce")
            valid=labels.notna() & scores.notna() & np.isfinite(scores)
            # A region with no finite normal-period baseline is not a valid
            # scoring stratum.  Keep the row for auditability, but never let
            # sklearn raise and abort all other regions/holdouts.
            if valid.sum() >= 2 and labels[valid].nunique() > 1:
                metric[method]=average_precision_score(labels[valid],scores[valid])
            else:
                metric[method]=np.nan
            rows.append({"target_admin1":admin1,"holdout_event_id":hold,"method":method,
                         "auprc":metric[method],"sensor_n":n,"n_cycle":len(z),
                         "valid_cycle_n":int(valid.sum()),"expected_baseline":expected})
        rows[-1]["delta_b2_vs_b1"] = metric.get("B2_region",np.nan)-metric.get("B1_region",np.nan)
    return pd.DataFrame(rows)


def _equal_region_meta(loo: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Equal-region hierarchical bootstrap; does not let a large oblast dominate."""
    if loo.empty:
        return pd.DataFrame()
    d=loo[loo.method.eq("B2_region") & loo.delta_b2_vs_b1.notna()].copy()
    rows=[]; rng=np.random.default_rng(int(cfg.runtime["random_seed"])+2500)
    for buffer_minutes,g in d.groupby("transition_buffer_minutes"):
        means=g.groupby("target_admin1").delta_b2_vs_b1.mean()
        boots=[]
        for _ in range(int(cfg.runtime["n_bootstrap"])):
            sampled=[]
            for _,rg in g.groupby("target_admin1"):
                sampled.append(float(rg.sample(len(rg),replace=True,
                                               random_state=int(rng.integers(0,2**31-1))).delta_b2_vs_b1.mean()))
            boots.append(float(np.mean(sampled)))
        rows.append({"target_admin1":"ALL_REGIONS_EQUAL_WEIGHT",
                     "transition_buffer_minutes":buffer_minutes,
                     "mean_delta_b2_vs_b1":float(means.mean()),
                     "ci_lo":float(np.quantile(boots,.025)),"ci_hi":float(np.quantile(boots,.975)),
                     "between_region_sd":float(means.std(ddof=1)) if len(means)>1 else np.nan,
                     "region_n":int(len(means)),"holdout_n":int(g.holdout_event_id.nunique())})
    return pd.DataFrame(rows)


def run(cfg: Config) -> dict:
    rcfg=cfg.regional_calibration
    if not bool(rcfg.get("enabled",True)):
        return {"status":"warning","outputs":[],"reason":"regional calibration disabled"}
    logger=get_logger(cfg.out_dir("logs")); dd=cfg.out_dir("data_derived"); rt=cfg.out_dir("results_tables")
    registry,input_paths=_load_inputs(cfg)
    grid=Events(cfg).build_cycle_grid(pd.read_parquet(dd/"cycle_quality.parquet")); ev=Events(cfg)
    buffer_values=sorted(set(int(x) for x in rcfg.get(
        "transition_buffer_sensitivity_minutes", [rcfg["transition_buffer_minutes"]])))
    cycles_by_buffer={b:regional_event_cycles(registry,grid,regions=list(rcfg["primary_regions"]),
        dates=[str(x) for x in rcfg["core_dates"]],cycle_hours=float(cfg.study["expected_cycle_interval_hours"]),
        min_overlap_fraction=float(cfg.calibration["min_cycle_schedule_overlap_fraction"]),
        transition_buffer_minutes=b) for b in buffer_values}
    targets=pd.read_parquet(dd/"target_ip_universe.parquet")
    base=dd/"regional_calibration"; score_dir=base/"ip_sensor_scores_by_training_event"; resp_dir=base/"responses_by_event"
    score_dir.mkdir(parents=True,exist_ok=True); resp_dir.mkdir(parents=True,exist_ok=True)
    artifacts={}; audits=[]
    with step("H oblast-specific calibration cache",logger):
        with CHClient(cfg) as ch:
            for buffer_minutes, cycles in cycles_by_buffer.items():
                for event_id,pos in cycles.items():
                    if pos.empty: continue
                    admin1=str(pos.target_admin1.iloc[0])
                    region_targets=targets[(targets.regional_eligible.eq(1))&targets.target_admin1.eq(admin1)]
                    controls=_matched_controls(grid,pos,ev,cfg)
                    if controls.empty: continue
                    selected=pd.concat([pos.assign(label=1),controls.assign(label=0)],ignore_index=True)
                    sp=score_dir/f"{event_id}.parquet"; rp=resp_dir/f"{event_id}.parquet"
                    if not sp.exists() or not rp.exists():
                        _query_event(ch,cfg,region_targets,controls.cycle_id.astype(int).tolist(),
                                     pos.cycle_id.astype(int).tolist(),sp,rp)
                    artifacts[event_id]={"scores":sp,"responses":rp,"cycles":selected,
                                         "transition_buffer_minutes":buffer_minutes}
                    audits.append({"event_id":event_id,"target_admin1":admin1,"positive_cycle_n":len(pos),
                                   "control_cycle_n":len(controls),"target_ip_n":region_targets.dst_ip.nunique(),
                                   "transition_buffer_minutes":buffer_minutes})
    score_frames=[]
    for event_id,a in artifacts.items():
        d=pd.read_parquet(a["scores"]); d["event_id"]=event_id
        d["transition_buffer_minutes"]=a["transition_buffer_minutes"]; score_frames.append(d)
    if not score_frames:
        raise RuntimeError("no regional event score artifacts produced")
    scores=pd.concat(score_frames,ignore_index=True)
    loo_parts=[]; stability_parts=[]; split_n=0
    for buffer_minutes,bscore in scores.groupby("transition_buffer_minutes"):
        splits=leave_one_event_out_splits(bscore,int(rcfg["min_train_events"])); split_n += len(splits)
        z=_evaluate_loo(bscore,artifacts,splits,cfg); z["transition_buffer_minutes"]=buffer_minutes; loo_parts.append(z)
        s=membership_stability(bscore); s["transition_buffer_minutes"]=buffer_minutes; stability_parts.append(s)
    loo=pd.concat(loo_parts,ignore_index=True) if loo_parts else pd.DataFrame()
    stability=pd.concat(stability_parts,ignore_index=True) if stability_parts else pd.DataFrame()
    final_members=[]
    for (buffer_minutes,admin1),g in scores.groupby(["transition_buffer_minutes","target_admin1"]):
        m=select_repeated_sensitive(g,min_events=int(rcfg["min_train_events"]),
                                    min_positive_fraction=float(rcfg["min_positive_event_fraction"]))
        total_events=g.event_id.nunique()
        complete=m.training_event_n.eq(total_events)
        m["in_B1_region"] &= complete; m["in_B2_region"] &= complete
        m["transition_buffer_minutes"]=buffer_minutes; m["available_event_n"]=total_events
        final_members.append(m)
    membership=pd.concat(final_members,ignore_index=True) if final_members else pd.DataFrame()
    membership_path=base/"regional_sensor_membership.parquet"
    membership.to_parquet(membership_path,index=False)
    summary=(loo[loo.method.eq("B2_region")].groupby(["target_admin1","transition_buffer_minutes"],as_index=False)
             .agg(mean_delta_b2_vs_b1=("delta_b2_vs_b1","mean"),holdout_n=("holdout_event_id","nunique"))) if not loo.empty else pd.DataFrame()
    meta=_equal_region_meta(loo,cfg)
    if not meta.empty:
        summary=pd.concat([summary,meta],ignore_index=True,sort=False)
    pd.DataFrame(audits).to_csv(rt/"regional_calibration_cycle_audit.csv",index=False)
    loo.to_csv(rt/"regional_calibration_loo.csv",index=False); stability.to_csv(rt/"regional_b2_membership_stability.csv",index=False)
    summary.to_csv(rt/"regional_calibration_meta_summary.csv",index=False)
    provenance={"input_sha256":{str(p):file_sha256(p) for p in input_paths},
                "transition_buffer_minutes":buffer_values,
                "claim_scope":"oblast-specific weak supervision; not IP-level power truth"}
    pp=rt/"regional_calibration_provenance.json"; pp.write_text(json.dumps(provenance,indent=2),encoding="utf-8")
    return {"status":"ok" if not loo.empty else "diagnostic_only_no_admissible_group",
            "outputs":[str(score_dir),str(resp_dir),str(membership_path),str(rt/"regional_calibration_loo.csv"),
                       str(rt/"regional_b2_membership_stability.csv"),str(rt/"regional_calibration_meta_summary.csv"),str(pp)],
            "region_event_n":len(artifacts),"loo_split_n":split_n}
