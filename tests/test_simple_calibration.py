from types import SimpleNamespace

import pandas as pd

from uresil.simple_calibration import (aggregate_sensors, build_calibration_events,
                                       score_event_rows)


def _cfg():
    return SimpleNamespace(simple_calibration={
        "min_normal_cycles": 4, "min_pre_cycles": 2,
        "min_outage_cycles": 1, "min_post_cycles": 2,
        "stable_reach_rate": 0.8, "min_drop": 0.5,
        "min_recovery": 0.5, "max_placebo_nonresponse": 0.2,
    })


def test_regional_schedule_builds_admin1_date_event_without_operator_membership():
    schedule = pd.DataFrame([{
        "analysis_eligible": 1, "publication_eligible": 1, "confound_free": 1,
        "schedule_positive": True, "scope_type_norm": "operator_service_area",
        "admin1": "A", "affected_admin1": "A", "operator": "PowerCo",
        "event_date": "2024-07-01", "start_utc": "2024-07-01T08:00:00Z",
        "end_utc": "2024-07-01T10:00:00Z", "record_id": "r1",
    }])
    events, segments = build_calibration_events(schedule, {"A"})
    assert len(events) == 1
    assert events.iloc[0].geo_name == "A"
    assert events.iloc[0].event_id == "CAL_A_20240701"
    assert segments.iloc[0].operator == "PowerCo"


def test_national_schedule_is_not_a_calibration_label():
    schedule = pd.DataFrame([{
        "analysis_eligible": 1, "publication_eligible": 1, "confound_free": 1,
        "schedule_positive": True, "scope_type_norm": "national",
        "admin1": "ALL", "affected_admin1": "A", "event_date": "2024-07-01",
        "start_utc": "2024-07-01T08:00:00Z", "end_utc": "2024-07-01T10:00:00Z",
    }])
    events, segments = build_calibration_events(schedule, {"A"})
    assert events.empty
    assert segments.empty


def test_single_event_stable_drop_recovery_selects_candidate():
    raw = pd.DataFrame([
        {"dst_ip": "good", "x_normal": 4, "x_pre": 2, "x_outage": 0, "x_post": 2},
        {"dst_ip": "no_recovery", "x_normal": 4, "x_pre": 2, "x_outage": 0, "x_post": 0},
        {"dst_ip": "unstable", "x_normal": 1, "x_pre": 2, "x_outage": 0, "x_post": 2},
    ])
    cycles = {"normal": [1, 2, 3, 4], "pre": [5, 6], "outage": [7], "post": [8, 9]}
    got = score_event_rows(raw, cycles, _cfg()).set_index("dst_ip")
    assert bool(got.loc["good", "is_event_candidate"])
    assert not bool(got.loc["no_recovery", "is_event_candidate"])
    assert not bool(got.loc["unstable", "is_event_candidate"])


def test_aggregate_uses_one_good_event_and_counts_repeated_support():
    candidates = pd.DataFrame([
        {"dst_ip": "x", "event_id": "e1", "signature": .6, "drop": .7,
         "recovery": .6, "is_event_candidate": True},
        {"dst_ip": "x", "event_id": "e2", "signature": .5, "drop": .5,
         "recovery": .8, "is_event_candidate": True},
        {"dst_ip": "y", "event_id": "e1", "signature": .7, "drop": .7,
         "recovery": .7, "is_event_candidate": True},
    ])
    got = aggregate_sensors(candidates).set_index("dst_ip")
    assert bool(got.loc["x", "is_power_sensitive"])
    assert got.loc["x", "support_event_n"] == 2
    assert got.loc["x", "calibration_event_id"] == "e1"
    assert got.loc["y", "support_event_n"] == 1
