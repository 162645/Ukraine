import pandas as pd

from scripts.import_v4_schedule import REQUIRED, transform


def _row(**overrides):
    row = {column: "" for column in REQUIRED}
    row.update({
        "merge_group_id": "m1", "event_date": "2024-07-01",
        "admin1": "Odesa Oblast", "operator": "DTEK Odesa Grids",
        "scope_type": "operator_service_area", "restriction_type": "hourly_schedule",
        "planned_start_utc": "2024-07-01T10:00:00Z",
        "planned_end_utc": "2024-07-01T12:00:00Z",
        "timezone_name": "Europe/Kyiv", "status": "operator_final_update",
        "confidence": "high", "source_grade": "primary",
        "source_url": "https://example.test", "experiment_use_v40": "1",
        "emergency_override": "0", "attack_recovery_confounded": "0",
        "technical_outage_confounded": "0", "weather_confounded": "0",
    })
    row.update(overrides)
    return row


def test_v4_positive_does_not_require_known_queue_count():
    got = transform(pd.DataFrame([_row(queue_count="")])).iloc[0]
    assert got.schedule_positive == 1
    assert got.analysis_eligible == 1
    assert got.geo_scope_precision == "L2_operator_admin1_proxy"


def test_v4_invalid_interval_is_preserved_but_not_eligible():
    got = transform(pd.DataFrame([_row(planned_end_utc="")])).iloc[0]
    assert got.interval_valid == 0
    assert got.analysis_eligible == 0
    assert got.publication_eligible == 0
