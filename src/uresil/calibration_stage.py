"""Formal Stage 3: audit the frozen planned-outage workbook.

This stage is registry-only. It preserves one row per ``window_id`` and
counts support by the workbook's frozen ``episode_id``. It never infers a
new episode from dates, fills internal clear gaps, or runs IP/attack analysis.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CalibrationInput, Config, file_sha256

STAGE = "stage03_calibration_events"
EVIDENCE_LEVELS = ["A+", "A", "B+", "B"]


def _root(cfg: Config) -> Path:
    root = cfg.run_base / "results" / "stages" / STAGE
    for name in ("tables", "figures", "figure_data", "diagnostics", "report"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root), text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _load(cfg: Config) -> tuple[CalibrationInput, pd.DataFrame, int]:
    data = cfg.load_final_calibration_input()
    windows = data.episode_windows[data.episode_windows.formal_stage3_usable].copy()
    if windows.empty:
        raise RuntimeError("No analysis-usable windows remain after workbook/status/boundary checks")
    windows["month"] = windows.start_utc.dt.strftime("%Y-%m")
    windows["quality"] = windows.evidence_level.str.upper()
    windows["evidence_tier"] = windows.evidence_level.str.upper()
    windows["geo_name"] = windows["state"]
    return data, windows.sort_values(["start_utc", "geo_name", "window_id"]).reset_index(drop=True), len(data.episode_windows)


def _episode_membership(windows: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for panel, flag in (("primary", "use_primary"), ("augmented", "use_augmented")):
        x = windows[windows[flag]].copy()
        if x.empty:
            continue
        x["panel"] = panel
        rows.append(x[["admin1_iso", "geo_name", "episode_id", "window_id", "start_utc", "end_utc", "duration_h",
                       "month", "evidence_level", "dataset", "final_status", "source_id",
                       "boundary_overlap", "uncertain_execution", "panel"]])
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).drop_duplicates(["panel", "episode_id", "window_id"])


def _episode_summary(membership: pd.DataFrame) -> pd.DataFrame:
    columns = ["panel", "admin1_iso", "geo_name", "episode_id", "window_n", "first_window_start_utc",
               "last_window_end_utc", "total_window_h", "episode_span_h", "internal_gap_h"]
    if membership.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (panel, admin1, state, episode), g in membership.groupby(["panel", "admin1_iso", "geo_name", "episode_id"], sort=True):
        g = g.sort_values("start_utc")
        gaps = (g.start_utc.iloc[1:].reset_index(drop=True) - g.end_utc.iloc[:-1].reset_index(drop=True)).dt.total_seconds().to_numpy() / 3600.0
        rows.append({"panel": panel, "admin1_iso": admin1, "geo_name": state, "episode_id": episode,
                     "window_n": int(len(g)), "first_window_start_utc": g.start_utc.min(),
                     "last_window_end_utc": g.end_utc.max(), "total_window_h": float(g.duration_h.sum()),
                     "episode_span_h": float((g.end_utc.max() - g.start_utc.min()).total_seconds() / 3600),
                     "internal_gap_h": float(np.maximum(gaps, 0).sum()) if len(gaps) else 0.0})
    return pd.DataFrame(rows, columns=columns)


def _bool_value(v: object) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y", "verified", "official"}


def _audit_workbook(data: CalibrationInput, windows: pd.DataFrame, root: Path) -> dict:
    sources = data.sources.copy()
    sources["verified_bool"] = sources.verified.map(_bool_value)
    sources["official_bool"] = sources.source_role.str.upper().isin({"PRIMARY_SOURCE", "OFFICIAL"})
    source_map = sources.set_index("source_id")[["verified_bool", "official_bool"]].to_dict("index")
    primary, augmented = windows[windows.use_primary], windows[windows.use_augmented]
    source_fk_missing = int((~windows.source_fk_ok).sum())

    cov = data.state_coverage.copy()
    recomputed_rows = []
    for admin1, g in windows.groupby("admin1_iso"):
        recomputed_rows.append({"admin1_iso": admin1,
                                "primary_episode_n_recomputed": int(g.loc[g.use_primary, "episode_id"].nunique()),
                                "augmented_episode_n_recomputed": int(g.loc[g.use_augmented, "episode_id"].nunique())})
    recomputed = pd.DataFrame(recomputed_rows)
    cross = cov[["admin1_iso", "state", "candidate_n", "primary_episode_n", "augmented_episode_n",
                 "primary_ge_3", "augmented_ge_3", "official_sources_checked_n", "search_status"]].merge(
        recomputed, on="admin1_iso", how="left")
    cross["primary_mismatch"] = cross.primary_episode_n.fillna(0).astype(int).ne(cross.primary_episode_n_recomputed.fillna(0).astype(int))
    cross["augmented_mismatch"] = cross.augmented_episode_n.fillna(0).astype(int).ne(cross.augmented_episode_n_recomputed.fillna(0).astype(int))
    cross.to_csv(root / "tables" / "02_STATE_COVERAGE_CROSSCHECK.csv", index=False, encoding="utf-8-sig")

    source_rows = []
    for panel, g in (("primary", primary), ("augmented", augmented)):
        source_rows.append({"panel": panel, "window_n": int(len(g)), "episode_n": int(g.episode_id.nunique()),
                            "source_n": int(g.source_id.nunique()),
                            "verified_source_n": int(sum(source_map.get(x, {}).get("verified_bool", False) for x in g.source_id.unique())),
                            "official_source_n": int(sum(source_map.get(x, {}).get("official_bool", False) for x in g.source_id.unique())),
                            "missing_source_fk_n": int((~g.source_fk_ok).sum())})
    pd.DataFrame(source_rows).to_csv(root / "tables" / "calibration_source_audit.csv", index=False, encoding="utf-8-sig")

    semantic_rows = []
    for (admin1, episode), g in data.episode_windows.groupby(["admin1_iso", "episode_id"], sort=True):
        g = g.sort_values("start_utc")
        gaps = (g.start_utc.iloc[1:].reset_index(drop=True) - g.end_utc.iloc[:-1].reset_index(drop=True)).dt.total_seconds().to_numpy() / 3600.0
        overlap_n = int(sum(g.start_utc.iloc[i] < g.end_utc.iloc[i - 1] for i in range(1, len(g))))
        hourly_24h = int((g.event_type.str.upper().eq("HOURLY_SCHEDULE") & g.duration_h.ge(24)).sum())
        semantic_rows.append({"admin1_iso": admin1, "state": g.state.iloc[0], "episode_id": episode,
                              "window_n": int(len(g)), "window_ids": "|".join(g.window_id.astype(str)),
                              "first_start_utc": g.start_utc.min(), "last_end_utc": g.end_utc.max(),
                              "total_window_h": float(g.duration_h.sum()),
                              "episode_span_h_descriptive": float((g.end_utc.max() - g.start_utc.min()).total_seconds() / 3600),
                              "internal_gap_h_descriptive": float(np.maximum(gaps, 0).sum()) if len(gaps) else 0.0,
                              "overlap_window_n": overlap_n, "hourly_schedule_ge24h_n": hourly_24h,
                              "review_flag": "REVIEW_24H_HOURLY_SCHEDULE" if hourly_24h else "OK_EXACT_WINDOWS",
                              "semantic_note": "Exact windows retained; no min(start)-max(end) fill; union only at exposure mapping time."})
    pd.DataFrame(semantic_rows).to_csv(root / "report" / "OUTAGE_WINDOW_SEMANTIC_REVIEW.csv", index=False, encoding="utf-8-sig")

    cross_overlap = []
    for state, g in data.episode_windows.groupby("admin1_iso"):
        rows = g.sort_values("start_utc").to_dict("records")
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a["episode_id"] != b["episode_id"] and a["start_utc"] < b["end_utc"] and b["start_utc"] < a["end_utc"]:
                    cross_overlap.append({"admin1_iso": state, "episode_a": a["episode_id"], "window_a": a["window_id"],
                                          "episode_b": b["episode_id"], "window_b": b["window_id"]})
    pd.DataFrame(cross_overlap, columns=["admin1_iso", "episode_a", "window_a", "episode_b", "window_b"]).to_csv(root / "tables" / "cross_episode_overlap_audit.csv", index=False, encoding="utf-8-sig")

    mask_report = root / "report" / "ACTIVITY_MASK_IMPACT_AUDIT.md"
    mask_report.write_text("\n".join([
        "# Activity-mask impact audit", "",
        "Stage 2's clean-cycle mask is defined by complete measurement cycles and the frozen attack/energy event registry.",
        "The planned-outage workbook is consumed only by the dedicated calibration workflow; it is not injected into `Events.clean_baseline_mask`.",
        "Therefore this workbook migration does not change the Stage 2 Activity denominator.", "",
        "**STAGE2_RERUN_NOT_REQUIRED**", "",
        "Only Stage 3 registry summaries and figures are regenerated.", "",
    ]) + "\n", encoding="utf-8")

    audit = {
        "workbook_path": str(data.workbook_path), "workbook_sha256": data.workbook_sha256,
        "workbook_bytes": data.workbook_bytes, "raw_window_n": int(len(data.episode_windows)),
        "usable_window_n": int(len(windows)), "unique_window_n": int(data.episode_windows.window_id.nunique()),
        "unique_episode_n": int(data.episode_windows.episode_id.nunique()),
        "primary_window_n": int(primary.window_id.nunique()), "primary_episode_n": int(primary.episode_id.nunique()),
        "augmented_window_n": int(augmented.window_id.nunique()), "augmented_episode_n": int(augmented.episode_id.nunique()),
        "state_n": int(data.episode_windows.admin1_iso.nunique()),
        "primary_ge3_state_n": int(primary.groupby("admin1_iso").episode_id.nunique().ge(3).sum()),
        "augmented_ge3_state_n": int(augmented.groupby("admin1_iso").episode_id.nunique().ge(3).sum()),
        "evidence_counts": {str(k): int(v) for k, v in windows.evidence_level.value_counts().items()},
        "status_counts": {str(k): int(v) for k, v in windows.final_status_norm.value_counts().items()},
        "dataset_consistency_fail_n": int((~windows.dataset_consistency_ok).sum()), "source_fk_missing_n": source_fk_missing,
        "cross_coverage_primary_mismatch_n": int(cross.primary_mismatch.sum()),
        "cross_coverage_augmented_mismatch_n": int(cross.augmented_mismatch.sum()),
        "cross_episode_overlap_n": int(len(cross_overlap)),
        "hourly_schedule_ge24h_n": int((data.episode_windows.event_type.str.upper().eq("HOURLY_SCHEDULE") & data.episode_windows.duration_h.ge(24)).sum()),
        "stage2_rerun": "NOT_REQUIRED",
    }
    (root / "tables" / "calibration_input_provenance.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# NEW_OUTAGE_WORKBOOK_AUDIT", "", f"Workbook: `{data.workbook_path}`", f"SHA256: `{data.workbook_sha256}`", f"Bytes: **{data.workbook_bytes:,}**", "",
        "## Frozen-sheet checks", "", f"- `01_EPISODES` rows/windows: **{len(data.episode_windows):,}**; unique windows: **{data.episode_windows.window_id.nunique():,}**; unique frozen episodes: **{data.episode_windows.episode_id.nunique():,}**.",
        f"- Analysis-usable windows: **{len(windows):,}**; Primary: **{len(primary):,}** windows / **{primary.episode_id.nunique():,}** episodes; Augmented: **{len(augmented):,}** windows / **{augmented.episode_id.nunique():,}** episodes.",
        f"- Oblasts: **{data.episode_windows.admin1_iso.nunique():,}**; Primary states with ≥3 episodes: **{audit['primary_ge3_state_n']:,}**; Augmented: **{audit['augmented_ge3_state_n']:,}**.",
        f"- Evidence levels: {audit['evidence_counts']}; final statuses: {audit['status_counts']}.", "", "## Contract and provenance", "",
        "- Selectors are evidence/status-derived `use_primary` and `use_augmented`; `dataset` is checked only for consistency.",
        "- `episode_id` is the frozen independent unit and `window_id` is the exact exposure window. Multiple windows remain separate; descriptive spans never fill clear gaps.",
        "- The retired legacy sheets and legacy episode IDs are not read.",
        f"- Source FK missing: **{source_fk_missing}**; dataset consistency failures: **{len(windows.loc[~windows.dataset_consistency_ok])}**; cross-episode overlap rows: **{len(cross_overlap)}**.",
        f"- `02_STATE_COVERAGE` exact episode-count mismatches: Primary **{int(cross.primary_mismatch.sum())}**, Augmented **{int(cross.augmented_mismatch.sum())}**. `candidate_n` is a search-pool field and is not compared to final rows.",
        f"- 24h+ `HOURLY_SCHEDULE` rows requiring semantic review: **{audit['hourly_schedule_ge24h_n']}**; they are retained, not reinterpreted.", "", "## Activity mask", "", "See `ACTIVITY_MASK_IMPACT_AUDIT.md`: **STAGE2_RERUN_NOT_REQUIRED**.", "",
    ]
    (root / "report" / "NEW_OUTAGE_WORKBOOK_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return audit


def _save_figure(fig, path: Path, cfg: Config) -> list[str]:
    import matplotlib.pyplot as plt
    dpi = int(cfg.figures.get("png_dpi", 600)); out = []
    for ext in ("png", "pdf", "svg"):
        p = path.with_suffix("." + ext); fig.savefig(p, dpi=dpi if ext == "png" else None, bbox_inches="tight"); out.append(str(p))
    plt.close(fig); return out


def _figures(cfg: Config, root: Path, windows: pd.DataFrame, membership: pd.DataFrame) -> list[str]:
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "axes.titlesize": 10, "axes.labelsize": 8, "xtick.labelsize": 7, "ytick.labelsize": 7, "svg.fonttype": "none"})
    out = []; states = sorted(windows.geo_name.astype(str).unique(), key=lambda s: str(s).lower()); state_order = windows.geo_name.value_counts().reindex(states).sort_values().index.tolist(); ypos = {s: i for i, s in enumerate(state_order)}
    colors = {"A+": "#1b9e77", "A": "#377eb8", "B+": "#7570b3", "B": "#999999"}
    for lang in ("en", "zh"):
        plt.rcParams["font.family"] = ["WenQuanYi Micro Hei", "DejaVu Sans"] if lang == "zh" else ["DejaVu Sans"]
        figdir = root / "figures" / lang; figdir.mkdir(parents=True, exist_ok=True)
        xlabel, ylabel = (("Window start (UTC)", "Oblast") if lang == "en" else ("停电窗口开始时间（UTC）", "州"))
        # S3-1: one marker per frozen window.
        fig, ax = plt.subplots(figsize=(7.16, 5.6))
        for level, g in windows.groupby("evidence_level", sort=False):
            ax.scatter(g.start_utc, [ypos[s] for s in g.geo_name], s=22, alpha=.85, color=colors.get(level, "#555555"), label=level, edgecolor="white", linewidth=.3)
        ax.set_title("Frozen outage windows by oblast" if lang == "en" else "各州冻结计划停电窗口"); ax.set(xlabel=xlabel, ylabel=ylabel, yticks=np.arange(len(state_order)), yticklabels=state_order); ax.grid(axis="x", color="#dddddd", lw=.5); ax.legend(frameon=False, title="Evidence" if lang == "en" else "证据级别", fontsize=7)
        ax.text(0, -0.12, "Each point is one frozen window; episode_id is the independent unit." if lang == "en" else "每个点对应一个冻结窗口；独立分析单位是 episode_id。", transform=ax.transAxes, fontsize=7, color="#555555"); fig.tight_layout(); out.extend(_save_figure(fig, figdir / "fig_S3_1_calibration_window_timeline", cfg))
        windows[["window_id", "episode_id", "geo_name", "admin1_iso", "start_utc", "end_utc", "evidence_level", "dataset", "final_status", "use_primary", "use_augmented"]].to_csv(root / "figure_data" / "fig_S3_1_calibration_window_timeline.csv", index=False, encoding="utf-8-sig")

        # S3-2: show Primary and Augmented support separately.
        counts = pd.DataFrame({"primary": membership[membership.panel.eq("primary")].groupby("geo_name").episode_id.nunique(), "augmented": membership[membership.panel.eq("augmented")].groupby("geo_name").episode_id.nunique()}).reindex(state_order).fillna(0)
        fig, axes = plt.subplots(1, 2, figsize=(7.16, 5.6), sharey=True)
        for ax, col, color, label in zip(axes, ("primary", "augmented"), ("#377eb8", "#7570b3"), ("Primary", "Augmented")):
            ax.barh(counts.index, counts[col], color=color); ax.axvline(3, color="#d95f02", ls="--", lw=1.1); ax.set_title(label); ax.set_xlabel("Independent episodes" if lang == "en" else "独立 episode 数"); ax.grid(axis="x", color="#dddddd", lw=.5)
            for y, v in enumerate(counts[col]): ax.text(float(v) + .08, y, f"{int(v)}", va="center", fontsize=6)
        axes[0].set_ylabel(ylabel); fig.suptitle("Independent episode support by oblast" if lang == "en" else "各州独立 episode 支持度"); fig.text(.01, -.03, "Dashed line: support=3; no state is removed." if lang == "en" else "虚线为 support=3；不删除任何州。", fontsize=7, color="#555555"); fig.tight_layout(); out.extend(_save_figure(fig, figdir / "fig_S3_2_independent_episodes_by_oblast", cfg)); counts.reset_index().rename(columns={"index": "geo_name"}).to_csv(root / "figure_data" / "fig_S3_2_independent_episodes_by_oblast.csv", index=False, encoding="utf-8-sig")

        # S3-3: month × oblast counts distinct frozen episode IDs.
        months = sorted(windows.month.unique()); aug = membership[membership.panel.eq("augmented")]; matrix = aug.groupby(["month", "geo_name"]).episode_id.nunique().unstack(fill_value=0).reindex(index=months, columns=state_order, fill_value=0)
        fig, ax = plt.subplots(figsize=(7.16, 5.6)); im = ax.imshow(matrix.to_numpy(), aspect="auto", cmap="Blues", vmin=0, vmax=max(1, int(matrix.to_numpy().max()))); ax.set_title("Augmented episode coverage by month and oblast" if lang == "en" else "Augmented episode 的月份×州覆盖"); ax.set(xticks=np.arange(len(state_order)), xticklabels=state_order, yticks=np.arange(len(months)), yticklabels=months, xlabel=ylabel, ylabel="Month (UTC)" if lang == "en" else "月份（UTC）"); plt.setp(ax.get_xticklabels(), rotation=60, ha="right"); cbar = fig.colorbar(im, ax=ax, pad=.02, fraction=.03); cbar.set_label("Independent episodes" if lang == "en" else "独立 episode 数"); fig.tight_layout(); out.extend(_save_figure(fig, figdir / "fig_S3_3_calibration_coverage_matrix", cfg)); matrix.reset_index().to_csv(root / "figure_data" / "fig_S3_3_calibration_coverage_matrix.csv", index=False, encoding="utf-8-sig")

        # S3-4: registry evidence and execution status.
        evidence = windows.evidence_level.value_counts().reindex(EVIDENCE_LEVELS, fill_value=0); status = windows.final_status_norm.value_counts().sort_values(); fig, axes = plt.subplots(1, 2, figsize=(7.16, 3.25)); axes[0].bar(evidence.index, evidence.to_numpy(), color=[colors[x] for x in evidence.index]); axes[0].set_title("Evidence level" if lang == "en" else "证据级别"); axes[0].set_ylabel("Window count" if lang == "en" else "窗口数"); axes[0].grid(axis="y", color="#dddddd", lw=.5); axes[1].barh(status.index, status.to_numpy(), color="#6a9fbf"); axes[1].set_title("Final status" if lang == "en" else "最终状态"); axes[1].set_xlabel("Window count" if lang == "en" else "窗口数"); axes[1].grid(axis="x", color="#dddddd", lw=.5); fig.suptitle("Calibration evidence and execution status" if lang == "en" else "校准证据与执行状态"); fig.tight_layout(); out.extend(_save_figure(fig, figdir / "fig_S3_4_calibration_evidence_status", cfg)); pd.DataFrame({"evidence_level": evidence.index, "window_n": evidence.to_numpy()}).to_csv(root / "figure_data" / "fig_S3_4_evidence_distribution.csv", index=False, encoding="utf-8-sig"); status.rename_axis("final_status").rename("window_n").reset_index().to_csv(root / "figure_data" / "fig_S3_4_status_distribution.csv", index=False, encoding="utf-8-sig")
    return out


def _manifest(cfg: Config, root: Path, started: datetime, status: str, raw: CalibrationInput) -> Path:
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "stage_manifest.json": files.append({"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": file_sha256(p)})
    payload = {"stage": STAGE, "run_id": cfg.run_id, "git_commit": _git_commit(cfg.root), "config_hash": file_sha256(cfg.config_path), "calibration_workbook": {"path": str(raw.workbook_path), "sha256": raw.workbook_sha256, "bytes": raw.workbook_bytes}, "input_hashes": {str(raw.workbook_path): raw.workbook_sha256}, "output_hashes": files, "start_time": started.isoformat(), "end_time": datetime.now(timezone.utc).isoformat(), "status": status}
    path = root / "stage_manifest.json"; path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"); return path


def run(cfg: Config) -> dict:
    started = datetime.now(timezone.utc); root = _root(cfg); raw, windows, raw_window_n = _load(cfg); membership = _episode_membership(windows); episodes = _episode_summary(membership); audit = _audit_workbook(raw, windows, root)
    windows.to_csv(root / "tables" / "calibration_windows.csv", index=False, encoding="utf-8-sig"); membership.to_csv(root / "tables" / "calibration_episode_membership.csv", index=False, encoding="utf-8-sig"); episodes.to_csv(root / "tables" / "calibration_episode_summary.csv", index=False, encoding="utf-8-sig")
    by_state = pd.DataFrame({"admin1_iso": sorted(windows.admin1_iso.unique())}); state_names = windows.drop_duplicates("admin1_iso").set_index("admin1_iso")["geo_name"]; by_state["state"] = by_state.admin1_iso.map(state_names)
    for panel, flag in (("primary", "use_primary"), ("augmented", "use_augmented")):
        g = windows[windows[flag]]; by_state[f"{panel}_window_n"] = by_state.admin1_iso.map(g.groupby("admin1_iso").window_id.nunique()).fillna(0).astype(int); by_state[f"{panel}_episode_n"] = by_state.admin1_iso.map(g.groupby("admin1_iso").episode_id.nunique()).fillna(0).astype(int); by_state[f"{panel}_ge3"] = by_state[f"{panel}_episode_n"].ge(3)
    by_state.to_csv(root / "tables" / "calibration_episodes_by_oblast.csv", index=False, encoding="utf-8-sig")
    windows.groupby(["month", "geo_name"], as_index=False).agg(window_n=("window_id", "nunique"), episode_n=("episode_id", "nunique"), primary_window_n=("use_primary", "sum"), augmented_window_n=("use_augmented", "sum")).to_csv(root / "tables" / "calibration_monthly_summary.csv", index=False, encoding="utf-8-sig")
    windows.evidence_level.value_counts().rename_axis("evidence_level").rename("window_n").reset_index().to_csv(root / "tables" / "calibration_evidence_summary.csv", index=False, encoding="utf-8-sig"); windows.final_status_norm.value_counts().rename_axis("final_status").rename("window_n").reset_index().to_csv(root / "tables" / "calibration_status_summary.csv", index=False, encoding="utf-8-sig")
    summary = {"raw_workbook_window_n": int(raw_window_n), "usable_window_n": int(len(windows)), "unique_window_n": int(windows.window_id.nunique()), "unique_episode_n": int(windows.episode_id.nunique()), "primary_window_n": int(windows[windows.use_primary].window_id.nunique()), "primary_episode_n": int(windows[windows.use_primary].episode_id.nunique()), "augmented_window_n": int(windows[windows.use_augmented].window_id.nunique()), "augmented_episode_n": int(windows[windows.use_augmented].episode_id.nunique()), "oblast_n": int(windows.admin1_iso.nunique()), "primary_ge3_state_n": int(by_state.primary_ge3.sum()), "augmented_ge3_state_n": int(by_state.augmented_ge3.sum()), "dataset_consistency_fail_n": int((~windows.dataset_consistency_ok).sum()), "source_fk_missing_n": int((~windows.source_fk_ok).sum()), "cross_episode_overlap_n": int(audit["cross_episode_overlap_n"]), "stage2_rerun": "NOT_REQUIRED", "workbook_sha256": raw.workbook_sha256}
    (root / "tables" / "calibration_stage_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    figures = _figures(cfg, root, windows, membership); failures = []
    if summary["dataset_consistency_fail_n"]: failures.append("dataset/evidence consistency failure")
    if summary["source_fk_missing_n"]: failures.append("source foreign-key failure")
    if audit["cross_coverage_primary_mismatch_n"] or audit["cross_coverage_augmented_mismatch_n"]: failures.append("state coverage mismatch")
    if audit["cross_episode_overlap_n"]: failures.append("cross-episode interval overlap requires audit")
    status = "FAIL" if failures else "PASS_WITH_STRONG_WARNING"
    report_lines = [f"# Stage 3 — Calibration Event Quality ({status})", "", f"Run ID: `{cfg.run_id}`", f"Workbook SHA256: `{raw.workbook_sha256}`", "", "## Scope", "", "This stage reads the v2-final five-sheet planned-outage registry only. It does not query ClickHouse, compute IP sensitivity, run Activity again, or use war-attack outcomes.", "", f"- Frozen rows/windows: **{summary['raw_workbook_window_n']:,}**; usable windows: **{summary['usable_window_n']:,}**; unique episodes: **{summary['unique_episode_n']:,}**.", f"- Primary: **{summary['primary_window_n']:,}** windows / **{summary['primary_episode_n']:,}** episodes; Augmented: **{summary['augmented_window_n']:,}** windows / **{summary['augmented_episode_n']:,}** episodes.", f"- Oblasts: **{summary['oblast_n']:,}**; states with ≥3 episodes: Primary **{summary['primary_ge3_state_n']:,}**, Augmented **{summary['augmented_ge3_state_n']:,}**.", "", "## Frozen semantics", "", "- `episode_id` is the independent unit supplied by the workbook; `window_id` is the exact outage window. No date-contiguity or 36-hour episode inference is performed.", "- Primary is evidence A/A+ with an explicitly positive final status; Augmented is evidence A+/A/B+/B excluding cancelled rows. Uncertain execution remains flagged and is not promoted to Primary.", "- `dataset` is a consistency check only. The retired legacy sheets and legacy episode IDs are not read.", "- Multiple windows in one episode remain separate; episode span/gap fields are descriptive and never fill clear gaps.", "", "## Audits", "", f"- Dataset/evidence consistency failures: **{summary['dataset_consistency_fail_n']}**; source FK failures: **{summary['source_fk_missing_n']}**; cross-episode overlap rows: **{summary['cross_episode_overlap_n']}**.", f"- `02_STATE_COVERAGE` recomputation mismatches: Primary **{audit['cross_coverage_primary_mismatch_n']}**, Augmented **{audit['cross_coverage_augmented_mismatch_n']}**.", f"- 24h+ hourly schedule rows requiring semantic review: **{audit['hourly_schedule_ge24h_n']}** (retained, not reinterpreted).", "- Activity mask impact: **STAGE2_RERUN_NOT_REQUIRED**; see `ACTIVITY_MASK_IMPACT_AUDIT.md`.", "", "## Gate", "", f"**{status}**" + (" — " + "; ".join(failures) if failures else " — strong warning: coverage is uneven; support≥3 is reported, not used to delete states."), "", "Stage 4 is intentionally not run by this command. H1–H4 and attack analysis are out of scope for this Stage 3 execution."]
    report = root / "report" / "STAGE03_REPORT.md"; report.write_text("\n".join(report_lines) + "\n", encoding="utf-8"); manifest = _manifest(cfg, root, started, "failed" if status == "FAIL" else "warning", raw)
    return {"status": "failed" if status == "FAIL" else "warning", "gate": status, **summary, "outputs": [str(report), str(manifest), str(root / "report" / "NEW_OUTAGE_WORKBOOK_AUDIT.md"), *figures]}
