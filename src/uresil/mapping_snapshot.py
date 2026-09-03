"""Freeze and verify the frozen mapping snapshot contract."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_MAPPING_FREEZE_CUTOFF_UTC = "2025-02-01 00:00:00"
REQUIRED_MAPPING_FREEZE_FIELDS = (
    "snapshot_date",
    "row_count",
    "content_checksum_uint64",
    "snapshot_hash",
)


def mapping_manifest_state(manifest: dict[str, Any]) -> tuple[dict[str, Any], bool, list[str]]:
    fr = manifest.get("freeze", {})
    frozen = bool(fr.get("frozen", False))
    missing = [x for x in REQUIRED_MAPPING_FREEZE_FIELDS if fr.get(x) in (None, "")]
    return fr, frozen, missing


def mapping_manifest_needs_freeze(manifest: dict[str, Any]) -> bool:
    _, frozen, missing = mapping_manifest_state(manifest)
    return (not frozen) or bool(missing)


def snapshot_sql(table: str, cutoff: str) -> str:
    return f"""
    SELECT
        count() AS row_count,
        ifNull(sum(cityHash64(ip, toString(asn), geo_country, geo_region,
                              formatDateTime(snapshot_updated_at, '%F %T'))), toUInt64(0)) AS content_checksum_uint64,
        max(snapshot_updated_at) AS max_updated_at
    FROM
    (
        SELECT
            ip,
            argMax(asn, updated_at) AS asn,
            argMax(geo_country, updated_at) AS geo_country,
            argMax(geo_region, updated_at) AS geo_region,
            max(updated_at) AS snapshot_updated_at
        FROM {table}
        WHERE updated_at <= toDateTime('{cutoff}', 'UTC')
        GROUP BY ip
    )
    """


def contract_hash(table: str, cutoff: str, row_count: int, checksum: str) -> str:
    raw = f"{table}|{cutoff}|{row_count}|{checksum}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def resolve_snapshot_cutoff(ch, table: str, cutoff: str | None = None) -> str:
    if cutoff is not None:
        return cutoff
    mx = ch.scalar(f"SELECT max(updated_at) FROM {table}")
    if mx is None:
        raise RuntimeError("Mapping table is empty")
    return str(mx).replace("T", " ")[:19]


def _coerce_int(value: Any) -> int:
    if pd.isna(value):
        return 0
    return int(value)


def query_mapping_snapshot(ch, table: str, cutoff: str | None = None) -> dict[str, Any]:
    cutoff_value = resolve_snapshot_cutoff(ch, table, cutoff)
    d = ch.query_df(snapshot_sql(table, cutoff_value))
    if d.empty:
        raise RuntimeError("Mapping snapshot query returned no result")
    row_count = _coerce_int(d.iloc[0]["row_count"])
    checksum = str(_coerce_int(d.iloc[0]["content_checksum_uint64"]))
    max_updated_at = d.iloc[0].get("max_updated_at")
    if row_count <= 0:
        raise RuntimeError("Frozen mapping snapshot contains no IP rows")
    return {
        "cutoff": cutoff_value,
        "row_count": row_count,
        "content_checksum_uint64": checksum,
        "max_updated_at": None if pd.isna(max_updated_at) else str(max_updated_at),
    }


def build_frozen_manifest(payload: dict[str, Any], *, table: str, cutoff: str,
                          row_count: int, checksum: str) -> dict[str, Any]:
    out = dict(payload)
    out["table"] = table
    out["freeze"] = {
        "frozen": True,
        "snapshot_date": cutoff + " UTC",
        "row_count": int(row_count),
        "content_checksum_uint64": str(checksum),
        "snapshot_hash": contract_hash(table, cutoff, int(row_count), str(checksum)),
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection": "latest row per IP by updated_at at or before snapshot_date",
    }
    return out


def write_frozen_manifest(path: Path, payload: dict[str, Any], *, table: str, cutoff: str,
                          row_count: int, checksum: str) -> dict[str, Any]:
    out = build_frozen_manifest(payload, table=table, cutoff=cutoff,
                                row_count=row_count, checksum=checksum)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
