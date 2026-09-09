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
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root), text=True).strip()
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
    # Deciles are descriptive population bins, not an admission rule.  The
    # formal label is within-Admin1 so that later comparisons do not encode
    # the large baseline differences already visible between states.  Keep a
    # global label only as a legacy audit field; it is never used in figures
    # or downstream inference.
    d["activity_decile"] = pd.NA
    ok = d["activity_estimable"] & d["activity_raw"].notna()
    if ok.any():
        d.loc[ok, "activity_decile_global"] = pd.qcut(
            d.loc[ok, "activity_raw"].rank(method="first"),
            10,
            labels=[f"D{i}" for i in range(1, 11)],
        )
        within_rank = d.loc[ok].groupby("target_admin1", sort=False)["activity_raw"].rank(
            method="first", pct=True
        )
        d.loc[ok, "activity_decile"] = within_rank.mul(10).apply(
            lambda x: f"D{min(10, max(1, math.ceil(x)))}"
        )
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
    import matplotlib.ticker as mtick

    plt.rcParams.update({
        "font.size": 8,
        "axes.labelsize": 8,
        "axes.titlesize": 10,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "svg.fonttype": "none",
    })
    out: list[str] = []
    ok = d[d.activity_estimable & d.activity_raw.notna()].copy()
    if ok.empty:
        return out
    figdir, datadir = root / "figures", root / "figure_data"
    n = len(ok)
    median = float(ok.activity_raw.median())
    q10, q90 = ok.activity_raw.quantile([.10, .90]).to_numpy(float)
    common_note = f"Clean complete cycles: {int(ok.n_normal.iloc[0]):,}; mapped IPs: {n:,}" 

    # S2-1: ECDF.  The title states the supported conclusion; the vertical
    # markers make the spread readable without smoothing the distribution.
    x = np.sort(ok.activity_raw.to_numpy(float)); y = np.arange(1, n + 1) / n
    fig, ax = plt.subplots(figsize=(7.16, 3.55))
    ax.step(x, y, where="post", color="#245f9e", lw=1.5)
    ax.axvline(median, color="#d95f02", ls="--", lw=1, label=f"Median {median:.2f}")
    ax.axvspan(q10, q90, color="#245f9e", alpha=.08, label=f"P10–P90 {q10:.2f}–{q90:.2f}")
    ax.set_title("Normal-period IP Activity is heterogeneous")
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="IP Activity (response fraction)", ylabel="Cumulative share")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0)); ax.grid(axis="y", color="#dddddd", lw=.5)
    ax.legend(frameon=False, loc="lower right", fontsize=7); ax.text(0, -0.24, common_note + "; incomplete cycles excluded", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout()
    p = figdir / "fig_S2_1_activity_ecdf"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    pd.DataFrame({"activity": x, "cumulative_share": y}).to_csv(datadir / "fig_S2_1_activity_ecdf.csv", index=False)

    # S2-2: fixed bins and shared [0,1] scale keep reruns comparable.
    bins = np.linspace(0, 1, 21); counts, _ = np.histogram(ok.activity_raw, bins=bins); shares = counts / n
    fig, ax = plt.subplots(figsize=(7.16, 3.55))
    ax.bar(bins[:-1], shares, width=.048, align="edge", color="#4c78a8", edgecolor="white", linewidth=.4)
    ax.axvline(median, color="#d95f02", ls="--", lw=1)
    ax.set_title("Activity spans the full response-fraction range")
    ax.set(xlim=(0, 1), xlabel="IP Activity (response fraction)", ylabel="Population share")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0)); ax.grid(axis="y", color="#dddddd", lw=.5)
    ax.text(0, -0.24, common_note + "; fixed 0.05-wide bins", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout()
    p = figdir / "fig_S2_2_activity_histogram"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    pd.DataFrame({"bin_left": bins[:-1], "bin_right": bins[1:], "ip_n": counts, "population_share": shares}).to_csv(datadir / "fig_S2_2_activity_histogram.csv", index=False)

    # S2-3: formal within-Admin1 deciles.  The bars are a diagnostic of the
    # construction (roughly 10% per state), not evidence of a treatment effect.
    labels = [f"D{i}" for i in range(1, 11)]
    state_dec = ok.groupby(["target_admin1", "activity_decile"], dropna=False).size().unstack(fill_value=0).reindex(columns=labels, fill_value=0)
    state_share = state_dec.div(state_dec.sum(axis=1).replace(0, np.nan), axis=0)
    dec_mean = state_share.mean(axis=0); dec_min = state_share.min(axis=0); dec_max = state_share.max(axis=0)
    fig, ax = plt.subplots(figsize=(7.16, 3.55))
    ax.bar(labels, dec_mean.to_numpy(), color="#4c78a8", edgecolor="white")
    ax.vlines(np.arange(10), dec_min.to_numpy(), dec_max.to_numpy(), color="#1b3a57", lw=1.2)
    ax.axhline(.1, color="#d95f02", ls="--", lw=1, label="10% target")
    ax.set_title("Within-oblast Activity deciles are balanced")
    ax.set(xlabel="Within-oblast Activity decile (D1 = lowest)", ylabel="Share within oblast")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0)); ax.set_ylim(0, .115); ax.grid(axis="y", color="#dddddd", lw=.5); ax.legend(frameon=False, fontsize=7)
    ax.text(0, -0.24, "Bars: mean share across 25 oblasts; whiskers: min–max; labels are descriptive bins", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout()
    p = figdir / "fig_S2_3_activity_decile_share"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    dec_out = pd.DataFrame({"activity_decile": labels, "mean_within_oblast_share": dec_mean.to_numpy(), "min_within_oblast_share": dec_min.to_numpy(), "max_within_oblast_share": dec_max.to_numpy()})
    dec_out.to_csv(datadir / "fig_S2_3_activity_decile_share.csv", index=False)

    # S2-4: common x scale, states ordered by median so the comparison is
    # immediately legible while preserving the full 0--1 Activity range.
    state_medians = ok.groupby("target_admin1").activity_raw.median().reindex(state_order).sort_values()
    plot_states = state_medians.index.tolist(); groups = [ok.loc[ok.target_admin1.eq(s), "activity_raw"].to_numpy(float) for s in plot_states]
    fig, ax = plt.subplots(figsize=(7.16, 6.0))
    bp = ax.boxplot(groups, vert=False, labels=plot_states, showfliers=False, patch_artist=True, widths=.65, boxprops={"facecolor": "#b9d4ea", "edgecolor": "#315a7d"}, medianprops={"color": "#111111", "lw": 1.2}, whiskerprops={"color": "#315a7d"})
    ax.set_title("Normal-period Activity differs across oblasts")
    ax.set(xlim=(0, 1), xlabel="IP Activity (response fraction)", ylabel="Oblast"); ax.grid(axis="x", color="#dddddd", lw=.5)
    ax.text(0, -0.12, "Common 0–1 scale; boxes show IQR, center line is median; fliers hidden for readability", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout()
    p = figdir / "fig_S2_4_activity_by_oblast"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    pd.DataFrame({"admin1": plot_states, "activity_values": ["|".join(map(str, g)) for g in groups]}).to_csv(datadir / "fig_S2_4_activity_by_oblast.csv", index=False)

    # S2-5: coverage is a data-quality check, not a stability result.
    cov = d.groupby("target_admin1", dropna=False).agg(target_ip_n=("dst_ip", "nunique"), activity_estimable_ip_n=("activity_estimable", "sum")).reindex(state_order).fillna(0).reset_index(); cov["estimable_coverage"] = cov["activity_estimable_ip_n"].div(cov["target_ip_n"].replace(0, np.nan))
    fig, ax = plt.subplots(figsize=(7.16, 4.6))
    ax.barh(cov.target_admin1, cov.estimable_coverage, color="#6a9fbf")
    ax.set_title("All mapped oblasts have estimable Activity")
    ax.set(xlim=(0, 1.08), xlabel="Activity-estimable coverage", ylabel="Oblast"); ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0)); ax.grid(axis="x", color="#dddddd", lw=.5)
    for y0, v in enumerate(cov.estimable_coverage): ax.text(min(float(v) + .01, 1.01), y0, f"{v:.0%}", va="center", fontsize=7)
    ax.text(0, -0.12, "Denominator: mapped regional target IPs; no Activity threshold was applied", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout()
    p = figdir / "fig_S2_5_activity_estimable_coverage"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    cov.to_csv(datadir / "fig_S2_5_activity_estimable_coverage.csv", index=False)

    # S2-6: sample-size diagnostic requested for the within-oblast labels.
    # Counts are shown on a log colour scale because oblast sizes differ by
    # orders of magnitude; the companion CSV retains the exact counts.
    fig, ax = plt.subplots(figsize=(7.16, 6.0))
    from matplotlib.colors import LogNorm
    heat_counts = state_dec.reindex(plot_states)
    positive = heat_counts.to_numpy()[heat_counts.to_numpy() > 0]
    im = ax.imshow(heat_counts.to_numpy(), aspect="auto", cmap="Blues", norm=LogNorm(vmin=max(1, float(positive.min())), vmax=float(positive.max())))
    ax.set_title("Within-oblast decile sample sizes vary with mapped IP population")
    ax.set(xticks=np.arange(10), xticklabels=labels, yticks=np.arange(len(plot_states)), yticklabels=plot_states, xlabel="Within-oblast Activity decile", ylabel="Oblast")
    cbar = fig.colorbar(im, ax=ax, pad=.02, fraction=.03); cbar.set_label("IP count per oblast × decile (log scale)")
    ax.text(0, -0.12, "Diagnostic heatmap; D1–D10 remain within-oblast labels; exact counts are in the source CSV", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout()
    p = figdir / "fig_S2_6_within_oblast_decile_heatmap"; _write_fig(fig, p, cfg); out.extend(str(p.with_suffix("." + e)) for e in ("png", "pdf", "svg"))
    heat = state_dec.reindex(plot_states).copy(); heat.insert(0, "target_admin1", heat.index); heat.reset_index(drop=True).to_csv(datadir / "fig_S2_6_within_oblast_decile_heatmap.csv", index=False)
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
    ok = d[d.activity_estimable & d.activity_raw.notna()].copy()
    labels = [f"D{i}" for i in range(1, 11)]
    state_dec = ok.groupby(["target_admin1", "activity_decile"], dropna=False).size().unstack(fill_value=0).reindex(columns=labels, fill_value=0)
    state_share = state_dec.div(state_dec.sum(axis=1).replace(0, np.nan), axis=0)
    dec = pd.DataFrame({
        "activity_decile": labels,
        "ip_n": state_dec.sum(axis=0).to_numpy(),
        "population_share": state_dec.sum(axis=0).to_numpy() / max(len(ok), 1),
        "mean_within_oblast_share": state_share.mean(axis=0).to_numpy(),
        "min_within_oblast_share": state_share.min(axis=0).to_numpy(),
        "max_within_oblast_share": state_share.max(axis=0).to_numpy(),
    })
    dec.to_csv(root / "tables" / "activity_decile_summary.csv", index=False, encoding="utf-8-sig")
    figs = _figures(cfg, root, d, states)
    report = root / "report" / "STAGE02_REPORT.md"; warnings = []
    low = state[state.estimable_coverage < .95]
    if not low.empty: warnings.append(f"{len(low)} Admin1 have Activity-estimable coverage below 95%; inspect the coverage table")
    status = "WARNING" if warnings else "PASS"
    report.write_text("\n".join([f"# Stage 2 — IP Activity ({status})", "", f"Run ID: `{cfg.run_id}`", "", "## Definition", "", "Activity is the raw response fraction for each mapped Ukrainian IP across clean, complete measurement cycles. The denominator is the number of retained normal cycles; an absent response in a complete cycle contributes zero. Incomplete cycles are excluded, not imputed.", "", f"- Clean complete Activity cycles: **{len(normal):,}**", f"- Regional target IPs: **{targets.dst_ip.nunique():,}**", f"- Activity-estimable IPs: **{int(d.activity_estimable.sum()):,}**", f"- Activity values written: **{len(ok):,}**", "- No B1, sensitivity, outage outcome, D1/D10 admission threshold, or predictive model was used.", "", "## Formal grouping", "", "- Activity labels D1–D10 are assigned **within each Admin1** (D1 = lowest Activity in that oblast). The global decile is retained only as a legacy audit field and is not used in the figures.", "- The decile-share panel and the Oblast × D1–D10 heatmap are construction diagnostics; they do not establish an outage effect.", "", "## Outputs", "", "- ECDF, histogram, within-Admin1 D1–D10 share, Admin1 boxplot, estimable coverage, and the within-Admin1 decile heatmap are emitted as PNG/PDF/SVG with source CSV files.", "", "## Gate", "", f"**{status}**" + (" — " + "; ".join(warnings) if warnings else ""), "", "The Activity stage is descriptive and supports later confounding control; it does not establish planned-outage causality or attack vulnerability."]), encoding="utf-8")
    manifest = _manifest(cfg, root, started, status, figs, targets_path, len(normal))
    return {"status": "warning" if status == "WARNING" else "ok", "gate": status, "normal_cycle_n": len(normal), "target_ip_n": int(targets.dst_ip.nunique()), "activity_ip_n": int(d.activity_estimable.sum()), "outputs": [str(report), str(manifest), *figs]}
