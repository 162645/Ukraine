#!/usr/bin/env python3
"""Extract registered posts from a Telegram Desktop JSON export."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def flat_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(x if isinstance(x, str) else str(x.get("text", "")) for x in value)
    return str(value or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_json")
    ap.add_argument("--root", default=".")
    ap.add_argument("--registry", default="config/source_post_registry_v1.csv")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    data = json.loads(Path(args.export_json).read_text(encoding="utf-8"))
    registry_path = root / args.registry
    registry = pd.read_csv(registry_path, dtype=str, keep_default_na=False)
    chats_raw = data.get("chats", {})
    chats = chats_raw.get("list", []) if isinstance(chats_raw, dict) else chats_raw
    out = root / "evidence/telegram_exports"
    out.mkdir(parents=True, exist_ok=True)
    manifest, found = [], set()
    for chat in chats:
        haystack = json.dumps({"name": chat.get("name"), "id": chat.get("id")}, ensure_ascii=False).lower()
        for idx, source in registry[registry["telegram_channel"].ne("")].iterrows():
            channel = source["telegram_channel"].lower().lstrip("@")
            if channel not in haystack.replace(" ", ""):
                continue
            wanted = source["telegram_message_id"].strip()
            candidates = [m for m in chat.get("messages", [])
                          if not wanted or str(m.get("id", "")) == wanted]
            # Missing message IDs deliberately require manual source/date review;
            # never guess from a weak month substring.
            if not wanted:
                continue
            for message in candidates:
                canonical = {"source_id": source["source_id"], "channel_title": chat.get("name", ""),
                             "chat_id": chat.get("id"), "message_id": message.get("id"),
                             "date": message.get("date"), "edited": message.get("edited"),
                             "text": flat_text(message.get("text", "")), "raw": message}
                payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()
                path = out / f"{source['source_id']}__msg_{message.get('id')}.json"
                path.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                manifest.append({"source_id": source["source_id"], "json": str(path.relative_to(root)),
                                 "sha256": digest,
                                 "export_ingested_at_utc": datetime.now(timezone.utc).isoformat()})
                registry.loc[idx, "snapshot_path"] = str(path.relative_to(root))
                registry.loc[idx, "text_sha256"] = digest
                registry.loc[idx, "immutable_status"] = "telegram_json_extracted"
                found.add(source["source_id"])
    registry.to_csv(registry_path, index=False, encoding="utf-8")
    (out / "telegram_export_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    missing = sorted(set(registry.loc[(registry["critical"].eq("1")) &
                                      registry["telegram_channel"].ne(""), "source_id"]) - found)
    print(json.dumps({"extracted": len(manifest), "missing_critical": missing}, ensure_ascii=False, indent=2))
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
