"""Formal Stage 1: canonical regional IPS/FBS signals."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .canonical_signals import add_rolling_ratios
from .config import Config, file_sha256
from .db import CHClient
from .geo import Admin1Canonicalizer
from .progress import get_logger, step

STAGE = "stage01_canonical"
CORE_ATTACKS = ["E2024_0826_ATTACK", "E2024_0917_SUMY", "E2024_1117_ATTACK",
                "E2024_1128_ATTACK", "E2024_1213_ATTACK", "E2024_1225_ATTACK"]


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _root(cfg: Config) -> Path:
    p = cfg.run_base / "results" / "stages" / STAGE
    for name in ("tables", "figures", "figure_data", "diagnostics", "report"):
        (p / name).mkdir(parents=True, exist_ok=True)
    return p


def _save(fig, path: Path, cfg: Config) -> list[str]:
    out = []
    dpi = int(cfg.figures.get("png_dpi", 600))
    for ext in ("png", "pdf", "svg"):
        p = path.with_suffix("." + ext)
        fig.savefig(p, dpi=dpi if ext == "png" else None, bbox_inches="tight")
        out.append(str(p))
    return out


def _meta(root: Path, stem: str, figure_id: str, source: Path, *, x: str, y: str,
          aggregation: str, sample: str, baseline: str, thresholds: dict,
          event_set: str = "none") -> None:
    payload = {"figure_id": figure_id, "stage": STAGE, "source_csv": str(source),
               "x_axis": x, "y_axis": y, "aggregation": aggregation,
               "sample_definition": sample, "baseline_definition": baseline,
               "thresholds": thresholds, "event_set": event_set,
               "missing_policy": "NA is masked; incomplete cycles are not zero",
               "title_in_figure": False}
    (root / "figure_data" / f"{stem}.meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _stage0_cycles(cfg: Config) -> pd.DataFrame:
    p = cfg.run_base / "results" / "stages" / "stage00_quality" / "tables" / "stage00_cycle_quality.csv"
    if not p.exists():
        raise FileNotFoundError(f"Stage-0 cycle-quality artifact is missing: {p}")
    d = pd.read_csv(p)
    d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True)
    d["cycle_complete"] = d["is_complete"].astype(bool)
    return d[["cycle_id", "measure_time", "cycle_complete", "responsive_ip_n"]].sort_values("measure_time")


def _valid_states(cfg: Config, canon: Admin1Canonicalizer) -> list[str]:
    return sorted(str(x) for x in canon.valid_ua if str(x) not in {
        canon.COUNTRY_ONLY_UA, canon.UNKNOWN, canon.UNMAPPED_UA})


def _mapping_cutoff(cfg: Config) -> str:
    try:
        payload = json.loads(cfg.resource_path("mapping_manifest").read_text(encoding="utf-8"))
        return str(payload["freeze"]["snapshot_date"]).replace(" UTC", "")[:19]
    except Exception:
        return ""


def _sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _month_query(cfg: Config, start: pd.Timestamp, end: pd.Timestamp,
                 complete_times: list[pd.Timestamp]) -> str:
    ping, mapping, dc = cfg.table("ping"), cfg.table("mapping"), cfg.study["data_center"]
    lo, hi = start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = _mapping_cutoff(cfg)
    aliases = ",".join(_sql_quote(x) for x in cfg.quality["valid_country_aliases"])
    if not complete_times:
        return "SELECT CAST(NULL AS DateTime) AS measure_time, '' AS country, '' AS region, toInt64(0) AS IPS, toInt64(0) AS FBS WHERE 0"
    times = ",".join(f"toDateTime64('{t.strftime('%Y-%m-%d %H:%M:%S')}', 6, 'UTC')" for t in complete_times)
    return f"""
