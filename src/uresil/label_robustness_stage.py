"""Stage 4.5: label-side WEAK versus STRICT robustness audit.

This module deliberately stops before any held-out war-event analysis.  It
reuses the frozen Stage-2 Activity population and the frozen Stage-4 WEAK
labels, then recalculates only the STRICT label after removing reviewed
``STATE_PLANNED_OUTAGE_WEAK_SUPERVISION`` windows.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, file_sha256
from . import simple_calibration, sensitivity_stage

STAGE = "stage04_5_label_robustness"
RANDOM_SEED = 0


def _root(cfg: Config) -> Path:
    root = cfg.run_base / "results" / "stages" / STAGE
    for name in ("tables", "figures", "report"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _git(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _source(cfg: Config, key: str) -> Path:
    name = str(cfg.raw.get("stage4_provenance", {}).get(key, "")).strip()
    if not name:
        raise ValueError(f"stage4_provenance.{key} must be frozen explicitly")
    path = cfg.root / cfg.raw["paths"]["run_root"] / name
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _load_weak(cfg: Config) -> tuple[pd.DataFrame, Path]:
    run = _source(cfg, "stage4_source_run")
    root = run / "results" / "stages" / "stage04_sensitivity"
    p = root / "primary" / "ip_sensitivity_primary.parquet"
    a = root / "augmented" / "ip_sensitivity_augmented.parquet"
    if not p.exists() or not a.exists():
        raise FileNotFoundError("frozen Stage 4 primary/augmented labels are required")
    primary = pd.read_parquet(p)
    augmented = pd.read_parquet(a)
    cols = ["dst_ip", "target_admin1", "activity_score_raw", "s_reach_primary", "support_episode_n_primary"]
    cols += ["s_reach_augmented", "support_episode_n_augmented"]
    base = primary[[c for c in cols if c in primary]].copy()
    add_cols = [c for c in ["dst_ip", "target_admin1", "activity_score_raw", "s_reach_augmented", "support_episode_n_augmented"] if c in augmented]
    add = augmented[add_cols].rename(columns={"target_admin1": "target_admin1_aug", "activity_score_raw": "activity_score_raw_aug"})
    out = base.drop(columns=[c for c in ["s_reach_augmented", "support_episode_n_augmented"] if c in base]).merge(add, on="dst_ip", how="outer")
    if "target_admin1_aug" in out:
        out["target_admin1"] = out["target_admin1"].fillna(out["target_admin1_aug"])
        out = out.drop(columns=["target_admin1_aug"])
    if "activity_score_raw_aug" in out:
        out["activity_score_raw"] = out["activity_score_raw"].fillna(out["activity_score_raw_aug"])
        out = out.drop(columns=["activity_score_raw_aug"])
    return out, root


def _strict_view(weak_root: Path, root: Path) -> tuple[Path, int, int]:
    src = weak_root / "tables" / "frozen_weak_supervision_exposure_v1.csv"
    if not src.exists():
        raise FileNotFoundError(src)
    view = pd.read_csv(src)
    excluded = view[view.exposure_semantics.eq("STATE_PLANNED_OUTAGE_WEAK_SUPERVISION")].copy()
    strict = view.loc[~view.exposure_semantics.eq("STATE_PLANNED_OUTAGE_WEAK_SUPERVISION")].copy()
    path = root / "tables" / "frozen_strict_exposure_v1.csv"
    strict.to_csv(path, index=False, encoding="utf-8-sig")
    excluded.to_csv(root / "tables" / "excluded_weak_supervision_windows.csv", index=False, encoding="utf-8-sig")
    return path, int(len(excluded)), int(len(strict))


def _panel_frame(df: pd.DataFrame, panel: str, suffix: str) -> pd.DataFrame:
    return df[["dst_ip", "target_admin1", "activity_score_raw",
               f"s_reach_{panel}", f"support_episode_n_{panel}"]].rename(columns={
                   f"s_reach_{panel}": f"s_{suffix}", f"support_episode_n_{panel}": f"support_{suffix}"})


def _corr(x: pd.Series, y: pd.Series, method: str = "pearson") -> float:
    z = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(z) < 2 or z.x.nunique() < 2 or z.y.nunique() < 2:
        return float("nan")
    return float(z.x.corr(z.y, method=method))


def _q_assign(g: pd.DataFrame, score: str) -> pd.Series:
    out = pd.Series(pd.NA, index=g.index, dtype="string")
    keyed = g.copy()
    # pandas cannot construct a categorical group containing a null category
    # with ``dropna=False`` on some versions.  Keep unmapped states explicit
    # and ungrouped rather than letting them abort the audit.
    keyed["_state_key"] = keyed["target_admin1"].astype("string").fillna("__MISSING_STATE__")
    for state, idx in keyed.groupby("_state_key", sort=True).groups.items():
        if state == "__MISSING_STATE__":
            continue
        z = g.loc[idx].dropna(subset=[score]).sort_values([score, "dst_ip"], kind="mergesort")
        if len(z) < 5:
            continue
        q = np.floor(np.arange(len(z)) * 5 / len(z)).astype(int) + 1
        out.loc[z.index] = pd.Series([f"Q{i}" for i in q], index=z.index, dtype="string")
    return out


def _save(fig, path: Path) -> None:
    fig.savefig(path.with_suffix(".png"), dpi=220, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight")


def _audit_panel(weak: pd.DataFrame, strict: pd.DataFrame, panel: str, root: Path) -> dict:
    w = _panel_frame(weak, panel, "weak")
    s = _panel_frame(strict, panel, "strict")
    m = w.merge(s[["dst_ip", "s_strict", "support_strict"]], on="dst_ip", how="outer", suffixes=("", "_s"))
    for c in ("s_weak", "s_strict", "support_weak", "support_strict"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    m["target_admin1"] = m["target_admin1"].fillna(m.pop("target_admin1_s")) if "target_admin1_s" in m else m["target_admin1"]
    m["support_weak"] = m["support_weak"].fillna(0); m["support_strict"] = m["support_strict"].fillna(0)
    weak_scored = m.s_weak.notna(); strict_scored = m.s_strict.notna()
    common = m[weak_scored & strict_scored & m.support_weak.ge(3) & m.support_strict.ge(3)].copy()
    common["delta_s"] = common.s_weak - common.s_strict
    common["q_weak"] = _q_assign(common, "s_weak")
    common["q_strict"] = _q_assign(common, "s_strict")
    common.to_csv(root / "tables" / f"stage4_5_common_{panel}_ip_sensitivity.csv", index=False, encoding="utf-8-sig")
    rows = []
    for state, g in m.groupby("target_admin1", dropna=False):
        c = common[common.target_admin1.eq(state)]
        d = c.delta_s.abs()
        rows.append({"panel": panel, "target_admin1": state, "n_common": int(len(c)),
                     "spearman_s_weak_strict": _corr(c.s_weak, c.s_strict, "spearman"),
                     "median_abs_difference": float(d.median()) if len(d) else np.nan,
                     "weak_support3_n": int((g.s_weak.notna() & g.support_weak.ge(3)).sum()),
                     "strict_support3_n": int((g.s_strict.notna() & g.support_strict.ge(3)).sum())})
    state = pd.DataFrame(rows)
    state.to_csv(root / "tables" / f"stage4_5_state_stability_{panel}.csv", index=False, encoding="utf-8-sig")
    for t in (1, 2, 3, 4):
        pass
    dep = {f"weak_support3_to_strict_{k}": int(((m.support_weak.ge(3)) & (m.support_strict.eq(k))).sum()) for k in (0, 1, 2)}
    dep["weak_support3_strict_support_ge3_common_ip_n"] = int(len(common))
    corr = {"panel": panel, "weak_support_ge1_ip_n": int((weak_scored & m.support_weak.ge(1)).sum()),
            "strict_support_ge1_ip_n": int((strict_scored & m.support_strict.ge(1)).sum()),
            "weak_support_ge2_ip_n": int((weak_scored & m.support_weak.ge(2)).sum()),
            "strict_support_ge2_ip_n": int((strict_scored & m.support_strict.ge(2)).sum()),
            "weak_support_ge3_ip_n": int((weak_scored & m.support_weak.ge(3)).sum()),
            "strict_support_ge3_ip_n": int((strict_scored & m.support_strict.ge(3)).sum()),
            "weak_support_ge4_ip_n": int((weak_scored & m.support_weak.ge(4)).sum()),
            "strict_support_ge4_ip_n": int((strict_scored & m.support_strict.ge(4)).sum()),
            "common_formal_ip_n": int(len(common)),
            "s_weak_strict_pearson": _corr(common.s_weak, common.s_strict),
            "s_weak_strict_spearman": _corr(common.s_weak, common.s_strict, "spearman"),
            "median_difference": float(common.delta_s.median()) if len(common) else np.nan,
            "median_absolute_difference": float(common.delta_s.abs().median()) if len(common) else np.nan,
            "p90_absolute_difference": float(common.delta_s.abs().quantile(.90)) if len(common) else np.nan,
            "p95_absolute_difference": float(common.delta_s.abs().quantile(.95)) if len(common) else np.nan,
            **dep}
    # Q transition statistics are based on state-wise Q assignments.
    q = common.dropna(subset=["q_weak", "q_strict"]).copy()
    matrix = pd.crosstab(q.q_weak, q.q_strict).reindex(index=[f"Q{i}" for i in range(1, 6)], columns=[f"Q{i}" for i in range(1, 6)], fill_value=0)
    matrix.to_csv(root / "tables" / f"stage4_5_quintile_transition_{panel}.csv", encoding="utf-8-sig")
    same = (q.q_weak == q.q_strict)
    dist = (q.q_weak.str[-1].astype(int) - q.q_strict.str[-1].astype(int)).abs()
    corr.update({"q_common_n": int(len(q)), "same_quintile_fraction": float(same.mean()) if len(q) else np.nan,
                 "within_one_quintile_fraction": float((dist <= 1).mean()) if len(q) else np.nan,
                 "q1_to_q5_count": int(((q.q_weak == "Q1") & (q.q_strict == "Q5")).sum()),
                 "q5_to_q1_count": int(((q.q_weak == "Q5") & (q.q_strict == "Q1")).sum())})
    return {"panel": panel, "metrics": corr, "common": common, "state": state, "matrix": matrix}


def _figures(results: dict[str, dict], root: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for panel, r in results.items():
        c = r["common"]
        fig, ax = plt.subplots(figsize=(5.6, 5.0)); ax.hexbin(c.s_weak, c.s_strict, gridsize=75, mincnt=1, bins="log", cmap="viridis")
        lim = np.nanpercentile(np.abs(np.r_[c.s_weak, c.s_strict]), 99) if len(c) else 1; lim = max(float(lim), .05)
        ax.plot([-lim, lim], [-lim, lim], "--", color="#555", lw=.8); ax.set(xlabel="S_i — WEAK", ylabel="S_i — STRICT", title=f"{panel.title()}: WEAK vs STRICT"); ax.grid(alpha=.2); _save(fig, root/"figures"/f"S4_5_1_weak_vs_strict_sensitivity_{panel}"); plt.close(fig)
        fig, ax = plt.subplots(figsize=(8.5, 5)); st=r["state"].sort_values("weak_support3_n"); y=np.arange(len(st)); ax.barh(y-.18, st.weak_support3_n, .36, label="WEAK", color="#245b8a"); ax.barh(y+.18, st.strict_support3_n, .36, label="STRICT", color="#d17b2f"); ax.set_yticks(y, st.target_admin1); ax.set_xlabel("support≥3 IP count"); ax.set_title(f"{panel.title()}: support coverage change"); ax.legend(); ax.grid(axis="x", alpha=.25); fig.tight_layout(); _save(fig, root/"figures"/f"S4_5_2_support_coverage_change_{panel}"); plt.close(fig)
        fig, ax = plt.subplots(figsize=(6.5, 4.2)); ax.hist(c.delta_s, bins=80, color="#666", alpha=.85); ax.axvline(0, color="#c33", lw=.8); ax.set(xlabel="S_WEAK − S_STRICT", ylabel="IP count", title=f"{panel.title()}: sensitivity difference"); ax.grid(axis="y", alpha=.25); fig.tight_layout(); _save(fig, root/"figures"/f"S4_5_3_sensitivity_difference_distribution_{panel}"); plt.close(fig)
        fig, ax = plt.subplots(figsize=(5.2, 4.4)); im=ax.imshow(r["matrix"].to_numpy(), cmap="Blues"); ax.set_xticks(range(5), [f"Q{i}" for i in range(1,6)]); ax.set_yticks(range(5), [f"Q{i}" for i in range(1,6)]); ax.set(xlabel="STRICT quintile", ylabel="WEAK quintile", title=f"{panel.title()}: Q transition"); fig.colorbar(im, ax=ax, label="IP count"); fig.tight_layout(); _save(fig, root/"figures"/f"S4_5_4_quintile_transition_matrix_{panel}"); plt.close(fig)
        fig, ax = plt.subplots(figsize=(8.5, 5)); st=r["state"].sort_values("n_common"); y=np.arange(len(st)); ax.barh(y, st.n_common, color="#6b8e23"); ax.set_yticks(y, st.target_admin1); ax.set_xlabel("common formal IP count"); ax.set_title(f"{panel.title()}: state-level stability support"); ax.grid(axis="x", alpha=.25); fig.tight_layout(); _save(fig, root/"figures"/f"S4_5_5_state_level_stability_{panel}"); plt.close(fig)


def run(cfg: Config) -> dict:
    started = datetime.now(timezone.utc); root = _root(cfg); weak, weak_root = _load_weak(cfg)
    weak_view = pd.read_csv(weak_root / "tables" / "frozen_weak_supervision_exposure_v1.csv")
    strict_view, excluded_n, strict_n = _strict_view(weak_root, root)
    # Explicitly reuse the frozen Stage-2 population and force a fresh
    # calibration cache in this separate run.  No war-event data is loaded.
    sensitivity_stage._prepare_reused_inputs(cfg)
    # The first invocation has an empty run directory.  Reusing its immutable
    # episode cache on a rerun makes this post-processing step reproducible
    # without issuing another full ClickHouse scan.
    cfg.raw.setdefault("_runtime_flags", {})["force_stage_recompute"] = False
    calibration = simple_calibration.run(cfg, exposure_view=strict_view)
    strict = pd.read_parquet(cfg.out_dir("results_tables") / "b1_full_sensitivity_labels.parquet")
    strict["activity_score_raw"] = pd.to_numeric(strict.get("activity_score_raw"), errors="coerce")
    results = {p: _audit_panel(weak, strict, p, root) for p in ("primary", "augmented")}
    rows = [r["metrics"] for r in results.values()]
    pd.DataFrame(rows).to_csv(root / "tables" / "stage4_5_coverage_comparison.csv", index=False, encoding="utf-8-sig")
    # Combined common-IP table for convenient downstream inspection.
    common_all = pd.concat([r["common"].assign(panel=p) for p, r in results.items()], ignore_index=True)
    common_all.to_parquet(root / "tables" / "stage4_5_common_ip_sensitivity.parquet", index=False)
    # Activity correlations use frozen Activity from Stage 2, not a new gate.
    ac = []
    for p, r in results.items():
        c = r["common"]; ac.append({"panel": p, "population": "support_ge_3_common", "ip_n": int(len(c)), "pearson_activity_s": _corr(c.activity_score_raw, c.s_strict), "spearman_activity_s": _corr(c.activity_score_raw, c.s_strict, "spearman")})
    pd.DataFrame(ac).to_csv(root / "tables" / "stage4_5_activity_correlation.csv", index=False, encoding="utf-8-sig")
    _figures(results, root)
    ratios = []
    for r in results.values():
        m = r["metrics"]; ratios.append(m["common_formal_ip_n"] / max(m["weak_support_ge3_ip_n"], 1))
    rho = [r["metrics"]["s_weak_strict_spearman"] for r in results.values() if np.isfinite(r["metrics"]["s_weak_strict_spearman"])]
    coverage = min(ratios) if ratios else 0; corr = min(rho) if rho else 0
    label = "LABEL_ROBUSTNESS_HIGH" if coverage >= .9 and corr >= .95 else ("LABEL_ROBUSTNESS_MODERATE" if coverage >= .75 and corr >= .9 else "LABEL_ROBUSTNESS_LOW")
    prov = cfg.raw.get("stage4_provenance", {}); workbook = cfg.resource_path("calibration_workbook")
    manifest = {"stage": STAGE, "run_id": cfg.run_id, "git_commit": _git(cfg.root), "stage2_frozen_source": str(_source(cfg, "stage2_source_run")), "stage3_frozen_source": str(_source(cfg, "stage3_source_run")), "stage4_frozen_source": str(weak_root.parents[2]), "calibration_workbook_sha256": file_sha256(workbook), "weak_window_count": int(len(weak_view)), "strict_window_count": strict_n, "excluded_weak_supervision_long_window_count": excluded_n, "random_seed": RANDOM_SEED, "label_robustness": label, "war_attack_data_used": False, "h1_h4_run": False, "generated_at": datetime.now(timezone.utc).isoformat()}
    (root / "stage4_5_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = ["# Stage 4.5 — Sensitivity Label Robustness Audit", "", f"Run ID: `{cfg.run_id}`", "", "This is a label-side audit only. H1–H4 and all held-out war-attack outcomes were not loaded.", "", "## Exposure definitions", "", f"- WEAK: frozen Stage 4 exposure, 172 windows.", f"- STRICT: excludes {excluded_n} `STATE_PLANNED_OUTAGE_WEAK_SUPERVISION` long windows; {strict_n} windows remain.", "- Episode aggregation remains cycle-union plus episode-equal; no gap fill and no stable-Activity gate.", "", "## Coverage and stability", ""]
    for r in results.values():
        m = r["metrics"]; lines.append(f"### {r['panel'].title()}"); lines.append(f"- WEAK support≥3: **{m['weak_support_ge3_ip_n']:,} IP**; STRICT support≥3: **{m['strict_support_ge3_ip_n']:,} IP**; common formal IP: **{m['common_formal_ip_n']:,}**."); lines.append(f"- Pearson: **{m['s_weak_strict_pearson']:.4f}**; Spearman: **{m['s_weak_strict_spearman']:.4f}**; median absolute difference: **{m['median_absolute_difference']:.6f}**; P90: **{m['p90_absolute_difference']:.6f}**."); lines.append(f"- Same quintile: **{m.get('same_quintile_fraction', float('nan')):.2%}**; within ±1: **{m.get('within_one_quintile_fraction', float('nan')):.2%}**; Q1→Q5: **{m.get('q1_to_q5_count', 0)}**; Q5→Q1: **{m.get('q5_to_q1_count', 0)}**.")
    lines += ["", "## Decision", "", f"**{label}**", "", "This is a robustness classification only; it does not select WEAK or STRICT as the main analysis label.", "", "## Outputs", "", "Coverage, common-IP, state stability, quintile transition tables and five figure families are in `tables/` and `figures/`."]
    (root / "report" / "STAGE4_5_LABEL_ROBUSTNESS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "PASS", "label_robustness": label, "excluded_windows": excluded_n, "strict_windows": strict_n, "panels": rows, "calibration": calibration}
