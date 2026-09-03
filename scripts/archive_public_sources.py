#!/usr/bin/env python3
"""Archive registered public URLs without treating live HTML as Telegram JSON.

Existing snapshots are preserved unless ``--overwrite`` is explicit.  A
filtered source list makes evidence correction/reverification auditable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--registry", default="config/source_post_registry_v1.csv")
    ap.add_argument("--timeout", type=int, default=45)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--source-id", action="append", default=[])
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    registry = root / args.registry
    rows = pd.read_csv(registry, dtype=str, keep_default_na=False)
    if args.source_id:
        wanted = set(args.source_id)
        unknown = sorted(wanted - set(rows["source_id"]))
        if unknown:
            raise SystemExit("Unknown source-id(s): " + ", ".join(unknown))
        selected = rows[rows["source_id"].isin(wanted)]
    else:
        selected = rows
    manifest = []
    for idx, row in selected.iterrows():
        url, rel = row["url"].strip(), row["expected_snapshot"].strip()
        if not url or not rel:
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.stat().st_size > 0 and not args.overwrite:
            data = target.read_bytes()
            manifest.append({"source_id": row["source_id"], "url": url,
                             "status": "existing", "bytes": len(data),
                             "sha256": hashlib.sha256(data).hexdigest(),
                             "snapshot_path": str(target.relative_to(root))})
            continue
        try:
            response = requests.get(url, headers={"User-Agent": "uresil-research-evidence-archiver/1.0"},
                                    timeout=args.timeout)
            response.raise_for_status()
            target.write_bytes(response.content)
            digest = hashlib.sha256(response.content).hexdigest()
            metadata = {"source_id": row["source_id"], "url": url,
                        "accessed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type", ""),
                        "etag": response.headers.get("etag", ""),
                        "last_modified": response.headers.get("last-modified", ""),
                        "bytes": len(response.content), "sha256": digest,
                        "snapshot_path": str(target.relative_to(root))}
            target.with_suffix(target.suffix + ".meta.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest.append(metadata)
        except Exception as exc:  # noqa: BLE001
            manifest.append({"source_id": row["source_id"], "url": url,
                             "error": f"{type(exc).__name__}: {exc}"})
        time.sleep(args.sleep)
    out = root / "evidence/public_snapshot_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    return 0 if all("error" not in item for item in manifest) else 2


if __name__ == "__main__":
    raise SystemExit(main())