WITH latest AS (
  SELECT ip, argMax(geo_country, updated_at) AS country, argMax(geo_region, updated_at) AS region
  FROM {mapping} WHERE updated_at <= toDateTime('{cutoff}', 'UTC') GROUP BY ip
), prefix_counts AS (
  SELECT concat(arrayElement(splitByChar('.', ip), 1), '.', arrayElement(splitByChar('.', ip), 2), '.', arrayElement(splitByChar('.', ip), 3)) AS prefix_key,
         country, region, count() AS n
  FROM latest WHERE country IN ({aliases}) GROUP BY prefix_key, country, region
), prefix_modal AS (
  SELECT prefix_key, country, region FROM prefix_counts
  ORDER BY prefix_key, n DESC, country, region LIMIT 1 BY prefix_key
), base AS (
  SELECT toStartOfInterval(p.measure_time, INTERVAL 2 HOUR) AS measure_time,
         p.dst_ip, p.prefix24, l.country AS ip_country, l.region AS ip_region,
         pm.country AS prefix_country, pm.region AS prefix_region
  FROM {ping} p INNER JOIN latest l ON p.dst_ip = l.ip
  LEFT JOIN prefix_modal pm ON pm.prefix_key = concat(arrayElement(splitByChar('.', p.prefix24), 1), '.', arrayElement(splitByChar('.', p.prefix24), 2), '.', arrayElement(splitByChar('.', p.prefix24), 3))
  WHERE p.data_center = {_sql_quote(dc)} AND p.measure_time >= toDateTime64('{lo}', 6, 'UTC')
    AND p.measure_time < toDateTime64('{hi}', 6, 'UTC') AND p.dst_ip != '' AND p.prefix24 != ''
    AND l.country IN ({aliases}) AND toStartOfInterval(p.measure_time, INTERVAL 2 HOUR) IN ({times})
), eligible AS (
  SELECT toStartOfMonth(measure_time) AS month, prefix24 FROM base GROUP BY month, prefix24 HAVING countDistinct(dst_ip) >= 3
), ips AS (
  SELECT measure_time, ip_country, ip_region, countDistinct(dst_ip) AS IPS FROM base GROUP BY measure_time, ip_country, ip_region
), active_blocks AS (
  SELECT DISTINCT measure_time, prefix24, prefix_country, prefix_region FROM base
), fbs AS (
  SELECT a.measure_time, a.prefix_country AS fbs_country, a.prefix_region AS fbs_region, countDistinct(a.prefix24) AS FBS
  FROM active_blocks a INNER JOIN eligible e ON e.month = toStartOfMonth(a.measure_time) AND e.prefix24 = a.prefix24
  WHERE a.prefix_country IN ({aliases}) GROUP BY a.measure_time, a.prefix_country, a.prefix_region
)
SELECT i.measure_time, i.ip_country AS country, i.ip_region AS region, i.IPS, coalesce(f.FBS, 0) AS FBS
FROM ips i LEFT JOIN fbs f ON f.measure_time = i.measure_time
  AND f.fbs_country = i.ip_country AND f.fbs_region = i.ip_region
