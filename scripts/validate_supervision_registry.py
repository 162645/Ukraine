#!/usr/bin/env python3
"""Offline publication-readiness audit for all frozen supervision inputs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uresil.config import load_config  # noqa: E402
from uresil.preflight import (validate_event_registry, validate_oblast_execution_registry,
                              validate_schedule_registry, validate_weather_episode_registry)  # noqa: E402


def main() -> int:
    cfg = load_config(run_id="supervision_registry_check", mode="demo")
    checks = {
        "event_registry": validate_event_registry(cfg),
        "schedule_registry": validate_schedule_registry(cfg),
        "oblast_execution_registry": validate_oblast_execution_registry(cfg),
        "weather_episode_registry": validate_weather_episode_registry(cfg),
    }
    wcfg = cfg.calibration.get("weather_sensitivity", {})
    weather = ROOT / str(wcfg.get("data_path", "data_derived/weather_admin1_2h.parquet"))
    checks["weather_admin1_2h"] = [] if weather.exists() else [f"missing {weather}"]
    evidence_report = ROOT / "evidence/evidence_verification_report.json"
    evidence_ok = False
    if evidence_report.exists():
        evidence_ok = bool(json.loads(evidence_report.read_text(encoding="utf-8")).get("ok"))
    checks["immutable_evidence"] = [] if evidence_ok else ["evidence verification is not submission-ready"]
    payload = {"ok": all(not errors for errors in checks.values()), "checks": checks,
               "frozen_hashes": cfg.frozen_hashes()}
    out = ROOT / "supervision_registry_check.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
