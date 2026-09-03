import pandas as pd
from uresil.config import load_config
from uresil.audit import event_availability


def test_event_availability_excludes_nominal_edges_but_keeps_supported_events(tmp_path):
    cfg=load_config(run_id='audit_support',mode='demo')
    times=pd.date_range('2024-06-22 08:00','2025-01-09 14:00',freq='2h',tz='UTC')
    cq=pd.DataFrame({
        'measure_time':times,
        'cycle_id':(times.astype('int64')//10**9//7200).astype('int64'),
        'is_complete':1,'in_observed_support':1,'is_analysis_cycle':1,
    })
    a=event_availability(cfg,cq)
    by=a.set_index('event_id')
    assert by.loc['E2024_0624_PLANNED','data_available']==1
    assert by.loc['E2024_0819_PLANNED','data_available']==1
    assert by.loc['E2024_1209_PLANNED','data_available']==1
    assert by.loc['E2025_0115_ATTACK','data_available']==0

from uresil.audit import run_cycle_audit


class _FakeAuditCH:
    def __init__(self, obs, imp):
        self.obs = obs
        self.imp = imp
        self.calls = 0

    def query_df(self, _query):
        self.calls += 1
        return self.obs.copy() if self.calls == 1 else self.imp.copy()


def test_import_complete_zero_response_cycle_is_retained(tmp_path, monkeypatch):
    """Ping row volume is an outcome; import metadata defines acquisition quality."""
    monkeypatch.setattr(pd.DataFrame, 'to_parquet', lambda self, *args, **kwargs: None)
    cfg = load_config(run_id='audit_zero_response', mode='demo')
    cfg.root = tmp_path
    cfg.raw['study']['start_utc'] = '2024-08-19 12:00:00'
    cfg.raw['study']['end_utc'] = '2024-08-19 18:00:00'
    times = pd.date_range('2024-08-19 12:00', '2024-08-19 18:00', freq='2h', tz='UTC')
    cids = (times.astype('int64') // 10**9 // 7200).astype('int64')
    # The 16:00 cycle has no returned Ping rows, but import_files confirms that
    # the full-scan Ping artifact exists and was imported successfully.
    obs = pd.DataFrame({
        'cycle_id': cids,
        'measure_time': times,
        'ping_rows': [100, 90, 0, 95],
        'ping_prefixes': [10, 9, 0, 10],
        'ping_unique_ips': [100, 90, 0, 95],
        'trace_rows': [5, 5, 5, 5],
        'trace_prefixes': [5, 5, 5, 5],
        'trace_reached_rate': [1.0, 1.0, 1.0, 1.0],
        'trace_star_rate': [0.1, 0.1, 0.1, 0.1],
        'as0_path_share': [0.0, 0.0, 0.0, 0.0],
        'geo_unknown_path_share': [0.0, 0.0, 0.0, 0.0],
    })
    imp = pd.DataFrame({
        'cycle_id': cids,
        'measure_time': times,
        'import_status': ['done'] * 4,
        'error_message': [''] * 4,
        'has_ping': [1] * 4,
        'has_trace': [1] * 4,
        'imported_ping_rows': [100, 90, 0, 95],
        'imported_trace_rows': [5] * 4,
        'import_updated_at': times,
    })
    out = run_cycle_audit(cfg, _FakeAuditCH(obs, imp))
    zero = out.loc[out['measure_time'].eq(times[2])].iloc[0]
    assert zero['ping_rows'] == 0
    assert zero['ping_acquisition_complete'] == 1
    assert zero['is_complete'] == 1
    assert zero['is_analysis_cycle'] == 1
