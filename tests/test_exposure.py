import pandas as pd
from uresil.config import load_config
from uresil.exp_d_recovery_debt import overlap_hours, prepare_exposure_registry, exposure_for_group

def test_overlap_and_regional_scope():
    cfg=load_config(run_id='t',mode='demo')
    reg=prepare_exposure_registry(cfg)
    a=pd.Timestamp('2024-09-18 00:00',tz='UTC')
    assert exposure_for_group(a,'Sumy Oblast',reg,48)>0
    assert exposure_for_group(a,'Lviv Oblast',reg,48)==0
    assert overlap_hours(pd.Timestamp('2024-01-01',tz='UTC'),pd.Timestamp('2024-01-02',tz='UTC'),
                         pd.Timestamp('2024-01-01 12:00',tz='UTC'),pd.Timestamp('2024-01-03',tz='UTC'))==12
