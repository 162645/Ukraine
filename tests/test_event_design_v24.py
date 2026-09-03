import pandas as pd

from uresil.config import load_config
from uresil.event_design import build_estimands, clean_baseline_interval, earliest_treatment_start
from uresil.exp_b_event_study import paired_dynamic, pretrend_diagnostic


def test_1128_power_and_network_estimands_are_not_collapsed():
    cfg = load_config(run_id="design_1128", mode="demo")
    e = cfg.load_event_registry().query("event_id == 'E2024_1128_ATTACK'").iloc[0]
    est = {x.estimand_id: x for x in build_estimands(e)}
    assert set(est) >= {"confirmatory_power", "attack_onset", "network_replication"}
    assert "Khmelnytskyi Oblast" in est["confirmatory_power"].treated_admin1
    assert "Kherson Oblast" in est["network_replication"].treated_admin1
    assert est["confirmatory_power"].treated_admin1 != est["network_replication"].treated_admin1
    assert earliest_treatment_start(e) < est["confirmatory_power"].anchor_utc
    b0, b1 = clean_baseline_interval(e, cfg)
    assert b1 < earliest_treatment_start(e)
    assert (b1 - b0).total_seconds() == 168 * 3600


def test_pair_centering_removes_clean_baseline_difference():
    cfg = load_config(run_id="pair_center", mode="demo")
    cfg.raw["runtime"]["n_bootstrap"] = 20
    rows=[]
    for unit, treated, base in [("t", True, .9), ("c", False, .8)]:
        for rel in [-48,-24,-6,0,2]:
            value=base if rel<0 else base-(.1 if treated else .02)
            rows.append({"analysis_unit_id":unit,"prefix24":unit,"rel_bin":rel,
                         "measure_time":pd.Timestamp("2024-01-10",tz="UTC")+pd.Timedelta(hours=rel),
                         "normalized_reach":value,"is_clean_baseline":int(rel<=-24)})
    panel=pd.DataFrame(rows)
    matches=pd.DataFrame([{"pair_id":"t::c","treated_unit":"t","control_unit":"c"}])
    curve=paired_dynamic(panel,matches,cfg,"e",1)
    assert abs(curve.loc[curve.rel_h.eq(-48),"effect"].iloc[0]) < 1e-12
    assert abs(curve.loc[curve.rel_h.eq(0),"effect"].iloc[0] + .08) < 1e-12


def test_pretrend_gate_uses_equivalence_intervals_not_nonsignificant_p():
    cfg=load_config(run_id="pretrend_equiv",mode="demo")
    x=pd.Series([-24,-20,-16,-12,-8,-4],dtype=float)
    # Tiny but precisely estimated slope can have a small classical p-value;
    # it should pass when both level and slope CIs lie inside practical margins.
    y=0.0004*x
    curve=pd.DataFrame({"rel_h":x,"effect":y,"ci_lo":y-.001,"ci_hi":y+.001})
    d=pretrend_diagnostic(curve,cfg,pre_end_rel_h=0)
    assert d["pretrend_equivalent"]
