#!/usr/bin/env python3
"""Fetch Cloudflare Radar outage annotations and traffic anomalies for Ukraine.

Requires CLOUDFLARE_API_TOKEN. Raw API responses are frozen and hashed. These
are post-hoc external validation inputs only; they must never tune internal
measurement thresholds or event anchors.
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
import pandas as pd, requests
from _external_io import write_manifest_for

API='https://api.cloudflare.com/client/v4'
ENDPOINTS={
 'outages':'/radar/annotations/outages',
 'traffic_anomalies':'/radar/traffic_anomalies',
}

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--targets',default='config/external_validation_targets_v1.csv')
    ap.add_argument('--output-dir',default='data_external/cloudflare'); ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args(); t=pd.read_csv(args.targets,dtype=str).fillna('')
    start=pd.to_datetime(t.start_utc,utc=True).min().strftime('%Y-%m-%dT%H:%M:%SZ')
    end=pd.to_datetime(t.end_utc,utc=True).max().strftime('%Y-%m-%dT%H:%M:%SZ')
    plans=[]
    for name,path in ENDPOINTS.items():
        plans.append({'name':name,'url':API+path,'params':{'location':'UA','dateStart':start,'dateEnd':end,'format':'JSON','limit':1000}})
    plan=Path('data_external/request_plans/cloudflare_requests.json'); plan.parent.mkdir(parents=True,exist_ok=True); plan.write_text(json.dumps(plans,indent=2),encoding='utf-8')
    if args.dry_run:
        print(json.dumps(plans,indent=2)); return 0
    token=os.environ.get('CLOUDFLARE_API_TOKEN','').strip()
    if not token: raise SystemExit('CLOUDFLARE_API_TOKEN is required. Dry-run works without a token.')
    outdir=Path(args.output_dir); outdir.mkdir(parents=True,exist_ok=True); s=requests.Session(); s.headers.update({'Authorization':f'Bearer {token}','User-Agent':'ukraine-resilience-research/2.4.3'})
    failed=0
    for q in plans:
        r=s.get(q['url'],params=q['params'],timeout=120)
        out=outdir/f"{q['name']}.json"
        if r.status_code>=400:
            out.with_suffix('.error.txt').write_text(f'{r.status_code}\n{r.url}\n{r.text[:5000]}',encoding='utf-8'); failed+=1; continue
        out.write_bytes(r.content); write_manifest_for(out, {'request_url':r.url,'http_status':r.status_code,'scientific_role':'post_hoc_external_validation_only'})
    print('Cloudflare endpoints',len(plans),'failed',failed); return 1 if failed else 0
if __name__=='__main__': raise SystemExit(main())

