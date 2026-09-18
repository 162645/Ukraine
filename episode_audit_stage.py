"""Formal Stage 3.5: audit independence of frozen calibration episodes.

The reviewed workbook contains episode identifiers, but an identifier is not
evidence of independence by itself.  This stage compares those frozen labels
with a preregistered temporal rule tied to the two-hour measurement cadence:
when two state outage windows are separated by at least one nominal two-hour
cycle, the audit segmentation starts a new episode.  The workbook labels are
never overwritten here and no endpoint sensitivity is calculated.

The 2-hour rule is the formal audit rule.  Six- and twelve-hour variants are
reported only as transparent sensitivity diagnostics; they are not selected
after looking at the resulting counts.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, file_sha256
from .simple_calibration import build_final_calibration_events

STAGE = "stage03_5_episode_audit"
FORMAL_GAP_H = 2.0
AUDIT_GAPS_H = (2.0, 6.0, 12.0)


def _root(cfg: Config) -> Path:
    root = cfg.run_base / "results" / "stages" / STAGE
    for name in ("tables", "figures", "figure_data", "diagnostics", "report"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _slug(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_").upper()


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(root), text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _load_events(cfg: Config) -> pd.DataFrame:
    events, _ = build_final_calibration_events(cfg)
    if events.empty:
        raise RuntimeError("No frozen calibration events available for episode audit")
    for col in ("start_utc", "end_utc"):
        events[col] = pd.to_datetime(events[col], utc=True, errors="coerce")
    events = events[events.start_utc.notna() & events.end_utc.notna()].copy()
    events["event_date"] = events.event_date.astype(str)
    for col in ("episode_id_main", "episode_id_augmented"):
        events[col] = events[col].fillna("").astype(str).str.strip()
    return events.sort_values(["geo_name", "start_utc", "event_id"]).reset_index(drop=True)


def _audit_panel(events: pd.DataFrame, panel: str, flag: str, frozen_col: str,
                 threshold_h: float) -> pd.DataFrame:
    x = events[events[flag].eq(1)].copy()
    if x.empty:
        return pd.DataFrame()
    rows = []
    for geo_name, g in x.groupby("geo_name", sort=True):
        g = g.sort_values(["start_utc", "end_utc", "event_id"]).copy()
        prev_end = g.end_utc.shift(1)
        gap_h = (g.start_utc - prev_end).dt.total_seconds() / 3600.0
        new_episode = prev_end.isna() | gap_h.ge(float(threshold_h))
        seq = new_episode.astype(int).cumsum()
        g["panel"] = panel
        g["prev_end_utc"] = prev_end
        g["gap_hours"] = gap_h
        g["nominal_clean_cycle_n"] = np.floor(gap_h.clip(lower=0) / 2.0).fillna(0).astype(int)
        g["new_audit_episode"] = new_episode.astype(int)
        g["audit_episode_id"] = [
            f"EP_{_slug(geo_name)}_USE_{panel.upper()}_AUDIT_{int(n):02d}" for n in seq
        ]
        g["frozen_episode_id"] = g[frozen_col]
        frozen_key = g["frozen_episode_id"].replace("", np.nan).fillna("__UNASSIGNED__")
        g["frozen_split_from_prev"] = frozen_key.ne(frozen_key.shift(1)).astype(int)
        # Compare partition boundaries, not literal identifier strings: audit
        # IDs intentionally carry a different provenance suffix.
        g["episode_label_changed"] = g["frozen_split_from_prev"].ne(g["new_audit_episode"])
        g["has_nominal_clean_cycle"] = g.nominal_clean_cycle_n.ge(1).astype(int)
        rows.append(g[[
            "panel", "geo_name", "event_id", "event_date", "start_utc", "end_utc",
            "prev_end_utc", "gap_hours", "nominal_clean_cycle_n",
            "has_nominal_clean_cycle", "new_audit_episode", "frozen_episode_id",
            "audit_episode_id", "frozen_split_from_prev", "episode_label_changed",
            "quality", "evidence_tier",
        ]])
    return pd.concat(rows, ignore_index=True)


def _comparison(gap_audit: pd.DataFrame, events: pd.DataFrame, threshold_h: float) -> pd.DataFrame:
    if gap_audit.empty:
        return pd.DataFrame(columns=["geo_name", "panel", "event_n", "frozen_episode_n", "audit_episode_n", "episode_n_delta", "changed_event_n", "meets_ge3_audit"])
    counts = gap_audit.groupby(["panel", "geo_name"], as_index=False).agg(
        event_n=("event_id", "nunique"),
        frozen_episode_n=("frozen_episode_id", lambda s: s.replace("", np.nan).nunique()),
        audit_episode_n=("audit_episode_id", "nunique"),
        changed_event_n=("episode_label_changed", "sum"),
        nominal_clean_gap_n=("has_nominal_clean_cycle", "sum"),
    )
    counts["episode_n_delta"] = counts.audit_episode_n - counts.frozen_episode_n
    counts["gap_threshold_h"] = float(threshold_h)
    counts["meets_ge3_audit"] = counts.audit_episode_n.ge(3)
    return counts.sort_values(["panel", "geo_name"]).reset_index(drop=True)


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


def _figures(cfg: Config, root: Path, audit2: pd.DataFrame, comparison2: pd.DataFrame) -> list[str]:
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 8, "axes.titlesize": 10, "axes.labelsize": 8,
                         "xtick.labelsize": 7, "ytick.labelsize": 7, "svg.fonttype": "none"})
    figdir, datadir = root / "figures", root / "figure_data"
    outputs: list[str] = []

    # S3.5-1: show the temporal gaps that the formal rule treats as new evidence.
    primary = audit2[audit2.panel.eq("primary")].copy()
    states = sorted(primary.geo_name.unique(), key=lambda s: (primary.loc[primary.geo_name.eq(s), "gap_hours"].median(skipna=True), s))
    fig, ax = plt.subplots(figsize=(7.16, 5.6))
    for y, state in enumerate(states):
        vals = primary.loc[(primary.geo_name.eq(state)) & primary.gap_hours.notna(), "gap_hours"]
        if not vals.empty:
            ax.scatter(vals, np.full(len(vals), y), s=14, color="#4c78a8", alpha=.72, edgecolor="white", linewidth=.25)
    ax.axvline(FORMAL_GAP_H, color="#d95f02", ls="--", lw=1.2, label="Formal split threshold: 2 h")
    ax.set_xscale("symlog", linthresh=1)
    ax.set_yticks(np.arange(len(states)), states)
    ax.set(xlabel="Gap between successive outage windows (hours; symlog)", ylabel="Oblast")
    ax.set_title("Temporal gaps expose possible over-merging of frozen episodes")
    ax.grid(axis="x", color="#dddddd", lw=.5); ax.legend(frameon=False, fontsize=7)
    ax.text(0, -0.12, "A gap ≥2 h is an audit split; this is a temporal opportunity, not proof that a clean cycle was observed", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout(); outputs.extend(_save_figure(fig, figdir / "fig_S3_5_episode_gap_distribution", cfg))
    primary[["geo_name", "event_id", "event_date", "start_utc", "end_utc", "prev_end_utc", "gap_hours", "nominal_clean_cycle_n", "new_audit_episode", "frozen_episode_id", "audit_episode_id"]].to_csv(datadir / "fig_S3_5_episode_gap_distribution.csv", index=False)

    # S3.5-2: frozen versus audit episode counts on the same scale.
    c = comparison2[comparison2.panel.eq("primary")].copy().sort_values("audit_episode_n")
    fig, ax = plt.subplots(figsize=(7.16, 5.6))
    y = np.arange(len(c)); h = .36
    ax.barh(y - h / 2, c.frozen_episode_n, height=h, color="#bdbdbd", label="Frozen workbook label")
    ax.barh(y + h / 2, c.audit_episode_n, height=h, color="#4c78a8", label="2 h gap audit")
    ax.set_yticks(y, c.geo_name)
    ax.set(xlabel="Independent primary episodes", ylabel="Oblast")
    ax.set_title("Episode support changes when temporal gaps are audited")
    ax.axvline(3, color="#d95f02", ls="--", lw=1.2, label="Support reference: 3")
    ax.grid(axis="x", color="#dddddd", lw=.5); ax.legend(frameon=False, fontsize=7, ncol=3)
    ax.text(0, -0.12, "The audit does not replace the frozen registry; it identifies labels requiring review before Stage 4", transform=ax.transAxes, fontsize=7, color="#555555")
    fig.tight_layout(); outputs.extend(_save_figure(fig, figdir / "fig_S3_6_episode_count_comparison", cfg))
    c.to_csv(datadir / "fig_S3_6_episode_count_comparison.csv", index=False)

    # S3.5-3: direct Volyn diagnostic requested by the audit question.
    vol = primary[primary.geo_name.eq("Volyn Oblast")].copy()
    if vol.empty:
        vol = primary[primary.geo_name.astype(str).str.contains("Volyn", case=False, na=False)].copy()
    if not vol.empty:
        fig, ax = plt.subplots(figsize=(7.16, 3.0))
        colors = plt.get_cmap("tab10")(np.arange(vol.audit_episode_id.nunique()) % 10)
        cmap = dict(zip(sorted(vol.audit_episode_id.unique()), colors))
        for _, row in vol.iterrows():
            y = 0
            ax.plot([row.start_utc, row.end_utc], [y, y], lw=6, solid_capstyle="butt", color=cmap[row.audit_episode_id])
            if pd.notna(row.gap_hours) and row.gap_hours >= FORMAL_GAP_H:
                ax.axvline(row.start_utc, color="#d95f02", lw=.65, alpha=.75)
        ax.set_yticks([0], ["Volyn Oblast"])
        ax.set(xlabel="UTC time", ylabel="", title="Volyn outage windows and 2 h audit episode splits")
        ax.grid(axis="x", color="#dddddd", lw=.5)
        fig.tight_layout(); outputs.extend(_save_figure(fig, figdir / "fig_S3_7_volyn_episode_audit", cfg))
        vol.to_csv(datadir / "fig_S3_7_volyn_episode_audit.csv", index=False)
    return outputs


def _manifest(cfg: Config, root: Path, started: datetime, status: str, raw_sources: list[Path]) -> Path:
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "stage_manifest.json":
            files.append({"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": file_sha256(p)})
    payload = {
        "stage": STAGE, "run_id": cfg.run_id, "git_commit": _git_commit(cfg.root),
        "formal_gap_threshold_hours": FORMAL_GAP_H, "audit_gap_thresholds_hours": list(AUDIT_GAPS_H),
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
    events = _load_events(cfg)
    audits = {h: pd.concat([
        _audit_panel(events, "primary", "use_main", "episode_id_main", h),
        _audit_panel(events, "augmented", "use_augmented", "episode_id_augmented", h),
    ], ignore_index=True) for h in AUDIT_GAPS_H}
    comparisons = {h: _comparison(audits[h], events, h) for h in AUDIT_GAPS_H}
    audit2 = audits[FORMAL_GAP_H]
    comparison2 = comparisons[FORMAL_GAP_H]
    audit2.to_csv(root / "tables" / "event_gap_audit_2h.csv", index=False, encoding="utf-8-sig")
    comparison2.to_csv(root / "tables" / "episode_count_comparison_2h.csv", index=False, encoding="utf-8-sig")
    for h in (6.0, 12.0):
        comparisons[h].to_csv(root / "tables" / f"episode_count_comparison_{int(h)}h.csv", index=False, encoding="utf-8-sig")
    audit2[audit2.episode_label_changed].to_csv(root / "tables" / "episode_resegmentation_candidates_2h.csv", index=False, encoding="utf-8-sig")
    audit2.to_csv(root / "tables" / "episode_resegmentation_2h.csv", index=False, encoding="utf-8-sig")

    primary2 = comparison2[comparison2.panel.eq("primary")]
    changed_primary = int(audit2[(audit2.panel.eq("primary")) & audit2.episode_label_changed].event_id.nunique())
    frozen_primary_n = int(primary2.frozen_episode_n.sum()) if not primary2.empty else 0
    audit_primary_n = int(primary2.audit_episode_n.sum()) if not primary2.empty else 0
    split_gap_n = int(audit2[(audit2.panel.eq("primary")) & audit2.new_audit_episode.eq(1) & audit2.prev_end_utc.notna()].shape[0])
    summary = {
        "formal_gap_threshold_hours": FORMAL_GAP_H,
        "audit_gap_thresholds_hours": list(AUDIT_GAPS_H),
        "event_n": int(events.event_id.nunique()),
        "primary_event_n": int(events[events.use_main.eq(1)].event_id.nunique()),
        "augmented_event_n": int(events[events.use_augmented.eq(1)].event_id.nunique()),
        "frozen_primary_episode_n": frozen_primary_n,
        "audit_primary_episode_n_2h": audit_primary_n,
        "primary_episode_count_delta_2h": audit_primary_n - frozen_primary_n,
        "primary_event_n_with_changed_episode_label_2h": changed_primary,
        "primary_split_boundaries_2h": split_gap_n,
        "primary_oblast_ge3_frozen": int((primary2.frozen_episode_n >= 3).sum()) if not primary2.empty else 0,
        "primary_oblast_ge3_audit_2h": int((primary2.audit_episode_n >= 3).sum()) if not primary2.empty else 0,
        "overmerge_detected": bool(audit_primary_n > frozen_primary_n or changed_primary > 0),
    }
    (root / "tables" / "stage03_5_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    comparisons[FORMAL_GAP_H].to_csv(root / "tables" / "episode_count_comparison_by_oblast.csv", index=False, encoding="utf-8-sig")
    figures = _figures(cfg, root, audit2, comparison2)

    status = "warning" if summary["overmerge_detected"] else "ok"
    gate = "PASS_WITH_STRONG_WARNING" if summary["overmerge_detected"] else "PASS"
    report_lines = [
        f"# Stage 3.5 — Episode Independence Audit ({gate})", "", f"Run ID: `{cfg.run_id}`", "",
        "## Scope", "",
        "This is an audit of the frozen workbook episode identifiers. It does not overwrite the registry, query ClickHouse, or calculate IP sensitivity.", "",
        "## Pre-registered rule", "",
        "For each oblast and panel, events are sorted by their reviewed outage windows. A new audit episode starts when the next window begins at least one nominal two-hour measurement interval after the previous window ends. This is a temporal opportunity for a clean cycle, not a claim that the cycle was observed; Stage 1 measurement completeness must be checked before using it as evidence.", "",
        f"- Formal split threshold: **{FORMAL_GAP_H:.0f} h**", "- Diagnostic thresholds: **6 h** and **12 h** (reported only, not selected post hoc)", "- The frozen workbook labels remain unchanged.", "",
        "## Findings", "",
        f"- Frozen primary episode count: **{frozen_primary_n:,}**", f"- 2 h audit primary episode count: **{audit_primary_n:,}**", f"- Difference: **{audit_primary_n - frozen_primary_n:+,}**", f"- Primary events whose episode assignment changes under the 2 h rule: **{changed_primary:,}**", f"- New primary split boundaries under the 2 h rule: **{split_gap_n:,}**", f"- Oblasts meeting ≥3 primary episodes under frozen labels: **{summary['primary_oblast_ge3_frozen']:,}**", f"- Oblasts meeting ≥3 primary episodes under the 2 h audit: **{summary['primary_oblast_ge3_audit_2h']:,}**", "",
        "## Decision", "",
        ("The audit detects possible over-merging in the frozen episode IDs. Stage 4 is held until the event registry is reviewed or explicitly frozen with a documented rationale. The support threshold remains ≥3; no threshold relaxation is permitted." if summary["overmerge_detected"] else "The frozen episode IDs are consistent with the preregistered 2 h temporal separation screen. Stage 4 may proceed using the frozen IDs, while the audit remains part of the provenance record."), "",
        f"**{gate}**", "",
    ]
    report = root / "report" / "STAGE03_5_REPORT.md"
    report.write_text("\n".join(report_lines), encoding="utf-8")
    registry_name = cfg.raw.get("freeze", {}).get("calibration_event_registry", "calibration_event_registry_v1.csv")
    sources = [cfg.config_path, cfg.resource_path("calibration_workbook"), cfg.config_dir / registry_name]
    manifest = _manifest(cfg, root, started, status, sources)
    return {"status": status, "gate": gate, **summary, "outputs": [str(report), str(manifest), *figures]}
