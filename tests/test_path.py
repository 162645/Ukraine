from uresil.config import load_config
from uresil.exp_e_path import extract_edges,build_reserved_nets

def test_gap_breaks_direct_edge():
    cfg=load_config(run_id='t',mode='demo');nets=build_reserved_nets(cfg)
    mp={'1.1.1.1':{'asn':1,'country':'Germany','admin1':'Hesse'},
        '8.8.8.8':{'asn':2,'country':'Ukraine','admin1':'Kyiv City'}}
    x=extract_edges([('1.1.1.1',1,1),('*',None,2),('8.8.8.8',2,3)],mp,nets)
    assert x['direct_as']==[] and x['ingress'] is None
    y=extract_edges([('1.1.1.1',1,1),('8.8.8.8',2,2)],mp,nets)
    assert len(y['direct_as'])==1 and y['ingress'] is not None
