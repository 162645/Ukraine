"""Data-quality audit for the v2.4 analysis contract.

Key corrections:
* Nominal study edges with no imported data are reported, but the cycle-completeness
  gate is evaluated inside the empirically observed acquisition-support span.
* Ping response volume is an outcome, not an acquisition-quality gate.  Under the
  confirmed full-scan contract, a low (or even zero) number of response rows can be
  a real network observation.  Import metadata determines whether the cycle was
  acquired; response-volume outliers are diagnostics only.
* Target geography is audited at endpoint level. Country-only Ukrainian mappings
  remain usable for national experiments but are excluded from regional inference.
* Prefix modal geography is diagnostic only; it is no longer a global fatal gate.
* Every registered event receives an explicit data-availability decision before
  downstream experiments run.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import sqlutil as S
from .config import Config
from .db import CHClient
from .geo import Admin1Canonicalizer
from .event_design import (build_estimands, clean_baseline_interval, event_panel_interval,
                           earliest_treatment_start)
from .progress import get_logger, step


def _full_grid(cfg: Config) -> pd.DataFrame:
    h = int(cfg.study["expected_cycle_interval_hours"])
    ts = pd.date_range(pd.Timestamp(cfg.study["start_utc"], tz="UTC"),
                       pd.Timestamp(cfg.study["end_utc"], tz="UTC").floor(f"{h}h"),
                       freq=f"{h}h")
    sec = h * 3600
    return pd.DataFrame({"measure_time": ts,
                         "cycle_id": (ts.view("int64") // 10**9 // sec).astype("int64")})


def _truthy(series: pd.Series) -> pd.Series:
    """Interpret ClickHouse boolean-like fields without treating NaN as True."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    numeric = pd.to_numeric(series, errors="coerce")
    text = series.fillna("").astype(str).str.strip().str.lower()
    return numeric.fillna(0).gt(0) | text.isin({"true", "yes", "y", "done"})


