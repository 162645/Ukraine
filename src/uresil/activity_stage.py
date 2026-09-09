"""Formal Stage 2: continuous IP Activity on clean complete cycles.

This stage is descriptive only.  It does not use B1, sensitivity labels,
attack outcomes, or any predictive model.  Activity is the raw fraction of
clean complete measurement cycles in which an IP returned a response.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import sqlutil as S
from .baseline_pool import select_baseline_cycles
from .config import Config, file_sha256
from .db import CHClient
from .progress import get_logger, pbar, step

STAGE = "stage02_activity"


def _root(cfg: Config) -> Path:
    root = cfg.run_base / "results" / "stages" / STAGE
    for name in ("tables", "figures", "figure_data", "diagnostics", "report"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def _load_cycles(cfg: Config) -> pd.DataFrame:
    p = cfg.run_base / "results" / "stages" / "stage00_quality" / "tables" / "stage00_cycle_quality.csv"
    if not p.exists():
        raise FileNotFoundError(f"Stage 0 cycle-quality artifact is missing: {p}")
    d = pd.read_csv(p)
    d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True)
    d["cycle_id"] = pd.to_numeric(d["cycle_id"], errors="raise").astype("int64")
    d["is_complete"] = d["is_complete"].astype(bool)
    return d.sort_values("measure_time").reset_index(drop=True)


def _load_targets(cfg: Config) -> tuple[pd.DataFrame, Path]:
    p = cfg.out_dir("data_derived", ensure=False) / "target_ip_universe.parquet"
    if not p.exists():
        raise FileNotFoundError(
            "Stage 2 requires the frozen target_ip_universe.parquet produced by the mapping/audit stage; "
            f"not found at {p}."
        )
    d = pd.read_parquet(p)
    # regional_eligible is the mapped Ukrainian IP population.  This is not a
    # B1 gate; every eligible IP is retained, including low-Activity endpoints.
    d = d[d.get("regional_eligible", 0).astype(bool)].copy()
    d = d[d.get("target_admin1", pd.Series(index=d.index)).notna()].copy()
    d = d.drop_duplicates(["dst_ip", "prefix24"])
    return d, p


def _normal_cycles(cfg: Config, cycles: pd.DataFrame, targets: pd.DataFrame) -> list[int]:
    # Reuse the reviewed event/schedule exclusion logic, but provide Stage 0's
    # frozen complete-cycle table directly.  No outcome or Activity threshold
    # enters this selection.
    return select_baseline_cycles(cfg, cycles, targets)


def _prefix_batches(prefixes: list[str], batch_size: int):
    for i in range(0, len(prefixes), batch_size):
        yield prefixes[i : i + batch_size]


def _query_part(cfg: Config, ch: CHClient, prefixes: list[str], normal_ids: list[int]) -> pd.DataFrame:
    sql = S.render(
        "12_ip_baseline_reach",
        ping=cfg.table("ping"),
        dc=cfg.study["data_center"],
        prefix_in=S.str_list(prefixes),
        normal_cids=S.int_list(normal_ids),
        cycle_seconds=int(float(cfg.study["expected_cycle_interval_hours"]) * 3600),
    )
    return ch.query_df(sql)


def _build_activity(cfg: Config, root: Path, targets: pd.DataFrame, normal_ids: list[int]) -> pd.DataFrame:
    dd = cfg.out_dir("data_derived")
    parts_dir = dd / "stage02_activity_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    prefixes = sorted(targets["prefix24"].dropna().astype(str).unique())
    batch_size = int(cfg.runtime.get("prefix_batch", 500))
    normal_hash = hashlib.sha256(",".join(map(str, normal_ids)).encode()).hexdigest()
    marker = parts_dir / "_normal_cycles.sha256"
    existing = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    expected_parts = math.ceil(len(prefixes) / batch_size)
    cached = existing == normal_hash and len(list(parts_dir.glob("part_*.parquet"))) == expected_parts
    if not cached:
        for p in parts_dir.glob("part_*.parquet"):
            p.unlink()
        logger = get_logger(cfg.out_dir("logs"))
        with step("Build Stage 2 clean-cycle IP Activity", logger):
            with CHClient(cfg) as ch:
                for i, batch in pbar(list(enumerate(_prefix_batches(prefixes, batch_size))), desc="activity prefix batches", unit="batch"):
                    raw = _query_part(cfg, ch, batch, normal_ids)
                    cols = [c for c in ("dst_ip", "prefix24", "target_asn", "target_country", "target_admin1", "target_city", "target_geo_latitude", "target_geo_longitude", "network_stratum") if c in targets]
                    base = targets[targets["prefix24"].astype(str).isin(set(batch))][cols].drop_duplicates(["dst_ip", "prefix24"])
                    if raw.empty:
                        raw = pd.DataFrame(columns=["dst_ip", "prefix24", "x_normal"])
                    raw = raw[[c for c in ("dst_ip", "prefix24", "x_normal") if c in raw]].drop_duplicates(["dst_ip", "prefix24"])
                    out = base.merge(raw, on=["dst_ip", "prefix24"], how="left", validate="one_to_one")
                    out["x_normal"] = pd.to_numeric(out["x_normal"], errors="coerce").fillna(0).astype("int64")
                    out["n_normal"] = int(len(normal_ids))
                    out.to_parquet(parts_dir / f"part_{i:05d}.parquet", index=False, compression="zstd")
        marker.write_text(normal_hash, encoding="utf-8")
    frames = [pd.read_parquet(p) for p in sorted(parts_dir.glob("part_*.parquet"))]
    if not frames:
        return pd.DataFrame(columns=["dst_ip", "prefix24", "target_admin1", "x_normal", "n_normal"])
    d = pd.concat(frames, ignore_index=True).drop_duplicates(["dst_ip", "prefix24"])
    d["activity_raw"] = d["x_normal"].div(d["n_normal"].replace(0, np.nan))
    min_cycles = int(cfg.raw.get("ip_activity", {}).get("min_normal_cycles", cfg.baseline.get("min_exposure_cycles", 24)))
    d["activity_estimable"] = d["n_normal"].ge(min_cycles)
    # Deciles are descriptive population bins, not an admission rule.  Keep
    # both global and within-state bins for later auditing.
    d["activity_decile"] = pd.NA
    ok = d["activity_estimable"] & d["activity_raw"].notna()
    if ok.any():
        d.loc[ok, "activity_decile_global"] = pd.qcut(d.loc[ok, "activity_raw"].rank(method="first"), 10, labels=[f"D{i}" for i in range(1, 11)])
        d.loc[ok, "activity_decile"] = d.loc[ok].groupby(d.loc[ok, "target_admin1"], group_keys=False)["activity_raw"].rank(method="first", pct=True).mul(10).apply(lambda x: f"D{min(10, max(1, math.ceil(x)))}")
    d.to_parquet(root / "tables" / "ip_activity.parquet", index=False, compression="zstd")
    d.to_csv(root / "tables" / "ip_activity.csv", index=False, encoding="utf-8-sig")
    return d


def _write_fig(fig, path: Path, cfg: Config):
    import matplotlib.pyplot as plt
    dpi = int(cfg.figures.get("png_dpi", 600))
    for ext in ("png", "pdf", "svg"):
        fig.savefig(path.with_suffix("." + ext), dpi=dpi if ext == "png" else None, bbox_inches="tight")
    plt.close(fig)


def _figures(cfg: Config, root: Path, d: pd.DataFrame, state_order: list[str]) -> list[str]:
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "svg.fonttype": "none"})
    import matplotlib.ticker as mtick
    out: list[str] = []
    ok = d[d.activity_estimable & d.activity_raw.notna()].copy()
    if ok.empty:
        return out
    figdir, datadir = root / "figures", root / "figure_data"
    # ECDF: continuous Activity is the object of interest; no smoothing.
    x = np.sort(ok.activity_raw.to_numpy(float)); y = np.arange(1, len(x) + 1) / len(x)
    fig, ax = plt.subplots(figsize=(7.16, 3.1)); ax.step(x, y, where="post", color="#245f9e", lw=1.4)
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="IP Activity (clean-cycle response fraction)", ylabel="Cumulative share")
    ax.grid(axis="y", color="#dddddd", lw=.5); ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0)); fig.tight_layout()
    p = figdir / "fig_S2_1_activity_ecdf"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    pd.DataFrame({"activity": x, "cumulative_share": y}).to_csv(datadir / "fig_S2_1_activity_ecdf.csv", index=False)
    # Histogram on a fixed [0,1] scale so states and reruns are comparable.
    fig, ax = plt.subplots(figsize=(7.16, 3.1)); ax.hist(ok.activity_raw, bins=np.linspace(0, 1, 21), color="#4c78a8", edgecolor="white", weights=np.ones(len(ok)) / len(ok))
    ax.set(xlim=(0, 1), xlabel="IP Activity (clean-cycle response fraction)", ylabel="Population share"); ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0)); ax.grid(axis="y", color="#dddddd", lw=.5); fig.tight_layout()
    p = figdir / "fig_S2_2_activity_histogram"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    pd.DataFrame({"bin_left": np.linspace(0, .95, 20), "bin_right": np.linspace(.05, 1, 20), "population_share": np.histogram(ok.activity_raw, bins=np.linspace(0, 1, 21), weights=np.ones(len(ok)) / len(ok))[0]}).to_csv(datadir / "fig_S2_2_activity_histogram.csv", index=False)
    # D1--D10 are global population deciles; keep counts and shares explicit.
    dec = ok["activity_decile_global"].astype(str).value_counts().reindex([f"D{i}" for i in range(1, 11)], fill_value=0)
    fig, ax = plt.subplots(figsize=(7.16, 3.0)); ax.bar(dec.index, dec.to_numpy() / len(ok), color="#4c78a8"); ax.set(xlabel="Global Activity decile", ylabel="Population share"); ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0)); ax.grid(axis="y", color="#dddddd", lw=.5); fig.tight_layout()
    p = figdir / "fig_S2_3_activity_decile_share"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    pd.DataFrame({"activity_decile": dec.index, "ip_n": dec.to_numpy(), "population_share": dec.to_numpy() / len(ok)}).to_csv(datadir / "fig_S2_3_activity_decile_share.csv", index=False)
    # Common 0--1 scale across states; show every mapped state, including low
    # populations, with the IP count in the source table.
    groups = [ok.loc[ok.target_admin1.eq(s), "activity_raw"].to_numpy(float) for s in state_order]
    fig, ax = plt.subplots(figsize=(7.16, 5.4)); ax.boxplot(groups, vert=False, labels=state_order, showfliers=False, patch_artist=True, boxprops={"facecolor": "#b9d4ea", "edgecolor": "#315a7d"}, medianprops={"color": "#111111"}); ax.set(xlim=(0, 1), xlabel="IP Activity (clean-cycle response fraction)", ylabel="Admin1"); ax.grid(axis="x", color="#dddddd", lw=.5); fig.tight_layout()
    p = figdir / "fig_S2_4_activity_by_oblast"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    pd.DataFrame({"admin1": state_order, "activity_values": ["|".join(map(str, g)) for g in groups]}).to_csv(datadir / "fig_S2_4_activity_by_oblast.csv", index=False)
    # Coverage is a separate figure so the boxplot is not mistaken for a
    # fixed-population comparison.
    cov = d.groupby("target_admin1", dropna=False).agg(target_ip_n=("dst_ip", "nunique"), activity_estimable_ip_n=("activity_estimable", "sum")).reindex(state_order).fillna(0).reset_index(); cov["estimable_coverage"] = cov["activity_estimable_ip_n"].div(cov["target_ip_n"].replace(0, np.nan))
    fig, ax = plt.subplots(figsize=(7.16, 4.2)); ax.barh(cov.target_admin1, cov.estimable_coverage, color="#6a9fbf"); ax.set(xlim=(0, 1), xlabel="Activity-estimable coverage", ylabel="Admin1"); ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0)); ax.grid(axis="x", color="#dddddd", lw=.5); fig.tight_layout()
    p = figdir / "fig_S2_5_activity_estimable_coverage"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    cov.to_csv(datadir / "fig_S2_5_activity_estimable_coverage.csv", index=False)
    return out


def _manifest(cfg: Config, root: Path, start: datetime, status: str, outputs: list[str], source: Path, normal_n: int) -> Path:
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "stage_manifest.json":
            files.append({"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": file_sha256(p)})
    payload = {"stage": STAGE, "run_id": cfg.run_id, "git_commit": _git_commit(cfg.root), "config_hash": file_sha256(cfg.config_path), "target_universe": str(source), "target_universe_sha256": file_sha256(source), "normal_cycle_n": normal_n, "output_hashes": files, "start_time": start.isoformat(), "end_time": datetime.now(timezone.utc).isoformat(), "status": status}
    p = root / "stage_manifest.json"; p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"); return p


def run(cfg: Config) -> dict:
    started = datetime.now(timezone.utc); root = _root(cfg)
    cycles, targets_path = _load_cycles(cfg), None
    targets, targets_path = _load_targets(cfg)
    normal = _normal_cycles(cfg, cycles, targets)
    if not normal:
        raise RuntimeError("No clean complete Activity cycles remain after the frozen event exclusions")
    d = _build_activity(cfg, root, targets, normal)
    states = sorted(targets.target_admin1.dropna().astype(str).unique())
    state = d.groupby("target_admin1", dropna=False).agg(target_ip_n=("dst_ip", "nunique"), activity_estimable_ip_n=("activity_estimable", "sum"), mean_activity=("activity_raw", "mean"), median_activity=("activity_raw", "median"), min_activity=("activity_raw", "min"), max_activity=("activity_raw", "max")).reindex(states).reset_index(); state["estimable_coverage"] = state.activity_estimable_ip_n.div(state.target_ip_n.replace(0, np.nan)); state.to_csv(root / "tables" / "activity_summary_by_oblast.csv", index=False, encoding="utf-8-sig")
    ok = d[d.activity_estimable & d.activity_raw.notna()].copy(); dec = ok["activity_decile_global"].astype(str).value_counts().reindex([f"D{i}" for i in range(1, 11)], fill_value=0).rename_axis("activity_decile").reset_index(name="ip_n"); dec["population_share"] = dec.ip_n / max(len(ok), 1); dec.to_csv(root / "tables" / "activity_decile_summary.csv", index=False, encoding="utf-8-sig")
    figs = _figures(cfg, root, d, states)
    report = root / "report" / "STAGE02_REPORT.md"; warnings = []
    low = state[state.estimable_coverage < .95]
    if not low.empty: warnings.append(f"{len(low)} Admin1 have Activity-estimable coverage below 95%; inspect the coverage table")
    status = "WARNING" if warnings else "PASS"
    report.write_text("\n".join([f"# Stage 2 — IP Activity ({status})", "", f"Run ID: `{cfg.run_id}`", "", "## Definition", "", "Activity is the raw response fraction for each mapped Ukrainian IP across clean, complete measurement cycles. The denominator is the number of retained normal cycles; an absent response in a complete cycle contributes zero. Incomplete cycles are excluded, not imputed.", "", f"- Clean complete Activity cycles: **{len(normal):,}**", f"- Regional target IPs: **{targets.dst_ip.nunique():,}**", f"- Activity-estimable IPs: **{int(d.activity_estimable.sum()):,}**", f"- Activity values written: **{len(ok):,}**", "- No B1, sensitivity, outage outcome, D1/D10 admission threshold, or predictive model was used.", "", "## Outputs", "", "- ECDF, histogram, D1–D10 population share, Admin1 boxplot, and Admin1 estimable coverage are emitted as PNG/PDF/SVG with source CSV files.", "- Global D1–D10 are descriptive population bins; within-Admin1 bins are retained in the table for audit only.", "", "## Gate", "", f"**{status}**" + (" — " + "; ".join(warnings) if warnings else ""), "", "The Activity stage is descriptive and supports later confounding control; it does not establish planned-outage causality or attack vulnerability."]), encoding="utf-8")
    manifest = _manifest(cfg, root, started, status, figs, targets_path, len(normal))
    return {"status": "warning" if status == "WARNING" else "ok", "gate": status, "normal_cycle_n": len(normal), "target_ip_n": int(targets.dst_ip.nunique()), "activity_ip_n": int(d.activity_estimable.sum()), "outputs": [str(report), str(manifest), *figs]}
