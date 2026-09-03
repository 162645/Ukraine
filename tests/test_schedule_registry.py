import pandas as pd

from uresil.config import load_config
from uresil.events import Events
from uresil.preflight import validate_schedule_registry


def test_frozen_schedule_registry_is_structurally_valid():
    cfg = load_config(run_id="schedule_valid", mode="demo")
    assert validate_schedule_registry(cfg) == []


def test_disjoint_schedule_uses_overlap_not_bounding_interval():
    cfg = load_config(run_id="schedule_overlap", mode="demo")
    ev = Events(cfg)
    row = ev.df[ev.df["event_id"].eq("E2024_0707_PLANNED")].iloc[0]
    times = pd.date_range("2024-07-07 02:00:00+00:00", periods=7, freq="2h")
    grid = pd.DataFrame({"cycle_id": range(len(times)), "measure_time": times,
                         "is_complete": 1})
    selected = set(ev.outage_cycles(grid, row))
    # 04:00-12:00 UTC is an explicitly registered zero-queue gap and must not
    # become treated merely because it lies inside the day's bounding interval.
    assert 1 not in selected
    assert 2 not in selected
    assert 3 not in selected
    assert 4 not in selected
    assert 0 in selected
    assert 5 in selected
