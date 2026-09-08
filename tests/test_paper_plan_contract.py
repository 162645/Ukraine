import pandas as pd

from uresil.canonical_signals import add_rolling_ratios
from uresil.paper_analysis import _h1_h2_h3_h4


def test_rolling_ratio_is_strictly_prior_and_uses_operational_thresholds():
    rows = [{"admin1": "A", "measure_time": t, "IPS": v, "FBS": v}
            for t, v in zip(pd.date_range("2024-01-01", periods=5, freq="2h", tz="UTC"), [100, 100, 100, 80, 100])]
    out = add_rolling_ratios(pd.DataFrame(rows), days=1)
    assert out.IPS_7d_mean.isna().all()  # fewer than seven days: no fabricated baseline
    assert not out.ips_outage.any()


def test_h_tables_are_explicitly_empty_without_frozen_features():
    out = _h1_h2_h3_h4(pd.DataFrame())
    assert set(out) == {"h1_ip_group_heterogeneity", "h2_sensitivity_generalization",
                        "h2_continuous_association", "h3_activity_x_sensitivity",
                        "h4_ips_loss_decomposition"}
    assert all(v.empty for v in out.values())


def test_h4_contribution_definition_sums_to_one_for_positive_loss():
    d = pd.DataFrame([
        {"event_id": "e", "target_admin1": "A", "sensor_method": "S_REACH", "sensitivity_stratum": "Q1", "sensor_n": 10, "expected_response_n": 10, "max_deficit": .2},
        {"event_id": "e", "target_admin1": "A", "sensor_method": "S_REACH", "sensitivity_stratum": "Q5", "sensor_n": 10, "expected_response_n": 10, "max_deficit": .6},
    ])
    h4 = _h1_h2_h3_h4(d)["h4_ips_loss_decomposition"]
    assert h4.loss_contribution.sum() == 1
