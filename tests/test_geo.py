from uresil.config import load_config
from uresil.geo import Admin1Canonicalizer

def test_target_admin1_is_strict_and_global():
    cfg=load_config(run_id='t',mode='demo')
    c=Admin1Canonicalizer(cfg.resource_path('admin1_aliases'),cfg.quality['unknown_labels'],cfg.quality['valid_country_aliases'])
    assert c.canonical_admin1('Ukraine','Одесская область')=='Odesa Oblast'
    assert c.canonical_admin1('Ukraine','DATAGROUP.UA')=='UNMAPPED_UA_ADMIN1'
    assert c.canonical_admin1('Germany','Hesse')=='Hesse'

def test_ukrainian_chinese_aliases_and_country_only_policy():
    cfg=load_config(run_id='t2',mode='demo')
    c=Admin1Canonicalizer(cfg.resource_path('admin1_aliases'),cfg.quality['unknown_labels'],
                          cfg.quality['valid_country_aliases'],cfg.quality['country_only_admin1_labels'])
    assert c.canonical_admin1('乌克兰','基辅')=='Kyiv City'
    assert c.canonical_admin1('乌克兰','基辅州')=='Kyiv Oblast'
    assert c.canonical_admin1('乌克兰','基洛沃格勒州')=='Kirovohrad Oblast'
    assert c.canonical_admin1('乌克兰','基洛夫格勒州')=='Kirovohrad Oblast'
    assert c.canonical_admin1('乌克兰','乌克兰')=='COUNTRY_ONLY_UA'
    assert not c.valid_target('乌克兰','COUNTRY_ONLY_UA')
