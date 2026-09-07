#!/usr/bin/env python3
"""Independent Figure-8-like regional active-scan diagnostic.

This deliberately has no dependency on planned-outage labels, B1, sensitivity
scores, or historical mapping.  It reads only the current mapping snapshot and
the two-hour active Ping observations.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from uresil.config import load_config
from uresil.db import CHClient
from uresil.geo import Admin1Canonicalizer


def query_signals(cfg):
    """Run bounded monthly aggregations, never one all-period hash aggregate."""
    start = pd.to_datetime(cfg.study["measurement_start_utc"], utc=True)
    end = pd.to_datetime(cfg.study["end_utc"], utc=True)
    ping, mapping, dc = cfg.table("ping"), cfg.table("mapping"), cfg.study["data_center"]
    frames = []
    # ``prefix_region`` is deliberately derived from the mapping table itself,
    # rather than response volume: it implements the requested modal mapping
    # count for each /24 and is fixed across all monthly signal chunks.
    for month_start in pd.date_range(start.normalize().replace(day=1), end.normalize(), freq="MS", tz="UTC"):
        chunk_start = max(month_start, start)
        month_end = min(month_start + pd.offsets.MonthBegin(1), end + pd.Timedelta(microseconds=1))
        month_start_s = chunk_start.strftime("%Y-%m-%d %H:%M:%S")
        month_end_s = month_end.strftime("%Y-%m-%d %H:%M:%S")
        sql = f"""
