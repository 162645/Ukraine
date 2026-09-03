#!/usr/bin/env python3
"""Download frozen IODA v2 raw-signal responses for external validation.

No IODA result is allowed to select B2 thresholds, attack anchors, or treated
regions. The script reads a preregistered query list and saves raw JSON plus a
request manifest. IODA's v2 API documents /signals/raw/{entityType}/{entityCode}.
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import pandas as pd, requests
from _external_io import write_json, write_manifest_for

BASE='https://api.ioda.inetintel.cc.gatech.edu/v2'

def epoch(s:str)->int:
    return int(pd.Timestamp(s,tz='UTC').timestamp())

def fetch(session, entity_type, entity_code, start, end, output, timeout=120):
    url=f'{BASE}/signals/raw/{entity_type}/{entity_code}'
    params={'from':epoch(start),'until':epoch(end)}
    r=session.get(url,params=params,timeout=timeout)
    if r.status_code >= 400:
        # Preserve the exact failed request for reproducibility rather than guessing API changes.
        Path(str(output)+'.error.txt').write_text(f'{r.status_code}\n{r.url}\n{r.text[:5000]}',encoding='utf-8')
        r.raise_for_status()
    Path(output).parent.mkdir(parents=True,exist_ok=True); Path(output).write_bytes(r.content)
    write_manifest_for(output, {'request_url':r.url,'entity_type':entity_type,'entity_code':str(entity_code),'start_utc':start,'end_utc':end,'http_status':r.status_code})
    return r.url

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--targets',default='config/external_validation_targets_v1.csv')
    ap.add_argument('--output-dir',default='data_external/ioda'); ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args(); t=pd.read_csv(args.targets,dtype=str).fillna('')
    plans=[]
    for _,r in t.iterrows():
        plans.append({'event_id':r.event_id,'entity_type':'country','entity_code':r.country_code,'start_utc':r.start_utc,'end_utc':r.end_utc})
        for asn in [x for x in r.asn_list.split('|') if x]:
            plans.append({'event_id':r.event_id,'entity_type':'asn','entity_code':asn,'start_utc':r.start_utc,'end_utc':r.end_utc})
    plan_path=Path('data_external/request_plans/ioda_requests.csv'); plan_path.parent.mkdir(parents=True,exist_ok=True); pd.DataFrame(plans).to_csv(plan_path,index=False)
    if args.dry_run:
        print(pd.DataFrame(plans).to_string(index=False)); return 0
    s=requests.Session(); s.headers['User-Agent']='ukraine-resilience-research/2.4.3'
    log=[]
    for p in plans:
        fn=f"{p['event_id']}__{p['entity_type']}_{p['entity_code']}.json"
        out=Path(args.output_dir)/fn
        try:
            url=fetch(s,p['entity_type'],p['entity_code'],p['start_utc'],p['end_utc'],out); status='ok'; error=''
        except Exception as e:
            status='failed'; error=repr(e); url=''
        log.append({**p,'status':status,'request_url':url,'output':str(out),'error':error}); time.sleep(.2)
    pd.DataFrame(log).to_csv(Path(args.output_dir)/'fetch_log.csv',index=False)
    failed=sum(x['status']!='ok' for x in log); print('IODA requests',len(log),'failed',failed)
    return 1 if failed else 0
if __name__=='__main__': raise SystemExit(main())

