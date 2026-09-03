from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    p=Path(path); h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def write_json(path: str | Path, obj: Any) -> Path:
    p=Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    return p


def write_manifest_for(path: str | Path, extra: dict | None=None) -> Path:
    p=Path(path)
    meta={
        'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha256_file(p),
        'created_unix': time.time(),
    }
    if extra: meta.update(extra)
    return write_json(str(p)+'.manifest.json', meta)


def env_present(name: str) -> bool:
    return bool(os.environ.get(name, '').strip())