def run_cycle_audit(cfg: Config, ch: CHClient) -> pd.DataFrame:
    logger = get_logger(cfg.out_dir("logs"))
    h = int(cfg.study["expected_cycle_interval_hours"])
    common = dict(start=cfg.study["start_utc"], end=cfg.study["end_utc"],
                  dc=cfg.study["data_center"], cycle_seconds=h * 3600)
    with step("Audit analysis-cycle coverage", logger):
        obs = ch.query_df(S.render("00_cycle_audit", ping=cfg.table("ping"), trace=cfg.table("trace"), **common))
        try:
            imp = ch.query_df(S.render("01_import_files", import_files=cfg.table("import_files"), **common))
        except Exception as e:  # noqa: BLE001
            if cfg.quality.get("allow_missing_import_metadata", False):
                logger.warning("import_files unavailable: %s", e)
                imp = pd.DataFrame()
            else:
                raise
    grid = _full_grid(cfg)
    if not obs.empty:
        obs["measure_time"] = pd.to_datetime(obs["measure_time"], utc=True)
        grid = grid.merge(obs, on=["cycle_id", "measure_time"], how="left")
    for c in ["ping_rows", "ping_prefixes", "ping_unique_ips", "trace_rows", "trace_prefixes"]:
        grid[c] = pd.to_numeric(grid.get(c), errors="coerce").fillna(0).astype("int64")
    for c in ["trace_reached_rate", "trace_star_rate", "as0_path_share", "geo_unknown_path_share"]:
        grid[c] = pd.to_numeric(grid.get(c), errors="coerce")

    if not imp.empty:
        imp["measure_time"] = pd.to_datetime(imp["measure_time"], utc=True)
        # import metadata may contain duplicates after retries; use the latest row per cycle.
        if "updated_at" in imp:
            imp["updated_at"] = pd.to_datetime(imp["updated_at"], utc=True, errors="coerce")
            imp = imp.sort_values("updated_at").drop_duplicates(["cycle_id", "measure_time"], keep="last")
        grid = grid.merge(imp, on=["cycle_id", "measure_time"], how="left")
    else:
        grid["import_status"] = "unknown"
        grid["error_message"] = ""
        grid["has_ping"] = np.nan
        grid["has_trace"] = np.nan

    slots_per_day = 24 // h
    grid["slot"] = grid["measure_time"].dt.dayofweek * slots_per_day + grid["measure_time"].dt.hour // h
    slot_stats = (grid.loc[grid["ping_rows"] > 0].groupby("slot")["ping_rows"]
                  .agg(slot_median="median",
                       slot_mad=lambda x: (x - x.median()).abs().median()).reset_index())
    grid = grid.merge(slot_stats, on="slot", how="left")
    denom = (1.4826 * grid["slot_mad"]).replace(0, np.nan)
    grid["ping_rows_robust_z"] = (grid["ping_rows"] - grid["slot_median"]) / denom
    # IMPORTANT: response volume is the dependent variable.  A severe outage can
    # legitimately reduce ping_rows, so it must never be used to discard a cycle.
    grid["response_volume_outlier"] = (
        grid["ping_rows_robust_z"].abs().fillna(0).gt(float(cfg.quality["ping_rows_mad_k"]))
    ).astype("int8")
    if cfg.quality.get("require_import_done", True):
        status_ok = grid["import_status"].fillna("missing").astype(str).str.strip().str.lower().eq("done")
    else:
        status_ok = ~grid["import_status"].fillna("missing").astype(str).str.strip().str.lower().eq("failed")
    no_error = grid["error_message"].fillna("").eq("")
    # import_files is the acquisition ledger.  has_ping means the full-scan Ping
    # artifact was present for that cycle; absence of an individual dst_ip row is
    # then a non-response.  This avoids censoring exactly the low-response cycles
    # that the paper is trying to measure.
    if "has_ping" in grid:
        ping_artifact_present = _truthy(grid["has_ping"])
    elif "imported_ping_rows" in grid:
        ping_artifact_present = pd.to_numeric(grid["imported_ping_rows"], errors="coerce").fillna(0).ge(0) & status_ok
    else:  # defensive fallback; current real pipeline requires import metadata.
        ping_artifact_present = grid["ping_rows"].gt(0)
    if "has_trace" in grid:
        trace_artifact_present = _truthy(grid["has_trace"])
    else:
        trace_artifact_present = grid["trace_rows"].gt(0)

    grid["ping_acquisition_complete"] = (status_ok & no_error & ping_artifact_present).astype("int8")
    grid["trace_acquisition_complete"] = (status_ok & no_error & trace_artifact_present).astype("int8")
    grid["is_complete"] = grid["ping_acquisition_complete"].astype("int8")

    acquired = grid["ping_acquisition_complete"].eq(1)
    if acquired.any():
        support_start = grid.loc[acquired, "measure_time"].min()
        support_end = grid.loc[acquired, "measure_time"].max()
        grid["in_observed_support"] = ((grid["measure_time"] >= support_start) &
                                        (grid["measure_time"] <= support_end)).astype("int8")
    else:
        grid["in_observed_support"] = 0
    grid["is_analysis_cycle"] = (grid["is_complete"].eq(1) & grid["in_observed_support"].eq(1)).astype("int8")

    grid["exclusion_reason"] = ""
    grid.loc[~ping_artifact_present, "exclusion_reason"] += "ping_artifact_absent;"
    grid.loc[~status_ok, "exclusion_reason"] += "import_not_done;"
    grid.loc[~no_error, "exclusion_reason"] += "import_error;"
    grid.loc[grid["in_observed_support"].eq(0), "exclusion_reason"] += "outside_observed_support;"
    grid.to_parquet(cfg.out_dir("data_derived") / "cycle_quality.parquet", index=False)
    return grid


def _canonicalizer(cfg: Config) -> Admin1Canonicalizer:
    return Admin1Canonicalizer(
        cfg.resource_path("admin1_aliases"),
        cfg.quality["unknown_labels"],
        cfg.quality["valid_country_aliases"],
        cfg.quality.get("country_only_admin1_labels", cfg.quality["valid_country_aliases"]),
    )


