#!/usr/bin/env python3
"""Audit whether final-closure external inputs are present and frozen."""
from __future__ import annotations
import argparse, json, importlib.util
from pathlib import Path
import pandas as pd

def present(p): return Path(p).exists() and Path(p).stat().st_size>0

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='.'); ap.add_argument('--strict',action='store_true'); a=ap.parse_args(); root=Path(a.root)
    checks=[]
    def ck(name,path,required=True):
        ok=present(root/path); checks.append({'check':name,'required':required,'ok':ok,'path':path}); return ok
    ck('weather_admin1_2h','data_derived/weather_admin1_2h.parquet',True)
    ck('adm1_geometry','data_external/geography/geoBoundaries-UKR-ADM1.geojson',True)
    ck('oblast_execution_registry','config/oblast_execution_registry_v1.csv',True)
    ck('weather_episode_registry','config/weather_episode_registry_v1.csv',True)
    # External platform data is useful but not mandatory for the core negative/positive closure.
    ck('ioda_fetch_log','data_external/ioda/fetch_log.csv',False)
    ck('cloudflare_outages','data_external/cloudflare/outages.json',False)
    # Evidence verification report should be produced by verify_evidence_archive.py.
    evidence_path = root/'evidence/evidence_verification_report.json'
    evidence_ok = False
    if present(evidence_path):
        try:
            evidence_ok = bool(json.loads(evidence_path.read_text(encoding='utf-8')).get('ok', False))
        except (OSError, ValueError, TypeError):
            evidence_ok = False
    checks.append({'check':'evidence_verification','required':True,'ok':evidence_ok,
                   'path':'evidence/evidence_verification_report.json'})
    checks.append({'check':'statsmodels_import','required':True,'ok':importlib.util.find_spec('statsmodels') is not None,'path':'python environment'})
    df=pd.DataFrame(checks); out=root/'data_external/manifests/external_closure_input_audit.csv'; out.parent.mkdir(parents=True,exist_ok=True); df.to_csv(out,index=False)
    print(df.to_string(index=False)); fail=df[df.required & ~df.ok]
    if len(fail): print('\nMissing required:', ', '.join(fail.check)); return 2 if a.strict else 0
    print('\nAll required external closure inputs present.'); return 0
if __name__=='__main__': raise SystemExit(main())
