import yaml

from uresil.config import load_config


def test_full_local_copy_cannot_override_frozen_science(tmp_path):
    path = tmp_path / "local.yaml"
    path.write_text(yaml.safe_dump({
        "freeze": {"plan_version": "obsolete"},
        "simple_calibration": {"min_drop": 0.0},
        "database": {"host": "db.internal"},
        "runtime": {"max_memory_gb": 48, "random_seed": 1},
    }), encoding="utf-8")
    cfg = load_config(path, run_id="scope-test", mode="real")
    assert cfg.raw["freeze"]["plan_version"] == "analysis_plan_v5_simple_outage_calibration"
    assert cfg.simple_calibration["min_drop"] == 0.5
    assert cfg.database["host"] == "db.internal"
    assert cfg.runtime["max_memory_gb"] == 48
    assert cfg.runtime["random_seed"] == 20240601
