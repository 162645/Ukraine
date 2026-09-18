import numpy as np
import pandas as pd

from uresil import aug26_state_case_study as m


def synthetic_state():
    rows = []
    for state, sign in [("A", 1.0), ("B", -1.0)]:
        for d_i, d in enumerate(m.DECILES, 1):
            for q_i, q in enumerate(m.QUINTILES, 1):
                for k in range(2):
                    rows.append({
                        "dst_ip": f"{state}-{d_i}-{q_i}-{k}",
                        # Each /24 contains all quintiles, allowing a valid
                        # cluster resample for the synthetic check.
                        "prefix24": f"192.0.{d_i}.0",
                        "target_admin1": state,
                        "activity_decile": d,
                        "quintile": q,
                        "activity_score_smoothed": d_i / 10,
                        "sensitivity": q_i / 5,
                        "reach_drop": sign * (0.01 * d_i + 0.005 * q_i),
                        "pre_attack_reach": 0.8,
                        "attack_reach": 0.8 - sign * (0.01 * d_i + 0.005 * q_i),
                    })
    return pd.DataFrame(rows)


def test_only_frozen_event_is_allowed():
    assert m.EVENT == "E2024_0826_ATTACK"
    assert len(m.QUINTILES) == 5 and len(m.DECILES) == 10
    assert m._state_seed("Cherkasy Oblast") == m._state_seed("Cherkasy Oblast")


def test_activity_adjustment_is_equal_decile_weighted():
    x = synthetic_state().query("target_admin1 == 'A'")
    adjusted, detail = m._adjusted_table(x)
    # The synthetic effect is additive, so equal-decile averaging has a known
    # Q5-Q1 difference independent of the number of IPs per decile.
    assert np.isclose(adjusted.loc["Q5", "mean_reach_drop"] - adjusted.loc["Q1", "mean_reach_drop"], 0.02)
    assert detail.activity_decile.nunique() == 10


def test_prefix24_is_the_bootstrap_unit():
    x = synthetic_state().query("target_admin1 == 'A'")
    clusters, sums, counts = m._cluster_arrays(x, "quintile", m.QUINTILES)
    assert len(clusters) == x.prefix24.nunique()
    assert sums.shape == counts.shape == (len(clusters), 5)
    lo, hi, n = m._cluster_bootstrap(x, "quintile", m.QUINTILES, m._boot_raw, n_boot=100)
    assert n == len(clusters) and lo <= hi


def test_signed_negative_state_is_retained_not_filtered():
    x = synthetic_state()
    shock = pd.DataFrame({"target_admin1": ["A", "B"], "mean_reach_drop": [0.2, 0.2]})
    summary, _, _ = m.state_analysis(x, shock)
    assert set(summary.target_admin1) == {"A", "B"}
    assert summary.loc[summary.target_admin1 == "B", "adjusted_q5_q1"].iloc[0] < 0


def test_no_pooled_ip_main_result_and_population_labels_are_explicit():
    source = open(m.__file__, encoding="utf-8").read()
    assert "population_type" in source
    assert "SENSITIVITY_CASE_POPULATION" in source
    assert "FULL_ACTIVITY_CONTEXT" in source
    assert m.BOOTSTRAP_N >= 1000
