"""Experiment F — independent temporal and spatial external validation.

Third-party network observations never define the confirmatory power estimand or
train a sensor.  They are used after Experiment B is frozen.  When available,
the separate ``network_replication`` estimand is used to test whether the self-
measurement reproduces the externally reported network geography.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config
from .events import Events
from .progress import get_logger, step

INVALID_ADMIN1 = {"COUNTRY_ONLY_UA", "UNKNOWN_ADMIN1", "UNMAPPED_UA_ADMIN1"}


def _first_consecutive_time(g: pd.DataFrame, cfg: Config) -> float:
    z = g.sort_values("rel_h")
    flags = ((z["ci_hi"] < float(cfg.external_validation["significant_upper_ci_below"])) &
             (z["rel_h"] >= 0))
    k = int(cfg.external_validation["consecutive_cycles"]); run = 0
    for rel, flag in zip(z.rel_h, flags):
        run = run + 1 if bool(flag) else 0
        if run >= k:
            return float(rel-(k-1)*float(cfg.study["expected_cycle_interval_hours"]))
    return np.nan


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else np.nan


def _simes(p: pd.Series) -> float:
    x = np.sort(pd.to_numeric(p, errors="coerce").dropna().clip(0, 1).to_numpy(float))
    if not len(x):
        return np.nan
    return float(min(1.0, np.min(x * len(x) / np.arange(1, len(x)+1))))


def _bh(values: pd.Series) -> pd.Series:
    p = pd.to_numeric(values, errors="coerce"); out = pd.Series(np.nan, index=p.index)
    valid = p.dropna().sort_values(); m = len(valid)
    if not m:
        return out
    raw = valid.to_numpy(float) * m / np.arange(1, m+1)
    q = np.minimum.accumulate(raw[::-1])[::-1].clip(0, 1)
    out.loc[valid.index] = q
    return out


def _consecutive_negative(z: pd.DataFrame, cfg: Config) -> bool:
    z = z.sort_values("rel_h")
    flags = ((z["ci_hi"] < 0) &
             (z["reach_dev"] <= float(cfg.external_validation["admin1_reach_deviation_threshold"])))
    k = int(cfg.external_validation["consecutive_cycles"]); run = 0
    for flag in flags:
        run = run + 1 if bool(flag) else 0
        if run >= k:
            return True
    return False


def spatial_detection_table(f5: pd.DataFrame, event_id: str, cfg: Config) -> pd.DataFrame:
    z = f5[(f5.event_id.eq(event_id)) & f5.rel_h.between(0, float(cfg.external_validation.get("spatial_window_h", 24)))].copy()
    z = z[~z.admin1.isin(INVALID_ADMIN1)]
    if z.empty:
        return pd.DataFrame()
    rows = []
    for admin1, g in z.groupby("admin1"):
        rows.append({"event_id": event_id, "admin1": admin1,
                     "min_reach_dev": float(g["reach_dev"].min()),
                     "simes_p": _simes(g.get("p_value", pd.Series(dtype=float))),
                     "consecutive_negative": int(_consecutive_negative(g, cfg)),
                     "n_cycles": len(g), "n_prefix_min": int(g["n_prefix"].min())})
    out = pd.DataFrame(rows); out["fdr_q"] = _bh(out["simes_p"])
    alpha = float(cfg.inference.get("fdr_alpha", 0.05))
    out["detected"] = ((out["consecutive_negative"].eq(1)) & (out["fdr_q"] <= alpha)).astype(int)
    out["rank"] = out["min_reach_dev"].rank(method="min", ascending=True)
    return out


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs")); rt = cfg.out_dir("results_tables")
    f4p, f5p, mainp = rt/"f4_event_study.csv", rt/"f5_state_time.csv", rt/"exp_b_main_results.csv"
    if not f4p.exists() or not mainp.exists():
        raise FileNotFoundError(f4p if not f4p.exists() else mainp)
    f4 = pd.read_csv(f4p); f5 = pd.read_csv(f5p) if f5p.exists() and f5p.stat().st_size else pd.DataFrame()
    main = pd.read_csv(mainp); ev = Events(cfg); rows=[]; spatial_parts=[]
    with step("Experiment F: independent external concordance", logger):
        for _, e in ev.attacks.iterrows():
            ext_time = pd.to_datetime(e.get("network_anomaly_start_utc"), utc=True, errors="coerce")
            ext_states = set(ev.observed_admin1(e)) - INVALID_ADMIN1
            admissible = bool(((main.event_id.eq(e.event_id)) &
                               main.get("design_admissible", pd.Series(0, index=main.index)).eq(1)).any())
            # Temporal replication uses the network-replication curve when present;
            # otherwise the confirmatory curve is reported with an explicit fallback.
            curve = f4[(f4.event_id.eq(e.event_id)) & (f4.estimand_id.eq("network_replication"))]
            temporal_estimand = "network_replication"
            if curve.empty:
                curve = f4[(f4.event_id.eq(e.event_id)) & (f4.get("confirmatory", 0).eq(1))]
                temporal_estimand = "confirmatory_fallback"
            onset_rel = _first_consecutive_time(curve, cfg) if admissible and not curve.empty else np.nan
            anchor_col = "anchor_utc" if "anchor_utc" in curve else None
            anchor = pd.to_datetime(curve.iloc[0][anchor_col], utc=True, errors="coerce") if not curve.empty and anchor_col else Events.anchor_time(e)
            internal_time = anchor + pd.Timedelta(hours=onset_rel) if np.isfinite(onset_rel) else pd.NaT
            offset = (internal_time-ext_time).total_seconds()/3600 if pd.notna(internal_time) and pd.notna(ext_time) else np.nan

            if not f5.empty:
                sf = f5[(f5.event_id.eq(e.event_id)) & (f5.estimand_id.eq("network_replication"))]
                spatial_estimand = "network_replication"
                if sf.empty:
                    sf = f5[(f5.event_id.eq(e.event_id)) & (f5.estimand_id.eq("confirmatory_power"))]
                    spatial_estimand = "confirmatory_fallback"
                det = spatial_detection_table(sf, str(e.event_id), cfg) if not sf.empty else pd.DataFrame()
            else:
                det = pd.DataFrame(); spatial_estimand = "none"
            if not det.empty:
                det["estimand_used"] = spatial_estimand; spatial_parts.append(det)
            detected = set(det.loc[det.detected.eq(1), "admin1"]) if not det.empty else set()
            k = len(ext_states)
            topk = set(det.nsmallest(k, "min_reach_dev")["admin1"]) if k and not det.empty else set()
            tp = len(detected & ext_states); precision = tp/len(detected) if detected else np.nan
            recall = tp/len(ext_states) if ext_states else np.nan
            non_ext = set(det.admin1)-ext_states if not det.empty else set()
            fpr = len(detected & non_ext)/len(non_ext) if non_ext else np.nan
            rows.append({
                "event_id": e.event_id, "analysis_role": e.analysis_role,
                "design_admissible": int(admissible), "temporal_estimand_used": temporal_estimand,
                "spatial_estimand_used": spatial_estimand,
                "external_network_start_utc": ext_time, "internal_onset_rel_h": onset_rel,
                "internal_onset_utc": internal_time, "temporal_offset_h": offset,
                "temporal_concordant": int(np.isfinite(offset) and abs(offset) <= float(cfg.external_validation["max_temporal_offset_h"])),
                "external_admin1": "|".join(sorted(ext_states)),
                "internally_detected_admin1": "|".join(sorted(detected)),
                "topk_internal_admin1": "|".join(sorted(topk)),
                "spatial_jaccard": _jaccard(ext_states, detected),
                "topk_jaccard": _jaccard(ext_states, topk),
                "spatial_precision": precision, "spatial_recall": recall,
                "spatial_false_positive_rate": fpr,
                "external_time_available": int(pd.notna(ext_time)),
                "external_space_available": int(bool(ext_states)),
            })
    out = pd.DataFrame(rows); out.to_csv(rt/"exp_f_external_validation.csv", index=False)
    out.to_csv(rt/"f13_external.csv", index=False)
    spatial = pd.concat(spatial_parts, ignore_index=True) if spatial_parts else pd.DataFrame()
    spatial.to_csv(rt/"exp_f_spatial_detection.csv", index=False)
    return {"status": "ok", "outputs": [str(rt/"exp_f_external_validation.csv"),
                                           str(rt/"exp_f_spatial_detection.csv"), str(rt/"f13_external.csv")]}
