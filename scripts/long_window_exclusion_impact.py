#!/usr/bin/env python3
"""Audit label coverage after excluding unconfirmed 24h schedule windows.

This is a derived-view audit only.  It never edits the Excel workbook, reads
attack outcomes, or calculates IP sensitivity.  Episode support is always
``nunique(episode_id)``; repeated windows in one episode cannot inflate it.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def run(stage_root: Path) -> dict:
    report = stage_root / "report"
    tables = stage_root / "tables"
    long = pd.read_csv(report / "LONG_WINDOW_SEMANTIC_REVIEW.csv")
    windows = pd.read_csv(tables / "calibration_windows.csv")
    if long.window_id.duplicated().any():
        raise ValueError("LONG_WINDOW_SEMANTIC_REVIEW.csv has duplicate window_id")
    if windows.window_id.duplicated().any():
        raise ValueError("calibration_windows.csv has duplicate window_id")
    required = {"window_id", "episode_id", "admin1_iso", "state", "use_primary", "use_augmented"}
    missing = sorted(required - set(windows.columns))
    if missing:
        raise ValueError(f"calibration_windows.csv missing columns: {missing}")
    long_idx = long.set_index("window_id")
    long_class = long_idx["semantic_class"]
    allowed_classes = {
        "A_CONFIRMED_UNIFORM",
        "B_GROUP_ROTATION_UNMAPPED",
        "C_UNCONFIRMED_REVIEW_REQUIRED",
    }
    unexpected_classes = sorted(set(long_class.dropna()) - allowed_classes)
    if unexpected_classes:
        raise ValueError(f"Unexpected long-window semantic classes: {unexpected_classes}")
    windows = windows.copy()
    windows["use_primary"] = _bool(windows["use_primary"])
    windows["use_augmented"] = _bool(windows["use_augmented"])
    windows["is_long_reviewed"] = windows.window_id.isin(long_class.index)
    windows["semantic_class"] = windows.window_id.map(long_class).fillna("NOT_LONG_WINDOW")
    for col in ("source_official", "source_verified", "notes"):
        if col in long_idx:
            windows[col] = windows.window_id.map(long_idx[col]).fillna("")
    windows["formal_positive"] = True
    windows.loc[windows.is_long_reviewed, "formal_positive"] = windows.loc[windows.is_long_reviewed, "semantic_class"].eq("A_CONFIRMED_UNIFORM")
    windows["use_primary_after_long_review"] = windows.use_primary & windows.formal_positive
    windows["use_augmented_after_long_review"] = windows.use_augmented & windows.formal_positive
    windows["exclusion_reason"] = ""
    windows.loc[windows.is_long_reviewed & ~windows.formal_positive, "exclusion_reason"] = "C_UNCONFIRMED_REVIEW_REQUIRED"

    # The derived frozen exposure view is the only view consumed by a future
    # Stage 4 run after a human accepts this audit.  The source workbook is
    # untouched and remains the provenance anchor.
    windows.to_csv(tables / "frozen_exposure_view.csv", index=False, encoding="utf-8-sig")
    excluded_ids = set(windows.loc[~windows.formal_positive, "window_id"])
    excluded = windows[windows.window_id.isin(excluded_ids)].copy()
    non_long = ~windows.window_id.isin(excluded_ids)
    # Support is evaluated both before and after exclusion, at episode level.
    state_rows = []
    for admin1, g in windows.groupby("admin1_iso", sort=True):
        state = str(g.state.iloc[0])
        row = {"admin1_iso": admin1, "state": state}
        for panel, before, after in (("primary", "use_primary", "use_primary_after_long_review"),
                                     ("augmented", "use_augmented", "use_augmented_after_long_review")):
            before_ep = set(g.loc[g[before], "episode_id"])
            after_ep = set(g.loc[g[after], "episode_id"])
            row[f"{panel}_window_n_before"] = int(g[before].sum())
            row[f"{panel}_window_n_after"] = int(g[after].sum())
            row[f"{panel}_episode_n_before"] = int(len(before_ep))
            row[f"{panel}_episode_n_after"] = int(len(after_ep))
            row[f"{panel}_episode_delta"] = int(len(after_ep) - len(before_ep))
            for threshold in (2, 3, 4):
                row[f"{panel}_ge{threshold}_before"] = len(before_ep) >= threshold
                row[f"{panel}_ge{threshold}_after"] = len(after_ep) >= threshold
                row[f"{panel}_crossed_ge{threshold}"] = len(before_ep) >= threshold and len(after_ep) < threshold
        state_rows.append(row)
    state_df = pd.DataFrame(state_rows).sort_values("admin1_iso")
    state_df.to_csv(report / "LONG_WINDOW_EXCLUSION_IMPACT_BY_STATE.csv", index=False, encoding="utf-8-sig")

    # Per-window audit includes whether removing it actually removes the
    # episode or whether other non-long windows preserve that episode.
    excluded_rows = []
    for _, r in excluded.iterrows():
        g = windows[(windows.admin1_iso == r.admin1_iso) & (windows.episode_id == r.episode_id)]
        other = g[~g.window_id.isin(excluded_ids)]
        same_state = state_df[state_df.admin1_iso.eq(r.admin1_iso)].iloc[0]
        excluded_rows.append({
            "window_id": r.window_id, "episode_id": r.episode_id, "admin1_iso": r.admin1_iso,
            "state": r.state, "start_utc": r.start_utc, "end_utc": r.end_utc,
            "duration_h": r.duration_h, "evidence_level": r.evidence_level, "dataset": r.dataset,
            "final_status": r.final_status_norm, "source_id": r.source_id,
            "semantic_class": r.semantic_class, "source_official": r.get("source_official", ""),
            "source_verified": r.get("source_verified", ""), "notes": r.get("notes", ""),
            "primary_episode_removed": bool(r.episode_id not in set(g.loc[g.use_primary_after_long_review, "episode_id"])),
            "augmented_episode_removed": bool(r.episode_id not in set(g.loc[g.use_augmented_after_long_review, "episode_id"])),
            "primary_retained_by_other_non_long_window": bool((other.use_primary).any()),
            "augmented_retained_by_other_non_long_window": bool((other.use_augmented).any()),
            "primary_state_ge3_before": bool(same_state.primary_ge3_before),
            "primary_state_ge3_after": bool(same_state.primary_ge3_after),
            "augmented_state_ge3_before": bool(same_state.augmented_ge3_before),
            "augmented_state_ge3_after": bool(same_state.augmented_ge3_after),
        })
    excluded_df = pd.DataFrame(excluded_rows)
    excluded_df.to_csv(report / "LONG_WINDOW_EXCLUDED_WINDOWS.csv", index=False, encoding="utf-8-sig")

    removed = []
    for panel, before, after in (("primary", "use_primary", "use_primary_after_long_review"),
                                 ("augmented", "use_augmented", "use_augmented_after_long_review")):
        for (admin1, state), g in windows.groupby(["admin1_iso", "state"], sort=True):
            b = set(g.loc[g[before], "episode_id"]); a = set(g.loc[g[after], "episode_id"])
            for episode in sorted(b - a):
                removed.append({"panel": panel, "admin1_iso": admin1, "state": state, "episode_id": episode,
                                "all_windows_are_excluded_long_windows": bool(g[g.episode_id.eq(episode)].window_id.isin(excluded_ids).all()),
                                "other_non_long_window_n": int((g[g.episode_id.eq(episode)].window_id.isin(set(windows.loc[non_long, "window_id"]))).sum())})
    removed_df = pd.DataFrame(removed, columns=["panel", "admin1_iso", "state", "episode_id", "all_windows_are_excluded_long_windows", "other_non_long_window_n"])
    removed_df.to_csv(report / "LONG_WINDOW_REMOVED_EPISODES.csv", index=False, encoding="utf-8-sig")

    # One row per panel/episode makes the two requested cases explicit:
    # completely removed versus retained by at least one non-long window.
    episode_rows = []
    for panel, before, after in (("primary", "use_primary", "use_primary_after_long_review"),
                                 ("augmented", "use_augmented", "use_augmented_after_long_review")):
        for (admin1, state), g in windows.groupby(["admin1_iso", "state"], sort=True):
            for episode, eg in g.groupby("episode_id", sort=True):
                if not bool(eg[before].any()):
                    continue
                non_long_n = int((eg.window_id.isin(set(windows.loc[non_long, "window_id"])) & eg[before]).sum())
                excluded_long_n = int((~eg.window_id.isin(set(windows.loc[non_long, "window_id"])) & eg[before]).sum())
                episode_rows.append({
                    "panel": panel,
                    "admin1_iso": admin1,
                    "state": state,
                    "episode_id": episode,
                    "episode_removed_after_exclusion": not bool(eg[after].any()),
                    "has_excluded_long_window": excluded_long_n > 0,
                    "excluded_long_window_n": excluded_long_n,
                    "retained_by_other_non_long_window": non_long_n > 0,
                    "other_non_long_window_n": non_long_n,
                })
    episode_df = pd.DataFrame(episode_rows)
    episode_df.to_csv(report / "LONG_WINDOW_EPISODE_IMPACT.csv", index=False, encoding="utf-8-sig")

    # Priority is only for the B conclusion: threshold crossings first, then
    # actual episode loss, official-source presence, and a possible path to a
    # precise sub-window in the source page/notes.
    if not excluded_df.empty:
        p = excluded_df.copy()
        p["threshold_impact"] = p.primary_state_ge3_before.astype(int).sub(p.primary_state_ge3_after.astype(int)).abs() + p.augmented_state_ge3_before.astype(int).sub(p.augmented_state_ge3_after.astype(int)).abs()
        p["episode_loss"] = p.primary_episode_removed.astype(int) + p.augmented_episode_removed.astype(int)
        p["official_source_score"] = _bool(p.source_official).astype(int)
        note = p.notes.fillna("").astype(str).str.lower()
        p["precise_subwindow_score"] = (note.str.contains(r"queue|group|rotat|hourly|schedule", regex=True).astype(int) + p.official_source_score)
        p = p.sort_values(["threshold_impact", "episode_loss", "official_source_score", "precise_subwindow_score", "state", "start_utc"], ascending=[False, False, False, False, True, True])
        p.insert(0, "priority_rank", range(1, len(p) + 1))
        p[["priority_rank", "window_id", "episode_id", "state", "start_utc", "end_utc", "evidence_level", "dataset", "source_id", "source_official", "source_verified", "threshold_impact", "episode_loss", "precise_subwindow_score", "notes"]].to_csv(report / "LONG_WINDOW_TARGETED_REVIEW_PRIORITY.csv", index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["priority_rank", "window_id", "episode_id", "state"]).to_csv(report / "LONG_WINDOW_TARGETED_REVIEW_PRIORITY.csv", index=False, encoding="utf-8-sig")

    primary_ge3_before = int(state_df.primary_ge3_before.sum()); primary_ge3_after = int(state_df.primary_ge3_after.sum()); augmented_ge3_before = int(state_df.augmented_ge3_before.sum()); augmented_ge3_after = int(state_df.augmented_ge3_after.sum())
    # Coverage-only decision: any >=3 support loss or any removed episode is a
    # material loss for the pre-registered support>=3 Stage 4 panel.
    conclusion = "B COVERAGE_TOO_LOW_TARGETED_SOURCE_REVIEW_RECOMMENDED" if (primary_ge3_after < primary_ge3_before or augmented_ge3_after < augmented_ge3_before or not removed_df.empty) else "A SAFE_TO_FREEZE_AND_RUN_STAGE4"
    primary_removed_n = int(((episode_df.panel == "primary") & episode_df.episode_removed_after_exclusion).sum())
    augmented_removed_n = int(((episode_df.panel == "augmented") & episode_df.episode_removed_after_exclusion).sum())
    primary_retained_n = int(((episode_df.panel == "primary") & episode_df.has_excluded_long_window & episode_df.retained_by_other_non_long_window).sum())
    augmented_retained_n = int(((episode_df.panel == "augmented") & episode_df.has_excluded_long_window & episode_df.retained_by_other_non_long_window).sum())
    lines = ["# LONG_WINDOW_EXCLUSION_IMPACT", "", "This is a label-coverage audit only. The original Excel workbook was not modified; no attack outcomes, IP sensitivity, or H1–H4 results were read.", "", "## Rule applied", "", "- C_UNCONFIRMED_REVIEW_REQUIRED → `formal_positive = false`.", "- A_CONFIRMED_UNIFORM → `formal_positive = true`.", "- B/other reviewed long windows remain non-positive unless explicitly confirmed; no C window was upgraded.", "- Episode support is `nunique(episode_id)`, never a window-row count.", "- The derived `tables/frozen_exposure_view.csv` is not activated as a Stage 4 input by this audit.", "", "## Coverage impact", "", f"- Excluded C long windows: **{len(excluded_df):,}**.", f"- Primary windows: **{int(windows.use_primary.sum()):,} → {int(windows.use_primary_after_long_review.sum()):,}**; independent episodes: **{int(windows.loc[windows.use_primary, 'episode_id'].nunique()):,} → {int(windows.loc[windows.use_primary_after_long_review, 'episode_id'].nunique()):,}**.", f"- Augmented windows: **{int(windows.use_augmented.sum()):,} → {int(windows.use_augmented_after_long_review.sum()):,}**; independent episodes: **{int(windows.loc[windows.use_augmented, 'episode_id'].nunique()):,} → {int(windows.loc[windows.use_augmented_after_long_review, 'episode_id'].nunique()):,}**.", f"- States with ≥2/≥3/≥4 Primary episodes: **{int(state_df.primary_ge2_before.sum())}/{primary_ge3_before}/{int(state_df.primary_ge4_before.sum())} → {int(state_df.primary_ge2_after.sum())}/{primary_ge3_after}/{int(state_df.primary_ge4_after.sum())}**.", f"- States with ≥2/≥3/≥4 Augmented episodes: **{int(state_df.augmented_ge2_before.sum())}/{augmented_ge3_before}/{int(state_df.augmented_ge4_before.sum())} → {int(state_df.augmented_ge2_after.sum())}/{augmented_ge3_after}/{int(state_df.augmented_ge4_after.sum())}**.", "", "## Episode-level impact", "", f"- Completely removed episodes: Primary **{primary_removed_n}**, Augmented **{augmented_removed_n}** (panel-specific; see `LONG_WINDOW_REMOVED_EPISODES.csv`).", f"- Episodes retained by at least one other non-long window: Primary **{primary_retained_n}**, Augmented **{augmented_retained_n}** (see `LONG_WINDOW_EPISODE_IMPACT.csv` and per-window flags in `LONG_WINDOW_EXCLUDED_WINDOWS.csv`).", "", "## States crossing below support=3", ""]
    crossed = state_df[state_df.primary_crossed_ge3 | state_df.augmented_crossed_ge3]
    if crossed.empty:
        lines.append("None.")
    else:
        for _, r in crossed.iterrows():
            lines.append(f"- {r.state} ({r.admin1_iso}): Primary {int(r.primary_episode_n_before)}→{int(r.primary_episode_n_after)}; Augmented {int(r.augmented_episode_n_before)}→{int(r.augmented_episode_n_after)}.")
    lines += ["", "## Decision", "", f"**{conclusion}**", ""]
    if conclusion.startswith("B"):
        lines += ["The decision uses label coverage only. No C window was upgraded. Review `LONG_WINDOW_TARGETED_REVIEW_PRIORITY.csv`; ranking prioritizes states crossing below support=3, episode loss, official-source presence, and the possibility of recovering precise queue/sub-window evidence.", ""]
    else:
        lines += ["No support threshold or episode coverage is lost under this label-only exclusion. This does not authorize Stage 4 automatically; wait for explicit confirmation.", ""]
    (report / "LONG_WINDOW_EXCLUSION_IMPACT.md").write_text("\n".join(lines), encoding="utf-8")
    return {"conclusion": conclusion, "excluded_window_n": int(len(excluded_df)), "removed_episode_n": int(len(removed_df)), "primary_window_before": int(windows.use_primary.sum()), "primary_window_after": int(windows.use_primary_after_long_review.sum()), "primary_episode_before": int(windows.loc[windows.use_primary, "episode_id"].nunique()), "primary_episode_after": int(windows.loc[windows.use_primary_after_long_review, "episode_id"].nunique()), "augmented_window_before": int(windows.use_augmented.sum()), "augmented_window_after": int(windows.use_augmented_after_long_review.sum()), "augmented_episode_before": int(windows.loc[windows.use_augmented, "episode_id"].nunique()), "augmented_episode_after": int(windows.loc[windows.use_augmented_after_long_review, "episode_id"].nunique()), "primary_ge3_before": primary_ge3_before, "primary_ge3_after": primary_ge3_after, "augmented_ge3_before": augmented_ge3_before, "augmented_ge3_after": augmented_ge3_after}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-root", required=True, type=Path)
    args = ap.parse_args()
    print(run(args.stage_root.resolve()))


if __name__ == "__main__":
    main()
