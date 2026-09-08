"""ClickHouse stage for canonical, label-independent IPS and FBS signals."""
from __future__ import annotations

import pandas as pd

from .config import Config
from .db import CHClient
from .progress import get_logger, step
from .canonical_signals import add_rolling_ratios


def _render_figures(d: pd.DataFrame, out):
    """Render Figure-8-like lanes and a continuous IPS-ratio heatmap."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    states = sorted(d.admin1.unique()); times = sorted(d.measure_time.unique())
    index = {s: i for i, s in enumerate(states)}
    fig, ax = plt.subplots(figsize=(16, max(5, .34 * len(states))))
    ax.set_facecolor("#eeeeee")
    for col, color, off in (("bgp_outage", "#1976d2", -.25),
                            ("fbs_outage", "#2ca02c", 0),
                            ("ips_outage", "#d62728", .25)):
        if col not in d:
            continue
        q = d[d[col].fillna(False)]
        for _, row in q.iterrows():
            x = times.index(row.measure_time); y = index[row.admin1] + off
            ax.vlines(x, y - .09, y + .09, color=color, lw=.65)
    ax.set_yticks(range(len(states)), states); ax.set_ylabel("Oblast")
    ax.set_xlabel("UTC 2-hour measurement cycle")
    ax.set_xticks(range(0, len(times), max(1, len(times)//10)),
                  [pd.Timestamp(times[i]).strftime("%Y-%m") for i in range(0, len(times), max(1, len(times)//10))], rotation=35, ha="right")
    fig.tight_layout()
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out / f"fig02_ips_fbs_oblast_time.{ext}", dpi=220 if ext == "png" else None)
    plt.close(fig)
    pivot = d.pivot(index="admin1", columns="measure_time", values="IPS_ratio").reindex(states)
    fig, ax = plt.subplots(figsize=(16, max(5, .34 * len(states))))
    im = ax.imshow(pivot, aspect="auto", cmap="RdYlGn", norm=TwoSlopeNorm(vmin=.4, vcenter=1, vmax=1.2))
    ax.set_yticks(range(len(states)), states); ax.set_ylabel("Oblast")
    ax.set_xlabel("UTC 2-hour measurement cycle")
    fig.colorbar(im, ax=ax, label="IPS / prior 7-day mean")
    fig.tight_layout()
    for ext in ("png", "pdf", "svg"):
        fig.savefig(out / f"fig02_ips_ratio_heatmap.{ext}", dpi=220 if ext == "png" else None)
    plt.close(fig)


def _month_query(cfg: Config, start: pd.Timestamp, end: pd.Timestamp) -> str:
    ping, mapping, dc = cfg.table("ping"), cfg.table("mapping"), cfg.study["data_center"]
    lo = start.strftime("%Y-%m-%d %H:%M:%S")
    hi = end.strftime("%Y-%m-%d %H:%M:%S")
    min_ips = int(cfg.raw.get("macro_signals", {}).get("fbs_monthly_min_ever_responsive_ips", 3))
    return f"""
