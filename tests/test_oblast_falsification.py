import pandas as pd

from uresil.config import load_config
from uresil.exp_g_oblast_falsification import _window_pair_effect


def test_operator_window_uses_overlap_and_pair_centering():
    cfg = load_config(run_id="oblast_unit", mode="demo")
    cfg.raw["runtime"]["n_bootstrap"] = 20
    rows = []
    for unit, admin, values in [
        ("t", "Zaporizhzhia Oblast", [1.0, 1.0, 0.6]),
        ("c", "Volyn Oblast", [1.0, 1.0, 1.0]),
    ]:
        for time, value, clean in zip(
            pd.to_datetime(["2024-07-24 05:00Z", "2024-07-24 07:00Z", "2024-07-24 12:30Z"]),
            values, [1, 1, 0]):
            rows.append({"analysis_unit_id": unit, "measure_time": time,
                         "normalized_reach": value, "is_clean_baseline": clean,
                         "target_admin1": admin})
    panel = pd.DataFrame(rows)
    matches = pd.DataFrame([{"pair_id": "t::c", "treated_unit": "t", "control_unit": "c"}])
    mean, lo, hi, pairs, cycles = _window_pair_effect(
        panel, matches, "2024-07-24 13:00Z", "2024-07-24 15:00Z", cfg)
    assert pairs == 1 and cycles == 1
    assert mean < 0 and lo <= mean <= hi
