"""Formal Stage 3: calibration-event quality and independent episode audit.

This stage reads only the frozen calibration workbook.  It does not query
ClickHouse and does not calculate endpoint sensitivity.  Its purpose is to
make the weak-supervision support visible before Stage 4 is allowed to run.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, file_sha256

STAGE = "stage03_calibration_events"
LABELS = ["A+", "A", "B+", "B", "proxy", "unrated"]


def _root(cfg: Config) -> Path:
    root = cfg.run_base / "results" / "stages" / STAGE
    for name in ("tables", "figures", "figure_data", "diagnostics", "report"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(root), text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _selected_events(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    raw_events, raw_segments = cfg.load_final_calibration_input()
    raw_event_n = int(
        raw_events[raw_events.measurement_start_ok.eq(1) &
                   ((raw_events.use_main.eq(1) | raw_events.use_augmented.eq(1)))].event_id.nunique()
    )
    from .simple_calibration import build_final_calibration_events

    events, segments = build_final_calibration_events(cfg)
    if events.empty:
        raise RuntimeError("No frozen P1/P2 calibration events remain after measurement-boundary filtering")
    events["event_date"] = events["event_date"].astype(str)
    events["start_utc"] = pd.to_datetime(events["start_utc"], utc=True)
    events["end_utc"] = pd.to_datetime(events["end_utc"], utc=True)
    events["month"] = events["start_utc"].dt.strftime("%Y-%m")
    events["quality"] = events.get("quality", "").fillna("").astype(str).str.strip().replace({"": "unrated"})
    events["evidence_tier"] = events.get("evidence_tier", "").fillna("").astype(str).str.strip().replace({"": "unrated"})
    return events.sort_values(["event_date", "geo_name"]).reset_index(drop=True), segments, raw_event_n


def _episode_table(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for panel, flag, col in (("primary", "use_main", "episode_id_main"),
                             ("augmented", "use_augmented", "episode_id_augmented")):
        if flag not in events:
            continue
        x = events[events[flag].eq(1)].copy()
        x["episode_id"] = x[col].fillna("").astype(str).str.strip()
        x = x[x.episode_id.ne("")]
        if x.empty:
            continue
        rows.append(x[["geo_name", "episode_id", "event_id", "event_date", "month", "quality", "evidence_tier"]].assign(panel=panel))
    if not rows:
        return pd.DataFrame(columns=["geo_name", "episode_id", "event_id", "event_date", "month", "quality", "evidence_tier", "panel"])
    return pd.concat(rows, ignore_index=True).drop_duplicates(["panel", "geo_name", "episode_id", "event_id"])


def _save_figure(fig, path: Path, cfg: Config) -> list[str]:
    import matplotlib.pyplot as plt

    dpi = int(cfg.figures.get("png_dpi", 600))
    out = []
    for ext in ("png", "pdf", "svg"):
        p = path.with_suffix("." + ext)
        fig.savefig(p, dpi=dpi if ext == "png" else None, bbox_inches="tight")
        out.append(str(p))
    plt.close(fig)
    return out


def _figures(cfg: Config, root: Path, events: pd.DataFrame, episodes: pd.DataFrame) -> list[str]:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mtick

    plt.rcParams.update({"font.size": 8, "axes.titlesize": 10, "axes.labelsize": 8,
                         "xtick.labelsize": 7, "ytick.labelsize": 7, "svg.fonttype": "none"})
    figdir, datadir = root / "figures", root / "figure_data"
    outputs: list[str] = []
    states = sorted(events.geo_name.astype(str).unique())
    state_order = events.geo_name.value_counts().reindex(states).sort_values().index.tolist()
    colors = {"A+": "#1b9e77", "A": "#377eb8", "B+": "#666666", "B": "#999999", "proxy": "#e66101", "unrated": "#bdbdbd"}

    # S3-1: each point is one frozen event; it is not a time-series outcome.
    fig, ax = plt.subplots(figsize=(7.16, 5.6))
    ypos = {s: i for i, s in enumerate(state_order)}
    for quality, g in events.groupby("quality", sort=False):
        ax.scatter(g.start_utc, [ypos[s] for s in g.geo_name], s=22, alpha=.85,
                   color=colors.get(quality, "#555555"), label=quality, edgecolor="white", linewidth=.3)
    ax.set_title("Frozen calibration events are concentrated in a limited time window")
    ax.set(xlabel="Event start (UTC)", ylabel="Oblast", yticks=np.arange(len(state_order)), yticklabels=state_order)
    ax.grid(axis="x", color="#dddddd", lw=.5); ax.legend(frameon=False, title="Quality", fontsize=7)
    ax.text(0, -0.12, "Each point is one reviewed state-date event; proximity does not imply independence", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout(); outputs.extend(_save_figure(fig, figdir / "fig_S3_1_calibration_event_timeline", cfg))
    events[["event_id", "geo_name", "event_date", "start_utc", "end_utc", "quality", "evidence_tier", "episode_id_main", "episode_id_augmented"]].to_csv(datadir / "fig_S3_1_calibration_event_timeline.csv", index=False)

    # S3-2: formal primary episode support with the pre-specified >=3 line.
    ep_main = episodes[episodes.panel.eq("primary")]
    counts = ep_main.groupby("geo_name").episode_id.nunique().reindex(state_order).fillna(0)
    fig, ax = plt.subplots(figsize=(7.16, 5.6))
    ax.barh(counts.index, counts.to_numpy(), color="#4c78a8")
    ax.axvline(3, color="#d95f02", ls="--", lw=1.2, label="3 independent episodes")
    ax.set_title("Primary calibration support varies by oblast")
    ax.set(xlabel="Independent primary episodes", ylabel="Oblast"); ax.grid(axis="x", color="#dddddd", lw=.5); ax.legend(frameon=False, fontsize=7)
    for y, v in enumerate(counts.to_numpy()): ax.text(float(v) + .08, y, f"{int(v)}", va="center", fontsize=7)
    ax.text(0, -0.12, "The reference line is a support diagnostic, not an IP-admission rule", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout(); outputs.extend(_save_figure(fig, figdir / "fig_S3_2_independent_episodes_by_oblast", cfg))
    pd.DataFrame({"geo_name": counts.index, "primary_episode_n": counts.to_numpy(), "meets_ge3": counts.to_numpy() >= 3}).to_csv(datadir / "fig_S3_2_independent_episodes_by_oblast.csv", index=False)

    # S3-3: month x oblast matrix of primary independent episodes.
    months = sorted(events.month.unique())
    matrix = ep_main.groupby(["month", "geo_name"]).episode_id.nunique().unstack(fill_value=0).reindex(index=months, columns=state_order, fill_value=0)
    fig, ax = plt.subplots(figsize=(7.16, 5.6))
    im = ax.imshow(matrix.to_numpy(), aspect="auto", cmap="Blues", vmin=0, vmax=max(1, int(matrix.to_numpy().max())))
    ax.set_title("Calibration coverage is uneven across months and oblasts")
    ax.set(xticks=np.arange(len(state_order)), xticklabels=state_order, yticks=np.arange(len(months)), yticklabels=months, xlabel="Oblast", ylabel="Event month (UTC)")
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right")
    cbar = fig.colorbar(im, ax=ax, pad=.02, fraction=.03); cbar.set_label("Independent primary episodes")
    ax.text(0, -0.20, "Cells count distinct primary episode IDs observed in that month; blank/zero means no registered support", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout(); outputs.extend(_save_figure(fig, figdir / "fig_S3_3_calibration_coverage_matrix", cfg))
    matrix.reset_index().to_csv(datadir / "fig_S3_3_calibration_coverage_matrix.csv", index=False)

    # S3-4: evidence and quality distributions, kept separate from support.
    q = events.quality.value_counts().reindex(LABELS, fill_value=0)
    e = events.evidence_tier.value_counts().sort_values(ascending=True)
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 3.25), gridspec_kw={"width_ratios": [1, 1.35]})
    axes[0].bar(q.index, q.to_numpy(), color=[colors.get(x, "#555555") for x in q.index]); axes[0].set_title("Quality tier"); axes[0].set_ylabel("Event count"); axes[0].grid(axis="y", color="#dddddd", lw=.5)
    axes[1].barh(e.index, e.to_numpy(), color="#6a9fbf"); axes[1].set_title("Evidence tier"); axes[1].set_xlabel("Event count"); axes[1].grid(axis="x", color="#dddddd", lw=.5)
    fig.suptitle("Calibration evidence is summarized separately from episode support", y=1.02, fontsize=10)
    fig.text(.01, -.03, "Counts describe the frozen registry; they do not measure outage effect size", fontsize=7, color="#555555")
    fig.tight_layout(); outputs.extend(_save_figure(fig, figdir / "fig_S3_4_calibration_evidence_distribution", cfg))
    pd.DataFrame({"quality": q.index, "event_n": q.to_numpy()}).to_csv(datadir / "fig_S3_4_quality_distribution.csv", index=False)
    e.rename_axis("evidence_tier").rename("event_n").reset_index().to_csv(datadir / "fig_S3_4_evidence_distribution.csv", index=False)
    return outputs


def _manifest(cfg: Config, root: Path, started: datetime, status: str, outputs: list[str], raw_sources: list[Path]) -> Path:
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "stage_manifest.json":
            files.append({"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": file_sha256(p)})
    payload = {
        "stage": STAGE, "run_id": cfg.run_id, "git_commit": _git_commit(cfg.root),
        "config_hash": file_sha256(cfg.config_path),
        "input_hashes": {str(p): file_sha256(p) for p in raw_sources},
        "output_hashes": files, "start_time": started.isoformat(),
        "end_time": datetime.now(timezone.utc).isoformat(), "status": status,
    }
    path = root / "stage_manifest.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run(cfg: Config) -> dict:
    started = datetime.now(timezone.utc)
    root = _root(cfg)
    events, segments, raw_event_n = _selected_events(cfg)
    episodes = _episode_table(events)
    primary = episodes[episodes.panel.eq("primary")]
    state_order = sorted(events.geo_name.astype(str).unique())
    by_state = pd.DataFrame({"geo_name": state_order})
    by_state["event_n"] = by_state.geo_name.map(events.geo_name.value_counts()).fillna(0).astype(int)
    by_state["primary_episode_n"] = by_state.geo_name.map(primary.groupby("geo_name").episode_id.nunique()).fillna(0).astype(int)
    by_state["augmented_episode_n"] = by_state.geo_name.map(episodes[episodes.panel.eq("augmented")].groupby("geo_name").episode_id.nunique()).fillna(0).astype(int)
    by_state["meets_ge3_primary"] = by_state.primary_episode_n.ge(3)
    by_state.to_csv(root / "tables" / "calibration_episodes_by_oblast.csv", index=False, encoding="utf-8-sig")
    events.to_csv(root / "tables" / "calibration_events.csv", index=False, encoding="utf-8-sig")
    episodes.to_csv(root / "tables" / "calibration_episode_membership.csv", index=False, encoding="utf-8-sig")
    events.assign(month=events.month).groupby("month", as_index=False).agg(event_n=("event_id", "nunique"), oblast_n=("geo_name", "nunique"), primary_episode_n=("episode_id_main", "nunique")).to_csv(root / "tables" / "calibration_monthly_summary.csv", index=False, encoding="utf-8-sig")
    quality = events.quality.value_counts().rename_axis("quality").rename("event_n").reset_index(); evidence = events.evidence_tier.value_counts().rename_axis("evidence_tier").rename("event_n").reset_index(); quality.to_csv(root / "tables" / "calibration_quality_summary.csv", index=False, encoding="utf-8-sig"); evidence.to_csv(root / "tables" / "calibration_evidence_summary.csv", index=False, encoding="utf-8-sig")
    summary = {
        "raw_selected_workbook_event_n": raw_event_n,
        "merged_event_n": int(events.event_id.nunique()),
        "segment_n": int(len(segments)),
        "primary_episode_n": int(primary.episode_id.nunique()),
        "augmented_episode_n": int(episodes[episodes.panel.eq("augmented")].episode_id.nunique()),
        "oblast_n": int(events.geo_name.nunique()),
        "oblast_ge3_primary_n": int(by_state.meets_ge3_primary.sum()),
        "quality_a_plus_n": int(events.quality.eq("A+").sum()),
        "quality_a_n": int(events.quality.eq("A").sum()),
        "proxy_n": int((events.quality.str.lower().eq("proxy") | events.evidence_tier.str.lower().eq("proxy")).sum()),
    }
    (root / "tables" / "calibration_stage_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    figures = _figures(cfg, root, events, episodes)
    below = by_state[~by_state.meets_ge3_primary]
    status = "PASS_WITH_WARNING" if not below.empty else "PASS"
    report_lines = [f"# Stage 3 — Calibration Event Quality ({status})", "", f"Run ID: `{cfg.run_id}`", "", "## Scope", "", "This stage audits the frozen calibration workbook only. It does not query ClickHouse, compute IP sensitivity, or use attack outcomes.", "", f"- Reviewed workbook events selected for measurement: **{raw_event_n:,}**", f"- Merged state-date calibration events: **{summary['merged_event_n']:,}**", f"- Schedule segments retained: **{summary['segment_n']:,}**", f"- Independent primary episodes: **{summary['primary_episode_n']:,}**", f"- Independent augmented episodes: **{summary['augmented_episode_n']:,}**", f"- Oblasts represented: **{summary['oblast_n']:,}**", f"- Oblasts with ≥3 primary episodes: **{summary['oblast_ge3_primary_n']:,} / {summary['oblast_n']:,}**", f"- Quality A+: **{summary['quality_a_plus_n']:,}**; A: **{summary['quality_a_n']:,}**; proxy evidence: **{summary['proxy_n']:,}**", "", "## Interpretation", "", "The ≥3 threshold is reported as a support diagnostic for later sensitivity estimation; it is not applied to IP Activity and no state is silently removed here.", "States below the threshold remain visible in the tables and figures and should receive NA, not a relaxed threshold, in later state-by-decile analyses.", "", "## Gate", "", f"**{status}**", "", "Stage 4 must use the frozen event and episode IDs audited here; this stage does not establish a power-outage effect."]
    report = root / "report" / "STAGE03_REPORT.md"; report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    registry_name = cfg.raw.get("freeze", {}).get("calibration_event_registry", "calibration_event_registry_v1.csv")
    sources = [cfg.config_path, cfg.resource_path("calibration_workbook"), cfg.config_dir / registry_name]
    manifest = _manifest(cfg, root, started, "warning" if status == "PASS_WITH_WARNING" else "ok", [*figures, str(report)], sources)
    return {"status": "warning" if status == "PASS_WITH_WARNING" else "ok", "gate": status, **summary, "outputs": [str(report), str(manifest), *figures]}
