import types

import numpy as np
import pandas as pd

from uresil import simple_calibration as sc


def _cfg():
    return types.SimpleNamespace(
        study={"expected_cycle_interval_hours": 2},
        simple_calibration={
            "min_cycle_overlap_fraction": 0.75,
            "transition_buffer_minutes": 0,
            "pre_window_h": 24,
            "post_window_h": 48,
            "normal_cycles_per_outage_cycle": 1,
        },
    )


def _grid(n=10):
    return pd.DataFrame({
        "cycle_id": np.arange(n, dtype="int64"),
        "measure_time": pd.date_range("2024-06-01", periods=n, freq="2h", tz="UTC"),
        "is_complete": True,
    })


def test_episode_outage_cycles_are_exact_union(monkeypatch):
    monkeypatch.setattr(sc, "Events", lambda cfg: types.SimpleNamespace(clean_baseline_mask=lambda grid: pd.Series(True, index=grid.index)))
    events = pd.DataFrame([
        {"start_utc": "2024-06-01T00:00:00Z", "end_utc": "2024-06-01T02:00:00Z"},
        {"start_utc": "2024-06-01T08:00:00Z", "end_utc": "2024-06-01T18:00:00Z"},
    ])
    segments = pd.DataFrame([
        {"event_id": "w1", "start_utc": "2024-06-01T00:00:00Z", "end_utc": "2024-06-01T02:00:00Z", "schedule_positive": 1},
        {"event_id": "w2", "start_utc": "2024-06-01T08:00:00Z", "end_utc": "2024-06-01T18:00:00Z", "schedule_positive": 1},
    ])
    events.index = [0, 1]
    # The frozen group must carry the event IDs used by its segments.
    events["event_id"] = ["w1", "w2"]
    got = sc.episode_cycle_sets(events, segments, _grid(), _cfg(), set())
    assert got["outage"] == [0, 4, 5, 6, 7, 8]


def test_episode_gap_not_filled(monkeypatch):
    monkeypatch.setattr(sc, "Events", lambda cfg: types.SimpleNamespace(clean_baseline_mask=lambda grid: pd.Series(True, index=grid.index)))
    events = pd.DataFrame([
        {"event_id": "w1", "start_utc": "2024-06-01T00:00:00Z", "end_utc": "2024-06-01T02:00:00Z"},
        {"event_id": "w2", "start_utc": "2024-06-01T08:00:00Z", "end_utc": "2024-06-01T10:00:00Z"},
    ])
    segments = pd.DataFrame([
        {"event_id": "w1", "start_utc": "2024-06-01T00:00:00Z", "end_utc": "2024-06-01T02:00:00Z", "schedule_positive": 1},
        {"event_id": "w2", "start_utc": "2024-06-01T08:00:00Z", "end_utc": "2024-06-01T10:00:00Z", "schedule_positive": 1},
    ])
    got = sc.episode_cycle_sets(events, segments, _grid(), _cfg(), set())
    assert got["outage"] == [0, 4]
    assert 1 not in got["outage"] and 2 not in got["outage"] and 3 not in got["outage"]


def test_episode_controls_not_double_counted(monkeypatch):
    monkeypatch.setattr(sc, "Events", lambda cfg: types.SimpleNamespace(clean_baseline_mask=lambda grid: pd.Series(True, index=grid.index)))
    events = pd.DataFrame([
        {"event_id": "w1", "start_utc": "2024-06-01T00:00:00Z", "end_utc": "2024-06-01T02:00:00Z"},
        {"event_id": "w2", "start_utc": "2024-06-01T08:00:00Z", "end_utc": "2024-06-01T10:00:00Z"},
    ])
    segments = pd.DataFrame([
        {"event_id": "w1", "start_utc": "2024-06-01T00:00:00Z", "end_utc": "2024-06-01T02:00:00Z", "schedule_positive": 1},
        {"event_id": "w2", "start_utc": "2024-06-01T08:00:00Z", "end_utc": "2024-06-01T10:00:00Z", "schedule_positive": 1},
    ])
    got = sc.episode_cycle_sets(events, segments, _grid(), _cfg(), set())
    assert len(got["normal"]) == len(set(got["normal"]))


def _candidate(event, episode, xn, nn, xo, no):
    return {"dst_ip": "192.0.2.1", "prefix24": "192.0.2.0/24", "target_admin1": "A",
            "event_id": event, "episode_id_main": episode, "episode_id_augmented": episode,
            "use_main": 1, "use_augmented": 1, "is_event_candidate": True,
            "x_normal": xn, "n_normal": nn, "x_outage": xo, "n_outage": no,
            "x_clear": 0, "n_clear": 0, "x_pre": xn, "n_pre": nn, "x_post": xn, "n_post": nn,
            "p_normal": xn / nn, "p_outage": xo / no, "p_clear": np.nan,
            "p_pre": xn / nn, "p_post": xn / nn, "s_reach_event": xn / nn - xo / no,
            "s_rtt_event": np.nan, "s_reach_explicit_clear": np.nan,
            "s_rtt_explicit_clear": np.nan, "rtt_estimable": 0}


def test_multiwindow_episode_is_scored_once():
    # Episode A has 1 + 5 outage cycles; Episode B has 1.  Pooling gives
    # A=(6/6 - 5/6), then A and B receive equal episode weight.
    candidates = pd.DataFrame([
        _candidate("A_w1", "A", 1, 1, 0, 1),
        _candidate("A_w2", "A", 5, 5, 5, 5),
        _candidate("B_w1", "B", 1, 1, 1, 1),
    ])
    got = sc.aggregate_sensors(candidates)
    assert int(got.loc[0, "support_episode_n_primary"]) == 2
    assert np.isclose(float(got.loc[0, "s_reach_primary"]), 1 / 12)


def test_episode_equal_final_average():
    candidates = pd.DataFrame([
        _candidate("A_w1", "A", 1, 1, 0, 1), _candidate("A_w2", "A", 5, 5, 5, 5),
        _candidate("B_w1", "B", 1, 1, 0, 1),
    ])
    got = sc.aggregate_sensors(candidates)
    # A=1/6, B=1, so the two independent episodes contribute 50/50.
    assert np.isclose(float(got.loc[0, "s_reach_primary"]), (1 / 6 + 1) / 2)
