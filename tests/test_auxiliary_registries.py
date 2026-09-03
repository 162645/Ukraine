from uresil.config import load_config
from uresil.preflight import validate_oblast_execution_registry, validate_weather_episode_registry


def test_frozen_auxiliary_registries_are_structurally_valid():
    cfg = load_config(run_id="test_aux", mode="demo")
    assert validate_oblast_execution_registry(cfg) == []
    assert validate_weather_episode_registry(cfg) == []


def test_only_verified_clean_operator_contrast_is_publication_eligible():
    cfg = load_config(run_id="test_aux_eligible", mode="demo")
    d = cfg.load_oblast_execution_registry()
    pub = d[d["publication_eligible"].eq("1")]
    assert set(pub["contrast_id"]) == {"C2024_0724_ZP_VOL"}
    assert set(pub["verification_status"]) == {"verified"}
    assert set(pub["action_type"]) == {"activated", "cancelled"}


def test_primary_operator_contrast_has_exact_source_and_pipeline_event():
    cfg = load_config(run_id="test_aux_event", mode="demo")
    sources = cfg.load_source_post_registry().set_index("source_id")
    assert sources.loc["SRC_ZP_0724", "telegram_message_id"] == "974"
    assert sources.loc["SRC_ZP_0724", "url"].endswith("/974")
    events = cfg.load_event_registry().set_index("event_id")
    row = events.loc["E2024_0724_OBLAST_FALSIFICATION"]
    assert row["analysis_role"] == "planned_falsification"
    assert row["analysis_treated_admin1"] == "Zaporizhzhia Oblast"
