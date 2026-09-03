#!/usr/bin/env python3
"""Download restartable monthly ERA5-Land temperature/dewpoint inputs."""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path


def month_range(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-06-22")
    ap.add_argument("--end", default="2025-01-09")
    ap.add_argument("--output-dir", default="data_external/weather/era5_land_raw")
    ap.add_argument("--area", nargs=4, type=float, default=[53.0, 22.0, 44.0, 41.5],
                    metavar=("N", "W", "S", "E"))
    ap.add_argument("--dry-run", action="store_true",
                    help="Write the frozen monthly request plan without contacting CDS")
    args = ap.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end precedes --start")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    plans = []
    for year, month in month_range(start, end):
        first = max(start, date(year, month, 1))
        last = min(end, date(year, month, calendar.monthrange(year, month)[1]))
        request = {
            "variable": ["2m_temperature", "2m_dewpoint_temperature"],
            "year": str(year), "month": f"{month:02d}",
            "day": [f"{day:02d}" for day in range(first.day, last.day + 1)],
            "time": [f"{hour:02d}:00" for hour in range(24)],
            "data_format": "netcdf", "download_format": "unarchived", "area": args.area,
        }
        target = out / f"era5_land_{year}{month:02d}.nc"
        manifest = target.with_suffix(".request.json")
        payload = {
            "dataset": "reanalysis-era5-land", "request": request,
            "target": str(target), "scientific_role": "weather_confounder_only",
        }
        manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        plans.append(payload)
    plan_path = Path("data_external/request_plans/era5_land_requests.json")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plans, indent=2), encoding="utf-8")
    if args.dry_run:
        print(plan_path)
        print("monthly requests:", len(plans))
        return 0
    try:
        import cdsapi
    except ImportError as exc:
        raise SystemExit("Install requirements-external.txt in the preprocessing environment") from exc
    client = cdsapi.Client()
    for payload in plans:
        request = payload["request"]
        target = Path(payload["target"])
        manifest = target.with_suffix(".request.json")
        if not target.exists() or not target.stat().st_size:
            client.retrieve(payload["dataset"], request, str(target))
        manifest.write_text(json.dumps({
            **payload,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "file": target.name, "bytes": target.stat().st_size, "sha256": digest(target),
        }, indent=2), encoding="utf-8")
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
