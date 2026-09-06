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
                                   build_v3_regional_event_registry,
                                   build_v4_regional_event_registry,
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


def _load_inputs(cfg: Config, valid_admin1: set[str] | None = None):
    path = cfg.resource_path("schedule_registry")
    schedule = cfg.load_schedule_registry()
    versions = schedule.get("schema_version", pd.Series("", index=schedule.index)).astype(str)
    if versions.str.startswith("v4").any():
        return build_v4_regional_event_registry(
            schedule, valid_admin1=valid_admin1,
            max_episode_gap_days=int(cfg.regional_calibration.get("episode_gap_days", 3))), [path]
    if versions.str.startswith("v3").any() or str(path).endswith("v3_0.csv"):
        return build_v3_regional_event_registry(schedule, valid_admin1=valid_admin1), [path]
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
            target_columns=[c for c in ("dst_ip","prefix24","target_admin1","target_city",
                           "target_geo_latitude","target_geo_longitude","target_geo_precision",
                           "target_asn","target_as_name","target_isp_domain","network_stratum")
                            if c in targets]
            d=d.merge(targets[target_columns],
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
    output_columns = [
        "target_admin1", "exposure_unit_id", "holdout_event_id", "method",
        "auprc", "sensor_n", "n_cycle", "valid_cycle_n",
        "expected_baseline", "delta_b2_vs_b1",
    ]
    rows=[]
    for split in splits:
        admin1=split["target_admin1"]; hold=split["holdout_event_id"]
        unit=split.get("exposure_unit_id", admin1)
        mask=all_scores.target_admin1.eq(admin1)
        if "exposure_unit_id" in all_scores:
            mask &= all_scores.exposure_unit_id.eq(unit)
        train=all_scores[mask & all_scores.event_id.isin(split["train_event_ids"])]
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
            rows.append({"target_admin1":admin1,"exposure_unit_id":unit,
                         "holdout_event_id":hold,"method":method,
                         "auprc":metric[method],"sensor_n":n,"n_cycle":len(z),
                         "valid_cycle_n":int(valid.sum()),"expected_baseline":expected})
        rows[-1]["delta_b2_vs_b1"] = metric.get("B2_region",np.nan)-metric.get("B1_region",np.nan)
    # Preserve a stable output schema even when the available measurement
    # window cannot support a leave-one-episode-out split.  An empty result is
    # a scientific estimability outcome, not a pipeline exception.
    return pd.DataFrame(rows, columns=output_columns)


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


def _regional_gate(loo: pd.DataFrame, membership: pd.DataFrame, cfg: Config) -> dict:
    """Publication-facing gate for the cross-fitted regional sensor panel."""
    rcfg = cfg.regional_calibration
    primary_buffer = int(rcfg["transition_buffer_minutes"])
    required = {"method", "transition_buffer_minutes", "delta_b2_vs_b1",
                "holdout_event_id", "target_admin1"}
    if loo.empty or not required.issubset(loo.columns):
        d = pd.DataFrame(columns=sorted(required))
    else:
        d = loo[(loo.method.eq("B2_region")) &
                (loo.transition_buffer_minutes.eq(primary_buffer)) &
                loo.delta_b2_vs_b1.notna()].copy()
    holdout_n = int(d.holdout_event_id.nunique()) if not d.empty else 0
    positive_fraction = float(d.delta_b2_vs_b1.gt(0).mean()) if not d.empty else 0.0
    region_means = d.groupby("target_admin1").delta_b2_vs_b1.mean() if not d.empty else pd.Series(dtype=float)
    rng = np.random.default_rng(int(cfg.runtime["random_seed"]) + 2600)
    boots = []
    if not d.empty:
        for _ in range(int(cfg.runtime["n_bootstrap"])):
            sampled = []
            for _, group in d.groupby("target_admin1"):
                sampled.append(float(group.sample(
                    len(group), replace=True,
                    random_state=int(rng.integers(0, 2**31 - 1))).delta_b2_vs_b1.mean()))
            boots.append(float(np.mean(sampled)))
    ci_lo = float(np.quantile(boots, .025)) if boots else np.nan
    ci_hi = float(np.quantile(boots, .975)) if boots else np.nan
    members = membership[
        membership.transition_buffer_minutes.eq(primary_buffer) & membership.in_B2_region.astype(bool)
    ] if not membership.empty else membership
    sensor_n = int(members.dst_ip.nunique()) if not members.empty else 0
    min_holdout = int(rcfg.get("min_holdout_events_for_estimability", 3))
    min_regions = int(rcfg.get("min_regions_for_success", 2))
    min_sensor = int(rcfg.get("min_regional_b2_ip", 200))
    min_fraction = float(rcfg.get("min_positive_event_fraction", 2 / 3))
    success = bool(holdout_n >= min_holdout and len(region_means) >= min_regions and
                   sensor_n >= min_sensor and
                   positive_fraction >= min_fraction and np.isfinite(ci_lo) and ci_lo > 0)
    return {
        "primary_buffer_minutes": primary_buffer,
        "regional_calibration_success": int(success),
        "holdout_episode_n": holdout_n,
        "region_n": int(len(region_means)),
        "regional_b2_ip_n": sensor_n,
        "mean_delta_b2_vs_b1_equal_region": float(region_means.mean()) if len(region_means) else np.nan,
        "ci_lo": ci_lo, "ci_hi": ci_hi,
        "positive_holdout_fraction": positive_fraction,
        "min_holdout_episode_n": min_holdout,
        "min_region_n": min_regions,
        "min_regional_b2_ip": min_sensor,
        "min_positive_holdout_fraction": min_fraction,
        "claim_scope": "network-visible regional outage-responsive endpoints; not IP-level power truth",
    }


def _network_control_support(targets: pd.DataFrame, audits: pd.DataFrame,
                             cfg: Config) -> pd.DataFrame:
    """Count same-ISP/ASN targets outside each treated Admin1 without querying outcomes."""
    if targets.empty or audits.empty or "network_stratum" not in targets:
        return pd.DataFrame()
    eligible = targets[targets.regional_eligible.eq(1)].copy()
    counts = (eligible.groupby(["target_admin1", "network_stratum"], as_index=False)
              .agg(ip_n=("dst_ip", "nunique"), prefix_n=("prefix24", "nunique")))
    min_control = int(cfg.regional_calibration.get("network_control", {}).get(
        "min_same_network_control_ip", 100))
    rows = []
    for _, event in audits.drop_duplicates(["event_id", "target_admin1"]).iterrows():
        region = str(event["target_admin1"])
        treated = counts[counts.target_admin1.eq(region)]
        control = counts[~counts.target_admin1.eq(region)]
        outside = (control.groupby("network_stratum", as_index=False)
                   .agg(control_ip_n=("ip_n", "sum"),
                        control_prefix_n=("prefix_n", "sum"),
                        control_admin1_n=("target_admin1", "nunique")))
        joined = treated.merge(outside, on="network_stratum", how="left").fillna(0)
        for _, row in joined.iterrows():
            rows.append({
                "event_id": event["event_id"], "episode_id": event.get("episode_id", ""),
                "target_admin1": region, "operator": event.get("operator", ""),
                "network_stratum": row["network_stratum"],
                "treated_ip_n": int(row["ip_n"]), "treated_prefix_n": int(row["prefix_n"]),
                "control_ip_n": int(row["control_ip_n"]),
                "control_prefix_n": int(row["control_prefix_n"]),
                "control_admin1_n": int(row["control_admin1_n"]),
                "same_network_control_eligible": int(row["control_ip_n"] >= min_control),
            })
    return pd.DataFrame(rows)


def _network_outcome_falsification(cfg: Config, artifacts: dict) -> pd.DataFrame:
    """Same-ASN outside-Admin1 diagnostic using the already built group panel.

    This is never used to select endpoints. It distinguishes a local deficit
    from a contemporaneous network-wide deficit without another ClickHouse scan.
    """
    path = cfg.out_dir("data_derived") / "group_cycle_panel.parquet"
    if not path.exists() or not path.stat().st_size:
        return pd.DataFrame()
    panel = pd.read_parquet(path, columns=[
        "cycle_id", "target_asn", "target_admin1", "reach_prefix_equal"
    ])
    rows = []
    threshold = float(cfg.external_validation.get("admin1_reach_deviation_threshold", -0.05))
    for event_id, artifact in artifacts.items():
        cycles = artifact["cycles"]
        pos_ids = set(cycles.loc[cycles.label.eq(1), "cycle_id"].astype(int))
        normal_ids = set(cycles.loc[cycles.label.eq(0), "cycle_id"].astype(int))
        region = str(cycles.target_admin1.iloc[0])
        relevant = panel[panel.cycle_id.isin(pos_ids | normal_ids)].copy()
        if relevant.empty:
            continue
        relevant["period"] = np.where(relevant.cycle_id.isin(pos_ids), "event", "normal")
        means = (relevant.groupby(["target_asn", "target_admin1", "period"])
                 .reach_prefix_equal.mean().unstack("period"))
        if not {"event", "normal"}.issubset(means.columns):
            continue
        means["delta"] = means["event"] - means["normal"]
        means = means.reset_index()
        treated = means[means.target_admin1.eq(region)][["target_asn", "delta"]].rename(
            columns={"delta": "treated_delta"})
        outside = (means[~means.target_admin1.eq(region)].groupby("target_asn", as_index=False)
                   .delta.mean().rename(columns={"delta": "outside_delta"}))
        paired = treated.merge(outside, on="target_asn", how="inner").dropna()
        if paired.empty:
            continue
        paired["regional_specific_delta"] = paired.treated_delta - paired.outside_delta
        rows.append({
            "event_id": event_id, "episode_id": artifact.get("episode_id", ""),
            "target_admin1": region, "operator": artifact.get("operator", ""),
            "common_asn_n": int(len(paired)),
            "treated_delta_equal_asn": float(paired.treated_delta.mean()),
            "outside_delta_equal_asn": float(paired.outside_delta.mean()),
            "regional_specific_delta_equal_asn": float(paired.regional_specific_delta.mean()),
            "outside_network_drop_fraction": float(paired.outside_delta.le(threshold).mean()),
            "same_network_falsification_direction": int(paired.regional_specific_delta.mean() < 0),
            "role": "diagnostic_not_sensor_selection",
        })
    return pd.DataFrame(rows)


def run(cfg: Config) -> dict:
    rcfg=cfg.regional_calibration
    if not bool(rcfg.get("enabled",True)):
        return {"status":"warning","outputs":[],"reason":"regional calibration disabled"}
    logger=get_logger(cfg.out_dir("logs")); dd=cfg.out_dir("data_derived"); rt=cfg.out_dir("results_tables")
    grid=Events(cfg).build_cycle_grid(pd.read_parquet(dd/"cycle_quality.parquet")); ev=Events(cfg)
    targets=pd.read_parquet(dd/"target_ip_universe.parquet")
    valid_admin1=set(targets.loc[targets.regional_eligible.eq(1), "target_admin1"].dropna().astype(str))
    registry,input_paths=_load_inputs(cfg, valid_admin1=valid_admin1)
    registry_path=rt/"regional_event_registry_v4.csv"
    registry.to_csv(registry_path,index=False,encoding="utf-8-sig")
    configured_regions=[str(x) for x in rcfg.get("primary_regions", [])]
    auto_regions=not configured_regions or configured_regions == ["AUTO"]
    regions=sorted(registry.target_admin1.dropna().astype(str).unique()) if auto_regions else configured_regions
    configured_dates=[str(x) for x in rcfg.get("core_dates", [])]
    auto_dates=not configured_dates or configured_dates == ["AUTO"]
    dates=sorted(registry.date.dropna().astype(str).unique()) if auto_dates else configured_dates
    buffer_values=sorted(set(int(x) for x in rcfg.get(
        "transition_buffer_sensitivity_minutes", [rcfg["transition_buffer_minutes"]])))
    cycles_by_buffer={b:regional_event_cycles(registry,grid,regions=regions,
        dates=dates,cycle_hours=float(cfg.study["expected_cycle_interval_hours"]),
        min_overlap_fraction=float(cfg.calibration["min_cycle_schedule_overlap_fraction"]),
        transition_buffer_minutes=b) for b in buffer_values}
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
                                         "transition_buffer_minutes":buffer_minutes,
                                         "episode_id":str(pos.episode_id.iloc[0]) if "episode_id" in pos else event_id,
                                         "exposure_unit_id":str(pos.exposure_unit_id.iloc[0]) if "exposure_unit_id" in pos else admin1,
                                         "operator":str(pos.operator.iloc[0]) if "operator" in pos else "",
                                         "exposure_precision":str(pos.exposure_precision.iloc[0]) if "exposure_precision" in pos else "L2_admin1"}
                    audits.append({"event_id":event_id,"target_admin1":admin1,"positive_cycle_n":len(pos),
                                   "control_cycle_n":len(controls),"target_ip_n":region_targets.dst_ip.nunique(),
                                   "episode_id":artifacts[event_id]["episode_id"],
                                   "exposure_unit_id":artifacts[event_id]["exposure_unit_id"],
                                   "operator":artifacts[event_id]["operator"],
                                   "exposure_precision":artifacts[event_id]["exposure_precision"],
                                   "transition_buffer_minutes":buffer_minutes})
    score_frames=[]
    for event_id,a in artifacts.items():
        d=pd.read_parquet(a["scores"]); d["event_id"]=event_id
        d["episode_id"]=a["episode_id"]; d["exposure_unit_id"]=a["exposure_unit_id"]
        d["operator"]=a["operator"]; d["exposure_precision"]=a["exposure_precision"]
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
    membership_groups=["transition_buffer_minutes","target_admin1","exposure_unit_id"]
    for (buffer_minutes,admin1,exposure_unit_id),g in scores.groupby(membership_groups):
        m=select_repeated_sensitive(g,min_events=int(rcfg["min_train_events"]),
                                    min_positive_fraction=float(rcfg["min_positive_event_fraction"]))
        total_events=g.event_id.nunique()
        complete=m.training_event_n.eq(total_events)
        m["in_B1_region"] &= complete; m["in_B2_region"] &= complete
        m["transition_buffer_minutes"]=buffer_minutes; m["available_event_n"]=total_events
        m["operator"]="|".join(sorted(g["operator"].dropna().astype(str).unique()))
        m["exposure_precision"]="|".join(sorted(g["exposure_precision"].dropna().astype(str).unique()))
        if "target_isp_domain" in g:
            isp=g.groupby("dst_ip",as_index=False)["target_isp_domain"].first()
            m=m.merge(isp,on="dst_ip",how="left",validate="one_to_one")
        if "network_stratum" in g:
            ns=g.groupby("dst_ip",as_index=False)["network_stratum"].first()
            m=m.merge(ns,on="dst_ip",how="left",validate="one_to_one")
        final_members.append(m)
    membership=pd.concat(final_members,ignore_index=True) if final_members else pd.DataFrame()
    membership_path=base/"regional_sensor_membership.parquet"
    membership.to_parquet(membership_path,index=False)
    summary=(loo[loo.method.eq("B2_region")].groupby(["target_admin1","transition_buffer_minutes"],as_index=False)
             .agg(mean_delta_b2_vs_b1=("delta_b2_vs_b1","mean"),holdout_n=("holdout_event_id","nunique"))) if not loo.empty else pd.DataFrame()
    meta=_equal_region_meta(loo,cfg)
    if not meta.empty:
        summary=pd.concat([summary,meta],ignore_index=True,sort=False)
    audit_frame=pd.DataFrame(audits)
    audit_frame.to_csv(rt/"regional_calibration_cycle_audit.csv",index=False)
    network_support=_network_control_support(targets,audit_frame,cfg)
    network_support_path=rt/"regional_network_control_support.csv"
    network_support.to_csv(network_support_path,index=False,encoding="utf-8-sig")
    network_falsification=_network_outcome_falsification(cfg,artifacts)
    network_falsification_path=rt/"regional_network_outcome_falsification.csv"
    network_falsification.to_csv(network_falsification_path,index=False,encoding="utf-8-sig")
    loo.to_csv(rt/"regional_calibration_loo.csv",index=False); stability.to_csv(rt/"regional_b2_membership_stability.csv",index=False)
    summary.to_csv(rt/"regional_calibration_meta_summary.csv",index=False)
    gate=_regional_gate(loo,membership,cfg)
    gate_path=rt/"regional_calibration_gate.json"
    gate_path.write_text(json.dumps(gate,indent=2,ensure_ascii=False),encoding="utf-8")
    provenance={"input_sha256":{str(p):file_sha256(p) for p in input_paths},
                "transition_buffer_minutes":buffer_values,
                "claim_scope":"oblast-specific weak supervision; not IP-level power truth"}
    pp=rt/"regional_calibration_provenance.json"; pp.write_text(json.dumps(provenance,indent=2),encoding="utf-8")
    return {"status":"ok" if not loo.empty else "diagnostic_only_no_admissible_group",
            "outputs":[str(registry_path),str(score_dir),str(resp_dir),str(membership_path),str(rt/"regional_calibration_loo.csv"),
                       str(rt/"regional_b2_membership_stability.csv"),str(rt/"regional_calibration_meta_summary.csv"),
                       str(network_support_path),str(network_falsification_path),str(gate_path),str(pp)],
            "region_event_n":len(artifacts),"loo_split_n":split_n}
