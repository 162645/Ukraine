#!/usr/bin/env python3
"""Freeze Ukraine ADM1 geometry for ERA5 aggregation.

Uses geoBoundaries' public API to resolve the current gbOpen Ukraine ADM1
GeoJSON. This geometry is *only* a climate-grid aggregation aid; it must not
replace the project's frozen target-IP country/Admin1 mapping.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import requests
from _external_io import write_json, write_manifest_for

API='https://www.geoboundaries.org/api/current/gbOpen/UKR/ADM1/'

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--output', default='data_external/geography/geoBoundaries-UKR-ADM1.geojson')
    ap.add_argument('--metadata', default='data_external/geography/geoBoundaries-UKR-ADM1.metadata.json')
    ap.add_argument('--dry-run', action='store_true')
    args=ap.parse_args()
    if args.dry_run:
        print(json.dumps({'metadata_api':API,'output':args.output,'scientific_role':'weather_grid_aggregation_only'},indent=2)); return 0
    r=requests.get(API,timeout=60); r.raise_for_status(); meta=r.json()
    required=['boundaryID','boundaryYearRepresented','admUnitCount','gjDownloadURL']
    missing=[k for k in required if not meta.get(k)]
    if missing: raise SystemExit(f'geoBoundaries metadata missing {missing}')
    write_json(args.metadata, meta); write_manifest_for(args.metadata, {'source_url':API})
    url=meta['gjDownloadURL']; g=requests.get(url,timeout=180); g.raise_for_status()
    p=Path(args.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(g.content)
    obj=json.loads(p.read_text(encoding='utf-8'))
    n=len(obj.get('features',[]))
    if n < 20: raise SystemExit(f'Unexpectedly few ADM1 features: {n}')
    write_manifest_for(p, {'source_url':url,'boundary_id':meta['boundaryID'],'boundary_year_represented':meta['boundaryYearRepresented'],'feature_count':n})
    print(p, 'features=', n, 'boundaryYearRepresented=', meta['boundaryYearRepresented'])
    return 0
if __name__=='__main__': raise SystemExit(main())