WITH latest AS (
  SELECT ip, argMax(geo_country, updated_at) AS country, argMax(geo_region, updated_at) AS region
  FROM {mapping} GROUP BY ip
), prefix_region AS (
  SELECT prefix_key, argMax(country, n) AS country, argMax(region, n) AS region
  FROM (
    SELECT concat(arrayElement(splitByChar('.', ip), 1), '.', arrayElement(splitByChar('.', ip), 2), '.', arrayElement(splitByChar('.', ip), 3)) AS prefix_key,
           country, region, count() AS n
    FROM latest WHERE ip LIKE '%.%.%.%' GROUP BY prefix_key, country, region
  ) GROUP BY prefix_key
), base AS (
  SELECT toStartOfInterval(p.measure_time, INTERVAL 2 HOUR) AS measure_time,
         concat(arrayElement(splitByChar('.', p.prefix24), 1), '.', arrayElement(splitByChar('.', p.prefix24), 2), '.', arrayElement(splitByChar('.', p.prefix24), 3)) AS prefix_key,
         p.dst_ip,
         l.country, l.region
  FROM {ping} AS p INNER JOIN latest AS l ON p.dst_ip = l.ip
  WHERE p.data_center = '{dc}'
    AND p.measure_time >= toDateTime64('{month_start_s}', 6, 'UTC')
    AND p.measure_time < toDateTime64('{month_end_s}', 6, 'UTC')
    AND p.dst_ip != '' AND p.prefix24 != ''
), eligible AS (
  SELECT prefix_key FROM base GROUP BY prefix_key HAVING countDistinct(dst_ip) >= 3
), ips AS (
  SELECT measure_time, country, region, countDistinct(dst_ip) AS value
  FROM base GROUP BY measure_time, country, region
), active AS (
  SELECT DISTINCT measure_time, prefix_key FROM base
), fbs AS (
  SELECT a.measure_time, r.country, r.region, countDistinct(a.prefix_key) AS value
  FROM active AS a INNER JOIN eligible AS e USING (prefix_key)
       INNER JOIN prefix_region AS r USING (prefix_key)
  GROUP BY a.measure_time, r.country, r.region
)
SELECT 'IPS' AS signal, measure_time, country, region, value FROM ips
UNION ALL SELECT 'FBS' AS signal, measure_time, country, region, value FROM fbs
"""
        with CHClient(cfg) as ch:
            frames.append(ch.query_df(sql))
        print(f"completed month {month_start:%Y-%m}", flush=True)
    return pd.concat(frames, ignore_index=True)


def complete_and_score(raw: pd.DataFrame, cfg) -> pd.DataFrame:
    canon = Admin1Canonicalizer(cfg.resource_path("admin1_aliases"), cfg.quality["unknown_labels"], cfg.quality["valid_country_aliases"])
    raw["admin1"] = [canon.canonical_admin1(c, r) for c, r in zip(raw.country, raw.region)]
    raw = raw[raw.admin1.isin(canon.valid_ua)].copy()
    raw["measure_time"] = pd.to_datetime(raw.measure_time, utc=True)
    raw = raw.groupby(["signal", "measure_time", "admin1"], as_index=False).value.sum()
    # The analysis ends at observed Ping support, not the nominal registry end.
    grid = pd.date_range(raw.measure_time.min(), raw.measure_time.max(), freq="2h", tz="UTC")
    states = sorted(raw.admin1.unique())
    wide = raw.pivot(index=["measure_time", "admin1"], columns="signal", values="value")
    full = pd.MultiIndex.from_product([grid, states], names=["measure_time", "admin1"])
    d = wide.reindex(full, fill_value=0).reset_index()
    for sig in ("IPS", "FBS"):
        if sig not in d: d[sig] = 0
        d[f"{sig}_7d_mean"] = d.groupby("admin1")[sig].transform(lambda x: x.shift(1).rolling(84, min_periods=84).mean())
        d[f"{sig}_ratio"] = d[sig] / d[f"{sig}_7d_mean"].replace(0, np.nan)
    d["ips_outage"] = d.IPS_ratio.lt(.90) & d.IPS_7d_mean.notna()
    d["fbs_outage"] = d.FBS_ratio.lt(.95) & d.IPS_ratio.lt(.95) & d.FBS_7d_mean.notna()
    d["BGP"] = np.nan; d["BGP_7d_mean"] = np.nan; d["BGP_ratio"] = np.nan; d["bgp_outage"] = False
    return d.rename(columns={"IPS": "ips", "FBS": "fbs"})


def draw(d: pd.DataFrame, out: Path):
    states = sorted(d.admin1.unique()); times = sorted(d.measure_time.unique())
    x = np.arange(len(times)); state_index = {s:i for i,s in enumerate(states)}
    fig, ax = plt.subplots(figsize=(18, max(6, .42 * len(states))))
    ax.set_facecolor("#eeeeee")
    for signal, col, offset in [("bgp_outage", "#1976d2", -.25), ("fbs_outage", "#2ca02c", 0), ("ips_outage", "#d62728", .25)]:
        q = d[d[signal]]
        ax.vlines([times.index(t) for t in q.measure_time], [state_index[s]+offset-.1 for s in q.admin1], [state_index[s]+offset+.1 for s in q.admin1], color=col, lw=.7)
    ax.set_yticks(range(len(states)), states); ax.set_ylim(-.6, len(states)-.4)
    ticks = np.linspace(0, len(times)-1, min(10, len(times)), dtype=int)
    ax.set_xticks(ticks, [pd.Timestamp(times[i]).strftime("%Y-%m") for i in ticks], rotation=35, ha="right")
    ax.set_xlabel("UTC time"); ax.set_ylabel("Oblast"); ax.set_title("Figure-8-like regional Internet anomalies (FBS / IPS; no BGP data)")
    fig.tight_layout(); fig.savefig(out / "figure8_like.png", dpi=220); plt.close(fig)
    pivot = d.pivot(index="admin1", columns="measure_time", values="IPS_ratio").reindex(states)
    fig, ax = plt.subplots(figsize=(18, max(6, .38 * len(states))))
    im = ax.imshow(pivot, aspect="auto", cmap="RdYlGn", norm=TwoSlopeNorm(vmin=.4, vcenter=1, vmax=1.2))
    ax.set_yticks(range(len(states)), states); ax.set_xticks(ticks, [pd.Timestamp(times[i]).strftime("%Y-%m") for i in ticks], rotation=35, ha="right")
    ax.set_title("IPS ratio: current responsive IPs / preceding 7-day mean"); fig.colorbar(im, ax=ax, label="IPS ratio")
    fig.tight_layout(); fig.savefig(out / "ips_ratio_heatmap.png", dpi=220); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--output-dir", required=True); ap.add_argument("--config", default=None); args = ap.parse_args()
    cfg = load_config(args.config, run_id="figure8_like", mode="real")
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    d = complete_and_score(query_signals(cfg), cfg)
    d.to_csv(out / "region_cycle_signals.csv", index=False, encoding="utf-8-sig")
    draw(d, out)
    print({"states": int(d.admin1.nunique()), "cycles": int(d.measure_time.nunique()), "rows": len(d), "ips_outage": int(d.ips_outage.sum()), "fbs_outage": int(d.fbs_outage.sum()), "output": str(out)})

if __name__ == "__main__": main()
