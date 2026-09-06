import pandas as pd

from uresil.config import load_config
from uresil.exp_b_event_study import (continuous_state_sensitivity_association,
                                      frozen_state_sensitivity_validation)
from uresil.event_design import primary_estimand
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


def test_frozen_sensitivity_validation_compares_high_and_low_within_state():
    cfg = load_config(run_id="sensitivity_validation", mode="demo")
    event = cfg.load_event_registry().query("event_id == 'E2024_0826_ATTACK'").iloc[0]
    estimand = primary_estimand(event)
    anchor = estimand.anchor_utc
    rows = []
    for tier, sensitivity, reach in [("low", .1, .9), ("middle", .5, .7), ("high", .9, .5)]:
        for rel, stage, value in [(-8, "clean_baseline", .9), (0, "outcome", reach), (2, "outcome", reach)]:
            rows.append({"analysis_unit_id": f"u-{tier}", "target_admin1": "Odesa Oblast",
                         "sensitivity_stratum": tier, "method": "S_REACH", "slot": 1,
                         "sensitivity_value": sensitivity,
                         "is_clean_baseline": int(stage == "clean_baseline"), "stage": stage,
                         "normalized_reach": value, "rtt_median": 50.0,
                         "rel_bin": rel, "measure_time": anchor + pd.Timedelta(hours=rel)})
    got = frozen_state_sensitivity_validation(pd.DataFrame(rows), event, estimand, cfg)
    high = got[got.sensitivity_stratum.eq("high")].iloc[0]
    assert high.mean_reach_deficit > 0
    assert high.high_minus_low_mean_reach_deficit > 0
    association = continuous_state_sensitivity_association(pd.DataFrame(rows), event, estimand, cfg)
    reach = association[association.attack_outcome.eq("mean_reach_deficit")].iloc[0]
    assert reach.slope_per_unit_sensitivity > 0


def test_continuous_sensitivity_association_reports_t90_recovery_slope():
    cfg = load_config(run_id="recovery_validation", mode="demo")
    event = cfg.load_event_registry().query("event_id == 'E2024_0826_ATTACK'").iloc[0]
    estimand = primary_estimand(event); anchor = estimand.anchor_utc; rows = []
    paths = [("low", .1, [.9, .9, .9, .9]), ("middle", .5, [.4, .9, .9, .9]),
             ("high", .9, [.4, .4, .9, .9])]
    for tier, score, values in paths:
        rows.append({"analysis_unit_id": f"u-{tier}", "target_admin1": "Odesa Oblast", "method": "S_REACH",
                     "sensitivity_stratum": tier, "sensitivity_value": score, "slot": 1,
                     "is_clean_baseline": 1, "stage": "clean_baseline", "normalized_reach": .9,
                     "rtt_median": 50., "rel_bin": -8, "measure_time": anchor - pd.Timedelta(hours=8)})
        for j, value in enumerate(values):
            rows.append({"analysis_unit_id": f"u-{tier}", "target_admin1": "Odesa Oblast", "method": "S_REACH",
                         "sensitivity_stratum": tier, "sensitivity_value": score, "slot": 1,
                         "is_clean_baseline": 0, "stage": "outcome", "normalized_reach": value,
                         "rtt_median": 50., "rel_bin": 2*j, "measure_time": anchor + pd.Timedelta(hours=2*j)})
    got = continuous_state_sensitivity_association(pd.DataFrame(rows), event, estimand, cfg)
    recovery = got[got.attack_outcome.eq("t90_h")].iloc[0]
    assert recovery.slope_per_unit_sensitivity > 0
    assert recovery.n_recovery_censored == 0
