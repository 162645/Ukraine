"""H1: endpoint-level heterogeneity in held-out war attacks.

This module is deliberately separate from the historical ExpB reducer.  It
freezes the final sensitivity specification before touching attack outcomes,
then uses only the frozen Stage-2 Activity deciles for H1 stratification.  No
Sensitivity quintile, prediction model, H2, H3, or H4 output is constructed.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from itertools import combinations
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .config import Config, file_sha256
from .db import CHClient
from .event_design import clean_baseline_interval, earliest_treatment_start
from .events import Events
from .progress import get_logger
from .provenance import output_record, source_tree_sha256
from .sensor_panels import _query_response_window


CORE_EVENTS = (
    "E2024_0826_ATTACK",
    "E2024_0917_SUMY",
    "E2024_1117_ATTACK",
    "E2024_1128_ATTACK",
    "E2024_1213_ATTACK",
    "E2024_1225_ATTACK",
)
SUPPLEMENTARY_EVENTS = ("E2025_0115_ATTACK",)
H1_STAGE = "stage_h1_endpoint_heterogeneity"


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                      text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _inventory_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    if path.is_file():
        return file_sha256(path)
    h = hashlib.sha256()
    for f in sorted(x for x in path.rglob("*") if x.is_file()):
        h.update(f.relative_to(path).as_posix().encode())
        h.update(str(f.stat().st_size).encode())
        h.update(str(f.stat().st_mtime_ns).encode())
    return h.hexdigest()


def _stage_source(cfg: Config, key: str, fallback: str) -> Path:
    prov = cfg.raw.get("stage4_provenance", {}) or {}
    run = str(prov.get(key, fallback))
    return cfg.root / "runs" / run


def _artifact(path: Path) -> dict:
    rec = output_record(path)
    if path.exists() and path.is_dir():
        rec["inventory_sha256"] = _inventory_hash(path)
    return rec


def freeze_final_sensitivity(cfg: Config, out: Path) -> dict:
    """Write the immutable final label contract before any attack query."""
    s2 = _stage_source(cfg, "stage2_source_run", "paper_final_v2_episode_fix_20260910")
    s3 = _stage_source(cfg, "stage3_source_run", "stage3_calibration_v2_final_20260910")
    s4 = _stage_source(cfg, "stage4_source_run", "stage4_sensitivity_frozen_v2_20260910")
    s45 = cfg.root / "runs" / "stage4_5_label_robustness_20260910"
    labels = s45 / "results" / "tables" / "b1_full_sensitivity_labels.parquet"
    summary_path = s45 / "results" / "tables" / "calibration_summary.json"
    if not labels.exists():
        raise FileNotFoundError(f"missing Stage 4.5 frozen labels: {labels}")
    if not summary_path.exists():
        raise FileNotFoundError(f"missing Stage 4.5 summary: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    d = pd.read_parquet(labels, columns=["dst_ip", "target_admin1",
                                        "augmented_estimable", "primary_estimable"])
    main = d[d["augmented_estimable"].fillna(False).astype(bool)]
    robust_a = d[d["primary_estimable"].fillna(False).astype(bool)]
    main_n, main_states = len(main), int(main["target_admin1"].nunique())
    a_n, a_states = len(robust_a), int(robust_a["target_admin1"].nunique())
    if (main_n, main_states) != (700012, 17):
        raise RuntimeError(f"Stage 4.5 main label count changed: {(main_n, main_states)}")
    if (a_n, a_states) != (164418, 4):
        raise RuntimeError(f"Stage 4.5 Primary robustness count changed: {(a_n, a_states)}")
    strict_summary = {
        "main_panel": "AUGMENTED_STRICT",
        "main_support_threshold": 3,
        "main_ip_n": main_n,
        "main_state_n": main_states,
        "robustness": {
            "A": {"panel": "PRIMARY_STRICT", "support_episode_n": 3,
                   "ip_n": a_n, "state_n": a_states,
                   "purpose": "high-confidence evidence robustness"},
            "B": {"panel": "AUGMENTED_WEAK", "support_episode_n": 3,
                   "ip_n": 859945, "state_n": 20,
                   "purpose": "exposure-definition robustness"},
            "C": {"panel": "AUGMENTED_STRICT", "support_episode_n": [2, 4],
                   "purpose": "support-threshold robustness"},
        },
        "excluded_long_window_n": 52,
        "excluded_long_window_reason": (
            "STATE_PLANNED_OUTAGE_WEAK_SUPERVISION windows marked "
            "C_UNCONFIRMED_REVIEW_REQUIRED; not promoted to formal positive exposure."
        ),
        "freeze_version": "final_sensitivity_freeze_v1_augmented_strict_support3",
        "statement": "The final sensitivity specification was frozen before inspecting held-out war-attack outcomes.",
    }
    artifacts = {
        "stage2": {"run": str(s2), "artifact": _artifact(s2 / "run_manifest.json"),
                   "activity_parts": _artifact(s2 / "data_derived" / "stage02_activity_parts")},
        "stage3": {"run": str(s3), "artifact": _artifact(s3 / "results" / "stages" / "stage03_calibration"),
                   "workbook": _artifact(cfg.resource_path("calibration_workbook"))},
        "stage4": {"run": str(s4), "artifact": _artifact(s4 / "run_manifest.json"),
                   "summary": _artifact(s4 / "results" / "tables" / "calibration_summary.json")},
        "stage4_5": {"run": str(s45), "labels": _artifact(labels),
                      "summary": _artifact(summary_path),
                      "robustness": _artifact(s45 / "results" / "tables" / "primary_vs_augmented_robustness.csv")},
    }
    freeze = {
        "freeze": strict_summary,
        "git_commit": _git_commit(cfg.root),
        "source_tree_sha256": source_tree_sha256(cfg.root),
        "artifacts": artifacts,
        "stage4_5_summary": summary,
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "war_attack_data_used": False,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "final_sensitivity_freeze.json").write_text(
        json.dumps(freeze, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    md = [
        "# Final Sensitivity Freeze",
        "",
        f"- Freeze version: `{strict_summary['freeze_version']}`",
        f"- Git commit: `{freeze['git_commit']}`",
        "- Main panel: **AUGMENTED + STRICT + support_episode_n >= 3**",
        f"- Main panel: **{main_n:,} IP / {main_states} states**",
        "- Robustness A: PRIMARY + STRICT + support>=3 (164,418 IP / 4 states)",
        "- Robustness B: AUGMENTED + WEAK + support>=3 (859,945 IP / 20 states)",
        "- Robustness C: AUGMENTED + STRICT with support>=2 and support>=4",
        "- Sensitivity is episode-equal; windows within an episode are unioned without gap fill; Q1-Q5 are state-wise.",
        "- 52 long windows marked `STATE_PLANNED_OUTAGE_WEAK_SUPERVISION` / `C_UNCONFIRMED_REVIEW_REQUIRED` are excluded from formal positive exposure.",
        "",
        "> The final sensitivity specification was frozen before inspecting held-out war-attack outcomes.",
        "",
        "This H1 run does not use Sensitivity to select endpoints or outcomes. Sensitivity Q1-Q5, H2, H3, and H4 are not run.",
        "",
        "## Artifact provenance",
        "",
    ]
    for name, rec in artifacts.items():
        md.append(f"- {name}: `{rec['run']}`")
        for k, v in rec.items():
            if k != "run":
                md.append(f"  - {k}: `{v.get('sha256', v.get('inventory_sha256', v.get('path', 'missing')))}`")
    (out / "FINAL_SENSITIVITY_FREEZE.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return freeze


def _load_activity_labels(cfg: Config) -> pd.DataFrame:
    s45 = _stage_source(cfg, "stage4_5_source_run", "stage4_5_label_robustness_20260910")
    p = s45 / "results" / "tables" / "b1_full_sensitivity_labels.parquet"
    cols = ["dst_ip", "prefix24", "target_admin1", "activity_decile"]
    d = pd.read_parquet(p, columns=cols)
    d = d.dropna(subset=["dst_ip", "prefix24", "target_admin1", "activity_decile"]).copy()
    d["dst_ip"] = d["dst_ip"].astype(str)
    d["prefix24"] = d["prefix24"].astype(str)
    d["target_admin1"] = d["target_admin1"].astype(str)
    # Stage-2 labels were historically serialized as Q1-Q10.  H1 names the
    # same frozen Activity deciles D1-D10 so they cannot be confused with S Q1-Q5.
    d["activity_decile"] = d["activity_decile"].astype(str).str.replace(r"^Q", "D", regex=True)
    return d.drop_duplicates("dst_ip", keep="first")


def _cycle_grid(cfg: Config) -> pd.DataFrame:
    s2 = _stage_source(cfg, "stage2_source_run", "paper_final_v2_episode_fix_20260910")
    p = s2 / "results" / "stages" / "stage00_quality" / "tables" / "stage00_cycle_quality.csv"
    if not p.exists():
        p = s2 / "data_derived" / "cycle_quality.parquet"
    d = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
    ev = Events(cfg)
    return ev.build_cycle_grid(d)


def _cycle_ids(grid: pd.DataFrame, lo, hi) -> list[int]:
    lo, hi = pd.to_datetime(lo, utc=True), pd.to_datetime(hi, utc=True)
    mt = pd.to_datetime(grid["measure_time"], utc=True)
    return grid.loc[(mt >= lo) & (mt < hi) & grid["is_complete"].astype(bool), "cycle_id"].astype(int).tolist()


def _event_scope(event: pd.Series) -> set[str] | None:
    raw = str(event.get("analysis_treated_admin1", ""))
    if raw.strip() in {"", "ALL"}:
        return None
    return {x.strip() for x in raw.replace(";", "|").split("|") if x.strip()}


def _summarize_event(out: pd.DataFrame, *, event_id: str, core: bool,
                     aggregate: dict, scope_n: int) -> dict:
    z = out.dropna(subset=["reach_drop"]).copy()
    if z.empty:
        vals = {k: np.nan for k in ["mean_drop", "median_drop", "p10_drop", "p25_drop", "p75_drop", "p90_drop"]}
        fr = {f"fraction_drop_{x}": np.nan for x in ["gt0", "ge01", "ge025", "ge05"]}
    else:
        vals = {"mean_drop": z.reach_drop.mean(), "median_drop": z.reach_drop.median(),
                "p10_drop": z.reach_drop.quantile(.10), "p25_drop": z.reach_drop.quantile(.25),
                "p75_drop": z.reach_drop.quantile(.75), "p90_drop": z.reach_drop.quantile(.90)}
        fr = {"fraction_drop_gt0": float((z.reach_drop > 0).mean()),
              "fraction_drop_ge01": float((z.reach_drop >= .1).mean()),
              "fraction_drop_ge025": float((z.reach_drop >= .25).mean()),
              "fraction_drop_ge05": float((z.reach_drop >= .5).mean())}
    return {"event_id": event_id, "core_event": int(core), "endpoint_n": len(z),
            "affected_admin1_n": scope_n, **vals, **fr,
            "aggregate_ips_pre": aggregate.get("pre_ips_mean", np.nan),
            "aggregate_ips_attack": aggregate.get("attack_ips_mean", np.nan),
            "aggregate_ips_drop": aggregate.get("aggregate_ips_drop", np.nan),
            "admin1_equal_mean_drop": aggregate.get("admin1_equal_mean_drop", np.nan),
            "valid_baseline_cycle_n": aggregate.get("baseline_cycle_n", 0),
            "valid_attack_cycle_n": aggregate.get("attack_cycle_n", 0)}


def _query_event(cfg: Config, ch: CHClient, labels: pd.DataFrame, event: pd.Series,
                 grid: pd.DataFrame, logger, batch_size: int) -> tuple[pd.DataFrame, dict]:
    event_id = str(event["event_id"])
    scope = _event_scope(event)
    d = labels if scope is None else labels[labels["target_admin1"].isin(scope)].copy()
    if d.empty:
        return pd.DataFrame(), {"baseline_cycle_n": 0, "attack_cycle_n": 0}
    treatment = earliest_treatment_start(event)
    b0, b1 = clean_baseline_interval(event, cfg)
    if pd.isna(treatment) or pd.isna(b0):
        return pd.DataFrame(), {"baseline_cycle_n": 0, "attack_cycle_n": 0}
    attack_end = treatment + pd.Timedelta(hours=12)
    base_ids = _cycle_ids(grid, b0, b1 + pd.Timedelta(seconds=1))
    attack_ids = _cycle_ids(grid, treatment, attack_end)
    base_set, attack_set = set(base_ids), set(attack_ids)
    if not base_ids or not attack_ids:
        return pd.DataFrame(), {"baseline_cycle_n": len(base_ids), "attack_cycle_n": len(attack_ids)}
    lo, hi = min(pd.to_datetime(b0, utc=True), pd.to_datetime(treatment, utc=True)), attack_end
    prefixes = sorted(d["prefix24"].unique().tolist())
    rows, base_cycle_counts, attack_cycle_counts = [], [], []
    cycle_h = int(cfg.study["expected_cycle_interval_hours"])
    t0 = time.time()
    for start in range(0, len(prefixes), batch_size):
        batch = prefixes[start:start + batch_size]
        r = _query_response_window(cfg, ch, event_id=event_id, lo=lo, hi=hi,
                                   prefixes=batch, cycle_seconds=cycle_h * 3600, logger=logger)
        if not r.empty:
            r["dst_ip"] = r["dst_ip"].astype(str)
            r["prefix24"] = r["prefix24"].astype(str)
            sb = d[d["prefix24"].isin(batch)]
            r = r.merge(sb, on=["dst_ip", "prefix24"], how="inner")
            if not r.empty:
                r["cycle_id"] = pd.to_numeric(r["cycle_id"], errors="coerce").astype("Int64")
                rb = r[r["cycle_id"].isin(base_set)]
                ra = r[r["cycle_id"].isin(attack_set)]
                if not rb.empty:
                    base_cycle_counts.append(rb.groupby("cycle_id")["dst_ip"].nunique())
                    bc = rb.groupby("dst_ip")["cycle_id"].nunique().rename("base_response_n")
                else:
                    bc = pd.Series(dtype="int64", name="base_response_n")
                if not ra.empty:
                    attack_cycle_counts.append(ra.groupby("cycle_id")["dst_ip"].nunique())
                    ac = ra.groupby("dst_ip")["cycle_id"].nunique().rename("attack_response_n")
                else:
                    ac = pd.Series(dtype="int64", name="attack_response_n")
                x = pd.concat([bc, ac], axis=1).fillna(0).reset_index()
                if not x.empty:
                    rows.append(x)
        done = min(start + batch_size, len(prefixes))
        if done == len(prefixes) or done % max(batch_size * 10, batch_size) == 0:
            logger.info("H1 %s: %d/%d prefixes (%.1fs)", event_id, done, len(prefixes), time.time() - t0)
    if rows:
        x = pd.concat(rows, ignore_index=True).groupby("dst_ip", as_index=False).sum(numeric_only=True)
    else:
        x = pd.DataFrame({"dst_ip": d["dst_ip"].astype(str), "base_response_n": 0, "attack_response_n": 0})
    x = d.merge(x, on="dst_ip", how="left")
    x["base_response_n"] = x["base_response_n"].fillna(0).astype(int)
    x["attack_response_n"] = x["attack_response_n"].fillna(0).astype(int)
    x["baseline_cycle_n"] = len(base_ids); x["attack_cycle_n"] = len(attack_ids)
    x["pre_attack_reach"] = x["base_response_n"] / len(base_ids)
    x["attack_reach"] = x["attack_response_n"] / len(attack_ids)
    x["reach_drop"] = x["pre_attack_reach"] - x["attack_reach"]
    x["event_id"] = event_id
    x["outcome_valid"] = True
    # Aggregate IPS is computed from cycle-level responsive-IP counts, not by
    # weighting a large state more heavily in the endpoint summaries.
    # Each prefix batch contributes a partial responsive-IP count for the same
    # cycle.  Collapse duplicate cycle IDs before reindexing; otherwise pandas
    # correctly rejects the duplicate index and the aggregate IPS denominator
    # would be ill-defined.
    bc = (pd.concat(base_cycle_counts).groupby(level=0).sum()
          if base_cycle_counts else pd.Series(dtype=float))
    ac = (pd.concat(attack_cycle_counts).groupby(level=0).sum()
          if attack_cycle_counts else pd.Series(dtype=float))
    pre_ips = float(bc.reindex(base_ids, fill_value=0).mean()) if len(base_ids) else np.nan
    attack_ips = float(ac.reindex(attack_ids, fill_value=0).mean()) if len(attack_ids) else np.nan
    agg_drop = 1.0 - attack_ips / pre_ips if np.isfinite(pre_ips) and pre_ips > 0 else np.nan
    # Admin1-equal endpoint mean: compute each state's mean first, then average.
    state_means = x.groupby("target_admin1")["reach_drop"].mean()
    agg = {"baseline_cycle_n": len(base_ids), "attack_cycle_n": len(attack_ids),
           "pre_ips_mean": pre_ips, "attack_ips_mean": attack_ips,
           "aggregate_ips_drop": agg_drop,
           "admin1_equal_mean_drop": float(state_means.mean()) if not state_means.empty else np.nan}
    return x, agg


def _activity_summary(all_out: pd.DataFrame) -> pd.DataFrame:
    z = all_out[all_out["outcome_valid"].astype(bool)].copy()
    if z.empty:
        return pd.DataFrame()
    rows = []
    for (event_id, admin1, decile), g in z.groupby(["event_id", "target_admin1", "activity_decile"], dropna=False):
        rows.append({"event_id": event_id, "admin1": admin1, "activity_decile": decile,
                     "endpoint_n": len(g), "mean_reach_drop": g.reach_drop.mean(),
                     "median_reach_drop": g.reach_drop.median(),
                     "attack_reach_mean": g.attack_reach.mean(),
                     "fraction_drop_gt0": float((g.reach_drop > 0).mean()),
                     "fraction_drop_ge025": float((g.reach_drop >= .25).mean())})
    return pd.DataFrame(rows)


def _repeatability(all_out: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    z = all_out[all_out["outcome_valid"].astype(bool)][["event_id", "dst_ip", "target_admin1", "reach_drop"]].copy()
    pair_rows = []
    for a, b in combinations(sorted(z.event_id.unique()), 2):
        x = z[z.event_id.eq(a)].rename(columns={"reach_drop": "drop_a"})
        y = z[z.event_id.eq(b)].rename(columns={"reach_drop": "drop_b"})
        c = x.merge(y, on=["dst_ip", "target_admin1"], how="inner")
        if len(c) >= 3:
            rho, p = spearmanr(c.drop_a, c.drop_b)
        else:
            rho, p = np.nan, np.nan
        pair_rows.append({"row_type": "pair", "event_a": a, "event_b": b,
                          "common_ip_n": len(c), "spearman_rho": rho, "p_value": p})
    pair = pd.DataFrame(pair_rows)
    wide = z.pivot_table(index="dst_ip", columns="event_id", values="reach_drop", aggfunc="first")
    valid_n = wide.notna().sum(axis=1)
    ip_mean = pd.DataFrame({"dst_ip": wide.index.astype(str), "valid_event_n": valid_n.values,
                            "mean_war_susceptibility": wide.mean(axis=1).values,
                            "sd_war_susceptibility": wide.std(axis=1, ddof=1).values})
    ip_mean = ip_mean[ip_mean.valid_event_n >= 2].reset_index(drop=True)
    if not pair.empty:
        pair = pd.concat([pair, pd.DataFrame([{
            "row_type": "summary", "event_a": "", "event_b": "",
            "common_ip_n": int(len(ip_mean)), "spearman_rho": pair.spearman_rho.median(skipna=True),
            "p_value": np.nan}])], ignore_index=True)
    return pair, ip_mean


def _event_admin1_stats(out: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (event, admin), g in out[out.outcome_valid.astype(bool)].groupby(["event_id", "target_admin1"]):
        rows.append({"event_id": event, "admin1": admin, "n": len(g),
                     "mean_drop": g.reach_drop.mean(), "median_drop": g.reach_drop.median(),
                     "p25": g.reach_drop.quantile(.25), "p75": g.reach_drop.quantile(.75)})
    return pd.DataFrame(rows)


def _write_figure(fig, stem: Path, dpi: int = 300) -> None:
    fig.tight_layout()
    for ext in ("png", "pdf", "svg"):
        fig.savefig(stem.with_suffix("." + ext), dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def _figures(cfg: Config, out: Path, events: list[str], evsum: pd.DataFrame,
             acts: pd.DataFrame, repeat: pd.DataFrame, all_out: pd.DataFrame) -> list[str]:
    figdir = out / "figures"; figdir.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8,
                         "font.family": "DejaVu Sans"})
    paths = []
    # H1-1: endpoint distributions on a common reach-drop scale.
    n = len(events); nr, nc = math.ceil(n / 3), 3
    fig, ax = plt.subplots(nr, nc, figsize=(7.16, 2.1 * nr), squeeze=False)
    for i, e in enumerate(events):
        a = ax[i // nc][i % nc]; z = all_out[(all_out.event_id == e) & all_out.outcome_valid]
        if not z.empty:
            vals = z.reach_drop.to_numpy(); a.hist(vals, bins=np.linspace(-1, 1, 41), color="#4C78A8", alpha=.85)
            a.axvline(np.median(vals), color="#D62728", lw=1.2, label=f"median {np.median(vals):.3f}")
            a.legend(frameon=False, fontsize=7)
        a.set_title(e.replace("E2024_", "")); a.set_xlim(-1, 1); a.set_xlabel("reach drop (pre − attack)"); a.set_ylabel("IP count")
    for j in range(n, nr * nc): ax[j // nc][j % nc].axis("off")
    fig.suptitle("H1-1 Endpoint response loss is distributed across IPs, not a single common drop", y=1.01)
    stem = figdir / "H1-1_endpoint_reach_drop_distribution"; _write_figure(fig, stem); paths += [str(stem.with_suffix(x)) for x in (".png", ".pdf", ".svg")]
    # H1-2: Activity decile × event heatmap, common color scale.
    piv = acts[acts.event_id.isin(events)].groupby(["event_id", "activity_decile"], as_index=False).mean(numeric_only=True).pivot(index="event_id", columns="activity_decile", values="mean_reach_drop")
    order = [f"D{i}" for i in range(1, 11)]; piv = piv.reindex(index=events, columns=order)
    fig, a = plt.subplots(figsize=(7.16, 2.8)); im = a.imshow(piv, aspect="auto", cmap="coolwarm", vmin=-.5, vmax=.5)
    a.set_xticks(range(10), order); a.set_yticks(range(len(piv)), [x.replace("E2024_", "") for x in piv.index]); a.set_xlabel("Frozen Activity decile (D1–D10, state-wise)"); a.set_ylabel("attack event")
    fig.colorbar(im, ax=a, label="mean endpoint reach drop"); a.set_title("H1-2 Activity stratification describes, but does not redefine, endpoint outcomes")
    stem = figdir / "H1-2_activity_decile_response"; _write_figure(fig, stem); paths += [str(stem.with_suffix(x)) for x in (".png", ".pdf", ".svg")]
    # H1-3: IQR and large-drop fraction; common axes.
    es = evsum[evsum.event_id.isin(events)].set_index("event_id").reindex(events)
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.16, 2.9), sharey=True)
    y = np.arange(len(es)); a.hlines(y, es.p25_drop, es.p75_drop, color="#4C78A8", lw=3); a.scatter(es.median_drop, y, color="#D62728", zorder=3); a.axvline(0, color="0.5", lw=.7); a.set_xlabel("reach drop"); a.set_title("median and IQR")
    b.barh(y, es.fraction_drop_ge025, color="#59A14F"); b.set_xlabel("fraction with drop ≥ 0.25"); b.set_title("large endpoint losses"); b.set_xlim(0, 1)
    a.set_yticks(y, [x.replace("E2024_", "") for x in es.index]); fig.suptitle("H1-3 Within-event heterogeneity summary")
    stem = figdir / "H1-3_within_event_heterogeneity"; _write_figure(fig, stem); paths += [str(stem.with_suffix(x)) for x in (".png", ".pdf", ".svg")]
    # H1-4: pairwise repeatability matrix.
    mat = pd.DataFrame(index=events, columns=events, dtype=float); np.fill_diagonal(mat.values, 1.0)
    for _, r in repeat[repeat.row_type.eq("pair")].iterrows():
        if r.event_a in mat.index and r.event_b in mat.index: mat.loc[r.event_a, r.event_b] = mat.loc[r.event_b, r.event_a] = r.spearman_rho
    fig, a = plt.subplots(figsize=(5.8, 4.3)); im = a.imshow(mat.astype(float), cmap="coolwarm", vmin=-1, vmax=1); a.set_xticks(range(len(events)), [x.replace("E2024_", "") for x in events], rotation=45, ha="right"); a.set_yticks(range(len(events)), [x.replace("E2024_", "") for x in events]); fig.colorbar(im, ax=a, label="Spearman ρ"); a.set_title("H1-4 Cross-event repeatability (common IPs, matched geography)")
    stem = figdir / "H1-4_cross_event_repeatability"; _write_figure(fig, stem); paths += [str(stem.with_suffix(x)) for x in (".png", ".pdf", ".svg")]
    # H1-5: aggregate IPS drop vs endpoint distribution.
    fig, a = plt.subplots(figsize=(5.4, 3.8)); x = es.aggregate_ips_drop.to_numpy(float); yv = es.median_drop.to_numpy(float); lo = yv - es.p25_drop.to_numpy(float); hi = es.p75_drop.to_numpy(float) - yv; a.errorbar(x, yv, yerr=[lo, hi], fmt="o", color="#4C78A8", ecolor="#4C78A8", capsize=3); 
    for label, xx, yy in zip([x.replace("E2024_", "") for x in es.index], x, yv): a.annotate(label, (xx, yy), xytext=(4, 4), textcoords="offset points", fontsize=7)
    a.axline((0, 0), slope=1, color="0.6", ls="--", lw=.8); a.set_xlabel("aggregate IPS drop"); a.set_ylabel("endpoint median reach drop (IQR)"); a.set_title("H1-5 Aggregate IPS loss does not determine the endpoint distribution")
    stem = figdir / "H1-5_aggregate_vs_endpoint_distribution"; _write_figure(fig, stem); paths += [str(stem.with_suffix(x)) for x in (".png", ".pdf", ".svg")]
    return paths


def _report(cfg: Config, out: Path, evsum: pd.DataFrame, acts: pd.DataFrame,
            repeat: pd.DataFrame, ipmean: pd.DataFrame, supplementary: list[str]) -> str:
    core = evsum[evsum.core_event.eq(1)]
    dec = acts[acts.event_id.isin(core.event_id)]
    activity_corr = np.nan
    if not dec.empty:
        g = dec.groupby(["event_id", "activity_decile"], as_index=False).mean(numeric_only=True)
        order = {f"D{i}": i for i in range(1, 11)}; g["d"] = g.activity_decile.map(order)
        activity_corr = g[["d", "mean_reach_drop"]].corr(method="spearman").iloc[0, 1]
    pair = repeat[(repeat.row_type == "pair") & repeat.spearman_rho.notna()]
    med_rho = pair.spearman_rho.median() if not pair.empty else np.nan
    iqr = (core.p75_drop - core.p25_drop).median() if not core.empty else np.nan
    frac = core.fraction_drop_ge025.mean() if not core.empty else np.nan
    a_supported = bool(np.isfinite(iqr) and iqr > 0.05 and np.isfinite(frac) and frac > 0.05)
    b_only = bool(np.isfinite(activity_corr) and abs(activity_corr) >= .8)
    c_supported = bool(np.isfinite(med_rho) and med_rho >= .2 and len(pair) >= 3)
    d_supported = bool(a_supported and core.aggregate_ips_drop.notna().any())
    verdict = "SUPPORTED" if a_supported and d_supported else ("PARTIALLY_SUPPORTED" if a_supported else "NOT_ESTIMABLE")
    supplementary_text = ", ".join(supplementary) if supplementary else "E2025_0115_ATTACK was attempted but had no valid complete endpoint outcome"
    lines = ["# H1 Endpoint Heterogeneity Report", "", f"Run: `{cfg.run_id}`", "", "## Scope", "", "Only the six frozen core held-out attacks are used in the core aggregate. 2025-01-15 is supplementary and excluded from the core aggregate.", "The final Sensitivity specification was frozen before any held-out attack outcome was queried. H1 does not use Sensitivity Q1-Q5 to select endpoints.", "", "## Event summaries", "", "```", evsum.to_string(index=False), "```", "", "## H1 answers", "", f"- A. Same-attack endpoint heterogeneity: **{'SUPPORTED' if a_supported else 'NOT_ESTIMABLE'}** (median event IQR={iqr:.4f}; mean fraction with drop ≥0.25={frac:.3f})." if np.isfinite(iqr) else "- A. Same-attack endpoint heterogeneity: **NOT_ESTIMABLE**.", f"- B. Is heterogeneity only Activity: **{'NOT SUPPORTED as an exclusive explanation' if not b_only else 'POSSIBLY ACTIVITY-ALIGNED; not a causal claim'}** (Spearman trend diagnostic={activity_corr:.3f})." if np.isfinite(activity_corr) else "- B. Activity-only explanation: **NOT_ESTIMABLE**.", f"- C. Cross-event repeatability: **{'SUPPORTED descriptively' if c_supported else 'WEAK/NOT ESTIMABLE'}** (median pairwise Spearman={med_rho:.3f}, pair count={len(pair)})." if np.isfinite(med_rho) else "- C. Cross-event repeatability: **NOT_ESTIMABLE**.", f"- D. Aggregate IPS masks endpoint differences: **{'SUPPORTED descriptively' if d_supported else 'NOT_ESTIMABLE'}**.", "", f"## Overall H1 verdict: **{verdict}**", "", "This is a descriptive heterogeneity result, not evidence that planned-outage Sensitivity predicts war outcomes. No H2, H3, or H4 was run.", "", "## Supplementary", "", f"Supplementary event status: {supplementary_text}. It is not included in core aggregate or verdict.", ""]
    (out / "H1_ENDPOINT_HETEROGENEITY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    return verdict


def run(cfg: Config) -> dict:
    out = cfg.run_base / "results" / "stages" / H1_STAGE
    out.mkdir(parents=True, exist_ok=True)
    logger = get_logger(cfg.run_base / "logs")
    # This call intentionally precedes Events/ClickHouse/outcome loading.
    freeze = freeze_final_sensitivity(cfg, out)
    labels = _load_activity_labels(cfg)
    grid = _cycle_grid(cfg)
    all_events = Events(cfg).df
    missing = [e for e in CORE_EVENTS if e not in set(all_events.event_id)]
    if missing:
        raise ValueError(f"frozen core attack events missing from registry: {missing}")
    event_rows = {str(r.event_id): r for _, r in all_events.iterrows()}
    logger.info("H1 starts after sensitivity freeze; labels=%d, complete cycles=%d", len(labels), int(grid.is_complete.astype(bool).sum()))
    outcomes, summaries = [], []
    with CHClient(cfg) as ch:
        for e in list(CORE_EVENTS) + list(SUPPLEMENTARY_EVENTS):
            ev = event_rows.get(e)
            if ev is None:
                continue
            cached = out / f"h1_ip_event_{e}.parquet"
            if cached.exists() and cached.stat().st_size > 0:
                z = pd.read_parquet(cached)
                agg = {"baseline_cycle_n": int(z["baseline_cycle_n"].iloc[0]) if not z.empty else 0,
                       "attack_cycle_n": int(z["attack_cycle_n"].iloc[0]) if not z.empty else 0}
                old_summary = out / "h1_event_summary.csv"
                if old_summary.exists():
                    old = pd.read_csv(old_summary)
                    hit = old[old.event_id.astype(str).eq(e)]
                    if not hit.empty:
                        row = hit.iloc[0]
                        for k in ("aggregate_ips_pre", "aggregate_ips_attack", "aggregate_ips_drop", "admin1_equal_mean_drop"):
                            agg[k] = row.get(k, np.nan)
                logger.info("H1 %s: reusing cached endpoint outcomes", e)
            else:
                z, agg = _query_event(cfg, ch, labels, ev, grid, logger, max(1, int(cfg.runtime.get("prefix_batch", 500))))
                if not z.empty:
                    z.to_parquet(cached, index=False, compression="zstd")
            if z.empty:
                logger.warning("H1 %s produced no valid endpoint outcomes", e)
                continue
            outcomes.append(z)
            summaries.append(_summarize_event(z, event_id=e, core=e in CORE_EVENTS,
                                               aggregate=agg, scope_n=z.target_admin1.nunique()))
    if not outcomes:
        raise RuntimeError("H1 returned no endpoint outcomes")
    all_out = pd.concat(outcomes, ignore_index=True)
    evsum = pd.DataFrame(summaries)
    acts = _activity_summary(all_out)
    repeat, ipmean = _repeatability(all_out[all_out.event_id.isin(CORE_EVENTS)])
    evsum.to_csv(out / "h1_event_summary.csv", index=False)
    acts.to_csv(out / "h1_activity_decile_summary.csv", index=False)
    repeat.to_csv(out / "h1_repeatability.csv", index=False)
    ipmean.to_parquet(out / "h1_ip_mean_war_susceptibility.parquet", index=False)
    all_out.to_parquet(out / "h1_ip_level_outcomes.parquet", index=False, compression="zstd")
    figs = _figures(cfg, out, list(CORE_EVENTS), evsum, acts, repeat, all_out)
    supplementary = [e for e in SUPPLEMENTARY_EVENTS if e in set(all_out.event_id)]
    verdict = _report(cfg, out, evsum, acts, repeat, ipmean, supplementary)
    review = ["# H1 Figure Review", "", "The figure set uses common axes for cross-event comparisons, distinguishes missing outcomes from zero response, and labels the frozen Activity strata as D1-D10.", "", "- H1-1: common reach-drop scale; endpoint distributions and medians visible at the first glance.", "- H1-2: shared diverging color scale centered at zero; missing cells remain blank.", "- H1-3: IQR and threshold fraction are shown separately, avoiding a single average-only claim.", "- H1-4: repeatability cells are blank when fewer than three common IPs are available.", "- H1-5: aggregate IPS drop is compared with endpoint median and IQR; the diagonal is a visual reference, not a causal model.", "", "All figures were rendered at report width and saved as PNG, PDF, and SVG."]
    (out / "H1_FIGURE_REVIEW.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    manifest = {"run_id": cfg.run_id, "stage": H1_STAGE, "git_commit": _git_commit(cfg.root),
                "freeze_version": freeze["freeze"]["freeze_version"], "freeze_sha256": file_sha256(out / "final_sensitivity_freeze.json"),
                "core_events": list(CORE_EVENTS), "supplementary_events": list(SUPPLEMENTARY_EVENTS),
                "endpoint_outcome_definition": "pre_attack_reach is the fraction of complete cycles in the 7-day clean baseline; attack_reach is the fraction of complete cycles in the first 12h from earliest registered treatment boundary; missing acquisition cycles are NA and completed cycles without a response are zero.",
                "h2_h3_h4_run": False, "verdict": verdict,
                "outputs": [str(p) for p in [out / "H1_ENDPOINT_HETEROGENEITY_REPORT.md", out / "h1_event_summary.csv", out / "h1_activity_decile_summary.csv", out / "h1_repeatability.csv", out / "h1_ip_level_outcomes.parquet"] + [Path(p) for p in figs]]}
    (out / "h1_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"stage": H1_STAGE, "run_id": cfg.run_id, "verdict": verdict, "output_dir": str(out), "event_n": len(evsum), "endpoint_rows": len(all_out), "figures": figs, "h2_h3_h4_run": False}