def _aggregate_prefixes(ipu: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Create a /24 contract without discarding country-only Ukrainian targets.

    The /24 ASN is chosen from all Ukrainian endpoints with a valid ASN.  Admin1 is
    the modal region among the same endpoints and may remain COUNTRY_ONLY_UA.  A
    separate regional flag prevents country-only prefixes from entering regional
    inference while retaining them in national analyses.
    """
    base = (ipu.groupby("prefix24")
            .agg(candidate_ip_n=("dst_ip", "size"),
                 valid_country_ip_n=("valid_target_country", "sum"),
                 valid_asn_ip_n=("valid_target_asn", "sum"),
                 national_eligible_ip_n=("national_eligible", "sum"),
                 regional_eligible_ip_n=("regional_eligible", "sum"),
                 country_only_ip_n=("country_only_admin1", "sum"),
                 asn_distinct=("target_asn", "nunique"),
                 country_distinct=("target_country", "nunique"),
                 admin1_distinct=("target_admin1", "nunique"),
                 mapping_min_updated=("mapping_updated_at", "min"),
                 mapping_max_updated=("mapping_updated_at", "max"))
            .reset_index())
    nat = ipu[ipu["national_eligible"].eq(1)].copy()
    if nat.empty:
        modal = pd.DataFrame(columns=["prefix24", "target_asn", "target_country", "target_admin1",
                                      "modal_group_ip_n", "mapping_mode_share", "asn_mode_share"])
    else:
        counts = (nat.groupby(["prefix24", "target_asn", "target_country", "target_admin1"])
                  .size().rename("modal_group_ip_n").reset_index())
        counts = counts.sort_values(["prefix24", "modal_group_ip_n", "target_asn", "target_admin1"],
                                    ascending=[True, False, True, True])
        modal = counts.drop_duplicates("prefix24", keep="first")
        denom = nat.groupby("prefix24").size().rename("national_ip_n").reset_index()
        asn_counts = (nat.groupby(["prefix24", "target_asn"]).size().rename("asn_ip_n").reset_index()
                      .sort_values(["prefix24", "asn_ip_n", "target_asn"], ascending=[True, False, True])
                      .drop_duplicates("prefix24"))
        modal = modal.merge(denom, on="prefix24", how="left").merge(
            asn_counts[["prefix24", "asn_ip_n"]], on="prefix24", how="left")
        modal["mapping_mode_share"] = modal["modal_group_ip_n"] / modal["national_ip_n"].replace(0, np.nan)
        modal["asn_mode_share"] = modal["asn_ip_n"] / modal["national_ip_n"].replace(0, np.nan)
    out = base.merge(modal, on="prefix24", how="left")
    out["target_asn"] = pd.to_numeric(out["target_asn"], errors="coerce").fillna(0).astype("int64")
    out["target_country"] = out["target_country"].fillna("Ukraine")
    out["target_admin1"] = out["target_admin1"].fillna(Admin1Canonicalizer.COUNTRY_ONLY_UA)
    out["mapping_mode_share"] = pd.to_numeric(out["mapping_mode_share"], errors="coerce").fillna(0.0)
    out["asn_mode_share"] = pd.to_numeric(out.get("asn_mode_share"), errors="coerce").fillna(0.0)
    out["valid_target_asn"] = out["target_asn"].gt(0).astype("int8")
    out["valid_target_admin1"] = (~out["target_admin1"].isin([
        Admin1Canonicalizer.COUNTRY_ONLY_UA, Admin1Canonicalizer.UNKNOWN,
        Admin1Canonicalizer.UNMAPPED_UA])).astype("int8")
    threshold = float(cfg.quality.get("min_prefix_mapping_mode_share", 0.5))
    out["valid_prefix_mapping"] = (out["asn_mode_share"] >= threshold).astype("int8")
    out["national_prefix_eligible"] = (out["valid_target_asn"].eq(1) & out["valid_prefix_mapping"].eq(1)).astype("int8")
    out["regional_prefix_eligible"] = (out["national_prefix_eligible"].eq(1) & out["valid_target_admin1"].eq(1)).astype("int8")
    out["group"] = (out["target_asn"].astype(str) + "|" + out["target_country"].astype(str)
                    + "|" + out["target_admin1"].astype(str))
    return out


def run_target_universe(cfg: Config, ch: CHClient) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    logger = get_logger(cfg.out_dir("logs"))
    manifest = cfg.load_mapping_manifest()
    snapshot = manifest.get("freeze", {}).get("snapshot_date")
    cutoff_value = str(snapshot).replace(" UTC", "")[:19] if snapshot else ""
    cutoff = f"AND updated_at <= toDateTime('{cutoff_value}', 'UTC')" if cutoff_value else ""
    with step("Audit frozen target IP mapping", logger):
        ipu = ch.query_df(S.render("02_target_ip_universe", mapping=cfg.table("mapping"),
                                   ping=cfg.table("ping"), dc=cfg.study["data_center"],
                                   start=cfg.study["start_utc"], end=cfg.study["end_utc"],
                                   mapping_cutoff_clause=cutoff))
    try:
        with step("Audit monthly responding-target drift", logger):
            drift = ch.query_df(S.render("08_monthly_target_drift", ping=cfg.table("ping"),
                                         start=cfg.study["start_utc"], end=cfg.study["end_utc"],
                                         dc=cfg.study["data_center"]))
    except Exception as e:  # noqa: BLE001
        logger.warning("monthly target drift unavailable: %s", e)
        drift = pd.DataFrame(columns=["month", "responding_prefixes"])
    canon = _canonicalizer(cfg)
    ipu = canon.canonicalize_frame(ipu, "target_country_raw", "target_admin1_raw")
    ipu["target_asn"] = pd.to_numeric(ipu["target_asn_raw"], errors="coerce").fillna(0).astype("int64")
    ipu["valid_target_country"] = ipu["target_country"].eq("Ukraine").astype("int8")
    ipu["valid_target_asn"] = ipu["target_asn"].gt(0).astype("int8")
    ipu["valid_target_admin1"] = [int(canon.valid_target(c, a))
                                    for c, a in zip(ipu["target_country"], ipu["target_admin1"])]
    ipu["country_only_admin1"] = ipu["target_admin1"].eq(canon.COUNTRY_ONLY_UA).astype("int8")
    ipu["national_eligible"] = (ipu["valid_target_country"].eq(1) & ipu["valid_target_asn"].eq(1)).astype("int8")
    ipu["regional_eligible"] = (ipu["national_eligible"].eq(1) & ipu["valid_target_admin1"].eq(1)).astype("int8")
    ipu["group"] = (ipu["target_asn"].astype(str) + "|" + ipu["target_country"].astype(str)
                    + "|" + ipu["target_admin1"].astype(str))
    ipu["analysis_unit_id"] = ipu["prefix24"].astype(str) + "|" + ipu["group"]
    ipu.to_parquet(cfg.out_dir("data_derived") / "target_ip_universe.parquet", index=False, compression="zstd")

    prefix = _aggregate_prefixes(ipu, cfg)
    prefix.to_parquet(cfg.out_dir("data_derived") / "target_universe.parquet", index=False, compression="zstd")

    # U1/U2/U3 target-universe sensitivity: original responding universe,
    # Ukraine+ASN, and strict Ukraine+ASN+Admin1.  These counts are required to
    # determine whether conclusions depend on Geo filtering.
    universes = pd.DataFrame([
        {"universe": "U1_all_responding_targets", "ip_n": int(ipu["dst_ip"].nunique()),
         "prefix_n": int(ipu["prefix24"].nunique()), "asn_n": int(ipu.loc[ipu["target_asn"].gt(0), "target_asn"].nunique())},
        {"universe": "U2_ukraine_valid_asn", "ip_n": int(ipu.loc[ipu["national_eligible"].eq(1), "dst_ip"].nunique()),
         "prefix_n": int(ipu.loc[ipu["national_eligible"].eq(1), "prefix24"].nunique()),
         "asn_n": int(ipu.loc[ipu["national_eligible"].eq(1), "target_asn"].nunique())},
        {"universe": "U3_ukraine_valid_admin1_asn", "ip_n": int(ipu.loc[ipu["regional_eligible"].eq(1), "dst_ip"].nunique()),
         "prefix_n": int(ipu.loc[ipu["regional_eligible"].eq(1), "prefix24"].nunique()),
         "asn_n": int(ipu.loc[ipu["regional_eligible"].eq(1), "target_asn"].nunique())},
    ])
    universes.to_csv(cfg.out_dir("results_tables") / "target_universe_sensitivity.csv", index=False, encoding="utf-8-sig")

    bad = ipu[ipu["target_admin1"].isin([canon.COUNTRY_ONLY_UA, canon.UNMAPPED_UA, canon.UNKNOWN])]
    (bad.groupby(["target_country_raw", "target_admin1_raw", "target_admin1"], dropna=False)
        .agg(ip_n=("dst_ip", "size"), prefix_n=("prefix24", "nunique"))
        .reset_index().sort_values("ip_n", ascending=False)
        .to_csv(cfg.out_dir("results_tables") / "admin1_unmapped.csv", index=False, encoding="utf-8-sig"))
    # Full raw→canonical frequency table makes choices such as 基辅→Kyiv City and
    # 基辅州→Kyiv Oblast reviewable instead of hiding them inside an alias file.
    (ipu.groupby(["target_country_raw", "target_admin1_raw", "target_country", "target_admin1",
                  "regional_eligible", "country_only_admin1"], dropna=False)
        .agg(ip_n=("dst_ip", "size"), prefix_n=("prefix24", "nunique"), asn_n=("target_asn", "nunique"))
        .reset_index().sort_values(["ip_n", "target_admin1_raw"], ascending=[False, True])
        .to_csv(cfg.out_dir("results_tables") / "admin1_canonicalization_audit.csv",
                index=False, encoding="utf-8-sig"))
    drift_out = cfg.out_dir("results_tables") / "monthly_target_drift.csv"
    if not drift.empty:
        drift["month"] = pd.to_datetime(drift["month"], utc=True)
        drift.to_csv(drift_out, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["month", "responding_prefixes"]).to_csv(
            drift_out, index=False, encoding="utf-8-sig"
        )
    return ipu, prefix, drift


def event_availability(cfg: Config, cq: pd.DataFrame,
                       ipu: pd.DataFrame | None = None) -> pd.DataFrame:
    ev = cfg.load_event_registry()
    g = cq.copy()
    g["measure_time"] = pd.to_datetime(g["measure_time"], utc=True)
    complete = g["is_analysis_cycle"].eq(1)
    trace_complete = (g.get("trace_acquisition_complete", pd.Series(0, index=g.index))
                      .fillna(0).astype(int).eq(1) & g["in_observed_support"].eq(1))
    support = g["in_observed_support"].eq(1)
    rows = []
    for _, r in ev.iterrows():
        try:
            lo, hi = event_panel_interval(r, cfg)
        except Exception:
            continue
        treatment = earliest_treatment_start(r)
        b0, b1 = clean_baseline_interval(r, cfg)
        anchor = pd.to_datetime(r.get("primary_anchor_utc"), utc=True, errors="coerce")
        wm = (g["measure_time"] >= lo) & (g["measure_time"] <= hi)
        clean_pre = (g["measure_time"] >= b0) & (g["measure_time"] <= b1)
        transition = (g["measure_time"] >= treatment) & (g["measure_time"] < anchor) if pd.notna(treatment) and pd.notna(anchor) else pd.Series(False,index=g.index)
        post = wm & (g["measure_time"] >= anchor) if pd.notna(anchor) else pd.Series(False,index=g.index)
        outage_lo = pd.to_datetime(r.get("outage_start_utc"), utc=True, errors="coerce")
        outage_hi = pd.to_datetime(r.get("outage_end_utc"), utc=True, errors="coerce")
        om = ((g["measure_time"] >= outage_lo) & (g["measure_time"] <= outage_hi)) if pd.notna(outage_lo) and pd.notna(outage_hi) else pd.Series(False, index=g.index)
        expected_n = int(wm.sum()); complete_n = int((wm & complete).sum())
        trace_complete_n = int((wm & trace_complete).sum())
        ratio = complete_n / expected_n if expected_n else 0.0
        anchor_in_support = bool(pd.notna(anchor) and ((g["measure_time"] <= anchor) & support).any() and ((g["measure_time"] >= anchor) & support).any())
        min_pre = int(cfg.quality.get("min_event_pre_complete_cycles", 6)); min_post = int(cfg.quality.get("min_event_post_complete_cycles", 12))
        min_ratio = float(cfg.quality.get("min_event_window_complete_ratio", 0.75))
        planned_positive_ok = str(r.get("event_family")) != "planned_outage" or int((om & complete).sum()) >= 1
        scope = str(r.get("scope_type", "")).strip().lower()
        treated = [x.strip() for x in str(r.get("analysis_treated_admin1", "")).split("|") if x.strip()]
        eligible_ip_n = eligible_prefix_n = eligible_asn_n = eligible_unit_n = 0
        treated_with_data=[]; treated_missing=[]; target_coverage_ok=True
        if ipu is not None and not ipu.empty:
            if scope == "regional" and treated and treated != ["ALL"]:
                z=ipu[ipu["regional_eligible"].eq(1)&ipu["target_admin1"].isin(treated)].copy()
                counts=z.groupby("target_admin1")["prefix24"].nunique()
                treated_with_data=[a for a in treated if int(counts.get(a,0))>0]
                treated_missing=[a for a in treated if int(counts.get(a,0))==0]
            else:
                z=ipu[ipu["national_eligible"].eq(1)].copy(); treated_with_data=["ALL"] if not z.empty else []; treated_missing=[] if not z.empty else ["ALL"]
            eligible_ip_n=int(z["dst_ip"].nunique()) if not z.empty else 0; eligible_prefix_n=int(z["prefix24"].nunique()) if not z.empty else 0
            eligible_asn_n=int(z["target_asn"].nunique()) if not z.empty else 0; eligible_unit_n=int(z["analysis_unit_id"].nunique()) if not z.empty else 0
            target_coverage_ok=eligible_prefix_n>=int(cfg.group_admission.get("min_valid_prefix24",20)) and len(treated_with_data)>=1
        clean_n=int((clean_pre&complete).sum()); post_n=int((post&complete).sum())
        available=(int(r.get("analysis_ready",0))==1 and anchor_in_support and ratio>=min_ratio and clean_n>=min_pre and post_n>=min_post and planned_positive_ok and target_coverage_ok)
        reason=[]
        if not anchor_in_support: reason.append("anchor_outside_observed_support")
        if ratio<min_ratio: reason.append("insufficient_window_coverage")
        if clean_n<min_pre: reason.append("insufficient_clean_baseline_cycles")
        if post_n<min_post: reason.append("insufficient_post_cycles")
        if not planned_positive_ok: reason.append("no_complete_outage_cycles")
        if not target_coverage_ok: reason.append("insufficient_target_mapping_coverage")
        rows.append({"event_id":r["event_id"],"analysis_role":r["analysis_role"],"event_family":r["event_family"],"anchor_utc":anchor,
                     "earliest_treatment_utc":treatment,"clean_baseline_start_utc":b0,"clean_baseline_end_utc":b1,"window_start_utc":lo,"window_end_utc":hi,
                     "expected_window_cycles":expected_n,"complete_window_cycles":complete_n,"window_complete_ratio":ratio,
                     "complete_clean_baseline_cycles":clean_n,"complete_transition_cycles":int((transition&complete).sum()),"complete_post_cycles":post_n,
                     "complete_outage_cycles":int((om&complete).sum()),"trace_complete_window_cycles":trace_complete_n,
                     "trace_window_complete_ratio":trace_complete_n/expected_n if expected_n else 0.0,
                     "eligible_target_ip_n":eligible_ip_n,"eligible_prefix24_n":eligible_prefix_n,"eligible_asn_n":eligible_asn_n,"eligible_analysis_unit_n":eligible_unit_n,
                     "treated_admin1_with_data":"|".join(treated_with_data),"treated_admin1_missing":"|".join(treated_missing),
                     "data_available":int(available),"unavailable_reason":";".join(reason)})
    out=pd.DataFrame(rows); out.to_csv(cfg.out_dir("results_tables")/"event_data_availability.csv",index=False,encoding="utf-8-sig"); return out


def estimand_availability(cfg: Config, ipu: pd.DataFrame, event_available: pd.DataFrame) -> pd.DataFrame:
    """Audit geographic support separately for every frozen event estimand.

    This catches cases such as 28 November where independently registered power
    exposure regions and third-party network-observed regions differ.  The table
    is diagnostic and never changes the frozen treatment definition.
    """
    events = cfg.load_event_registry()
    event_ok = (event_available.set_index("event_id")["data_available"].to_dict()
                if not event_available.empty else {})
    rows: list[dict] = []
    for _, event in events.iterrows():
        for est in build_estimands(event):
            treated = list(est.treated_admin1)
            national = treated == ["ALL"] or str(event.get("scope_type", "")).lower() == "national"
            if national:
                z = ipu[ipu["national_eligible"].eq(1)].copy()
                treated_units = int(z["analysis_unit_id"].nunique())
                treated_prefixes = int(z["prefix24"].nunique())
                common_asn_n = int(z["target_asn"].nunique())
                control_units = 0
                same_asn_treated_units = treated_units
                missing_regions: list[str] = []
            else:
                z = ipu[ipu["regional_eligible"].eq(1)].copy()
                t = z[z["target_admin1"].isin(treated)]
                c = z[~z["target_admin1"].isin(treated)]
                common = sorted(set(t["target_asn"]) & set(c["target_asn"]))
                treated_units = int(t["analysis_unit_id"].nunique())
                treated_prefixes = int(t["prefix24"].nunique())
                control_units = int(c[c["target_asn"].isin(common)]["analysis_unit_id"].nunique())
                same_asn_treated_units = int(t[t["target_asn"].isin(common)]["analysis_unit_id"].nunique())
                common_asn_n = len(common)
                present = set(t["target_admin1"].dropna().astype(str))
                missing_regions = [x for x in treated if x not in present]
            min_pairs = int(cfg.matching.get("min_matched_pairs", 30))
            geography_ready = bool(treated_units > 0 and
                                   (national or (same_asn_treated_units >= min_pairs and control_units > 0)))
            rows.append({
                "event_id": event["event_id"], "analysis_role": event["analysis_role"],
                "estimand_id": est.estimand_id, "claim_scope": est.claim_scope,
                "confirmatory": int(est.confirmatory), "anchor_utc": est.anchor_utc,
                "treatment_start_utc": est.treatment_start_utc,
                "treated_admin1": "|".join(treated), "national": int(national),
                "event_time_available": int(bool(event_ok.get(event["event_id"], 0))),
                "treated_analysis_unit_n": treated_units,
                "treated_prefix_n": treated_prefixes,
                "same_asn_treated_unit_n": same_asn_treated_units,
                "control_analysis_unit_n": control_units,
                "common_asn_n": common_asn_n,
                "treated_admin1_missing": "|".join(missing_regions),
                "geography_ready": int(geography_ready),
                "estimand_data_available": int(bool(event_ok.get(event["event_id"], 0)) and geography_ready),
            })
    out = pd.DataFrame(rows)
    out.to_csv(cfg.out_dir("results_tables") / "estimand_data_availability.csv",
               index=False, encoding="utf-8-sig")
    return out


def write_report(cfg: Config, cq: pd.DataFrame, ipu: pd.DataFrame,
                 prefix: pd.DataFrame, drift: pd.DataFrame, avail: pd.DataFrame) -> dict:
    nominal_ratio = float(cq["is_complete"].mean()) if len(cq) else 0.0
    support_rows = cq[cq["in_observed_support"].eq(1)]
    support_ratio = float(support_rows["is_complete"].mean()) if len(support_rows) else 0.0
    valid_admin = float(ipu["regional_eligible"].mean()) if len(ipu) else 0.0
    country_only = float(ipu["country_only_admin1"].mean()) if len(ipu) else 0.0
    national_rows = ipu[ipu["valid_target_country"].eq(1)] if len(ipu) else ipu
    valid_asn = float(national_rows["valid_target_asn"].mean()) if len(national_rows) else 0.0
    offtarget_ratio = 1.0 - float(ipu["valid_target_country"].mean()) if len(ipu) else 0.0
    prefix_mode = float((prefix["mapping_mode_share"] >= float(cfg.quality.get("min_prefix_mapping_mode_share_warning", 0.5))).mean()) if len(prefix) else 0.0
    turnover = np.nan
    if len(drift) >= 2:
        vals = pd.to_numeric(drift["responding_prefixes"], errors="coerce")
        turnover = float((vals.max() - vals.min()) / max(vals.max(), 1))

    available = avail[avail["data_available"].eq(1)] if not avail.empty else pd.DataFrame()
    n_train = int(available["analysis_role"].eq("planned_train").sum()) if not available.empty else 0
    n_valid = int(available["analysis_role"].eq("planned_valid").sum()) if not available.empty else 0
    n_attack = int(available["analysis_role"].isin(["attack_national", "attack_regional", "blind_test"]).sum()) if not available.empty else 0
    event_ok = (n_train >= int(cfg.calibration.get("min_training_events", 1)) and
                n_valid >= int(cfg.calibration.get("min_validation_events", 2)) and n_attack >= 3)

    fatal_gates = set(cfg.quality.get("fatal_gates", []))

    def gate(name, value, threshold, passed, note=""):
        severity = "fatal" if name in fatal_gates else "warning"
        return {"value": value, "threshold": threshold, "pass": bool(passed),
                "severity": severity, "note": note}

    gates = {
        "support_complete_cycle_ratio": gate(
            "support_complete_cycle_ratio",
            support_ratio, cfg.quality["min_complete_cycle_ratio_within_support"],
            support_ratio >= float(cfg.quality["min_complete_cycle_ratio_within_support"]),
            "Evaluated only between the first and last import-complete Ping acquisition cycles."),
        "valid_asn_ratio": gate(
            "valid_asn_ratio", valid_asn, cfg.quality["min_asn_mapping_ratio"],
            valid_asn >= float(cfg.quality["min_asn_mapping_ratio"]),
            "Evaluated on the Ukrainian analysis population only; off-target mappings are reported separately."),
        "denominator_confirmed": gate(
            "denominator_confirmed", bool(cfg.study["static_full_scan_confirmed"]), True,
            bool(cfg.study["static_full_scan_confirmed"])),
        "primary_event_availability": gate(
            "primary_event_availability",
            {"planned_train": n_train, "planned_valid": n_valid, "primary_attack": n_attack},
            {"planned_train": int(cfg.calibration.get("min_training_events", 1)),
             "planned_valid": int(cfg.calibration.get("min_validation_events", 2)), "primary_attack": 3},
            event_ok),
        "regional_admin1_coverage": gate(
            "regional_admin1_coverage",
            valid_admin, cfg.quality.get("min_valid_admin1_ratio_warning", 0.5),
            valid_admin >= float(cfg.quality.get("min_valid_admin1_ratio_warning", 0.5)),
            "Country-only mappings remain in national analyses and are excluded from regional analyses."),
        "prefix_modal_mapping_share": gate(
            "prefix_modal_mapping_share",
            prefix_mode, cfg.quality.get("min_prefix_mapping_mode_share_warning", 0.5),
            prefix_mode >= float(cfg.quality.get("min_prefix_mapping_mode_share_warning", 0.5)),
            "Diagnostic only; endpoint-level mapping is the primary grouping contract."),
        "offtarget_target_ip_ratio": gate(
            "offtarget_target_ip_ratio",
            offtarget_ratio, 0.0, True,
            "Diagnostic only; non-Ukrainian or unknown target mappings remain visible here and are excluded from the fatal ASN denominator."),
    }
    fatal_ok = all(v["pass"] for v in gates.values() if v["severity"] == "fatal")
    warnings = [k for k, v in gates.items() if v["severity"] == "warning" and not v["pass"]]
    support_start = support_rows["measure_time"].min() if len(support_rows) else None
    support_end = support_rows["measure_time"].max() if len(support_rows) else None
    report = {
        "run_id": cfg.run_id,
        "analysis_cycle_hours": int(cfg.study["expected_cycle_interval_hours"]),
        "nominal_study_start": cfg.study["start_utc"], "nominal_study_end": cfg.study["end_utc"],
        "observed_support_start": support_start, "observed_support_end": support_end,
        "acquisition_support_start": support_start, "acquisition_support_end": support_end,
        "n_nominal_cycles": int(len(cq)), "n_support_cycles": int(len(support_rows)),
        "n_complete_support_cycles": int(support_rows["is_complete"].sum()),
        "nominal_complete_cycle_ratio": nominal_ratio,
        "n_target_ips": int(len(ipu)), "n_prefix24_mapping": int(len(prefix)),
        "national_eligible_ip_ratio": float(ipu["national_eligible"].mean()) if len(ipu) else 0.0,
        "regional_eligible_ip_ratio": valid_admin, "country_only_admin1_ip_ratio": country_only,
        "offtarget_target_ip_ratio": offtarget_ratio,
        "responding_prefix_turnover_fraction": turnover,
        "gates": gates, "fatal_pass": fatal_ok, "warning_failures": warnings,
        "overall_pass": fatal_ok,
        "interpretation": {
            "missing_ping_row": "Under the confirmed static full-scan contract, an absent target row in an import-complete cycle is a non-response. Low or zero aggregate response rows are retained as outcomes when import_files confirms that the Ping artifact was acquired.",
            "study_edges": "Nominal edge periods without an import-complete Ping artifact are excluded from the completeness denominator and reported as unsupported acquisition time.",
            "response_volume": "Ping-row MAD outliers are reported as diagnostics only and never used to remove event cycles, because response volume is the main outcome.",
            "admin1": "基辅 is explicitly mapped to Kyiv City; 基辅州 maps to Kyiv Oblast. Country-only labels such as 乌克兰 are retained for national analyses only.",
            "prefix_mapping": "Mixed mappings inside a /24 are handled at IP level. Prefix modal mapping is not used to assign every endpoint to one region.",
        },
    }
    p = cfg.out_dir("results_tables") / "quality_report.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    f1_cols = ["measure_time", "ping_rows", "ping_prefixes", "ping_unique_ips", "trace_rows",
               "trace_reached_rate", "as0_path_share", "geo_unknown_path_share",
               "import_status", "has_ping", "has_trace", "ping_acquisition_complete",
               "trace_acquisition_complete", "response_volume_outlier", "in_observed_support",
               "is_complete", "is_analysis_cycle", "exclusion_reason"]
    f1 = cq[[c for c in f1_cols if c in cq]].copy()
    f1.to_csv(cfg.out_dir("results_tables") / "f1_coverage.csv", index=False, encoding="utf-8-sig")
    if cfg.runtime.get("strict_fail_on_gate", True) and not fatal_ok:
        raise RuntimeError(f"Fatal quality gates failed; see {p}")
    return report


def run(cfg: Config) -> dict:
    with CHClient(cfg) as ch:
        cq = run_cycle_audit(cfg, ch)
        ipu, prefix, drift = run_target_universe(cfg, ch)
    avail = event_availability(cfg, cq, ipu)
    estimand_availability(cfg, ipu, avail)
    report = write_report(cfg, cq, ipu, prefix, drift, avail)
    status = "warning" if report.get("warning_failures") else "ok"
    return {"status": status, "outputs": [
        str(cfg.out_dir("data_derived") / "cycle_quality.parquet"),
        str(cfg.out_dir("data_derived") / "target_ip_universe.parquet"),
        str(cfg.out_dir("data_derived") / "target_universe.parquet"),
        str(cfg.out_dir("results_tables") / "event_data_availability.csv"),
        str(cfg.out_dir("results_tables") / "estimand_data_availability.csv"),
        str(cfg.out_dir("results_tables") / "admin1_canonicalization_audit.csv"),
        str(cfg.out_dir("results_tables") / "target_universe_sensitivity.csv"),
        str(cfg.out_dir("results_tables") / "monthly_target_drift.csv"),
        str(cfg.out_dir("results_tables") / "quality_report.json"),
    ], "report": report}