WITH latest AS (
  SELECT ip, argMax(geo_country, updated_at) AS country,
         argMax(geo_region, updated_at) AS region
  FROM {mapping} GROUP BY ip
), prefix_region AS (
  SELECT prefix_key, argMax(country, n) AS country, argMax(region, n) AS region
  FROM (
    SELECT concat(arrayElement(splitByChar('.', ip), 1), '.',
                 arrayElement(splitByChar('.', ip), 2), '.',
                 arrayElement(splitByChar('.', ip), 3)) AS prefix_key,
           country, region, count() AS n
    FROM latest WHERE ip LIKE '%.%.%.%'
    GROUP BY prefix_key, country, region
  ) GROUP BY prefix_key
), base AS (
  SELECT toStartOfInterval(p.measure_time, INTERVAL 2 HOUR) AS measure_time,
         p.dst_ip,
         concat(arrayElement(splitByChar('.', p.prefix24), 1), '.',
                arrayElement(splitByChar('.', p.prefix24), 2), '.',
                arrayElement(splitByChar('.', p.prefix24), 3)) AS prefix_key,
         p.prefix24, l.country, l.region
  FROM {ping} p INNER JOIN latest l ON p.dst_ip = l.ip
  WHERE p.data_center = '{dc}'
    AND p.measure_time >= toDateTime64('{lo}', 6, 'UTC')
    AND p.measure_time < toDateTime64('{hi}', 6, 'UTC')
    AND p.dst_ip != '' AND p.prefix24 != ''
), eligible AS (
  SELECT prefix24 FROM base GROUP BY prefix24
  HAVING countDistinct(dst_ip) >= {min_ips}
), ips AS (
  SELECT measure_time, country, region, countDistinct(dst_ip) AS IPS
  FROM base GROUP BY measure_time, country, region
), fbs AS (
  SELECT b.measure_time, r.country, r.region, countDistinct(b.prefix24) AS FBS
  FROM (SELECT DISTINCT measure_time, prefix24, prefix_key FROM base) b
  INNER JOIN eligible e USING (prefix24)
  INNER JOIN prefix_region r USING (prefix_key)
  GROUP BY b.measure_time, r.country, r.region
)
SELECT i.measure_time, i.country, i.region, i.IPS, coalesce(f.FBS, 0) AS FBS
FROM ips i LEFT JOIN fbs f USING (measure_time, country, region)
"""


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    start = pd.to_datetime(cfg.study["measurement_start_utc"], utc=True)
    end = pd.to_datetime(cfg.study["end_utc"], utc=True) + pd.Timedelta(microseconds=1)
    frames = []
    with step("Build canonical label-independent IPS/FBS", logger):
        with CHClient(cfg) as ch:
            for month in pd.date_range(start.normalize().replace(day=1), end, freq="MS", tz="UTC"):
                lo, hi = max(month, start), min(month + pd.offsets.MonthBegin(1), end)
                if lo >= hi:
                    continue
                frames.append(ch.query_df(_month_query(cfg, lo, hi)))
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["measure_time", "country", "region", "IPS", "FBS"])
    if raw.empty:
        raise RuntimeError("canonical IPS/FBS query returned no rows")
    from .geo import Admin1Canonicalizer
    canon = Admin1Canonicalizer(cfg.resource_path("admin1_aliases"),
                                cfg.quality["unknown_labels"], cfg.quality["valid_country_aliases"])
    raw["admin1"] = [canon.canonical_admin1(c, r) for c, r in zip(raw.country, raw.region)]
    raw = raw[raw.admin1.isin(canon.valid_ua)].copy()
    raw = raw.groupby(["measure_time", "admin1"], as_index=False)[["IPS", "FBS"]].sum()
    mcfg = cfg.raw.get("macro_signals", {})
    scored = add_rolling_ratios(
        raw,
        days=int(mcfg.get("ips_baseline_days", 7)),
        ips_threshold=float(mcfg.get("ips_outage_ratio", .90)),
        fbs_threshold=float(mcfg.get("fbs_outage_ratio", .95)),
    )
    dd = cfg.out_dir("data_derived"); rt = cfg.out_dir("results_tables")
    fd = cfg.out_dir("results_figure_data"); fd.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(dd / "canonical_ips_fbs_2h.parquet", index=False)
    scored.loc[:, ["measure_time", "admin1", "IPS", "IPS_7d_mean", "IPS_ratio", "ips_outage",
                   "FBS", "FBS_7d_mean", "FBS_ratio", "fbs_outage"]].to_csv(
        rt / "canonical_ips_fbs_2h.csv", index=False, encoding="utf-8-sig")
    scored.to_csv(fd / "fig02_ips_fbs_oblast_time.csv", index=False, encoding="utf-8-sig")
    (fd / "fig02_ips_fbs_oblast_time.meta.json").write_text(
        '{"figure_id":"fig02","research_question":"Canonical regional Internet disruption signals",'
        '"hypothesis":"Macro signal prerequisite for H1-H4","x_axis":"UTC 2-hour cycle",'
        '"y_axis":"Oblast","aggregation":"responsive IPs and active eligible /24 blocks",'
        '"baseline":"strictly prior 7-day mean","sample_definition":"all mapped responsive observations",'
        '"source_table":"canonical_ips_fbs_2h.csv"}', encoding="utf-8")
    scored.loc[:, ["measure_time", "admin1", "IPS", "IPS_7d_mean", "IPS_ratio", "ips_outage"]].to_parquet(
        dd / "canonical_ips_2h.parquet", index=False)
    scored.loc[:, ["measure_time", "admin1", "FBS", "FBS_7d_mean", "FBS_ratio", "fbs_outage"]].to_parquet(
        dd / "canonical_fbs_2h.parquet", index=False)
    _render_figures(scored, cfg.out_dir("results_figures"))
    return {"status": "ok", "outputs": [str(dd / "canonical_ips_2h.parquet"),
            str(dd / "canonical_fbs_2h.parquet"), str(rt / "canonical_ips_fbs_2h.csv"),
            str(fd / "fig02_ips_fbs_oblast_time.csv"),
            str(cfg.out_dir("results_figures") / "fig02_ips_fbs_oblast_time.png"),
            str(cfg.out_dir("results_figures") / "fig02_ips_ratio_heatmap.png")],
            "rows": len(scored), "admin1_n": int(scored.admin1.nunique())}
