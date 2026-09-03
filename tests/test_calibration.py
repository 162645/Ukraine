import pandas as pd
from uresil.config import load_config
from uresil.exp_a_calibration import score_endpoints, _metrics

def test_power_sensitive_score_and_full_pr():
    cfg=load_config(run_id='t',mode='demo')
    raw=pd.DataFrame({'x_normal':[20,20,10],'n_normal':[24]*3,'x_planned':[2,18,9],'n_planned':[20]*3})
    d=score_endpoints(raw,cfg,stable_rate=.5)
    assert d.loc[0,'in_B2']
    obs=[]
    for m in ['B0','B1','B2']:
        for i in range(30): obs.append({'method':m,'label':int(i<10),'score':(30-i)/30+(0.05 if m=='B2' and i<10 else 0)})
    pr,au=_metrics(pd.DataFrame(obs))
    assert pr.groupby('method').size().min()>5
    assert len(au)==3

from uresil.events import Events, slot_of
from uresil.exp_a_calibration import matched_validation_cycles


def test_validation_controls_are_pre_event_slot_matched_and_never_recovery():
    cfg = load_config(run_id='cal_match_test', mode='demo')
    ev = Events(cfg)
    event = ev.planned_valid.query("event_id == 'E2024_1209_PLANNED'").iloc[0]
    times = pd.date_range('2024-06-22 08:00', '2024-12-10 12:00', freq='2h', tz='UTC')
    grid = pd.DataFrame({
        'cycle_id': range(len(times)), 'measure_time': times, 'is_complete': 1,
        'slot': slot_of(pd.Series(times), 2),
    })
    selected, audit = matched_validation_cycles(grid, event, ev, cfg)
    assert not selected.empty and not audit.empty
    cutoff = pd.to_datetime(event.outage_start_utc, utc=True)
    neg = selected[selected.label.eq(0)]
    pos = selected[selected.label.eq(1)]
    assert (neg.measure_time < cutoff).all()
    assert set(neg.slot).issubset(set(pos.slot))
    assert not ((neg.measure_time >= cutoff) &
                (neg.measure_time <= pd.to_datetime(event.outage_end_utc, utc=True))).any()
