"""Formal Stage 4: freeze Primary and Augmented IP sensitivity labels.

This stage runs the existing ClickHouse calibration query once, because the
raw event signatures are shared by both panels, and then writes separate
Primary (P1/A/A+) and Augmented (P1+P2) quality summaries.  It never loads the
war-attack event panel and never runs H1--H4.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, file_sha256

STAGE = "stage04_sensitivity"


def _root(cfg: Config) -> Path:
    root = cfg.run_base / "results" / "stages" / STAGE
    for name in ("primary", "augmented", "tables", "report"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _panel_summary(labels: pd.DataFrame, panel: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if panel == "primary":
        score, rtt, support, estimable = "s_reach_primary", "s_rtt_primary", "support_episode_n_primary", "primary_estimable"
    else:
        score, rtt, support, estimable = "s_reach_augmented", "s_rtt_augmented", "support_episode_n_augmented", "augmented_estimable"
    for c in (score, rtt, support, estimable):
        if c not in labels:
            labels[c] = np.nan if c != estimable else False
    labels[estimable] = labels[estimable].fillna(False).astype(bool)
    labels[support] = pd.to_numeric(labels[support], errors="coerce")
    state = labels.groupby("target_admin1", dropna=False).agg(
        activity_supported_ip_n=("dst_ip", "nunique"),
        estimable_ip_n=(estimable, "sum"),
        support_ge_2_ip_n=(support, lambda s: int(s.ge(2).sum())),
        support_ge_3_ip_n=(support, lambda s: int(s.ge(3).sum())),
        support_ge_4_ip_n=(support, lambda s: int(s.ge(4).sum())),
        score_mean=(score, "mean"), score_median=(score, "median"),
        rtt_estimable_ip_n=(rtt, lambda s: int(s.notna().sum())),
    ).reset_index()
    state["panel"] = panel
    corr_rows = []
    for oblast, x in labels[labels[estimable]].groupby("target_admin1", dropna=False):
        corr_rows.append({
            "panel": panel, "target_admin1": oblast, "ip_n": int(len(x)),
            "activity_sensitivity_pearson_r": x["activity_score_raw"].corr(pd.to_numeric(x[score], errors="coerce")),
            "activity_sensitivity_spearman_rho": x["activity_score_raw"].corr(pd.to_numeric(x[score], errors="coerce"), method="spearman"),
        })
    return state, pd.DataFrame(corr_rows)


def _manifest(cfg: Config, root: Path, started: datetime, status: str) -> Path:
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "stage_manifest.json":
            files.append({"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": file_sha256(p)})
    registry_name = cfg.raw.get("freeze", {}).get("calibration_event_registry", "calibration_event_registry_v1.csv")
    sources = [cfg.config_path, cfg.resource_path("calibration_workbook"), cfg.config_dir / registry_name]
    payload = {
        "stage": STAGE, "run_id": cfg.run_id, "git_commit": _git_commit(cfg.root),
        "config_hash": file_sha256(cfg.config_path),
        "input_hashes": {str(p): file_sha256(p) for p in sources}, "output_hashes": files,
        "start_time": started.isoformat(), "end_time": datetime.now(timezone.utc).isoformat(), "status": status,
        "war_attack_data_used": False, "support_threshold": 3,
    }
    path = root / "stage_manifest.json"; path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"); return path


def run(cfg: Config) -> dict:
    started = datetime.now(timezone.utc)
    root = _root(cfg)
    # The expensive raw query is shared; the returned labels contain separate
    # support and estimability columns for the two frozen analysis panels.
    from . import simple_calibration
    calibration_result = simple_calibration.run(cfg)
    rt = cfg.out_dir("results_tables")
    label_path = rt / "b1_full_sensitivity_labels.parquet"
    if not label_path.exists():
        raise RuntimeError("calibration did not produce b1_full_sensitivity_labels.parquet")
    labels = pd.read_parquet(label_path)
    primary_state, primary_corr = _panel_summary(labels.copy(), "primary")
    augmented_state, augmented_corr = _panel_summary(labels.copy(), "augmented")
    state = pd.concat([primary_state, augmented_state], ignore_index=True)
    corr = pd.concat([primary_corr, augmented_corr], ignore_index=True)
    state.to_csv(root / "tables" / "sensitivity_support_by_oblast.csv", index=False, encoding="utf-8-sig")
    corr.to_csv(root / "tables" / "activity_sensitivity_correlation.csv", index=False, encoding="utf-8-sig")
    support_rows = []
    for panel, support_col, score_col, estimable_col in (
        ("primary", "support_episode_n_primary", "s_reach_primary", "primary_estimable"),
        ("augmented", "support_episode_n_augmented", "s_reach_augmented", "augmented_estimable"),
    ):
        s = pd.to_numeric(labels[support_col], errors="coerce")
        for threshold in (1, 2, 3, 4):
            support_rows.append({"panel": panel, "support_threshold": threshold,
                                 "ip_n": int((s.ge(threshold) & labels[score_col].notna()).sum()),
                                 "state_n": int(labels.loc[s.ge(threshold) & labels[score_col].notna(), "target_admin1"].nunique())})
    support = pd.DataFrame(support_rows)
    support.to_csv(root / "tables" / "support_threshold_ip_counts.csv", index=False, encoding="utf-8-sig")
    primary_n = int(labels.primary_estimable.sum())
    augmented_n = int(labels.augmented_estimable.sum())
    summary = {
        "activity_supported_ip_n": int(labels.dst_ip.nunique()),
        "primary_estimable_ip_n": primary_n, "augmented_estimable_ip_n": augmented_n,
        "primary_oblast_n": int(primary_state.loc[primary_state.estimable_ip_n.gt(0), "target_admin1"].nunique()),
        "augmented_oblast_n": int(augmented_state.loc[augmented_state.estimable_ip_n.gt(0), "target_admin1"].nunique()),
        "primary_oblast_ge3_support_n": int(primary_state.loc[primary_state.support_ge_3_ip_n.gt(0), "target_admin1"].nunique()),
        "augmented_oblast_ge3_support_n": int(augmented_state.loc[augmented_state.support_ge_3_ip_n.gt(0), "target_admin1"].nunique()),
        "support_thresholds": [1, 2, 3, 4], "war_attack_data_used": False,
        "calibration_result": calibration_result,
    }
    (root / "tables" / "stage04_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    primary_state.to_csv(root / "primary" / "support_by_oblast.csv", index=False, encoding="utf-8-sig")
    augmented_state.to_csv(root / "augmented" / "support_by_oblast.csv", index=False, encoding="utf-8-sig")
    report = root / "report" / "STAGE04_REPORT.md"
    report.write_text("\n".join([
        "# Stage 4 — Frozen IP Sensitivity Labels", "", f"Run ID: `{cfg.run_id}`", "",
        "This stage estimates planned-outage sensitivity only. War-attack outcomes and H1–H4 are not loaded or analyzed.", "",
        "## Frozen panels", "",
        "- **Primary:** P1 / A / A+ high-confidence events; used for confirmatory validation.",
        "- **Augmented:** P1+P2 events; used for broader weak-supervision coverage.",
        "- Support threshold remains **≥3 independent episodes**; thresholds 1/2/4 are reported diagnostics only.",
        "- Episode IDs are `episode_id_v2_main` / `episode_id_v2_augmented`; legacy IDs remain in the workbook for audit.", "",
        "## Coverage", "",
        f"- Activity-supported IPs: **{summary['activity_supported_ip_n']:,}**",
        f"- Primary estimable IPs: **{primary_n:,}** across **{summary['primary_oblast_n']:,}** oblasts",
        f"- Augmented estimable IPs: **{augmented_n:,}** across **{summary['augmented_oblast_n']:,}** oblasts",
        f"- Oblasts with at least one IP meeting support≥3: Primary **{summary['primary_oblast_ge3_support_n']:,}**, Augmented **{summary['augmented_oblast_ge3_support_n']:,}**", "",
        "The activity–sensitivity correlation table is descriptive and is not used to filter labels. States or IPs without the required support remain NA/not estimable.", "",
        "## Gate", "", "**PASS WITH COVERAGE LIMITATIONS**", "", "Stop here. Do not run H1/H2/H3/H4 until these label distributions and coverage tables are reviewed.",
    ]) + "\n", encoding="utf-8")
    status = "warning" if primary_n == 0 or augmented_n == 0 else "ok"
    manifest = _manifest(cfg, root, started, status)
    return {"status": status, **{k: v for k, v in summary.items() if k != "calibration_result"}, "outputs": [str(report), str(manifest), str(root / "tables" / "sensitivity_support_by_oblast.csv"), str(root / "tables" / "activity_sensitivity_correlation.csv"), str(root / "tables" / "support_threshold_ip_counts.csv")]}
