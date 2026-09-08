import pandas as pd

from uresil.canonical_signals import (add_rolling_ratios, compute_canonical_fbs,
                                      compute_canonical_ips, eligible_blocks)


def test_canonical_ips_counts_distinct_responsive_ips_without_label_filter():
    d = pd.DataFrame({
        "measure_time": ["2024-01-01T00:00Z"] * 3,
        "dst_ip": ["1", "1", "2"],
        "admin1": ["A", "A", "A"],
    })
    got = compute_canonical_ips(d)
    assert got.IPS.tolist() == [2]


def test_fbs_uses_monthly_eligible_blocks_and_active_cycles():
    d = pd.DataFrame({
        "measure_time": ["2024-01-01T00:00Z", "2024-01-01T00:00Z",
                          "2024-01-01T02:00Z", "2024-01-01T02:00Z"],
        "prefix24": ["p", "p", "p", "q"],
        "dst_ip": ["1", "2", "1", "3"],
    })
    assert eligible_blocks(d, 3).query("prefix24 == 'p'").empty is False
    blocks = pd.DataFrame({"prefix24": ["p", "q"], "admin1": ["A", "A"]})
    got = compute_canonical_fbs(d, blocks, 2)
    assert got.FBS.tolist() == [1, 1]


def test_ratios_use_only_strictly_prior_cycles():
    times = pd.date_range("2024-01-01", periods=4, freq="2h", tz="UTC")
    d = pd.DataFrame({"measure_time": times, "admin1": "A", "IPS": [1, 2, 3, 4], "FBS": [1, 1, 1, 1]})
    got = add_rolling_ratios(d, days=1)
    assert got.IPS_7d_mean.isna().all()
