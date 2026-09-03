#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='data_external'); ap.add_argument('--output',default='data_external/manifests/SHA256SUMS.tsv')
    a=ap.parse_args(); root=Path(a.root); rows=[]
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.resolve()!=Path(a.output).resolve(): rows.append((digest(p),p.stat().st_size,str(p)))
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text('sha256\tbytes\tpath\n'+'\n'.join(f'{h}\t{n}\t{p}' for h,n,p in rows)+'\n',encoding='utf-8')
    print(out, len(rows)); return 0
if __name__=='__main__': raise SystemExit(main())

