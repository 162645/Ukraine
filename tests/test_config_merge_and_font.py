from pathlib import Path

from uresil.config import load_config
from uresil.viz.style import cjk_font_report


def test_local_config_inherits_scientific_defaults():
    cfg = load_config(run_id="config_merge", mode="demo")
    assert cfg.inference["ci_level"] == 0.95
    assert cfg.prediction["min_test_events_for_claim"] == 3
    assert cfg.figures["png_dpi"] == 600


def test_cjk_font_has_representative_glyphs():
    report = cjk_font_report(load_config(run_id="font_check", mode="demo"))
    assert Path(report["path"]).exists()
    assert report["ok"], report


def test_clickhouse_environment_overrides_are_typed(monkeypatch):
    monkeypatch.setenv("UR_CH_CONNECT_TIMEOUT", "7")
    monkeypatch.setenv("UR_CH_SEND_RECEIVE_TIMEOUT", "91")
    monkeypatch.setenv("UR_CH_APPLY_SETTINGS", "0")
    monkeypatch.setenv("UR_CH_SECURE", "true")
    cfg = load_config("config/experiment_v2.yaml", run_id="db_env", mode="demo")
    db = cfg.db_conn()
    assert db["connect_timeout"] == 7
    assert db["send_receive_timeout"] == 91
    assert db["apply_query_settings"] is False
    assert db["secure"] is True
