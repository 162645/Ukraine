"""Formal Stage 0: measurement-quality artifacts and gate.

This stage deliberately stops at acquisition quality.  It does not build the
target universe, Activity, calibration labels, or any H1--H4 outcome.  The
cycle audit is reused only as the raw acquisition ledger; all deliverables are
written under the immutable stage-specific directory.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import audit
from .config import Config, file_sha256
from .db import CHClient
from .progress import get_logger, step


STAGE = "stage00_quality"


def _stage_root(cfg: Config) -> Path:
    root = cfg.run_base / "results" / "stages" / STAGE
    for name in ("tables", "figures", "figure_data", "diagnostics", "report"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _save_figure(fig, path: Path) -> list[str]:
    outputs = []
    for ext in ("png", "pdf", "svg"):
        out = path.with_suffix(f".{ext}")
        fig.savefig(out, dpi=220 if ext == "png" else None, bbox_inches="tight")
        outputs.append(str(out))
    return outputs


def _run_lengths(mask: pd.Series) -> list[int]:
    values = mask.astype(bool).to_numpy()
    lengths: list[int] = []
    current = 0
    for value in values:
        if value:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return lengths


def _core_event_quality(cfg: Config, cq: pd.DataFrame) -> pd.DataFrame:
    """Report acquisition coverage around registered core attacks only.

    Event labels are never used to decide whether a cycle is complete.  They
    are included here solely for the Stage-0 gate requested by the protocol.
    """
    try:
        events = cfg.load_event_registry()
    except Exception:
        return pd.DataFrame(columns=["event_id", "anchor_utc", "expected_cycle_n",
                                     "complete_cycle_n", "complete_ratio"])
    core = events[(events.get("analysis_ready", 0).astype(str).isin(["1", "True", "true"])) &
                  events.get("analysis_role", "").astype(str).str.contains("attack|blind", regex=True)]
    if core.empty:
        return pd.DataFrame(columns=["event_id", "anchor_utc", "expected_cycle_n",
                                     "complete_cycle_n", "complete_ratio"])
    rows = []
    times = pd.to_datetime(cq["measure_time"], utc=True)
    for _, event in core.iterrows():
        anchor = pd.to_datetime(event.get("primary_anchor_utc"), utc=True, errors="coerce")
        if pd.isna(anchor):
            continue
        lo, hi = anchor - pd.Timedelta(hours=24), anchor + pd.Timedelta(hours=72)
        window = cq[(times >= lo) & (times <= hi)]
        expected = int(round((hi - lo).total_seconds() / (2 * 3600))) + 1
        complete = int(window["is_complete"].astype(bool).sum())
        rows.append({"event_id": str(event.get("event_id", "")), "anchor_utc": anchor,
                     "expected_cycle_n": expected, "observed_cycle_n": int(len(window)),
                     "complete_cycle_n": complete,
                     "complete_ratio": complete / expected if expected else np.nan})
    return pd.DataFrame(rows)


def _write_metadata(root: Path, name: str, *, figure_id: str, source_csv: Path,
                    x_axis: str, y_axis: str, line_or_color: str, aggregation: str,
                    sample_definition: str, event_set: str, baseline_definition: str,
                    thresholds: dict, cfg: Config) -> Path:
    p = root / "figure_data" / f"{name}.meta.json"
    payload = {"figure_id": figure_id, "stage": STAGE,
               "hypothesis": "measurement quality only; no H1-H4 claim",
               "source_csv": str(source_csv), "x_axis": x_axis, "y_axis": y_axis,
               "line_or_color": line_or_color, "aggregation": aggregation,
               "sample_definition": sample_definition, "event_set": event_set,
               "baseline_definition": baseline_definition, "thresholds": thresholds,
               "git_commit": _git_commit(cfg.root), "run_id": cfg.run_id}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return p


def _git_commit(root: Path) -> str | None:
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root),
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _render_figures(cfg: Config, root: Path, cycle: pd.DataFrame, daily: pd.DataFrame) -> list[str]:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.colors import Normalize

    outputs: list[str] = []
    plt.rcParams.update({"font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8,
                         "xtick.labelsize": 7, "ytick.labelsize": 7, "svg.fonttype": "none"})

    # S0-1: incomplete cycles are never joined into the response line.
    src = root / "figure_data" / "fig_S0_1_measurement_response_timeline.csv"
    cycle[["measure_time", "responsive_ip_n", "is_complete", "import_status",
           "failure_reason"]].to_csv(src, index=False, encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(7.0, 2.8))
    t = pd.to_datetime(cycle.measure_time, utc=True)
    y = cycle.responsive_ip_n.where(cycle.is_complete.astype(bool))
    ax.plot(t, y, color="#2c5f8a", lw=0.8, label="Complete cycle")
    bad = ~cycle.is_complete.astype(bool)
    if bad.any():
        ax.scatter(t[bad], cycle.loc[bad, "responsive_ip_n"], marker="x", s=14,
                   color="#777777", label="Incomplete cycle", zorder=3)
    ax.set_xlabel("UTC measurement time")
    ax.set_ylabel("Responsive IP count")
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m", tz=timezone.utc))
    ax.grid(axis="y", color="#dddddd", lw=0.4)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    fig.autofmt_xdate(); fig.tight_layout()
    outputs += _save_figure(fig, root / "figures" / "fig_S0_1_measurement_response_timeline")
    plt.close(fig)
    _write_metadata(root, "fig_S0_1_measurement_response_timeline", figure_id="S0-1",
                    source_csv=src, x_axis="UTC measurement time", y_axis="responsive IP count",
                    line_or_color="complete line; incomplete x marker", aggregation="one point per 2h cycle",
                    sample_definition="nominal study cycles", event_set="none for gate",
                    baseline_definition="none", thresholds={}, cfg=cfg)

    # S0-2: daily count with the theoretical 12-cycle reference.
    src = root / "figure_data" / "fig_S0_2_daily_cycle_completeness.csv"
    daily.to_csv(src, index=False, encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(7.0, 2.8))
    ax.bar(pd.to_datetime(daily["date"]), daily["complete_cycle_n"], width=0.85,
           color="#4c78a8", edgecolor="none")
    ax.axhline(12, color="#777777", ls="--", lw=0.7)
    ax.set_xlabel("UTC date"); ax.set_ylabel("Complete 2h cycles per day")
    ax.set_ylim(0, 12.8); ax.grid(axis="y", color="#dddddd", lw=0.4)
    fig.tight_layout()
    outputs += _save_figure(fig, root / "figures" / "fig_S0_2_daily_cycle_completeness")
    plt.close(fig)
    _write_metadata(root, "fig_S0_2_daily_cycle_completeness", figure_id="S0-2",
                    source_csv=src, x_axis="UTC date", y_axis="complete 2h cycles per day",
                    line_or_color="bars; y=12 reference", aggregation="daily count",
                    sample_definition="nominal study cycles", event_set="none",
                    baseline_definition="none", thresholds={"theoretical_daily_max": 12}, cfg=cfg)

    # S0-3: day-of-month × month fraction matrix.  Missing days remain NA/gray.
    src = root / "figure_data" / "fig_S0_3_cycle_completeness_matrix.csv"
    matrix = daily.copy()
    dt = pd.to_datetime(matrix["date"], utc=True)
    matrix["month"] = dt.dt.strftime("%Y-%m")
    matrix["day"] = dt.dt.day
    matrix["complete_fraction"] = matrix["complete_cycle_n"] / matrix["total_cycle_n"].replace(0, np.nan)
    matrix.to_csv(src, index=False, encoding="utf-8-sig")
    piv = matrix.pivot(index="month", columns="day", values="complete_fraction")
    fig, ax = plt.subplots(figsize=(7.0, max(2.8, 0.22 * len(piv))))
    cmap = plt.get_cmap("YlGn").copy(); cmap.set_bad("#d9d9d9")
    ax.imshow(piv.to_numpy(dtype=float), aspect="auto", cmap=cmap, norm=Normalize(0, 1), interpolation="none")
    ax.set_xlabel("Day of month"); ax.set_ylabel("Month")
    ax.set_xticks(range(len(piv.columns)), [str(x) for x in piv.columns])
    ax.set_yticks(range(len(piv.index)), piv.index)
    fig.colorbar(ax.images[0], ax=ax, label="Complete-cycle fraction")
    fig.tight_layout()
    outputs += _save_figure(fig, root / "figures" / "fig_S0_3_cycle_completeness_matrix")
    plt.close(fig)
    _write_metadata(root, "fig_S0_3_cycle_completeness_matrix", figure_id="S0-3",
                    source_csv=src, x_axis="day of month", y_axis="month",
                    line_or_color="complete-cycle fraction; gray=NA", aggregation="daily fraction",
                    sample_definition="nominal study cycles", event_set="none",
                    baseline_definition="none", thresholds={"daily_expected_cycles": 12}, cfg=cfg)
    return outputs


def _write_stage_manifest(cfg: Config, root: Path, *, start: datetime,
                          end: datetime, status: str, input_paths: list[Path]) -> Path:
    def inventory() -> list[dict]:
        rows = []
        for p in sorted(x for x in root.rglob("*") if x.is_file() and x.name != "stage_manifest.json"):
            rows.append({"path": str(p.relative_to(root)), "bytes": p.stat().st_size,
                         "sha256": file_sha256(p)})
        return rows
    manifest = {"stage": STAGE, "run_id": cfg.run_id, "git_commit": _git_commit(cfg.root),
                "config_hash": file_sha256(cfg.config_path),
                "event_registry_hash": file_sha256(cfg.resource_path("event_registry")),
                "input_hashes": {str(p): file_sha256(p) for p in input_paths if p.exists()},
                "output_hashes": inventory(), "start_time": start.isoformat(),
                "end_time": end.isoformat(), "elapsed_seconds": (end - start).total_seconds(),
                "status": status}
    p = root / "stage_manifest.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def run(cfg: Config) -> dict:
    root = _stage_root(cfg)
    started = datetime.now(timezone.utc)
    logger = get_logger(cfg.out_dir("logs"))
    with step("Stage 0: measurement quality", logger):
        with CHClient(cfg) as ch:
            cycle = audit.run_cycle_audit(cfg, ch, persist=False)
    cycle = cycle.copy()
    cycle["measure_time"] = pd.to_datetime(cycle["measure_time"], utc=True)
    cycle["responsive_ip_n"] = pd.to_numeric(cycle.get("ping_unique_ips", 0), errors="coerce").fillna(0).astype("int64")
    cycle["import_status"] = cycle.get("import_status", "unknown").fillna("unknown").astype(str)
    cycle["failure_reason"] = cycle.get("exclusion_reason", "").fillna("").astype(str)
    # When the configured study envelope is wider than the actually observed
    # Ping span, cycles outside that support are not acquisition failures.  The
    # formal quality denominator follows support_inference=observed_ping_span;
    # keep the excluded count for transparent reporting.
    outside_support = cycle["failure_reason"].str.contains("outside_observed_support", na=False)
    support_excluded_n = int(outside_support.sum())
    if str(cfg.study.get("support_inference", "")).strip() == "observed_ping_span":
        cycle = cycle.loc[~outside_support].copy()
    required = ["cycle_id", "measure_time", "is_complete", "responsive_ip_n",
                "import_file_n", "import_status", "failure_reason"]
    cycle["import_file_n"] = (cycle["import_status"].ne("unknown")).astype("int8")
    cycle_out = cycle[[c for c in required if c in cycle]].copy()
    cycle_out.to_csv(root / "tables" / "stage00_cycle_quality.csv", index=False, encoding="utf-8-sig")

    dates = cycle_out["measure_time"].dt.floor("D")
    daily = (cycle_out.assign(date=dates.dt.strftime("%Y-%m-%d"))
             .groupby("date", as_index=False)
             .agg(total_cycle_n=("cycle_id", "size"), complete_cycle_n=("is_complete", "sum"),
                  responsive_ip_n_min=("responsive_ip_n", "min"), responsive_ip_n_max=("responsive_ip_n", "max")))
    daily["complete_fraction"] = daily["complete_cycle_n"] / daily["total_cycle_n"].replace(0, np.nan)
    daily.to_csv(root / "tables" / "stage00_daily_quality.csv", index=False, encoding="utf-8-sig")

    missing = cycle_out[~cycle_out["is_complete"].astype(bool)].copy()
    missing.to_csv(root / "diagnostics" / "stage00_missing_cycles.csv", index=False, encoding="utf-8-sig")
    complete = cycle_out[cycle_out["is_complete"].astype(bool)].copy()
    low_cut = float(complete["responsive_ip_n"].quantile(float(cfg.quality.get("stage00_low_response_quantile", 0.05)))) if not complete.empty else np.nan
    low = complete[complete["responsive_ip_n"] <= low_cut].copy() if np.isfinite(low_cut) else complete.iloc[0:0]
    low.to_csv(root / "diagnostics" / "stage00_low_response_complete_cycles.csv", index=False, encoding="utf-8-sig")
    event_quality = _core_event_quality(cfg, cycle_out)
    event_quality.to_csv(root / "diagnostics" / "stage00_core_event_quality.csv", index=False, encoding="utf-8-sig")

    missing_lengths = _run_lengths(~cycle_out["is_complete"].astype(bool))
    longest_missing = max(missing_lengths, default=0)
    completion_rate = float(cycle_out["is_complete"].mean()) if len(cycle_out) else 0.0
    core_min = float(event_quality["complete_ratio"].min()) if not event_quality.empty else np.nan
    max_missing = int(cfg.quality.get("stage00_max_consecutive_missing", 6))
    min_event_ratio = float(cfg.quality.get("stage00_min_core_event_complete_ratio", cfg.quality.get("min_event_window_complete_ratio", .75)))
    fail_reasons = []
    if longest_missing >= max_missing:
        fail_reasons.append(f"longest consecutive incomplete run={longest_missing} >= {max_missing}")
    if np.isfinite(core_min) and core_min < min_event_ratio:
        fail_reasons.append(f"core-event window minimum completion={core_min:.3f} < {min_event_ratio:.3f}")
    status = "FAIL" if fail_reasons else ("WARNING" if len(missing) else "PASS")
    figure_outputs = _render_figures(cfg, root, cycle_out, daily)
    report = root / "report" / "STAGE00_REPORT.md"
    report.write_text("\n".join([
        f"# Stage 0 — Measurement Quality ({status})", "",
        f"Run ID: `{cfg.run_id}`", "",
        "## Key statistics", "",
        f"- Total nominal cycles: **{len(cycle_out):,}**",
        f"- Cycles outside observed Ping support excluded from the denominator: **{support_excluded_n:,}**",
        f"- Complete cycles: **{int(cycle_out.is_complete.sum()):,}**",
        f"- Incomplete cycles: **{int((~cycle_out.is_complete.astype(bool)).sum()):,}**",
        f"- Completion rate: **{completion_rate:.3%}**",
        f"- Longest consecutive incomplete run: **{longest_missing} cycles**",
        f"- Minimum responsive IP count among complete cycles: **{int(complete.responsive_ip_n.min()) if not complete.empty else 'NA'}**",
        f"- Complete cycles in the low-response diagnostic tail (q05): **{len(low):,}**",
        f"- Minimum core-attack window completion: **{core_min:.3%}**" if np.isfinite(core_min) else "- Core-attack window completion: **not available**",
        "", "## Interpretation", "",
        "A missing target response row inside an import-complete full scan is retained as a true non-response; only acquisition-ledger incompleteness marks a cycle incomplete. Low response in a complete cycle is a diagnostic, not a failure.",
        "", "## Gate", "",
        f"**{status}**" + (" — " + "; ".join(fail_reasons) if fail_reasons else ""),
        "", "## Figures", "",
        "- Figure S0-1: measurement response timeline",
        "- Figure S0-2: daily cycle completeness",
        "- Figure S0-3: cycle completeness matrix",
        "", "Visual review status: `rendered_not_visually_reviewed` until the PNG/SVG are opened at final paper size.",
    ]) + "\n", encoding="utf-8")
    ended = datetime.now(timezone.utc)
    manifest = _write_stage_manifest(cfg, root, start=started, end=ended, status=status,
                                     input_paths=[cfg.config_path, cfg.resource_path("event_registry")])
    outputs = [str(p) for p in [root / "tables" / "stage00_cycle_quality.csv",
                                root / "tables" / "stage00_daily_quality.csv",
                                root / "diagnostics" / "stage00_missing_cycles.csv",
                                root / "diagnostics" / "stage00_low_response_complete_cycles.csv",
                                root / "diagnostics" / "stage00_core_event_quality.csv", report, manifest]] + figure_outputs
    return {"status": "warning" if status == "WARNING" else ("failed" if status == "FAIL" else "ok"),
            "gate": status, "outputs": outputs, "total_cycles": len(cycle_out),
            "complete_cycles": int(cycle_out.is_complete.sum()), "missing_cycles": int(len(missing)),
            "completion_rate": completion_rate, "longest_missing_run": longest_missing,
            "core_event_min_completion": core_min, "report": str(report)}
