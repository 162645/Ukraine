import pandas as pd
from uresil.exp_c_fingerprint import prepare_features

def test_history_features_are_strictly_lagged():
    d=pd.DataFrame({
      'group':['1|Ukraine|A']*3,'target_asn':[1]*3,'target_country':['Ukraine']*3,'target_admin1':['A']*3,
      'event_id':['e1','e2','e3'],'event_anchor_utc':pd.to_datetime(['2024-01-01','2024-02-01','2024-03-01'],utc=True),
      'analysis_role':['attack_regional']*3,'deficit_auc_full':[1.,2.,100.],
      'max_deficit':[.1,.2,.9],'t90_h':[2,4,100],'immediate_drop':[.1,.2,.9],
      'deficit_auc_24h':[1,2,3],'onset_delay_h':[0,2,4],'t50_h':[1,2,3],
      'baseline_level':[1]*3,'eligible_prefix_n':[50]*3,'pretrend_slope':[0]*3})
    z=prepare_features(d)
    assert pd.isna(z.loc[0,'hist_deficit_auc_full_mean'])
    assert z.loc[1,'hist_deficit_auc_full_mean']==1
    assert z.loc[2,'hist_deficit_auc_full_mean']==1.5
    assert z.loc[2,'last_feature_event_utc']<z.loc[2,'event_anchor_utc']

from uresil.config import load_config
import uresil.exp_c_fingerprint as expc


def test_failed_ml_fit_is_marked_not_credited(monkeypatch):
    cfg = load_config(run_id='pred_fit_test', mode='demo')
    cfg.raw['prediction']['min_train_events'] = 1
    rows = []
    for ei, date in enumerate(['2024-01-01', '2024-02-01', '2024-03-01']):
        for gi in range(4):
            rows.append({
                'target_asn': gi + 1, 'target_country': 'Ukraine',
                'target_admin1': f'A{gi}', 'event_id': f'e{ei}',
                'event_anchor_utc': pd.Timestamp(date, tz='UTC'),
                'analysis_role': 'attack_regional', 'is_treated': 1,
                'deficit_auc_full': float(ei + gi), 'max_deficit': .1 * (ei + 1),
                't90_h': float(2 + ei), 'immediate_drop': .05,
                'deficit_auc_24h': 1., 'onset_delay_h': 0., 't50_h': 1.,
                'baseline_level': 1., 'eligible_prefix_n': 50., 'pretrend_slope': 0.,
            })
    d = expc.prepare_features(pd.DataFrame(rows))
    monkeypatch.setattr(expc, '_fit_ml', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    pred, perf, audit = expc.rolling_origin_predict(d, 'deficit_auc_full', cfg)
    assert not pred.empty and not perf.empty and not audit.empty
    assert (pred.loc[pred.model.eq('M4_ridge_history'), 'fit_status'] == 'fallback_failed').all()
    q = perf[(perf.model.eq('M4_ridge_history')) & (perf.event_id.eq('EVENT_EQUAL'))]
    assert int(q.iloc[0].fit_failure_n) > 0
