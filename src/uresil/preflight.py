"""Fast configuration, event-registry, schema, and provenance preflight checks."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import Config
from .db import CHClient
from .geo import Admin1Canonicalizer
from .mapping_snapshot import mapping_manifest_state, query_mapping_snapshot
from .progress import get_logger, step
from .time_contract import measurement_time_contract
from .viz.style import cjk_font_report

REQUIRED_COLUMNS = {
    "ping": {"cycle_id", "measure_time", "data_center", "prefix24", "dst_ip", "rtt_ms"},
    "trace": {"cycle_id", "measure_time", "data_center", "prefix24", "dst_ip", "hop_path",
              "hop_count", "responded_hop_count", "star_hop_count", "reached_target",
              "as_path_text", "asgeo_path_text", "probe_ts_us"},
    "mapping": {"ip", "asn", "geo_country", "geo_region", "updated_at"},
    "import_files": {"cycle_id", "measure_time", "data_center", "import_status", "error_message", "updated_at", "has_ping", "has_trace", "ping_rows", "trace_rows"},
}


def validate_event_registry(cfg: Config) -> list[str]:
    ev = cfg.load_event_registry()
    errors: list[str] = []
    if ev["event_id"].duplicated().any():
        errors.append("duplicate event_id")
    ready = ev[ev["analysis_ready"].eq(1)]
    if ready.empty:
        errors.append("no analysis_ready events")
    canon = Admin1Canonicalizer(cfg.resource_path("admin1_aliases"),
                                cfg.quality["unknown_labels"], cfg.quality["valid_country_aliases"])
    for _, r in ready.iterrows():
        if pd.isna(r["primary_anchor_utc"]):
            errors.append(f"{r['event_id']}: missing primary_anchor_utc")
        if not str(r.get("source_hash", "")).strip():
            errors.append(f"{r['event_id']}: missing source_hash")
        lo, hi = r.get("anchor_lower_utc"), r.get("anchor_upper_utc")
        if pd.notna(lo) and pd.notna(hi) and lo > hi:
            errors.append(f"{r['event_id']}: anchor lower > upper")
        if pd.notna(r.get("outage_start_utc")) and pd.notna(r.get("outage_end_utc")) and r["outage_start_utc"] > r["outage_end_utc"]:
            errors.append(f"{r['event_id']}: outage start > end")
        for col in ("analysis_treated_admin1", "power_affected_admin1", "network_observed_admin1"):
            for admin in [x.strip() for x in str(r.get(col, "")).split("|") if x.strip() and x.strip() != "ALL"]:
                if canon.canonical_admin1("Ukraine", admin) in {"UNKNOWN_ADMIN1", "UNMAPPED_UA_ADMIN1"}:
                    errors.append(f"{r['event_id']}: invalid {col} value {admin!r}")
    min_train = int(cfg.calibration.get("min_training_events", 1))
    min_valid = int(cfg.calibration.get("min_validation_events", 2))
    if ready[ready["analysis_role"].eq("planned_train")].shape[0] < min_train:
        errors.append(f"fewer than {min_train} planned_train events")
    if ready[ready["analysis_role"].eq("planned_valid")].shape[0] < min_valid:
        errors.append(f"fewer than {min_valid} planned_valid events")
    return errors


def validate_schedule_registry(cfg: Config) -> list[str]:
    schedule = cfg.load_schedule_registry()
    events = cfg.load_event_registry()
    errors: list[str] = []
    required = {"segment_id", "event_id", "independence_cluster", "start_utc", "end_utc",
                "queue_count", "timezone_name", "source_authority", "source_url",
                "final_version", "publication_eligible"}
    missing = sorted(required - set(schedule.columns))
    if missing:
        return [f"missing columns: {missing}"]
    if schedule["segment_id"].duplicated().any():
        errors.append("duplicate segment_id")
    known = set(events["event_id"].astype(str))
    unknown = sorted(set(schedule["event_id"].astype(str)) - known)
    # v3.0 contains a date-complete regional/evidence registry.  Rows that do
    # not correspond to the frozen v2 event registry remain available for the
    # regional overlay, but are not silently promoted to core event claims.
    is_v3 = "schema_version" in schedule and schedule["schema_version"].astype(str).str.startswith("v3").any()
    if unknown and not is_v3:
        errors.append(f"schedule references unknown events: {unknown}")
    if schedule["independence_cluster"].astype(str).str.strip().eq("").any():
        errors.append("blank independence_cluster")
    if (~schedule["timezone_name"].eq("Europe/Kyiv")).any():
        errors.append("all schedule rows must use Europe/Kyiv")
    if (schedule["end_utc"] <= schedule["start_utc"]).any():
        errors.append("non-positive schedule interval")
    if (~schedule["queue_count"].between(0, 6)).any():
        errors.append("queue_count outside [0,6]")
    if schedule["final_version"].ne(1).any():
        errors.append("non-final schedule version present in frozen registry")
    if is_v3:
        if (~schedule["source_url"].astype(str).str.startswith("https://")).any():
            errors.append("v3 schedule contains non-HTTPS source URL")
    elif (~schedule["source_url"].astype(str).str.startswith(("https://t.me/s/Ukrenergo", "https://t.me/s/ukrenergo"))).any():
        errors.append("non-official schedule source URL")
    grouping = ["event_id"]
    if is_v3:
        # Regional v3 rows may legitimately overlap national rows.  Only
        # reject overlaps within the same administrative/operator scope.
        grouping = [c for c in ("event_id", "admin1", "operator", "scope_type", "queue_id") if c in schedule]
    for _, group in schedule.sort_values("start_utc").groupby(grouping, dropna=False):
        prev_end = None
        for _, row in group.iterrows():
            if prev_end is not None and row["start_utc"] < prev_end:
                errors.append("overlapping final schedule segments within one scope")
                break
            prev_end = row["end_utc"]
    return errors


def validate_oblast_execution_registry(cfg: Config) -> list[str]:
    d = cfg.load_oblast_execution_registry()
    errors: list[str] = []
    required = {"record_id", "contrast_id", "admin1", "action_type", "timezone_name",
                "start_utc", "end_utc", "verification_status", "analysis_eligible",
                "publication_eligible", "source_url", "attack_recovery_confounded"}
    missing = sorted(required - set(d.columns))
    if missing:
        return [f"missing columns: {missing}"]
    if d["record_id"].duplicated().any():
        errors.append("duplicate record_id")
    if (~d["timezone_name"].eq("Europe/Kyiv")).any():
        errors.append("all operator records must use Europe/Kyiv")
    if (d["end_utc"] <= d["start_utc"]).any():
        errors.append("non-positive operator interval")
    allowed = {"scheduled", "activated", "reduced", "cancelled", "restored", "emergency_override"}
    bad = sorted(set(d["action_type"]) - allowed)
    if bad:
        errors.append(f"invalid action_type: {bad}")
    eligible = d[pd.to_numeric(d["analysis_eligible"], errors="coerce").fillna(0).eq(1)]
    for contrast_id, g in eligible.groupby("contrast_id"):
        if g["admin1"].nunique() < 2:
            errors.append(f"{contrast_id}: fewer than two Admin1 arms")
        if not {"activated", "cancelled"}.issubset(set(g["action_type"])):
            errors.append(f"{contrast_id}: requires activated and cancelled arms")
        if g["verification_status"].ne("verified").any():
            errors.append(f"{contrast_id}: analysis-eligible row is not verified")
    return errors


def validate_weather_episode_registry(cfg: Config) -> list[str]:
    d = cfg.load_weather_episode_registry()
    errors: list[str] = []
    required = {"episode_id", "start_utc", "end_utc", "timezone_name", "source_url",
                "source_authority", "verification_status"}
    missing = sorted(required - set(d.columns))
    if missing:
        return [f"missing columns: {missing}"]
    if d["episode_id"].duplicated().any():
        errors.append("duplicate weather episode_id")
    if (d["end_utc"] <= d["start_utc"]).any():
        errors.append("non-positive weather episode")
    if d["verification_status"].ne("verified").any():
        errors.append("unverified weather episode in frozen registry")
    return errors


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    checks = []
    event_errors = validate_event_registry(cfg)
    checks.append({"check": "event_registry", "ok": not event_errors, "detail": event_errors})
    schedule_errors = validate_schedule_registry(cfg)
    checks.append({"check": "planned_outage_schedule_registry", "ok": not schedule_errors,
                   "detail": schedule_errors})
    oblast_errors = validate_oblast_execution_registry(cfg)
    checks.append({"check": "oblast_execution_registry", "ok": not oblast_errors,
                   "detail": oblast_errors})
    weather_errors = validate_weather_episode_registry(cfg)
    checks.append({"check": "weather_episode_registry", "ok": not weather_errors,
                   "detail": weather_errors})

    # These are publication-readiness checks, not reasons to prevent the expensive
    # measurement analysis from starting. A positive mechanism claim cannot be
    # released until both are complete.
    weather_cfg = cfg.calibration.get("weather_sensitivity", {})
    weather_path = cfg.root / str(weather_cfg.get("data_path", "data_derived/weather_admin1_2h.parquet"))
    weather_ready = weather_path.exists()
    weather_detail: dict = {"path": str(weather_path), "exists": weather_ready}
    if weather_ready:
        try:
            cols = set(pd.read_parquet(weather_path, columns=None).columns)
            missing_weather = sorted(set(weather_cfg.get("required_columns", [])) - cols)
            weather_ready = not missing_weather
            weather_detail["missing_columns"] = missing_weather
        except Exception as exc:  # noqa: BLE001
            weather_ready = False
            weather_detail["error"] = f"{type(exc).__name__}: {exc}"
    checks.append({"check": "weather_admin1_2h_ready", "ok": weather_ready,
                   "required": False, "detail": weather_detail})

    sources = cfg.load_source_post_registry()
    required_sources = sources[pd.to_numeric(sources["archive_required"], errors="coerce").fillna(0).eq(1)]
    archived = required_sources["snapshot_path"].astype(str).str.strip().ne("") & required_sources["text_sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}")
    checks.append({"check": "primary_source_archive_ready", "ok": bool(archived.all()),
                   "required": False,
                   "detail": {"required": int(len(required_sources)), "archived": int(archived.sum()),
                              "message": "Live official URLs are verified; immutable local exports and hashes remain a release gate."}})

    ready = cfg.load_event_registry()
    ready = ready[ready["analysis_ready"].eq(1)]
    role_counts = ready.groupby("analysis_role").size().astype(int).to_dict()
    registered_valid = int(role_counts.get("planned_valid", 0))
    required_valid = int(cfg.calibration.get("min_publication_validation_events", 2))
    schedule = cfg.load_schedule_registry()
    valid_ids = set(ready.loc[ready["analysis_role"].eq("planned_valid"), "event_id"].astype(str))
    pub_schedule = schedule[(schedule["event_id"].isin(valid_ids)) & schedule["publication_eligible"].eq(1)]
    registered_valid_clusters = int(pub_schedule["independence_cluster"].replace("", pd.NA).dropna().nunique())
    required_valid_clusters = int(cfg.calibration.get("min_publication_validation_clusters", 2))
    attack_roles = {"attack_national", "attack_regional", "blind_test", "stress_test"}
    registered_attacks = int(ready[ready["analysis_role"].isin(attack_roles)].shape[0])
    min_train = int(cfg.prediction.get("min_train_events", 2))
    potential_prediction_holdouts = max(0, registered_attacks - min_train)
    required_prediction_holdouts = int(cfg.prediction.get("min_test_events_for_claim", 3))
    capacity_ok = (registered_valid >= required_valid and
                   registered_valid_clusters >= required_valid_clusters and
                   potential_prediction_holdouts >= required_prediction_holdouts)
    checks.append({
        "check": "registered_core_closure_capacity", "ok": capacity_ok, "required": False,
        "detail": {
            "role_counts": role_counts,
            "scheduled_outage_validation": {"registered": registered_valid,
                                                "required": required_valid,
                                                "independent_publication_clusters": registered_valid_clusters,
                                                "required_clusters": required_valid_clusters},
            "prospective_prediction_holdouts_upper_bound": {
                "registered_attack_events": registered_attacks,
                "after_minimum_training_events": potential_prediction_holdouts,
                "required": required_prediction_holdouts,
            },
            "interpretation": ("Registry can support the configured closure counts if data windows pass."
                               if capacity_ok else
                               "Even perfect execution cannot satisfy every configured publication-count gate; "
                               "add independently registered evidence or expect YELLOW_INCOMPLETE_CORE_EVIDENCE."),
        },
    })

    # Fail before a multi-hour database run if a confirmatory model dependency is
    # missing.  Experiment D has a documented NumPy fallback, but statsmodels is
    # still required for the preregistered clustered model and variance components.
    dep_versions = {}
    dep_errors = []
    for module in ("numpy", "pandas", "scipy", "sklearn", "statsmodels", "pyarrow", "matplotlib"):
        try:
            mod = __import__(module)
            dep_versions[module] = getattr(mod, "__version__", "unknown")
        except Exception as exc:  # noqa: BLE001
            dep_errors.append(f"{module}: {type(exc).__name__}: {exc}")
    checks.append({"check": "scientific_dependencies", "ok": not dep_errors,
                   "detail": {"versions": dep_versions, "errors": dep_errors}})

    try:
        font_report = cjk_font_report(cfg)
        checks.append({"check": "cjk_submission_font", "ok": bool(font_report["ok"]),
                       "detail": font_report})
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "cjk_submission_font", "ok": False,
                       "detail": f"{type(exc).__name__}: {exc}"})

    manifest = cfg.load_mapping_manifest()
    fr, frozen, freeze_missing = mapping_manifest_state(manifest)
    checks.append({"check": "mapping_manifest_frozen", "ok": frozen and not freeze_missing,
                   "detail": {"message": "Final paper run requires a frozen mapping contract; exploratory runs may continue.",
                              "missing": freeze_missing}})

    if cfg.study.get("denominator_mode") != "static_full_scan" or not cfg.study.get("static_full_scan_confirmed"):
        checks.append({"check": "ping_denominator", "ok": False,
                       "detail": "Cannot infer non-response without a confirmed target denominator."})
    else:
        checks.append({"check": "ping_denominator", "ok": True,
                       "detail": "Static full-scan denominator explicitly confirmed in config."})

    if cfg.mode == "real":
        with step("ClickHouse schema preflight", logger):
            with CHClient(cfg) as ch:
                try:
                    time_report = measurement_time_contract(ch, cfg)
                    checks.append({"check": "measurement_timestamp_timezone_contract",
                                   "ok": bool(time_report["contract_ok"]),
                                   "detail": time_report})
                except Exception as e:  # noqa: BLE001
                    checks.append({"check": "measurement_timestamp_timezone_contract",
                                   "ok": False, "detail": str(e)})
                for logical, required in REQUIRED_COLUMNS.items():
                    try:
                        d = ch.describe(logical)
                        names = set(d.iloc[:, 0].astype(str))
                        missing = sorted(required - names)
                        checks.append({"check": f"schema:{logical}", "ok": not missing,
                                       "detail": {"missing": missing, "n_columns": len(names)}})
                    except Exception as e:  # noqa: BLE001
                        checks.append({"check": f"schema:{logical}", "ok": False, "detail": str(e)})
                if frozen and not freeze_missing:
                    try:
                        cutoff = str(fr["snapshot_date"]).replace(" UTC", "")[:19]
                        snap = query_mapping_snapshot(ch, cfg.table("mapping"), cutoff)
                        actual_count = int(snap["row_count"])
                        actual_checksum = str(snap["content_checksum_uint64"])
                        ok = (actual_count == int(fr["row_count"]) and
                              actual_checksum == str(fr["content_checksum_uint64"]))
                        checks.append({"check": "mapping_snapshot_matches", "ok": ok,
                                       "detail": {"actual_row_count": actual_count,
                                                  "expected_row_count": int(fr["row_count"]),
                                                  "actual_checksum": actual_checksum,
                                                  "expected_checksum": str(fr["content_checksum_uint64"])}})
                    except Exception as e:  # noqa: BLE001
                        checks.append({"check": "mapping_snapshot_matches", "ok": False, "detail": str(e)})
    else:
        checks.append({"check": "schema:demo", "ok": True, "detail": "DB checks skipped in demo mode"})

    out = cfg.out_dir("results_tables") / "preflight_report.json"
    require_mapping = bool(cfg.runtime.get("require_frozen_mapping", True)) and cfg.mode == "real"
    def _required(x):
        if x.get("required") is False:
            return False
        return x["check"] != "mapping_manifest_frozen" or require_mapping
    payload = {"run_id": cfg.run_id, "mode": cfg.mode, "checks": checks,
               "ok": all(x["ok"] for x in checks if _required(x))}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    hard_fail = [x for x in checks if not x["ok"] and _required(x)]
    if hard_fail and cfg.runtime.get("strict_fail_on_gate", True):
        raise RuntimeError(f"Preflight failed: {hard_fail}")
    return {"status": "ok" if not hard_fail else "warning", "outputs": [str(out)], "checks": checks}
