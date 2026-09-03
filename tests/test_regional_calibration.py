import pandas as pd

from uresil.regional_calibration import (build_regional_event_registry,
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