"""


def _fetch_signals(cfg: Config, cycles: pd.DataFrame, canon: Admin1Canonicalizer) -> pd.DataFrame:
    complete = cycles.loc[cycles.cycle_complete]
    if complete.empty:
        return pd.DataFrame(columns=["measure_time", "admin1", "IPS", "FBS"])
    start = complete.measure_time.min(); end = complete.measure_time.max() + pd.Timedelta(hours=2)
    frames = []
    with CHClient(cfg) as ch:
        for month in pd.date_range(start.normalize().replace(day=1), end, freq="MS", tz="UTC"):
            lo, hi = max(month, start), min(month + pd.offsets.MonthBegin(1), end)
            ts = complete.loc[(complete.measure_time >= lo) & (complete.measure_time < hi), "measure_time"].tolist()
            if ts:
                frames.append(ch.query_df(_month_query(cfg, lo, hi, ts)))
    if not frames:
        return pd.DataFrame(columns=["measure_time", "admin1", "IPS", "FBS"])
    raw = pd.concat(frames, ignore_index=True)
    raw["measure_time"] = pd.to_datetime(raw["measure_time"], utc=True)
    raw["admin1"] = [canon.canonical_admin1(c, r) for c, r in zip(raw["country"], raw["region"])]
    raw = raw[raw.admin1.isin(canon.valid_ua)].copy()
    return raw.groupby(["measure_time", "admin1"], as_index=False)[["IPS", "FBS"]].sum(min_count=1)


def _skeleton(cycles: pd.DataFrame, states: list[str], raw: pd.DataFrame) -> pd.DataFrame:
    full = pd.MultiIndex.from_product([cycles.measure_time.tolist(), states], names=["measure_time", "admin1"]).to_frame(index=False)
    d = full.merge(raw, on=["measure_time", "admin1"], how="left")
    d = d.merge(cycles[["measure_time", "cycle_complete"]], on="measure_time", how="left", validate="many_to_one")
    for c in ("IPS", "FBS"):
        x = pd.to_numeric(d[c], errors="coerce").fillna(0)
        d[c] = x.where(d.cycle_complete, np.nan).astype(float)
    return d.sort_values(["admin1", "measure_time"]).reset_index(drop=True)


def _events(cfg: Config) -> pd.DataFrame:
    return cfg.load_event_registry().query("event_id in @CORE_ATTACKS").copy()


def _split_states(value: object, states: list[str], canon: Admin1Canonicalizer) -> list[str]:
    text = str(value or "")
    if text.strip().upper() == "ALL" or not text.strip():
        return list(states)
    out = []
    for item in text.split("|"):
        state = canon.canonical_admin1("Ukraine", item.strip())
        if state in states and state not in out:
            out.append(state)
    return out


def _core_summaries(scored: pd.DataFrame, events: pd.DataFrame, states: list[str], canon: Admin1Canonicalizer):
    summaries, checks = [], []
    for _, event in events.iterrows():
        affected = _split_states(event.get("analysis_treated_admin1", "ALL"), states, canon)
        anchor = pd.to_datetime(event.primary_anchor_utc, utc=True); lo, hi = anchor - pd.Timedelta(hours=24), anchor + pd.Timedelta(hours=72)
        times = pd.date_range(lo, hi, freq="2h", tz="UTC")
        d = scored[scored.admin1.isin(affected) & scored.measure_time.isin(times)]
        curve = d.groupby("measure_time", as_index=False).agg(ips_ratio=("IPS_ratio", "mean"), fbs_ratio=("FBS_ratio", "mean"))
        curve["ips_outage"] = curve.ips_ratio.lt(.90); curve["fbs_outage"] = curve.fbs_ratio.lt(.95) & curve.ips_ratio.lt(.95)
        coverage = curve.measure_time.nunique() / len(times) if len(times) else np.nan
        ipmin, fbmin = curve.ips_ratio.min(), curve.fbs_ratio.min()
        summaries.append({"event_id": event.event_id, "admin1": "|".join(affected), "event_anchor": anchor,
                          "available_cycle_n": int(curve.measure_time.nunique()), "expected_cycle_n": len(times), "coverage": coverage,
                          "min_ips_ratio": ipmin, "ips_peak_drop": 1 - ipmin if pd.notna(ipmin) else np.nan,
                          "ips_outage_hours": int(curve.ips_outage.sum() * 2), "min_fbs_ratio": fbmin,
                          "fbs_peak_drop": 1 - fbmin if pd.notna(fbmin) else np.nan, "fbs_outage_hours": int(curve.fbs_outage.sum() * 2),
                          "ips_only_anomaly_cycle_n": int((curve.ips_outage & ~curve.fbs_outage).sum())})
        state = d.assign(ips_drop=d.IPS_ratio.lt(.90), fbs_drop=d.FBS_ratio.lt(.95) & d.IPS_ratio.lt(.95)).groupby("admin1").agg(ips_drop=("ips_drop", "any"), fbs_drop=("fbs_drop", "any"))
        checks.append({"event_id": event.event_id, "affected_state_n": len(affected), "states_with_ips_drop_n": int(state.ips_drop.sum()) if not state.empty else 0,
                       "states_with_fbs_drop_n": int(state.fbs_drop.sum()) if not state.empty else 0,
                       "states_with_ips_only_drop_n": int((state.ips_drop & ~state.fbs_drop).sum()) if not state.empty else 0,
                       "event_equal_min_ips_ratio": ipmin, "event_equal_peak_ips_drop": 1 - ipmin if pd.notna(ipmin) else np.nan,
                       "event_equal_min_fbs_ratio": fbmin, "event_equal_peak_fbs_drop": 1 - fbmin if pd.notna(fbmin) else np.nan,
                       "attack_window_complete_fraction": coverage})
    return pd.DataFrame(summaries), pd.DataFrame(checks)


def _low_response_diagnosis(scored: pd.DataFrame, cycles: pd.DataFrame, states: list[str]) -> pd.DataFrame:
    rows = []
    for t in cycles[cycles.cycle_complete].nsmallest(20, "responsive_ip_n").measure_time:
        d = scored[scored.measure_time.eq(t)]; valid = d.IPS_ratio.notna(); below90 = int((d.IPS_ratio.lt(.90) & valid).sum()); below80 = int((d.IPS_ratio.lt(.80) & valid).sum()); n = int(valid.sum())
        if n < max(1, int(.75 * len(states))): pattern = "INSUFFICIENT_BASELINE"
        elif below90 >= max(1, int(.75 * len(states))): pattern = "NATIONAL_SYNCHRONOUS"
        elif below90 <= max(1, int(.40 * len(states))): pattern = "REGIONAL_CONCENTRATED"
        else: pattern = "MULTI_REGION"
        rows.append({"measure_time": t, "national_responsive_ip_n": int(cycles.loc[cycles.measure_time.eq(t), "responsive_ip_n"].iloc[0]), "affected_admin1_n": below90,
                     "median_admin1_ips_ratio": d.IPS_ratio.median(), "min_admin1_ips_ratio": d.IPS_ratio.min(), "admin1_below_090_n": below90,
                     "admin1_below_080_n": below80, "fbs_decline_admin1_n": int((d.fbs_outage & d.FBS_ratio.notna()).sum()), "pattern": pattern,
                     "baseline_supported_admin1_n": n})
    return pd.DataFrame(rows)


def _power_calendar(cfg: Config, scored: pd.DataFrame, states: list[str], events: pd.DataFrame) -> pd.DataFrame:
    days = pd.date_range(scored.measure_time.min().floor("D"), scored.measure_time.max().floor("D"), freq="D", tz="UTC")
    x = scored.copy(); x["date"] = x.measure_time.dt.floor("D")
    ips = x[x.IPS_ratio.notna()].groupby(["date", "admin1"], as_index=False).agg(hours=("ips_outage", lambda z: float(z.sum() * 2)))
    fbs = x[x.FBS_ratio.notna()].groupby(["date", "admin1"], as_index=False).agg(hours=("fbs_outage", lambda z: float(z.sum() * 2)))
    ips_d = ips.groupby("date").hours.agg(["mean", "count"]).rename(columns={"mean": "ips_outage_hours", "count": "ips_admin1_n"})
    fbs_d = fbs.groupby("date").hours.agg(["mean", "count"]).rename(columns={"mean": "fbs_outage_hours", "count": "fbs_admin1_n"})
    exposure = cfg.load_exposure_registry(); exposure = exposure[exposure.exposure_type.astype(str).str.contains("scheduled", case=False, na=False)]
    canon = Admin1Canonicalizer(cfg.resource_path("admin1_aliases"), cfg.quality["unknown_labels"], cfg.quality["valid_country_aliases"])
    rows = []
    for day in days:
        state_hours = {}
        for _, r in exposure.iterrows():
            a = pd.to_datetime(r.start_utc, utc=True, errors="coerce"); b = pd.to_datetime(r.end_utc, utc=True, errors="coerce")
            if pd.isna(a) or pd.isna(b) or b <= day or a >= day + pd.Timedelta(days=1): continue
            for state in _split_states(r.get("affected_admin1", "ALL"), states, canon):
                state_hours.setdefault(state, []).append((max(a, day), min(b, day + pd.Timedelta(days=1))))
        vals = []
        for intervals in state_hours.values():
            intervals.sort(); total = 0.; end = None
            for a, b in intervals:
                if end is None or a > end: total += (b - a).total_seconds() / 3600; end = b
                elif b > end: total += (b - end).total_seconds() / 3600; end = b
            vals.append(total)
        rows.append({"date": day, "power_outage_hours": np.mean(vals) if vals else np.nan, "power_admin1_n": len(vals),
                     "ips_outage_hours": ips_d.loc[day, "ips_outage_hours"] if day in ips_d.index else np.nan,
                     "ips_admin1_n": int(ips_d.loc[day, "ips_admin1_n"]) if day in ips_d.index else 0,
                     "fbs_outage_hours": fbs_d.loc[day, "fbs_outage_hours"] if day in fbs_d.index else np.nan,
                     "fbs_admin1_n": int(fbs_d.loc[day, "fbs_admin1_n"]) if day in fbs_d.index else 0})
    out = pd.DataFrame(rows); out["month"] = out.date.dt.strftime("%Y-%m"); out["day"] = out.date.dt.day
    marks = {}
    for _, e in events.iterrows():
        day = pd.to_datetime(e.primary_anchor_utc, utc=True).floor("D"); marks[day] = marks.get(day, []) + [str(e.event_id)]
    out["attack_event_ids"] = out.date.map(lambda x: "|".join(marks.get(x, [])))
    return out


def _render_figures(cfg: Config, root: Path, scored: pd.DataFrame, states: list[str], events: pd.DataFrame, calendar: pd.DataFrame) -> list[str]:
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    from matplotlib.patches import Rectangle
    plt.rcParams.update({"font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "svg.fonttype": "none"})
    times = sorted(pd.to_datetime(scored.measure_time.unique(), utc=True)); anchors = [pd.to_datetime(x, utc=True) for x in events.primary_anchor_utc]
    def marks(ax):
        for t in anchors:
            i = int(np.argmin([abs((x - t).total_seconds()) for x in times])); ax.axvline(i, color="#111", lw=.5, ls=(0, (2, 2))); ax.plot(i, 1.01, marker="v", ms=3, color="#111", transform=ax.get_xaxis_transform(), clip_on=False)
    def arr(col): return scored.pivot(index="admin1", columns="measure_time", values=col).reindex(index=states, columns=times).to_numpy(dtype=float)
    outs = []
    def heat(col, stem, fid, label, vmin=.4, vmax=1.2):
        src = root / "figure_data" / f"{stem}.csv"; scored[["measure_time", "admin1", "cycle_complete", col, f"{col.split('_')[0]}_7d_mean", f"{col.split('_')[0]}_baseline_cycle_n"]].to_csv(src, index=False, encoding="utf-8-sig")
        fig, ax = plt.subplots(figsize=(7.16, 3.9)); cm = plt.get_cmap("RdYlGn").copy(); cm.set_bad("#d9d9d9"); im = ax.imshow(np.ma.masked_invalid(arr(col)), aspect="auto", cmap=cm, norm=TwoSlopeNorm(vmin=vmin, vcenter=1, vmax=vmax), interpolation="none"); ax.set_yticks(range(len(states)), states); ax.set_ylabel("Oblast"); xt = np.linspace(0, len(times)-1, min(8, len(times)), dtype=int); ax.set_xticks(xt, [pd.Timestamp(times[i]).strftime("%Y-%m") for i in xt], rotation=35, ha="right"); ax.set_xlabel("UTC date / time"); marks(ax); fig.colorbar(im, ax=ax, label=label); fig.tight_layout(); outs.extend(_save(fig, root / "figures" / stem, cfg)); plt.close(fig)
        _meta(root, stem, fid, src, x="UTC date / time", y="Oblast", aggregation="one cell per 2h state-cycle", sample="all valid Ukraine Admin1; no Activity/B1 restriction", baseline="preceding 7-day complete-cycle mean; current cycle excluded", thresholds={"baseline_min_fraction": .75, "min_history_cycles": 63}, event_set="six fixed core attacks")
    heat("IPS_ratio", "fig_S1_1_ips_oblast_time", "S1-1", "IPS / preceding 7-day mean")
    heat("FBS_ratio", "fig_S1_2_fbs_oblast_time", "S1-2", "FBS / preceding 7-day mean", .5, 1.2)
    src = root / "figure_data" / "fig_S1_3_ips_fbs_binary.csv"; scored[["measure_time", "admin1", "cycle_complete", "ips_outage", "fbs_outage", "IPS_ratio", "FBS_ratio"]].to_csv(src, index=False, encoding="utf-8-sig")
    fig, axes = plt.subplots(2, 1, figsize=(7.16, 5.8), sharex=True, sharey=True)
    for ax, col, label in zip(axes, ["ips_outage", "fbs_outage"], ["IPS outage", "FBS outage"]):
        cm = plt.get_cmap("Greys").copy(); cm.set_bad("#d9d9d9"); im = ax.imshow(np.ma.masked_invalid(arr(col).astype(float)), aspect="auto", cmap=cm, vmin=0, vmax=1, interpolation="none"); ax.set_yticks(range(len(states)), states); ax.set_ylabel("Oblast"); ax.text(-.08, .5, label, transform=ax.transAxes, rotation=90, va="center", ha="right"); marks(ax)
    xt = np.linspace(0, len(times)-1, min(8, len(times)), dtype=int); axes[-1].set_xticks(xt, [pd.Timestamp(times[i]).strftime("%Y-%m") for i in xt], rotation=35, ha="right"); axes[-1].set_xlabel("UTC date / time"); fig.tight_layout(); outs.extend(_save(fig, root / "figures" / "fig_S1_3_ips_fbs_binary", cfg)); plt.close(fig)
    _meta(root, "fig_S1_3_ips_fbs_binary", "S1-3", src, x="UTC date / time", y="Oblast", aggregation="binary state-cycle flags", sample="all valid Ukraine Admin1", baseline="preceding 7-day mean", thresholds={"IPS": .90, "FBS": .95, "joint_IPS": .95}, event_set="six fixed core attacks")
    e = events[events.event_id.eq("E2024_0826_ATTACK")].iloc[0]; anchor = pd.to_datetime(e.primary_anchor_utc, utc=True); d = scored[(scored.measure_time >= anchor-pd.Timedelta(hours=24)) & (scored.measure_time <= anchor+pd.Timedelta(hours=72))].copy(); d["relative_h"] = (d.measure_time-anchor).dt.total_seconds()/3600; curve = d.groupby("relative_h", as_index=False).agg(IPS_ratio=("IPS_ratio", "mean"), FBS_ratio=("FBS_ratio", "mean"), n_admin1_ips=("IPS_ratio", "count"), n_admin1_fbs=("FBS_ratio", "count")); curve.insert(0, "event_id", e.event_id); src = root / "figure_data" / "fig_S1_4_0826_signal_curve.csv"; curve.to_csv(src, index=False, encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(7.16, 3.2)); ax.plot(curve.relative_h, curve.IPS_ratio, color="#c62828", lw=1.2, label="Overall IPS ratio"); ax.plot(curve.relative_h, curve.FBS_ratio, color="#2e7d32", lw=1.2, label="Overall FBS ratio"); ax.axhline(1, color="#555", lw=.7); ax.axhline(.90, color="#c62828", ls=":", lw=.7, label="IPS threshold 0.90"); ax.axhline(.95, color="#2e7d32", ls=":", lw=.7, label="FBS threshold 0.95"); ax.axvline(0, color="#111", ls="--", lw=.7); ax.set_xlim(-24,72); ax.set_xlabel("Hours relative to registered attack anchor"); ax.set_ylabel("Signal ratio"); ax.legend(frameon=False, ncol=2, fontsize=7); fig.tight_layout(); outs.extend(_save(fig, root / "figures" / "fig_S1_4_0826_signal_curve", cfg)); plt.close(fig); _meta(root, "fig_S1_4_0826_signal_curve", "S1-4", src, x="hours relative to registered attack anchor", y="signal ratio", aggregation="equal mean of Admin1 ratios", sample="affected Admin1 for E2024_0826_ATTACK", baseline="preceding 7-day mean", thresholds={"IPS": .90, "FBS": .95}, event_set="E2024_0826_ATTACK")
    src = root / "figure_data" / "fig_S1_5_power_internet_calendar.csv"; calendar.to_csv(src, index=False, encoding="utf-8-sig"); months = sorted(calendar.month.unique()); days = list(range(1, 32)); fig, axes = plt.subplots(3, 1, figsize=(7.16, 5.5), sharex=True, sharey=True)
    for ax, col, label, cmap_name in zip(axes, ["power_outage_hours", "ips_outage_hours", "fbs_outage_hours"], ["Planned power outage hours", "IPS outage hours", "FBS outage hours"], ["Oranges", "Reds", "Purples"]):
        piv = calendar.pivot(index="month", columns="day", values=col).reindex(index=months, columns=days); cm = plt.get_cmap(cmap_name).copy(); cm.set_bad("#d9d9d9"); ax.imshow(np.ma.masked_invalid(piv.to_numpy(dtype=float)), aspect="auto", cmap=cm, interpolation="none"); ax.set_ylabel("Month"); ax.text(-.08, .5, label, transform=ax.transAxes, rotation=90, va="center", ha="right")
        for yi, m in enumerate(months):
            for xi, day in enumerate(days):
                cell = calendar[(calendar.month.eq(m)) & (calendar.day.eq(day))]
                if not cell.empty and str(cell.iloc[0].attack_event_ids): ax.add_patch(Rectangle((xi-.5, yi-.5), 1, 1, fill=False, edgecolor="#111", lw=.8))
    axes[-1].set_xlabel("Day of month"); axes[-1].set_xticks(range(31), days); fig.tight_layout(); outs.extend(_save(fig, root / "figures" / "fig_S1_5_power_internet_calendar", cfg)); plt.close(fig); _meta(root, "fig_S1_5_power_internet_calendar", "S1-5", src, x="day of month", y="month", aggregation="equal-average hours across Admin1 with evidence", sample="registered scheduled intervals and estimable Internet ratios", baseline="Internet preceding 7-day mean; power direct interval union", thresholds={"IPS": .90, "FBS": .95}, event_set="six fixed core attacks")
    return outs


def _manifest(cfg: Config, root: Path, start: datetime, end: datetime, status: str) -> Path:
    files = [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": file_sha256(p)} for p in sorted(root.rglob("*")) if p.is_file() and p.name != "stage_manifest.json"]
    payload = {"stage": STAGE, "run_id": cfg.run_id, "git_commit": _git_commit(cfg.root), "config_hash": file_sha256(cfg.config_path), "event_registry_hash": file_sha256(cfg.resource_path("event_registry")), "input_hashes": {str(cfg.config_path): file_sha256(cfg.config_path), str(cfg.resource_path("event_registry")): file_sha256(cfg.resource_path("event_registry"))}, "output_hashes": files, "start_time": start.isoformat(), "end_time": end.isoformat(), "elapsed_seconds": (end-start).total_seconds(), "status": status}
    p = root / "stage_manifest.json"; p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); return p


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs")); started = datetime.now(timezone.utc); root = _root(cfg)
    with step("Stage 1: canonical IPS/FBS", logger):
        cycles = _stage0_cycles(cfg); canon = Admin1Canonicalizer(cfg.resource_path("admin1_aliases"), cfg.quality["unknown_labels"], cfg.quality["valid_country_aliases"]); states = _valid_states(cfg, canon)
        raw = _fetch_signals(cfg, cycles, canon); scored = _skeleton(cycles, states, raw); mcfg = cfg.raw.get("macro_signals", {})
        scored = add_rolling_ratios(scored, days=7, cycle_hours=2, ips_threshold=float(mcfg.get("ips_outage_ratio", .90)), fbs_threshold=float(mcfg.get("fbs_outage_ratio", .95)), baseline_min_fraction=float(mcfg.get("baseline_min_fraction", .75)))
        scored = scored.sort_values(["measure_time", "admin1"]).reset_index(drop=True); scored.loc[~scored.cycle_complete, ["IPS", "FBS", "IPS_7d_mean", "IPS_ratio", "FBS_7d_mean", "FBS_ratio", "ips_outage", "fbs_outage"]] = np.nan
        events = _events(cfg); calendar = _power_calendar(cfg, scored, states, events); core, checks = _core_summaries(scored, events, states, canon); low = _low_response_diagnosis(scored, cycles, states)
        summary = scored.groupby("admin1", as_index=False).agg(complete_cycle_n=("cycle_complete", "sum"), ips_estimable_cycle_n=("IPS_ratio", "count"), fbs_estimable_cycle_n=("FBS_ratio", "count"), mean_ips=("IPS", "mean"), median_ips=("IPS", "median"), min_ips_ratio=("IPS_ratio", "min"), ips_outage_cycle_n=("ips_outage", "sum"), min_fbs_ratio=("FBS_ratio", "min"), fbs_outage_cycle_n=("fbs_outage", "sum")); summary["ips_outage_hours"] = summary.ips_outage_cycle_n * 2; summary["fbs_outage_hours"] = summary.fbs_outage_cycle_n * 2
        cols = ["measure_time", "admin1", "IPS", "IPS_7d_mean", "IPS_ratio", "ips_baseline_cycle_n", "ips_outage", "FBS", "FBS_7d_mean", "FBS_ratio", "fbs_baseline_cycle_n", "fbs_outage", "cycle_complete"]
        scored[cols].to_csv(root / "tables" / "canonical_ips_fbs_2h.csv", index=False, encoding="utf-8-sig"); scored[cols].to_parquet(root / "tables" / "canonical_ips_fbs_2h.parquet", index=False); summary.to_csv(root / "tables" / "canonical_summary_by_oblast.csv", index=False, encoding="utf-8-sig"); core.to_csv(root / "tables" / "core_attack_macro_summary.csv", index=False, encoding="utf-8-sig"); low.to_csv(root / "diagnostics" / "low_response_cycle_spatial_diagnosis.csv", index=False, encoding="utf-8-sig"); checks.to_csv(root / "diagnostics" / "core_attack_macro_check.csv", index=False, encoding="utf-8-sig")
        figures = _render_figures(cfg, root, scored, states, events, calendar)
    warnings = []
    if len(scored) != len(cycles) * len(states): warnings.append("complete-cycle × valid-Admin1 skeleton is incomplete")
    if checks.empty or (checks.attack_window_complete_fraction < .75).any(): warnings.append("at least one core attack window has coverage below 75%")
    if not low.empty and (low.pattern == "NATIONAL_SYNCHRONOUS").any(): warnings.append("some low-response complete cycles are nationally synchronous; inspect diagnostic")
    status = "WARNING" if warnings else "PASS"; report = root / "report" / "STAGE01_REPORT.md"; n_ips = int(scored.IPS_ratio.notna().sum()); n_fbs = int(scored.FBS_ratio.notna().sum())
    report.write_text("\n".join([f"# Stage 1 — Canonical IPS/FBS ({status})", "", f"Run ID: `{cfg.run_id}`", f"Git commit: `{_git_commit(cfg.root)}`", "", "## Fixed contract", "", f"- Complete-cycle × valid-Admin1 rows: **{len(scored):,}** ({len(cycles):,} cycles × {len(states)} states)", f"- Complete cycles: **{int(cycles.cycle_complete.sum()):,}**; incomplete cycles retained as NA: **{int((~cycles.cycle_complete).sum()):,}**", f"- IPS estimable state-cycles: **{n_ips:,}**; FBS estimable state-cycles: **{n_fbs:,}**", "- Baseline: preceding 7-day complete cycles, current cycle excluded, minimum 63 historical cycles.", "- FBS eligibility: monthly distinct responsive IP count ≥ 3 per /24; no 256-address denominator is used.", "", "## Scientific answers", "", f"1. Canonical IPS outage state-cycles: **{int(scored.ips_outage.sum()):,}**.", f"2. Canonical FBS outage state-cycles: **{int(scored.fbs_outage.sum()):,}**.", f"3. IPS-only state-cycles: **{int((scored.ips_outage & ~scored.fbs_outage).sum()):,}**.", f"4. Core attacks with event-equal IPS peak drop >10%: **{int((core.ips_peak_drop > .10).sum()) if not core.empty else 0}/{len(core)}**.", "5. Low-response complete cycles are classified in the spatial diagnostic; no cycle is deleted by response volume.", "6. Weak attack signals are scientific findings, not gate failures.", "7. The canonical prerequisite supports human review before Activity.", "", "## Gate", "", f"**{status}**" + (" — " + "; ".join(warnings) if warnings else ""), "", "Visual review status: `rendered_not_visually_reviewed` until the five figure families are opened at final paper size."]) + "\n", encoding="utf-8")
    ended = datetime.now(timezone.utc); manifest = _manifest(cfg, root, started, ended, status); outputs = [str(report), str(manifest)] + [str(x) for x in figures]
    return {"status": "warning" if status == "WARNING" else "ok", "gate": status, "outputs": outputs, "rows": len(scored), "admin1_n": len(states), "ips_estimable_rows": n_ips, "fbs_estimable_rows": n_fbs, "report": str(report), "elapsed_seconds": (ended-started).total_seconds()}
