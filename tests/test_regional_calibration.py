import pandas as pd
from types import SimpleNamespace

from uresil.exp_h_regional_calibration import _regional_gate
from uresil.regional_calibration import (build_regional_event_registry,
                                         build_v3_regional_event_registry,
                                         build_v4_regional_event_registry,
                                         membership_stability,
                                         select_repeated_sensitive)


def test_queue_specific_update_is_not_promoted_to_region_binary_truth():
    d = pd.DataFrame([{"date": "2024-08-20", "oblast": "Volyn Oblast",
                       "operator": "DSO", "queue": "3", "status": "cancelled",
                       "coverage": "full_oblast", "start_utc": "2024-08-20T14:00Z",
                       "end_utc": "2024-08-20T15:00Z"}])
    got = build_regional_event_registry(d)
    assert got.iloc[0].regional_state == "queue_specific_cancelled"
    assert got.iloc[0].region_binary_usable == 0
    assert got.iloc[0].ip_level_power_truth == 0


def test_repeated_selector_rejects_one_event_winner():
    d = pd.DataFrame([
        {"target_admin1": "A", "dst_ip": "x", "event_id": "e1", "in_B1": 1, "S": .8, "S_lo": .7},
        {"target_admin1": "A", "dst_ip": "x", "event_id": "e2", "in_B1": 1, "S": 0, "S_lo": -.1},
        {"target_admin1": "A", "dst_ip": "x", "event_id": "e3", "in_B1": 1, "S": 0, "S_lo": -.1},
        {"target_admin1": "A", "dst_ip": "y", "event_id": "e1", "in_B1": 1, "S": .3, "S_lo": .1},
        {"target_admin1": "A", "dst_ip": "y", "event_id": "e2", "in_B1": 1, "S": .2, "S_lo": .1},
        {"target_admin1": "A", "dst_ip": "y", "event_id": "e3", "in_B1": 1, "S": .1, "S_lo": -.1},
    ])
    got = select_repeated_sensitive(d, min_events=3, min_positive_fraction=2/3).set_index("dst_ip")
    assert not got.loc["x", "in_B2_region"]
    assert got.loc["y", "in_B2_region"]
    stability = membership_stability(d)
    assert len(stability) == 3


def test_v3_regional_registry_excludes_national_and_expands_explicit_admin1():
    d = pd.DataFrame([
        {"record_id": "n", "event_date": "2024-07-01", "admin1": "ALL",
         "scope_type_norm": "national", "record_role": "planned_or_final_dispatch",
         "analysis_eligible": 1, "schedule_positive": True,
         "start_utc": "2024-07-01T10:00Z", "end_utc": "2024-07-01T12:00Z"},
        {"record_id": "o", "event_date": "2024-07-01", "admin1": "Sumy Oblast",
         "affected_admin1": "Sumy Oblast", "scope_type_norm": "oblast",
         "record_role": "planned_or_final_dispatch", "analysis_eligible": 1,
         "schedule_positive": True, "queue_count": 2,
         "start_utc": "2024-07-01T10:00Z", "end_utc": "2024-07-01T12:00Z"},
    ])
    got = build_v3_regional_event_registry(d, {"Sumy Oblast", "Kyiv City"})
    assert got.target_admin1.tolist() == ["Sumy Oblast"]
    assert got.iloc[0].regional_state == "published_queue_schedule"
    assert got.iloc[0].estimated_exposed_fraction == 2 / 6


def test_v4_registry_uses_actual_time_and_groups_dates_into_independent_episodes():
    rows = []
    for date, start, actual in (
        ("2024-06-01", "2024-06-01T10:00Z", ""),
        ("2024-06-03", "2024-06-03T10:00Z", "2024-06-03T10:30Z"),
        ("2024-06-08", "2024-06-08T10:00Z", ""),
    ):
        rows.append({
            "record_id": date, "event_date": date, "admin1": "Odesa Oblast",
            "affected_admin1": "Odesa Oblast", "operator": "DTEK Odesa Grids",
            "scope_type_norm": "operator_service_area", "analysis_eligible": 1,
            "publication_eligible": 1, "confound_free": 1, "schedule_positive": True,
            "start_utc": start, "end_utc": start.replace("10:00", "12:00"),
            "actual_start_utc": actual,
            "actual_end_utc": actual.replace("10:30", "11:30") if actual else "",
            "restriction_type": "hourly_schedule", "status_norm": "confirmed",
            "source_grade": "primary", "source_url": "https://example.test",
        })
    rows.append({
        "record_id": "national", "event_date": "2024-06-01", "admin1": "ALL",
        "affected_admin1": "ALL", "operator": "Ukrenergo", "scope_type_norm": "national",
        "analysis_eligible": 1, "publication_eligible": 1, "confound_free": 1,
        "schedule_positive": True, "start_utc": "2024-06-01T10:00Z",
        "end_utc": "2024-06-01T12:00Z", "restriction_type": "hourly_schedule",
    })
    got = build_v4_regional_event_registry(pd.DataFrame(rows), {"Odesa Oblast"})
    assert len(got) == 3
    assert got.episode_id.nunique() == 2
    actual = got[got.date.eq("2024-06-03")].iloc[0]
    assert actual.label_uses_actual_time == 1
    assert actual.start_utc == pd.Timestamp("2024-06-03T10:30Z")


def test_repeated_selector_keeps_power_operator_strata_separate():
    d = pd.DataFrame([
        {"target_admin1": "A", "exposure_unit_id": operator, "dst_ip": "x",
         "event_id": f"{operator}-{event}", "in_B1": 1, "S": score, "S_lo": score - .05}
        for operator, values in (("A|DSO1", (.2, .2, .2)), ("A|DSO2", (-.1, -.1, -.1)))
        for event, score in enumerate(values)
    ])
    got = select_repeated_sensitive(d, min_events=3).set_index("exposure_unit_id")
    assert bool(got.loc["A|DSO1", "in_B2_region"])
    assert not bool(got.loc["A|DSO2", "in_B2_region"])


def test_regional_gate_treats_empty_loo_as_non_estimable_not_exception():
    cfg = SimpleNamespace(
        regional_calibration={
            "transition_buffer_minutes": 30,
            "min_holdout_events_for_estimability": 3,
            "min_regions_for_success": 2,
            "min_regional_b2_ip": 200,
            "min_positive_event_fraction": 2 / 3,
        },
        runtime={"random_seed": 7, "n_bootstrap": 10},
    )
    got = _regional_gate(pd.DataFrame(), pd.DataFrame(), cfg)
    assert got["regional_calibration_success"] == 0
    assert got["holdout_episode_n"] == 0
    assert got["min_region_n"] == 2
