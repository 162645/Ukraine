"""Scientific closure checks for the simplified calibration -> application chain."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config
from .provenance import read_manifest


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _application_gain(table: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, dict]:
    required = {"event_id", "estimand_id", "sensor_method", "status",
                "deficit_auc_full", "max_deficit"}
    if table.empty or not required.issubset(table.columns):
        return pd.DataFrame(), {"estimable": False}
    d = table[table.status.eq("ok") & table.sensor_method.isin(["B1", "B2"])].copy()
    rows = []
    for (event_id, estimand_id), group in d.groupby(["event_id", "estimand_id"]):
        methods = group.drop_duplicates("sensor_method").set_index("sensor_method")
        if not {"B1", "B2"}.issubset(methods.index):
            continue
        b1_auc = pd.to_numeric(pd.Series([methods.loc["B1", "deficit_auc_full"]]), errors="coerce").iloc[0]
        b2_auc = pd.to_numeric(pd.Series([methods.loc["B2", "deficit_auc_full"]]), errors="coerce").iloc[0]
        b1_max = pd.to_numeric(pd.Series([methods.loc["B1", "max_deficit"]]), errors="coerce").iloc[0]
        b2_max = pd.to_numeric(pd.Series([methods.loc["B2", "max_deficit"]]), errors="coerce").iloc[0]
        if pd.notna(b1_auc) and pd.notna(b2_auc):
            rows.append({"event_id": event_id, "estimand_id": estimand_id,
                         "b1_deficit_auc": b1_auc, "sensor_deficit_auc": b2_auc,
                         "gain_deficit_auc": b2_auc - b1_auc,
                         "b1_max_deficit": b1_max, "sensor_max_deficit": b2_max,
                         "gain_max_deficit": b2_max - b1_max})
    out = pd.DataFrame(rows)
    if out.empty:
        return out, {"estimable": False}
    event_gain = out.groupby("event_id").gain_deficit_auc.mean()
    rng = np.random.default_rng(int(cfg.runtime["random_seed"]) + 5000)
    boots = [float(rng.choice(event_gain.to_numpy(), len(event_gain), replace=True).mean())
             for _ in range(int(cfg.runtime["n_bootstrap"]))]
    return out, {
        "estimable": True, "independent_event_n": int(len(event_gain)),
        "mean_gain_deficit_auc": float(event_gain.mean()),
        "ci_lo": float(np.quantile(boots, .025)), "ci_hi": float(np.quantile(boots, .975)),
        "positive_event_fraction": float(event_gain.gt(0).mean()),
    }


def run(cfg: Config) -> dict:
    rt = cfg.out_dir("results_tables")
    checks = []

    def add(name: str, passed: bool, evidence, required: bool = True):
        checks.append({"check": name, "status": "PASS" if passed else "FAIL",
                       "required": required, "evidence": evidence})

    manifest = read_manifest(cfg)
    add("real_provenance", manifest.get("demo") is False and cfg.mode == "real",
        {"run_id": cfg.run_id, "mode": cfg.mode})
    quality_path = rt / "quality_report.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    add("measurement_quality", bool(quality.get("overall_pass")), quality.get("gates", {}))

    calibration_path = rt / "calibration_summary.json"
    calibration = json.loads(calibration_path.read_text(encoding="utf-8")) if calibration_path.exists() else {}
    calibration_ok = (int(calibration.get("estimable_event_n", 0)) > 0 and
                      int(calibration.get("calibrated_sensor_n", 0)) > 0)
    add("scheduled_outage_calibration", calibration_ok, calibration)

    panel = _read_csv(rt / "sensor_panel_summary.csv")
    method = str(panel.iloc[0].get("primary_sensor_method", "")) if not panel.empty else ""
    add("frozen_calibrated_sensor_panel", method == "B2",
        {"primary_sensor_method": method,
         "sensor_n": None if panel.empty else panel.iloc[0].get("n_B2_sensor")})

    main = _read_csv(rt / "exp_b_main_results.csv")
    attack_n = int(pd.to_numeric(main.get("inference_admissible", pd.Series(dtype=float)),
                                 errors="coerce").fillna(0).eq(1).sum()) if not main.empty else 0
    add("independent_unplanned_events", attack_n > 0,
        {"inference_admissible_result_n": attack_n})

    comparison, application = _application_gain(_read_csv(rt / "exp_b_method_sensitivity.csv"), cfg)
    comparison_path = rt / "calibrated_vs_stable_by_event.csv"
    comparison.to_csv(comparison_path, index=False, encoding="utf-8-sig")
    add("calibrated_vs_stable_comparison", bool(application.get("estimable")), application)

    external = _read_csv(rt / "exp_f_external_validation.csv")
    add("external_event_concordance", not external.empty, {"row_n": len(external)}, required=False)
    recovery = _read_csv(rt / "exp_d_summary.csv")
    recovery_ok = not recovery.empty and int(recovery.iloc[0].get("n_identified_model", 0)) > 0
    add("recovery_estimation", recovery_ok,
        {} if recovery.empty else recovery.iloc[0].to_dict(), required=False)

    hard_fail = [x for x in checks if x["required"] and x["status"] == "FAIL"]
    if hard_fail:
        closure = "RED_DATA_OR_DESIGN_FAILURE"
    elif not application.get("estimable"):
        closure = "YELLOW_INCOMPLETE_CORE_EVIDENCE"
    elif float(application.get("mean_gain_deficit_auc", 0)) > 0:
        closure = "GREEN_POSITIVE_CHAIN"
    else:
        closure = "GREEN_VALID_NEGATIVE_FINDINGS"
    interpretation = {
        "GREEN_POSITIVE_CHAIN": "Regional scheduled outages calibrated a frozen endpoint set that showed stronger network-visible disruption in independent unplanned energy shocks than the stable-IP pool.",
        "GREEN_VALID_NEGATIVE_FINDINGS": "The simplified chain was estimable, but calibrated endpoints did not improve independent-shock observation over the stable-IP pool.",
        "YELLOW_INCOMPLETE_CORE_EVIDENCE": "Calibration ran, but the independent calibrated-versus-stable comparison was not estimable.",
        "RED_DATA_OR_DESIGN_FAILURE": "A required provenance, measurement, calibration, frozen-panel, or independent-event contract failed.",
    }[closure]
    payload = {"run_id": cfg.run_id, "closure": closure, "calibration": calibration,
               "application": application, "checks": checks, "interpretation": interpretation}
    json_path = rt / "closure_report.json"
    md_path = rt / "closure_report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [f"# Scientific closure report — {cfg.run_id}", "", f"**Status: {closure}**",
             "", interpretation, ""]
    lines.extend(f"- **{x['status']}** `{x['check']}` — {x['evidence']}" for x in checks)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"status": closure, "outputs": [str(json_path), str(md_path), str(comparison_path)],
            "hard_failures": len(hard_fail)}
