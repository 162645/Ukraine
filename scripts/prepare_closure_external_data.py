#!/usr/bin/env python3
"""Orchestrate external closure-data preparation.

Default is --dry-run so Codex/users can inspect exactly what would be accessed.
Use --execute to perform network/API actions. Cloudflare is skipped unless a
CLOUDFLARE_API_TOKEN is present. Telegram Desktop export remains manual by
construction and is verified separately.
"""
from __future__ import annotations
import argparse, os, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def run(args):
    print('+',' '.join(map(str,args))); return subprocess.run(args,cwd=ROOT).returncode

def main()->int:
    ap=argparse.ArgumentParser(); g=ap.add_mutually_exclusive_group(); g.add_argument('--dry-run',action='store_true'); g.add_argument('--execute',action='store_true')
    ap.add_argument('--skip-era5',action='store_true'); ap.add_argument('--skip-ioda',action='store_true'); ap.add_argument('--skip-cloudflare',action='store_true'); ap.add_argument('--skip-geography',action='store_true')
    a=ap.parse_args(); dry=not a.execute
    py=sys.executable; rc=[]
    if not a.skip_geography: rc.append(run([py,'scripts/fetch_geoboundaries_ukraine_adm1.py']+(['--dry-run'] if dry else [])))
    if not a.skip_era5: rc.append(run([py,'scripts/download_era5_land.py','--start','2024-06-22','--end','2025-01-09']+(['--dry-run'] if dry else [])))
    if not a.skip_ioda: rc.append(run([py,'scripts/fetch_ioda_validation.py']+(['--dry-run'] if dry else [])))
    if not dry and not a.skip_geography and not a.skip_era5:
        rc.append(run([py,'scripts/build_weather_admin1_2h.py',
                       '--admin1-geojson','data_external/geography/geoBoundaries-UKR-ADM1.geojson',
                       '--output','data_derived/weather_admin1_2h.parquet']))
    if not a.skip_cloudflare:
        if dry or os.environ.get('CLOUDFLARE_API_TOKEN'):
            rc.append(run([py,'scripts/fetch_cloudflare_radar.py']+(['--dry-run'] if dry else [])))
        else: print('SKIP Cloudflare: CLOUDFLARE_API_TOKEN not set')
    run([py,'scripts/hash_external_data.py'])
    print('\nTelegram evidence is intentionally manual: export official channels from Telegram Desktop to JSON+HTML, then run scripts/ingest_telegram_export.py and scripts/verify_evidence_archive.py.')
    return 1 if any(x not in (0,) for x in rc) else 0
if __name__=='__main__': raise SystemExit(main())
