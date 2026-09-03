import pandas as pd

from uresil.config import load_config
from uresil.sensor_panels import build_event_panel, choose_primary_method


def test_sensor_panel_materialises_zero_response_and_primary_gate(tmp_path):
    cfg = load_config(run_id="sensor_test", mode="demo")
    event = cfg.load_event_registry().query("event_id == 'E2024_0610_PLANNED'").iloc[0]
    times = pd.date_range("2024-06-09 13:00", "2024-06-11 13:00", freq="2h", tz="UTC")
    cq = pd.DataFrame({
        "cycle_id": (times.astype("int64") // 10**9 // 7200).astype("int64"),
        "measure_time": times,
        "is_complete": 1,
    })
    denom = pd.DataFrame([
        {"prefix24": "1.2.3.0/24", "target_asn": 1, "target_country": "Ukraine",
         "target_admin1": "Odesa Oblast", "method": "B1", "sensor_n": 10,
         "expected_response_n": 8.0, "group": "1|Ukraine|Odesa Oblast"},
        {"prefix24": "1.2.3.0/24", "target_asn": 1, "target_country": "Ukraine",
         "target_admin1": "Odesa Oblast", "method": "B2", "sensor_n": 4,
         "expected_response_n": 3.5, "group": "1|Ukraine|Odesa Oblast"},
    ])
    # Only one cycle has a response; all other complete cells must remain explicit zeros.
    cid = int(cq.iloc[10].cycle_id)
    numer = pd.DataFrame([
        {"cycle_id": cid, "prefix24": "1.2.3.0/24", "method": "B1",
         "responders": 4, "rtt_median": 30.0},
    ])
    panel = build_event_panel(cfg, event, denom, numer, cq)
    assert len(panel) > 2
    b1 = panel[panel.method.eq("B1")]
    assert (b1.responders == 0).any()
    assert b1.loc[b1.cycle_id.eq(cid), "normalized_reach"].iloc[0] == 0.5

    # No Experiment-A file means the conservative primary method is B1.
    assert choose_primary_method(cfg) == "B1"

def test_split_prefix_groups_do_not_share_response_numerator():
    cfg = load_config(run_id="sensor_split", mode="demo")
    event = cfg.load_event_registry().query("event_id == 'E2024_0624_PLANNED'").iloc[0]
    times = pd.date_range("2024-06-23 00:00", "2024-06-25 00:00", freq="2h", tz="UTC")
    cq = pd.DataFrame({
        "cycle_id": (times.astype("int64") // 10**9 // 7200).astype("int64"),
        "measure_time": times, "is_complete": 1,
    })
    denom = pd.DataFrame([
        {"prefix24":"1.2.3.0","target_asn":1,"target_country":"Ukraine","target_admin1":"Kyiv City",
         "method":"B1","sensor_n":5,"expected_response_n":5.0,"group":"1|Ukraine|Kyiv City",
         "analysis_unit_id":"1.2.3.0|1|Ukraine|Kyiv City"},
        {"prefix24":"1.2.3.0","target_asn":2,"target_country":"Ukraine","target_admin1":"Kyiv Oblast",
         "method":"B1","sensor_n":7,"expected_response_n":7.0,"group":"2|Ukraine|Kyiv Oblast",
         "analysis_unit_id":"1.2.3.0|2|Ukraine|Kyiv Oblast"},
    ])
    cid=int(cq.iloc[12].cycle_id)
    numer=pd.DataFrame([{"cycle_id":cid,"analysis_unit_id":"1.2.3.0|1|Ukraine|Kyiv City",
                         "method":"B1","responders":3,"rtt_median":20.0}])
    panel=build_event_panel(cfg,event,denom,numer,cq)
    at=panel[(panel.cycle_id.eq(cid))&panel.method.eq('B1')]
    assert at.loc[at.target_admin1.eq('Kyiv City'),'responders'].iloc[0]==3
    assert at.loc[at.target_admin1.eq('Kyiv Oblast'),'responders'].iloc[0]==0
