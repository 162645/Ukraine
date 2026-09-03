"""End-to-end scientific closure checks for analysis plan v2.4.

Closure is based on *estimability and design validity*, not on forcing a positive
result.  A well-powered negative answer to calibration, repeatability, or
prediction is a scientific result; missing events, contaminated pre-periods, or
leakage are incomplete designs.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config
from .provenance import read_manifest


def _read_csv(p: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(p) if p.exists() and p.stat().st_size else pd.DataFrame()
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _truth(v) -> bool:
    if pd.isna(v):
        return False
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "pass"}
    return bool(v)


def run(cfg: Config) -> dict:
    rt = cfg.out_dir("results_tables")
    checks: list[dict] = []

    def add(name: str, status: str, evidence, required: bool = True, outcome: str = ""):
        checks.append({"check": name, "status": status, "required": required,
                       "outcome": outcome, "evidence": evidence})

    # Provenance and acquisition contract.
    m = read_manifest(cfg)
    add("real_provenance", "PASS" if (m.get("demo") is False and cfg.mode == "real") else "FAIL",
        {"mode": cfg.mode, "manifest_demo": m.get("demo"), "run_id": m.get("run_id")})
    qpath = rt / "quality_report.json"
    q = json.loads(qpath.read_text()) if qpath.exists() else {}
    add("measurement_quality_gates", "PASS" if q.get("overall_pass") else "FAIL", q.get("gates", {}))

    # Question 1: can scheduled outages calibrate sensors?
    a = _read_csv(rt / "exp_a_summary.csv")
    pr = _read_csv(rt / "f3_pr.csv")
    pr_ok = not pr.empty and pr["method"].nunique() >= 3 and pr.groupby("method").size().min() >= 5
    n_val = int(pd.to_numeric(a.get("n_estimable_validation_event", pd.Series([0])), errors="coerce").max()) if not a.empty else 0
    min_val = int(cfg.calibration.get("min_publication_validation_events", 2))
    n_val_clusters = int(pd.to_numeric(a.get("n_publication_validation_cluster", pd.Series([0])), errors="coerce").max()) if not a.empty else 0
    min_val_clusters = int(cfg.calibration.get("min_publication_validation_clusters", 2))
    cal_positive = bool(not a.empty and a.get("publication_calibration_closed", pd.Series(False)).map(_truth).any())
    cal_operational = bool(not a.empty and a.get("calibration_success", pd.Series(False)).map(_truth).any())
    delta = float(pd.to_numeric(a.get("delta_b2_vs_b1", pd.Series([np.nan])), errors="coerce").dropna().iloc[0]) if not a.empty and pd.to_numeric(a.get("delta_b2_vs_b1", pd.Series(dtype=float)), errors="coerce").notna().any() else np.nan
    cal_estimable = pr_ok and n_val >= min_val and n_val_clusters >= min_val_clusters
    add("calibration_full_pr_curve", "PASS" if pr_ok else "FAIL",
        {"points_per_method": pr.groupby("method").size().to_dict() if not pr.empty else {}})
    add("scheduled_outage_calibration_estimability",
        "PASS" if cal_estimable else "INCOMPLETE_EVIDENCE",
        {"estimable_validation_events": n_val, "required": min_val,
         "publication_validation_clusters": n_val_clusters,
         "required_clusters": min_val_clusters,
         "operational_success": cal_operational, "publication_positive": cal_positive,
         "delta_auprc_b2_vs_b1": delta}, required=False,
        outcome="POSITIVE" if cal_positive else ("NEGATIVE" if np.isfinite(delta) and delta <= 0 else "INCONCLUSIVE"))

    sensor = _read_csv(rt / "sensor_panel_summary.csv")
    primary = str(sensor.iloc[0]["primary_sensor_method"]) if not sensor.empty else ""
    expected_primary = "B2" if cal_operational else "B1"
    add("frozen_sensor_method", "PASS" if primary == expected_primary else "FAIL",
        {"expected": expected_primary, "actual": primary, "summary": sensor.to_dict("records")})

    # Question 2: does the frozen sensor panel quantify held-out attacks?
    b = _read_csv(rt / "exp_b_main_results.csv")
    if not b.empty:
        has_auc = pd.to_numeric(b.get("deficit_auc_full"), errors="coerce").notna()
        method_ok = b.get("sensor_method", pd.Series("", index=b.index)).eq(primary)
        inference = b.get("inference_admissible", pd.Series(0, index=b.index)).fillna(0).astype(int).eq(1) & has_auc
        design = b.get("design_admissible", pd.Series(0, index=b.index)).fillna(0).astype(int).eq(1) & has_auc
        role = b.get("analysis_role", pd.Series("", index=b.index)).astype(str)
        regional_inference = int((inference & role.eq("attack_regional")).sum())
        blind_inference = int((inference & role.eq("blind_test")).sum())
        primary_inference = int((inference & role.isin(["attack_national", "attack_regional", "blind_test"])).sum())
        design_only = int(design.sum())
        b_method_ok = bool(method_ok[has_auc].all()) if has_auc.any() else False
    else:
        regional_inference = blind_inference = primary_inference = design_only = 0
        b_method_ok = False
    add("attack_results_use_frozen_sensor", "PASS" if b_method_ok else "FAIL",
        {"primary_sensor_method": primary})
    attack_estimable = primary_inference >= 2 and (regional_inference >= 1 or blind_inference >= 1)
    add("held_out_attack_inference",
        "PASS" if attack_estimable else "FAIL",
        {"inference_admissible_primary_events": primary_inference,
         "regional": regional_inference, "blind": blind_inference,
         "design_admissible_before_pretrend_gate": design_only})

    # Independent validation is supportive but cannot define treatment.
    f = _read_csv(rt / "exp_f_external_validation.csv")
    temporal_n = int((f.get("external_time_available", pd.Series(dtype=int)).eq(1) &
                      f.get("temporal_concordant", pd.Series(dtype=int)).eq(1)).sum()) if not f.empty else 0
    spatial_metric = pd.to_numeric(f.get("topk_jaccard", f.get("spatial_jaccard", pd.Series(dtype=float))), errors="coerce") if not f.empty else pd.Series(dtype=float)
    spatial_n = int((spatial_metric > 0).sum())
    add("independent_external_concordance",
        "PASS" if temporal_n >= 1 and spatial_n >= 1 else "SUPPORT_LIMITED",
        {"temporally_concordant_events": temporal_n, "positive_spatial_events": spatial_n}, required=False)

    # Question 3: repeatable and predictable ASN×Admin1 resilience?
    csum = _read_csv(rt / "exp_c_summary.csv")
    caudit = _read_csv(rt / "prediction_feature_audit.csv")
    leak = int(csum.iloc[0].get("leakage_alert", 1)) if not csum.empty else 1
    test_events = int(csum.iloc[0].get("n_test_event", 0)) if not csum.empty else 0
    fit_failures = int(csum.iloc[0].get("primary_model_fit_failures", 1)) if not csum.empty else 1
    pred_positive = int(csum.iloc[0].get("prediction_success", 0)) == 1 if not csum.empty else False
    repeat_positive = int(csum.iloc[0].get("repeatability_success", 0)) == 1 if not csum.empty else False
    repeat_pairs = int(csum.iloc[0].get("repeatability_admissible_pairs", 0)) if not csum.empty else 0
    min_test = int(cfg.prediction.get("min_test_events_for_claim", 3))
    min_pairs = int(cfg.prediction.get("min_repeatability_pairs", 3))
    leak_ok = leak == 0 and not caudit.empty and caudit.get("feature_time_safe", pd.Series(0)).fillna(0).astype(int).eq(1).all()
    add("prediction_leakage_audit", "PASS" if leak_ok else "FAIL",
        {"leakage_alert": leak, "audit_rows": len(caudit)})
    prediction_estimable = leak_ok and fit_failures == 0 and test_events >= min_test
    repeatability_estimable = repeat_pairs >= min_pairs
    add("prospective_prediction_estimability",
        "PASS" if prediction_estimable else "INCOMPLETE_EVIDENCE",
        {"held_out_events": test_events, "required": min_test,
         "fit_failures": fit_failures, "positive_result": pred_positive}, required=False,
        outcome="POSITIVE" if pred_positive else "NEGATIVE")
    add("cross_event_repeatability_estimability",
        "PASS" if repeatability_estimable else "INCOMPLETE_EVIDENCE",
        {"admissible_pairs": repeat_pairs, "required": min_pairs,
         "positive_result": repeat_positive}, required=False,
        outcome="POSITIVE" if repeat_positive else "NEGATIVE")

    # Recovery debt and path adaptation are part of the stated paper chain when
    # enabled by the frozen closure contract. They may be scientifically null,
    # but they must be estimable before the complete paper can be green.
    d = _read_csv(rt / "exp_d_summary.csv")
    nonzero = float(d.iloc[0].get("primary_nonzero_share", 0)) if not d.empty else 0
    identified = int(d.iloc[0].get("n_identified_model", 0)) if not d.empty else 0
    require_recovery = bool(cfg.closure.get("require_recovery_debt", True))
    min_recovery = int(cfg.closure.get("min_identified_recovery_models", 1))
    recovery_estimable = identified >= min_recovery
    add("recovery_debt_estimability", "PASS" if recovery_estimable else "INCOMPLETE_EVIDENCE",
        {"nonzero_share": nonzero, "identified_models": identified,
         "required_models": min_recovery}, required=False)
    e = _read_csv(rt / "exp_e_summary.csv")
    admissible = int(e.iloc[0].get("n_admissible", 0)) if not e.empty else 0
    require_path = bool(cfg.closure.get("require_path_adaptation", True))
    min_path = int(cfg.closure.get("min_admissible_path_group_events", 1))
    path_estimable = admissible >= min_path
    add("path_adaptation_estimability", "PASS" if path_estimable else "INCOMPLETE_EVIDENCE",
        {"admissible_group_events": admissible, "required": min_path}, required=False)

    g = _read_csv(rt / "exp_g_oblast_falsification_summary.csv")
    regional_falsification_estimable = bool(not g.empty and int(g.iloc[0].get("estimable", 0)) == 1)
    add("operator_oblast_falsification_estimability",
        "PASS" if regional_falsification_estimable else "INCOMPLETE_EVIDENCE",
        {"estimable": regional_falsification_estimable,
         "effect_did": None if g.empty else g.iloc[0].get("effect_did"),
         "partial_queue_treatment": None if g.empty else g.iloc[0].get("partial_queue_treatment")},
        required=False)
    weather_ready = bool(not a.empty and int(a.iloc[0].get("weather_sensitivity_ready", 0)) == 1)
    weather_robust = bool(not a.empty and int(a.iloc[0].get("weather_robust_positive", 0)) == 1)
    add("calibration_weather_sensitivity",
        "PASS" if weather_ready else "INCOMPLETE_EVIDENCE",
        {"ready": weather_ready, "positive_robustness": weather_robust,
         "coverage": None if a.empty else a.iloc[0].get("weather_coverage")}, required=False,
        outcome="POSITIVE" if weather_robust else "NEGATIVE")

    # v2.5 keeps the national calibration as a frozen comparator and adds the
    # oblast-specific calibration as a required estimability branch. A null
    # regional delta is a valid result; missing LOO evidence is not.
    rh = _read_csv(rt / "regional_calibration_loo.csv")
    primary_buffer = int(cfg.regional_calibration.get("transition_buffer_minutes", 30))
    rb2 = (rh[rh.get("method", pd.Series(index=rh.index, dtype=str)).eq("B2_region") &
              pd.to_numeric(rh.get("transition_buffer_minutes", pd.Series(index=rh.index)),
                            errors="coerce").eq(primary_buffer)] if not rh.empty else pd.DataFrame())
    regional_holdouts = int(rb2["holdout_event_id"].nunique()) if not rb2.empty else 0
    regional_regions = int(rb2["target_admin1"].nunique()) if not rb2.empty else 0
    min_regional_holdouts = int(cfg.regional_calibration.get("min_holdout_events_for_estimability", 3))
    regional_estimable = regional_regions >= 1 and regional_holdouts >= min_regional_holdouts
    require_regional = bool(cfg.regional_calibration.get("enabled", True) and
                            cfg.regional_calibration.get("required_for_v25_closure", True))
    regional_positive = bool(not rb2.empty and rb2["delta_b2_vs_b1"].mean() > 0)
    add("oblast_specific_calibration_estimability",
        "PASS" if regional_estimable else ("FAIL" if require_regional else "INCOMPLETE_EVIDENCE"),
        {"primary_transition_buffer_minutes": primary_buffer,
         "regions": regional_regions, "held_out_events": regional_holdouts,
         "required_held_out_events": min_regional_holdouts,
         "mean_delta_b2_vs_b1": None if rb2.empty else rb2["delta_b2_vs_b1"].mean()},
        required=require_regional, outcome="POSITIVE" if regional_positive else "NEGATIVE")

    hard_fail = [x for x in checks if x["required"] and x["status"] == "FAIL"]
    core_complete = (cal_estimable and (regional_estimable or not require_regional) and
                     attack_estimable and prediction_estimable and
                     repeatability_estimable and
                     (recovery_estimable or not require_recovery) and
                     (path_estimable or not require_path))
    if hard_fail:
        closure = "RED_DATA_OR_DESIGN_FAILURE"
    elif core_complete:
        positive = cal_positive and pred_positive and repeat_positive
        positive_release_ready = (
            (weather_ready or not bool(cfg.closure.get("require_weather_sensitivity_for_positive_chain", True))) and
            (regional_falsification_estimable or not bool(cfg.closure.get("require_regional_falsification_for_positive_chain", True))))
        closure = ("GREEN_POSITIVE_CHAIN" if positive_release_ready else "YELLOW_INCOMPLETE_CORE_EVIDENCE") if positive else "GREEN_VALID_NEGATIVE_FINDINGS"
    else:
        closure = "YELLOW_INCOMPLETE_CORE_EVIDENCE"

    interpretations = {
        "GREEN_POSITIVE_CHAIN": "The full positive calibration → held-out attack → repeatable/predictive resilience chain is estimable and supported.",
        "GREEN_VALID_NEGATIVE_FINDINGS": "The full core chain is estimable; one or more preregistered hypotheses are not supported. This is a scientifically closed negative/mixed-result study, not a pipeline failure.",
        "YELLOW_INCOMPLETE_CORE_EVIDENCE": "The data pipeline is coherent, but too few independent scheduled-outage or held-out attack events remain for the full paper claim. Add evidence; do not tune results post hoc.",
        "RED_DATA_OR_DESIGN_FAILURE": "At least one required provenance, measurement, frozen-sensor, leakage, or event-inference contract failed.",
    }
    payload = {"run_id": cfg.run_id, "closure": closure, "checks": checks,
               "core_estimability": {"calibration": cal_estimable,
                                      "oblast_specific_calibration": regional_estimable,
                                      "attacks": attack_estimable,
                                      "repeatability": repeatability_estimable, "prediction": prediction_estimable,
                                      "recovery_debt": recovery_estimable,
                                      "path_adaptation": path_estimable},
               "core_outcomes": {"calibration_positive": cal_positive,
                                  "oblast_specific_calibration_positive": regional_positive,
                                  "repeatability_positive": repeat_positive,
                                  "prediction_positive": pred_positive},
               "interpretation": interpretations[closure]}
    (rt / "closure_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [f"# Scientific closure report — {cfg.run_id}", "", f"**Status: {closure}**", "", interpretations[closure], ""]
    for x in checks:
        lines.append(f"- **{x['status']}** `{x['check']}` — {x['evidence']}")
    (rt / "closure_report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"status": closure, "outputs": [str(rt / "closure_report.json"), str(rt / "closure_report.md")],
            "hard_failures": len(hard_fail)}
