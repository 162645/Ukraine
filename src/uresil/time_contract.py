"""Measurement timestamp contract inferred from epoch values, not event labels."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd


CANDIDATE_ZONES = ("UTC", "Europe/Kyiv", "Asia/Shanghai")


def infer_display_timezone(samples: pd.DataFrame, *, raw_col: str = "raw_time",
                           epoch_col: str = "epoch_us",
                           server_timezone: str = "UTC") -> dict:
    """Infer how client-returned timestamps must be interpreted to match epoch.

    The Unix epoch is timezone invariant.  For naive client datetimes, test IANA
    zones and require one semantic instant across every sample.  Aware values are
    compared directly.  This deliberately uses no outage/event label.
    """
    parsed = [pd.Timestamp(x) for x in samples[raw_col]]
    if parsed and all(x.tzinfo is not None for x in parsed):
        errors = [abs(int(x.tz_convert("UTC").timestamp() * 1_000_000) - int(epoch))
                  for x, epoch in zip(parsed, samples[epoch_col])]
        zone = str(parsed[0].tzinfo)
        canonical = "UTC" if zone in {"UTC", "Etc/UTC", "GMT", "+00:00"} else zone
        return {"inferred_timezone": canonical, "matching_timezones": [canonical],
                "candidate_diagnostics": [{"candidate_timezone": canonical,
                                           "matches_epoch": int(max(errors) <= 1_000),
                                           "max_abs_error_us": max(errors)}],
                "sample_n": int(len(samples))}
    candidates = []
    zones = list(dict.fromkeys(("UTC", server_timezone, *CANDIDATE_ZONES)))
    detail = []
    for zone in zones:
        ok = True
        max_abs_error_us = 0
        for _, row in samples.iterrows():
            ts = pd.Timestamp(row[raw_col])
            if ts.tzinfo is None:
                try:
                    ts = ts.tz_localize(ZoneInfo(zone), ambiguous="raise", nonexistent="raise")
                except Exception:
                    ok = False
                    break
            actual = int(ts.tz_convert("UTC").timestamp() * 1_000_000)
            err = abs(actual - int(row[epoch_col]))
            max_abs_error_us = max(max_abs_error_us, err)
            if err > 1_000:  # tolerate sub-millisecond driver conversion only
                ok = False
        detail.append({"candidate_timezone": zone, "matches_epoch": int(ok),
                       "max_abs_error_us": max_abs_error_us})
        if ok:
            candidates.append(zone)
    # UTC and an explicitly UTC server zone are semantic duplicates.
    canonical = ["UTC" if z in {"UTC", "Etc/UTC", "GMT"} else z for z in candidates]
    canonical = list(dict.fromkeys(canonical))
    inferred = canonical[0] if len(canonical) == 1 else "AMBIGUOUS"
    return {"inferred_timezone": inferred, "matching_timezones": canonical,
            "candidate_diagnostics": detail, "sample_n": int(len(samples))}


def measurement_time_contract(ch, cfg) -> dict:
    """Query raw timestamp/epoch pairs and enforce the configured UTC contract."""
    table = cfg.table("ping")
    dc = str(cfg.study["data_center"]).replace("'", "\\'")
    server_timezone = str(ch.scalar("SELECT timezone()"))
    table_db, table_name = ((table.split(".", 1) + [cfg.db_conn()["database"]])[:2]
                            if "." in table else (cfg.db_conn()["database"], table))
    column_type = str(ch.scalar(
        f"SELECT type FROM system.columns WHERE database='{table_db}' "
        f"AND table='{table_name}' AND name='measure_time' LIMIT 1"))
    sql = f"""
SELECT * FROM (
  SELECT measure_time AS raw_time, toUnixTimestamp64Micro(toDateTime64(measure_time, 6, 'UTC')) AS epoch_us
  FROM {table} WHERE data_center='{dc}' ORDER BY measure_time ASC LIMIT 4
)
UNION ALL
SELECT * FROM (
  SELECT measure_time AS raw_time, toUnixTimestamp64Micro(toDateTime64(measure_time, 6, 'UTC')) AS epoch_us
  FROM {table} WHERE data_center='{dc}' ORDER BY measure_time DESC LIMIT 4
)
""".strip()
    samples = ch.query_df(sql)
    if samples.empty:
        raise RuntimeError("timestamp contract cannot be inferred: ping table returned no samples")
    report = infer_display_timezone(samples, server_timezone=server_timezone)
    expected = str(cfg.study.get("measurement_timestamp_timezone", "UTC"))
    report.update({"expected_timezone": expected, "server_timezone": server_timezone,
                   "column_type": column_type,
                   "sample_min_epoch_us": int(samples.epoch_us.min()),
                   "sample_max_epoch_us": int(samples.epoch_us.max()),
                   "samples": [{"raw_time": str(r.raw_time), "epoch_us": int(r.epoch_us),
                                "epoch_as_utc": str(pd.to_datetime(int(r.epoch_us), unit="us", utc=True))}
                               for r in samples.itertuples(index=False)]})
    report["contract_ok"] = int(report["inferred_timezone"] == expected)
    if not report["contract_ok"]:
        raise RuntimeError(
            "measurement timestamp timezone contract mismatch: "
            f"expected={expected}, inferred={report['inferred_timezone']}, "
            f"matches={report['matching_timezones']}, server={server_timezone}, type={column_type}"
        )
    return report
