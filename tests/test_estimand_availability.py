from types import SimpleNamespace

import pandas as pd

from uresil.audit import estimand_availability


class DummyConfig:
    matching = {"min_matched_pairs": 2}

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path

    def load_event_registry(self):
        return pd.DataFrame([{
            "event_id": "E", "analysis_role": "attack_regional", "event_family": "attack",
            "scope_type": "regional", "attack_start_utc": "2024-11-27 17:30:00+00:00",
            "outage_start_utc": "2024-11-28 04:00:00+00:00",
            "network_anomaly_start_utc": "2024-11-28 05:00:00+00:00",
            "primary_anchor_utc": "2024-11-28 04:00:00+00:00", "anchor_lower_utc": "",
            "power_affected_admin1": "Lviv Oblast|Rivne Oblast",
            "network_observed_admin1": "Kherson Oblast|Mykolaiv Oblast",
            "analysis_treated_admin1": "Lviv Oblast|Rivne Oblast",
        }])

    def out_dir(self, key):
        assert key == "results_tables"
        return self.tmp_path


def test_estimand_availability_keeps_power_and_network_scopes_separate(tmp_path):
    rows = []
    for asn in (1, 2):
        for region in ("Lviv Oblast", "Rivne Oblast", "Kherson Oblast", "Mykolaiv Oblast", "Odesa Oblast"):
            rows.append({"national_eligible": 1, "regional_eligible": 1,
                         "target_asn": asn, "target_admin1": region,
                         "analysis_unit_id": f"{asn}|{region}", "prefix24": f"10.{asn}.{len(rows)}.0/24"})
    ipu = pd.DataFrame(rows)
    available = pd.DataFrame([{"event_id": "E", "data_available": 1}])
    out = estimand_availability(DummyConfig(tmp_path), ipu, available)
    assert set(out["estimand_id"]) == {"confirmatory_power", "attack_onset", "network_replication"}
    scopes = out.set_index("estimand_id")["treated_admin1"].to_dict()
    assert scopes["confirmatory_power"] == "Lviv Oblast|Rivne Oblast"
    assert scopes["network_replication"] == "Kherson Oblast|Mykolaiv Oblast"
    assert out["estimand_data_available"].eq(1).all()
