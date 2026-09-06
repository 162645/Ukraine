from types import SimpleNamespace

import pandas as pd
import pytest

from uresil.events import slot_of
from uresil.simple_calibration import (_overlap_cycle_ids, aggregate_sensors, b1_score_parts,
                                       build_calibration_events, build_final_calibration_events, score_event_rows)
from uresil.config import load_config


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


def test_formal_registry_is_a_whitelist_and_preserves_evidence_tier():
    schedule = pd.DataFrame([
        {"analysis_eligible": 1, "publication_eligible": 1, "confound_free": 1,
         "schedule_positive": 1, "scope_type_norm": "oblast", "affected_admin1": "A",
         "event_date": "2024-07-01", "start_utc": "2024-07-01T08:00:00Z", "end_utc": "2024-07-01T10:00:00Z"},
        {"analysis_eligible": 1, "publication_eligible": 1, "confound_free": 1,
         "schedule_positive": 1, "scope_type_norm": "oblast", "affected_admin1": "A",
         "event_date": "2024-07-02", "start_utc": "2024-07-02T08:00:00Z", "end_utc": "2024-07-02T10:00:00Z"},
    ])
    registry = pd.DataFrame([{"registry_id": "x", "geo_name": "A", "event_date": "2024-07-01",
                              "evidence_tier": "primary_Aplus", "scope_requirement": "oblast"}])
    events, _ = build_calibration_events(schedule, {"A"}, registry)
    assert events.event_id.tolist() == ["CAL_A_20240701"]
    assert events.evidence_tier.tolist() == ["primary_Aplus"]


def test_clear_windows_are_retained_and_consecutive_days_share_an_episode():
    schedule = pd.DataFrame([
        {"analysis_eligible": 1, "publication_eligible": 1, "confound_free": 1,
         "schedule_positive": 1, "scope_type_norm": "oblast", "affected_admin1": "A",
         "event_date": "2024-07-01", "start_utc": "2024-07-01T00:00:00Z", "end_utc": "2024-07-01T12:00:00Z"},
        {"analysis_eligible": 1, "publication_eligible": 1, "confound_free": 1,
         "schedule_positive": 0, "scope_type_norm": "oblast", "affected_admin1": "A",
         "event_date": "2024-07-01", "start_utc": "2024-07-01T12:00:00Z", "end_utc": "2024-07-01T15:00:00Z"},
        {"analysis_eligible": 1, "publication_eligible": 1, "confound_free": 1,
         "schedule_positive": 1, "scope_type_norm": "oblast", "affected_admin1": "A",
         "event_date": "2024-07-02", "start_utc": "2024-07-02T00:00:00Z", "end_utc": "2024-07-02T12:00:00Z"},
    ])
    events, segments = build_calibration_events(schedule, {"A"})
    assert len(events) == 2
    assert events.explicit_clear_segment_n.sum() == 1
    assert segments.schedule_positive.eq(0).any()
    assert events.episode_id.nunique() == 1


def test_slot_encodes_weekday_and_two_hour_time():
    times = pd.to_datetime(["2024-07-01T18:00:00Z", "2024-07-08T18:00:00Z", "2024-07-02T18:00:00Z"])
    slots = slot_of(pd.Series(times), 2)
    assert slots.iloc[0] == slots.iloc[1]
    assert slots.iloc[0] != slots.iloc[2]


def test_overlapping_queue_segments_use_a_true_time_union():
    grid = pd.DataFrame({"cycle_id": [1], "measure_time": pd.to_datetime(["2024-07-01T18:00:00Z"]),
                         "is_complete": [1]})
    duplicate = pd.DataFrame([{"start_utc": "2024-07-01T18:00:00Z", "end_utc": "2024-07-01T18:30:00Z",
                               "schedule_positive": 1} for _ in range(4)])
    # Four identical 30-minute queue records cover 30 minutes, not four hours.
    assert _overlap_cycle_ids(grid, duplicate, cycle_h=2, min_overlap_fraction=.5, buffer_minutes=0) == []
    one_hour = duplicate.copy(); one_hour["end_utc"] = "2024-07-01T19:00:00Z"
    assert _overlap_cycle_ids(grid, one_hour, cycle_h=2, min_overlap_fraction=.5, buffer_minutes=0) == [1]


