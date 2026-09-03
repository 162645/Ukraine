#!/usr/bin/env python3
"""Read-only ClickHouse connectivity and schema inventory.

The inspector queries metadata and aggregates only. It never prints credentials
or raw measurement rows and tries both supported protocols.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uresil.config import load_config  # noqa: E402
from uresil.db import CHClient  # noqa: E402


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


def safe_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe ClickHouse identifier in configuration: {value!r}")
    return value


def records(frame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def inspect_table(client: CHClient, logical: str, full_name: str, deep: bool) -> dict[str, Any]:
    full_name = safe_identifier(full_name)
    database, table = full_name.split(".", 1) if "." in full_name else (
        client.cfg.db_conn()["database"], full_name)
    columns = client.describe(full_name)
    item: dict[str, Any] = {
        "logical_name": logical,
        "table": full_name,
        "columns": records(columns),
    }
    meta_sql = """
        SELECT sum(rows) AS active_rows, sum(bytes_on_disk) AS bytes_on_disk,
               min(min_time) AS min_part_time, max(max_time) AS max_part_time
        FROM system.parts
        WHERE active AND database = %(database)s AND table = %(table)s
    """
    try:
        meta = client.query_df(meta_sql, {"database": database, "table": table})
        item["active_parts"] = records(meta)[0] if len(meta) else {}
    except Exception as exc:
        item["active_parts_warning"] = f"metadata unavailable: {type(exc).__name__}"
    if deep:
        item["exact_rows"] = int(client.scalar(f"SELECT count() FROM {full_name}"))
        time_columns = [
            str(row["name"]) for _, row in columns.iterrows()
            if "Date" in str(row.get("type", ""))
        ]
        if time_columns:
            time_col = safe_identifier(time_columns[0])
            span = client.query_df(
                f"SELECT min({time_col}) AS min_time, max({time_col}) AS max_time "
                f"FROM {full_name}"
            )
            item["time_span"] = records(span)[0] if len(span) else {}
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None, help="YAML config/local override")
    parser.add_argument("--prefer", choices=("connect", "driver"), default="connect",
                        help="Protocol to try first: connect=HTTP, driver=native")
    parser.add_argument("--deep", action="store_true",
                        help="Also run exact count() and min/max time aggregates")
    parser.add_argument("--output", type=Path,
                        help="Optional JSON path; credentials are never included")
    args = parser.parse_args()

    cfg = load_config(args.config, run_id="check_ch", mode="real")
    db = cfg.db_conn()
    report: dict[str, Any] = {
        "endpoint": {
            "host": db["host"], "http_port": db["http_port"],
            "native_port": db["native_port"], "database": db["database"],
            "secure": db["secure"],
        },
        "read_only": True,
        "deep": args.deep,
    }
    try:
        with CHClient(cfg, prefer=args.prefer) as client:
            identity = client.query_df(
                "SELECT version() AS version, currentDatabase() AS database, "
                "currentUser() AS user, timezone() AS timezone, now() AS server_time"
            )
            report["backend"] = client.backend
            report["server"] = records(identity)[0]
            report["tables"] = []
            for logical, full_name in cfg.database.get("tables", {}).items():
                try:
                    report["tables"].append(
                        inspect_table(client, str(logical), str(full_name), args.deep))
                except Exception as exc:
                    report["tables"].append({
                        "logical_name": logical, "table": full_name,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
    except Exception as exc:
        print(
            "ClickHouse application handshake failed. TCP-open alone is not sufficient; "
            "check Docker port publishing, listen_host, firewall/proxy routing, and protocol/port mapping.",
            file=sys.stderr,
        )
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    print(payload)
    if args.output:
        target = args.output if args.output.is_absolute() else ROOT / args.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
        print(f"Inventory written to {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
