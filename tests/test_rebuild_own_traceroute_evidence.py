from pathlib import Path
import importlib.util
import sys

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_own_traceroute_evidence.py"
SPEC = importlib.util.spec_from_file_location("rebuild_own_traceroute_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_public_ipv4_classifier_excludes_special_ranges():
    assert MODULE.classify_ipv4("8.8.8.8") == ("8.8.8.8", "public")
    assert MODULE.classify_ipv4("10.1.2.3")[1] == "private_10"
    assert MODULE.classify_ipv4("100.100.2.66")[1] == "shared_cgnat"
    assert MODULE.classify_ipv4("127.0.0.1")[1] == "loopback"
    assert MODULE.classify_ipv4("169.254.1.1")[1] == "link_local"
    assert MODULE.classify_ipv4("172.16.0.1")[1] == "private_172"
    assert MODULE.classify_ipv4("192.168.0.1")[1] == "private_192"
    assert MODULE.classify_ipv4("198.51.100.1")[1] == "documentation_198"
    assert MODULE.classify_ipv4("224.0.0.1")[1] == "multicast"
    assert MODULE.classify_ipv4("240.0.88.15")[1] == "reserved"
    assert MODULE.classify_ipv4("*")[1] == "invalid_ipv4"


def test_query_enforces_preterminal_observed_non_target_hops():
    q = MODULE.extraction_query(
        pd.Timestamp("2024-06-01", tz="UTC"),
        pd.Timestamp("2024-07-01", tz="UTC"),
    )
    assert "hop_position < path_length" in q
    assert "hop.1 != dst_ip" in q
    assert "hop.1 != '*'" in q
    assert "IPv4StringToNumOrNull" in q
    assert "HAVING intermediate_observation_n > 0" in q


def test_frozen_descriptive_bins_keep_equal_values_together():
    master = pd.DataFrame({
        "ip": ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"],
        "power_availability": [0.0, 0.5, 0.5, 1.0],
        "label": [0, 1, 0, 1],
    })
    edges = np.array([0.0, 0.5, 1.0])
    result = MODULE.descriptive_bins(master, "label", "test", edges)
    assert result["ip_n"].sum() == 4
    assert result.loc[result["bin_index"].eq(2), "ip_n"].iloc[0] == 3


def test_difference_reason_identifies_terminal_only_legacy_positive():
    row = pd.Series({
        "ip": "8.8.8.8",
        "frozen_own_traceroute_intermediate": 1,
        "rebuilt_own_traceroute_intermediate": 0,
        "terminal_non_target_observation_n": 4,
        "intermediate_observation_n": 0,
    })
    assert MODULE.difference_reason(row, {"8.8.8.8"}) == "observed_only_as_terminal_endpoint_under_strict_rule"