def test_b1_score_part_discovery_uses_the_real_glob_entry_path(tmp_path):
    part_dir = tmp_path / "ip_sensor_scores_parts"; part_dir.mkdir()
    (part_dir / "part_00001.parquet").touch(); (part_dir / "other.parquet").touch()
    assert b1_score_parts(tmp_path) == [str(part_dir / "part_00001.parquet")]


def test_single_event_yields_continuous_reach_and_rtt_sensitivity_without_recovery_gate():
    raw = pd.DataFrame([
        {"dst_ip": "good", "x_normal": 4, "x_pre": 2, "x_outage": 0, "x_post": 2,
         "rtt_normal": 40.0, "rtt_outage": 52.0},
        {"dst_ip": "no_recovery", "x_normal": 4, "x_pre": 2, "x_outage": 0, "x_post": 0,
         "rtt_normal": 20.0, "rtt_outage": 20.0},
        {"dst_ip": "unstable", "x_normal": 1, "x_pre": 2, "x_outage": 0, "x_post": 2,
         "rtt_normal": 30.0, "rtt_outage": 45.0},
    ])
    cycles = {"normal": [1, 2, 3, 4], "pre": [5, 6], "outage": [7], "post": [8, 9]}
    got = score_event_rows(raw, cycles, _cfg()).set_index("dst_ip")
    assert bool(got.loc["good", "is_event_usable"])
    assert bool(got.loc["no_recovery", "is_event_usable"])
    assert not bool(got.loc["unstable", "is_event_usable"])
    assert got.loc["good", "s_reach_event"] == 1.0
    assert got.loc["good", "s_rtt_event"] == 0.3
    assert pd.isna(got.loc["good", "s_reach_explicit_clear"])
    assert pd.isna(got.loc["good", "s_rtt_explicit_clear"])


def test_aggregate_freezes_mean_sensitivity_and_within_state_tertiles():
    candidates = pd.DataFrame([
        {"dst_ip": "x", "target_admin1": "A", "event_id": "e1", "s_reach_event": .6, "s_rtt_event": .2,
         "p_normal": .9, "p_outage": .3, "drop": .7, "recovery": .6, "rtt_estimable": True, "is_event_usable": True},
        {"dst_ip": "x", "target_admin1": "A", "event_id": "e2", "s_reach_event": .4, "s_rtt_event": .4,
         "p_normal": .9, "p_outage": .5, "drop": .5, "recovery": .8, "rtt_estimable": True, "is_event_usable": True},
        {"dst_ip": "y", "target_admin1": "A", "event_id": "e1", "s_reach_event": .7, "s_rtt_event": .1,
         "p_normal": .9, "p_outage": .2, "drop": .7, "recovery": .7, "rtt_estimable": True, "is_event_usable": True},
        {"dst_ip": "z", "target_admin1": "A", "event_id": "e1", "s_reach_event": .1, "s_rtt_event": .8,
         "p_normal": .9, "p_outage": .8, "drop": .1, "recovery": .1, "rtt_estimable": True, "is_event_usable": True},
    ])
    got = aggregate_sensors(candidates).set_index("dst_ip")
    assert got.loc["x", "support_event_n"] == 2
    assert got.loc["x", "s_reach_primary"] == pytest.approx(.5)
    assert got.loc["x", "s_rtt_primary"] == pytest.approx(.3)
    assert got.loc["y", "s_reach_tier"] == "high"
    assert got.loc["z", "s_reach_tier"] == "low"


def test_final_workbook_is_the_direct_p1_p2_source_and_respects_measurement_start():
    cfg = load_config(run_id="excel-input", mode="demo")
    events, segments = build_final_calibration_events(cfg)
    assert not events.empty
    assert set(segments.segment_type).issubset({"outage", "explicit_clear"})
    assert (segments.start_utc >= pd.Timestamp("2024-06-22T08:00:00Z")).all()
    assert events.use_main.sum() == 56
    assert events.use_augmented.sum() == 123
