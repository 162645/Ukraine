#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

ap=argparse.ArgumentParser();ap.add_argument('run_id');args=ap.parse_args()
p=Path(__file__).resolve().parents[1]/'runs'/args.run_id/'results/tables/closure_report.json'
if not p.exists(): raise SystemExit(f'Missing {p}')
x=json.loads(p.read_text(encoding='utf-8'))
print(x['closure']);print(x.get('interpretation',''))
for c in x.get('checks',[]): print(f"{c['status']:>28}  {c['check']}")
