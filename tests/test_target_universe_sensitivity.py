import pandas as pd

from uresil.exp_b_event_study import target_universe_panels


def test_national_target_universe_keeps_country_only_only_in_u2():
    d = pd.DataFrame({
        "target_admin1": ["Kyiv City", "COUNTRY_ONLY_UA", "UNMAPPED_UA_ADMIN1"],
        "analysis_unit_id": ["a", "b", "c"],
    })
    universes = target_universe_panels(d, national=True)
    assert len(universes["U2_ukraine_valid_asn"]) == 3
    assert universes["U3_ukraine_valid_admin1_asn"]["analysis_unit_id"].tolist() == ["a"]


def test_regional_target_universe_is_strict_admin1_only():
    d = pd.DataFrame({
        "target_admin1": ["Sumy Oblast", "COUNTRY_ONLY_UA"],
        "analysis_unit_id": ["a", "b"],
    })
    universes = target_universe_panels(d, national=False)
    assert list(universes) == ["U3_ukraine_valid_admin1_asn"]
    assert universes["U3_ukraine_valid_admin1_asn"]["analysis_unit_id"].tolist() == ["a"]
