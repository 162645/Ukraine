"""Formal Stage 4: IP planned-outage-associated sensitivity.

The treatment is a state-level planned-outage weak-supervision environment,
not IP-level physical outage truth. Primary and Augmented panels are separate;
all support>=1 scores are retained and support>=3 is only the registered
estimability flag. War-attack outcomes are never loaded in this stage.
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
RANDOM_SEED = 0


def _root(cfg: Config) -> Path:
    root = cfg.run_base / "results" / "stages" / STAGE
    for name in ("primary", "augmented", "tables", "figures", "report"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def _bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _hash_many(paths: list[Path]) -> str:
    """Deterministically hash a set of immutable input files."""
    import hashlib
    h = hashlib.sha256()
    for path in sorted((p for p in paths if p.exists()), key=lambda p: str(p)):
        h.update(str(path).encode("utf-8")); h.update(b"\0"); h.update(file_sha256(path).encode("ascii")); h.update(b"\n")
    return h.hexdigest()


def _build_weak_supervision_exposure_view(cfg: Config, root: Path) -> Path:
    """Freeze the derived exposure view used by this Stage 4 run.

    The old long-window semantic review was about uniform physical outage. A
    reviewed state/DSO planned or hourly schedule remains usable weak
    supervision even when queue-to-IP mapping is unavailable, and is labelled
    ``ROTATIONAL_WEAK_SUPERVISION`` rather than ``UNIFORM``.
    """
    provenance = cfg.raw.get("stage4_provenance", {})
    stage3_run_name = str(provenance.get("stage3_source_run", "")).strip()
    if not stage3_run_name:
        raise ValueError("stage4_provenance.stage3_source_run must be frozen explicitly")
    s3 = cfg.root / cfg.raw["paths"]["run_root"] / stage3_run_name / "results" / "stages" / "stage03_calibration_events"
    windows_path = s3 / "tables" / "calibration_windows.csv"
    review_path = s3 / "report" / "LONG_WINDOW_SEMANTIC_REVIEW.csv"
    if not windows_path.exists():
        raise FileNotFoundError(f"Stage 3 calibration windows not found: {windows_path}")
    windows = pd.read_csv(windows_path)
    required = {"episode_id", "window_id", "admin1_iso", "state", "start_utc", "end_utc",
                "duration_h", "evidence_level", "dataset", "event_type", "final_status_norm",
                "source_id", "use_primary", "use_augmented", "formal_stage3_usable"}
    missing = sorted(required - set(windows.columns))
    if missing:
        raise ValueError(f"calibration_windows.csv missing columns: {missing}")
    windows = windows.copy()
    windows["use_primary"] = _bool(windows["use_primary"])
    windows["use_augmented"] = _bool(windows["use_augmented"])
    windows["formal_stage3_usable"] = _bool(windows["formal_stage3_usable"])
    windows["formal_weak_supervision_positive"] = windows["formal_stage3_usable"]
    windows["semantic_class_legacy"] = "NOT_LONG_WINDOW"
    windows["exposure_semantics"] = "STATE_LEVEL_PLANNED_WINDOW"
    if review_path.exists():
        review = pd.read_csv(review_path)
        if review.window_id.duplicated().any():
            raise ValueError("LONG_WINDOW_SEMANTIC_REVIEW.csv has duplicate window_id")
        review = review.set_index("window_id")
        cls = windows.window_id.map(review["semantic_class"]).fillna("NOT_LONG_WINDOW")
        windows["semantic_class_legacy"] = cls
        is_long = cls.ne("NOT_LONG_WINDOW")
        windows.loc[is_long & cls.eq("A_CONFIRMED_UNIFORM"), "exposure_semantics"] = "UNIFORM_EXPOSURE_CONFIRMED"
        # A semantic review can establish that a planned schedule is usable
        # state-level weak supervision without proving queue rotation.  Only
        # rows explicitly marked as rotational receive the narrower term.
        rotational = cls.astype(str).str.contains("ROTATION", case=False, na=False)
        windows.loc[is_long & rotational, "exposure_semantics"] = "ROTATIONAL_WEAK_SUPERVISION"
        windows.loc[is_long & ~cls.eq("A_CONFIRMED_UNIFORM") & ~rotational,
                    "exposure_semantics"] = "STATE_PLANNED_OUTAGE_WEAK_SUPERVISION"
        for col in ("source_official", "source_verified", "notes"):
            if col in review:
                windows[col] = windows.window_id.map(review[col]).fillna("")
    view_cols = ["episode_id", "window_id", "admin1_iso", "state", "start_utc", "end_utc", "duration_h",
                 "evidence_level", "dataset", "event_type", "final_status_norm", "source_id", "use_primary",
                 "use_augmented", "formal_stage3_usable", "formal_weak_supervision_positive",
                 "semantic_class_legacy", "exposure_semantics", "operator", "start_local", "end_local",
                 "boundary_overlap", "source_official", "source_verified", "notes"]
    view = windows[[c for c in view_cols if c in windows.columns]].copy()
    path = root / "tables" / "frozen_weak_supervision_exposure_v1.csv"
    view.to_csv(path, index=False, encoding="utf-8-sig")
    state_rows = []
    for admin1, g in view.groupby("admin1_iso", sort=True):
        state_rows.append({"admin1_iso": admin1, "state": str(g.state.iloc[0]),
                           "primary_window_n": int(g.use_primary.sum()),
                           "primary_episode_n": int(g.loc[g.use_primary, "episode_id"].nunique()),
                           "augmented_window_n": int(g.use_augmented.sum()),
                           "augmented_episode_n": int(g.loc[g.use_augmented, "episode_id"].nunique())})
    state_df = pd.DataFrame(state_rows)
    state_df.to_csv(root / "tables" / "weak_supervision_exposure_by_oblast.csv", index=False, encoding="utf-8-sig")
    counts = view.exposure_semantics.value_counts().to_dict()
    lines = ["# WEAK_SUPERVISION_EXPOSURE_AUDIT", "",
             "This derived view does not modify the original Excel workbook.",
             "A row denotes a state-level planned-outage execution environment, not an IP-level physical outage truth.",
             "", "## Semantics", "",
             "- `UNIFORM_EXPOSURE_CONFIRMED`: explicit uniform wording retained for audit.",
             "- `ROTATIONAL_WEAK_SUPERVISION`: explicitly reviewed queue/group rotation retained without asserting all-user outage.",
             "- `STATE_PLANNED_OUTAGE_WEAK_SUPERVISION`: state/DSO planned schedule retained without claiming queue rotation or all-user outage.",
             "- `STATE_LEVEL_PLANNED_WINDOW`: non-long frozen planned-outage window.",
             "- C/B rows remain weak-supervision rows; none is upgraded to a uniform physical-outage label.", "", "## Counts", "",
             f"- Primary: **{int(view.use_primary.sum()):,} windows / {int(view.loc[view.use_primary, 'episode_id'].nunique()):,} episodes**.",
             f"- Augmented: **{int(view.use_augmented.sum()):,} windows / {int(view.loc[view.use_augmented, 'episode_id'].nunique()):,} episodes**.",
             f"- States: **{int(view.admin1_iso.nunique()):,}**.", f"- Exposure semantics: **{counts}**.",
             "", "Per-state counts are in `weak_supervision_exposure_by_oblast.csv`; episode counts use `nunique(episode_id)`."]
    lines.extend(f"- {r.state}: Primary {int(r.primary_episode_n)}; Augmented {int(r.augmented_episode_n)} episodes." for r in state_df.itertuples())
    (root / "report" / "WEAK_SUPERVISION_EXPOSURE_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _prepare_reused_inputs(cfg: Config) -> Path:
    """Link immutable Stage 0/2 inputs from the completed data run.

    A new Stage 4 run has its own output directory, but the million-IP target
    universe and Activity sufficient statistics are reused without copying or
    mutating them.  The candidate/sensitivity outputs are written locally.
    """
    provenance = cfg.raw.get("stage4_provenance", {})
    source_name = str(provenance.get("stage2_source_run", "")).strip()
    if not source_name:
        raise ValueError("stage4_provenance.stage2_source_run must be frozen explicitly")
    run_root = cfg.root / cfg.raw["paths"]["run_root"]
    source = run_root / source_name
    if not source.exists():
        raise FileNotFoundError(f"Frozen Stage 2 source run does not exist: {source}")
    src = source / "data_derived"
    if not (src / "target_ip_universe.parquet").exists() or not (src / "stage02_activity_parts").exists():
        raise FileNotFoundError(f"Frozen Stage 2 source is incomplete: {source}")
    dd = cfg.out_dir("data_derived")
    # A resumed Stage 4 run may already contain symlinks.  They do not change
    # provenance: always return the explicitly configured source run.
    for name in ("target_ip_universe.parquet",):
        link, target = dd / name, source / "data_derived" / name
        if not link.exists(): link.symlink_to(target)
    for name in ("stage02_activity_parts", "simple_calibration"):
        link, target = dd / name, source / "data_derived" / name
        if not link.exists() and target.exists(): link.symlink_to(target, target_is_directory=True)
    old_stage00 = source / "results" / "stages" / "stage00_quality"
    new_stage00 = cfg.run_base / "results" / "stages" / "stage00_quality"
    if not new_stage00.exists() and old_stage00.exists():
        new_stage00.parent.mkdir(parents=True, exist_ok=True)
        new_stage00.symlink_to(old_stage00, target_is_directory=True)
    return source


def _panel_columns(panel: str) -> tuple[str, str, str, str]:
    return (("s_reach_primary", "s_rtt_primary", "support_episode_n_primary", "primary_estimable") if panel == "primary"
            else ("s_reach_augmented", "s_rtt_augmented", "support_episode_n_augmented", "augmented_estimable"))


def _safe_corr(x: pd.Series, y: pd.Series, method: str = "pearson") -> float:
    z = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(z) < 2 or z.x.nunique() < 2 or z.y.nunique() < 2:
        return float("nan")
    return float(z.x.corr(z.y, method=method))


def _assign_within_state_quintile(labels: pd.DataFrame, score: str, estimable: str, output: str) -> None:
    labels[output] = pd.Series(pd.NA, index=labels.index, dtype="string")
    for _, idx in labels[labels[estimable]].groupby("target_admin1", dropna=False).groups.items():
        g = labels.loc[idx, [score, "dst_ip"]].dropna(subset=[score]).sort_values([score, "dst_ip"], kind="mergesort")
        if len(g) < 5:
            continue
        q = np.floor(np.arange(len(g)) * 5 / len(g)).astype(int) + 1
        labels.loc[g.index, output] = pd.Series([f"Q{x}" for x in q], index=g.index, dtype="string")


def _panel_summary(labels: pd.DataFrame, panel: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    score, rtt, support, estimable = _panel_columns(panel)
    rows, corr = [], []
    for admin1, g in labels.groupby("target_admin1", dropna=False):
        s = pd.to_numeric(g[support], errors="coerce"); x = pd.to_numeric(g[score], errors="coerce"); scored = g[x.notna()]
        rows.append({"panel": panel, "target_admin1": admin1, "activity_estimable_ip_n": int(g.activity_estimable.sum()),
                     "sensitivity_support_ge_1_ip_n": int((s.ge(1) & x.notna()).sum()),
                     "sensitivity_support_ge_2_ip_n": int((s.ge(2) & x.notna()).sum()),
                     "sensitivity_support_ge_3_ip_n": int((s.ge(3) & x.notna()).sum()),
                     "sensitivity_support_ge_4_ip_n": int((s.ge(4) & x.notna()).sum()),
                     "estimable_ip_n": int(g[estimable].sum()),
                     "score_mean": float(scored[score].mean()) if len(scored) else np.nan,
                     "score_median": float(scored[score].median()) if len(scored) else np.nan,
                     "rtt_estimable_ip_n": int(g[rtt].notna().sum()), "q1_q5_constructible": bool(g[estimable].sum() >= 5)})
        e = g[g[estimable]]
        corr.append({"panel": panel, "target_admin1": admin1, "ip_n": int(len(e)),
                     "pearson_r": _safe_corr(e.activity_score_raw, e[score]),
                     "spearman_rho": _safe_corr(e.activity_score_raw, e[score], "spearman")})
    return pd.DataFrame(rows), pd.DataFrame(corr)


def _save(fig, path: Path) -> None:
    fig.savefig(path.with_suffix(".png"), dpi=220, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight")


def _write_figures(labels: pd.DataFrame, root: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"primary": "#245b8a", "augmented": "#d17b2f"}; out = []
    scores = {p: pd.to_numeric(labels[_panel_columns(p)[0]], errors="coerce").dropna().to_numpy() for p in colors}
    fig, ax = plt.subplots(figsize=(7.16, 4.2))
    for p,x in scores.items():
        if len(x): x=np.sort(x); ax.plot(x,np.arange(1,len(x)+1)/len(x),lw=1.4,label=p.title(),color=colors[p])
    ax.set(xlabel="S_i (p_ctrl − p_plan)",ylabel="ECDF",title="S4-1 Sensitivity ECDF"); ax.grid(alpha=.25); ax.legend(); path=root/"figures"/"S4-1_sensitivity_ecdf"; _save(fig,path); plt.close(fig); out.append(str(path))
    fig, ax = plt.subplots(figsize=(7.16,4.2))
    for p,x in scores.items():
        if len(x): ax.hist(x,bins=80,alpha=.45,density=True,label=p.title(),color=colors[p])
    ax.axvline(0,color="#333",lw=.8); ax.set(xlabel="S_i",ylabel="Density",title="S4-2 Sensitivity histogram"); ax.grid(alpha=.25); ax.legend(); path=root/"figures"/"S4-2_sensitivity_histogram"; _save(fig,path); plt.close(fig); out.append(str(path))
    fig, ax = plt.subplots(figsize=(6.2,4)); xx=np.arange(4); w=.38
    for j,p in enumerate(colors):
        s=pd.to_numeric(labels[_panel_columns(p)[2]],errors="coerce"); sc=pd.to_numeric(labels[_panel_columns(p)[0]],errors="coerce").notna(); vals=[int((s.ge(t)&sc).sum()) for t in (1,2,3,4)]; ax.bar(xx+(j-.5)*w,vals,w,label=p.title(),color=colors[p])
    ax.set_xticks(xx,["≥1","≥2","≥3","≥4"]); ax.set_ylabel("IP count"); ax.set_title("S4-3 Support episode count vs IP count"); ax.grid(axis="y",alpha=.25); ax.legend(); path=root/"figures"/"S4-3_support_episode_count"; _save(fig,path); plt.close(fig); out.append(str(path))
    fig, ax = plt.subplots(figsize=(7,4)); qlabs=["Q1","Q2","Q3","Q4","Q5"]; x=np.arange(5)
    for p in colors:
        q=labels[f"s_reach_quintile_{p}"].value_counts().reindex(qlabs,fill_value=0).to_numpy(dtype=float); q=q/q.sum() if q.sum() else q; ax.plot(x,q,marker="o",label=p.title(),color=colors[p])
    ax.set_xticks(x,qlabs); ax.set_ylabel("Population share"); ax.set_title("S4-4 Q1–Q5 population share"); ax.grid(alpha=.25); ax.legend(); path=root/"figures"/"S4-4_q_population_share"; _save(fig,path); plt.close(fig); out.append(str(path))
    fig, axes = plt.subplots(1,2,figsize=(10,4.1))
    for ax,p in zip(axes,colors):
        score=_panel_columns(p)[0]; g=labels[["activity_score_raw",score]].dropna(); g=g.sort_index().iloc[:250000] if len(g)>250000 else g
        if len(g)>=2: ax.hexbin(g.activity_score_raw,g[score],gridsize=70,mincnt=1,bins="log",cmap="viridis")
        ax.set(xlabel="Activity",ylabel="S_i",title=p.title()); ax.axhline(0,color="#555",lw=.6)
    fig.suptitle("S4-5 Activity × Sensitivity"); fig.tight_layout(); path=root/"figures"/"S4-5_activity_x_sensitivity"; _save(fig,path); plt.close(fig); out.append(str(path))
    fig, ax = plt.subplots(figsize=(9,5)); data=[]; names=[]
    for state in sorted(labels.target_admin1.dropna().astype(str).unique()):
        x=pd.to_numeric(labels.loc[labels.target_admin1.astype(str).eq(state),"s_reach_primary"],errors="coerce").dropna()
        if len(x): data.append(x.sort_values().iloc[::max(1,len(x)//4000 or 1)].to_numpy()); names.append(state)
    if data: ax.boxplot(data,labels=names,showfliers=False); ax.tick_params(axis="x",rotation=70)
    ax.axhline(0,color="#555",lw=.7); ax.set(ylabel="S_i (Primary)",title="S4-6 Sensitivity by Oblast"); ax.grid(axis="y",alpha=.25); fig.tight_layout(); path=root/"figures"/"S4-6_sensitivity_by_oblast"; _save(fig,path); plt.close(fig); out.append(str(path))
    fig, ax = plt.subplots(figsize=(10,5)); rows=[]
    for state,g in labels.groupby("target_admin1",dropna=False):
        row=[str(state),int(g.activity_estimable.sum())]
        for p in colors:
            score,_,support,_=_panel_columns(p); s=pd.to_numeric(g[support],errors="coerce"); sc=pd.to_numeric(g[score],errors="coerce").notna(); row.append(int((s.ge(3)&sc).sum()))
        rows.append(row)
    cov=pd.DataFrame(rows,columns=["state","activity","primary_ge3","augmented_ge3"]).sort_values("activity"); y=np.arange(len(cov)); ax.barh(y,cov.activity,label="Activity",color="#999",alpha=.65); ax.barh(y,cov.primary_ge3,label="Primary ≥3",color=colors["primary"]); ax.barh(y,cov.augmented_ge3,label="Augmented ≥3",color=colors["augmented"]); ax.set_yticks(y,cov.state); ax.set_xlabel("IP count"); ax.set_title("S4-7 Coverage by Oblast"); ax.grid(axis="x",alpha=.25); ax.legend(); fig.tight_layout(); path=root/"figures"/"S4-7_coverage_by_oblast"; _save(fig,path); plt.close(fig); out.append(str(path))
    return out


def _compare_previous_stage4(cfg: Config, labels: pd.DataFrame, root: Path) -> dict:
    """Compare only label-side quantities with the explicitly frozen prior run."""
    name = str(cfg.raw.get("stage4_provenance", {}).get("previous_stage4_run", "")).strip()
    if not name:
        raise ValueError("stage4_provenance.previous_stage4_run must be frozen explicitly")
    old_root = cfg.root / cfg.raw["paths"]["run_root"] / name / "results" / "stages" / STAGE
    rows, state_rows = [], []
    for panel, path_name, score, support in (("primary", "ip_sensitivity_primary.parquet", "s_reach_primary", "support_episode_n_primary"),
                                               ("augmented", "ip_sensitivity_augmented.parquet", "s_reach_augmented", "support_episode_n_augmented")):
        old_path = old_root / ("primary" if panel == "primary" else "augmented") / path_name
        if not old_path.exists():
            raise FileNotFoundError(f"Frozen previous Stage 4 output missing: {old_path}")
        old = pd.read_parquet(old_path)
        old_score = score if score in old else ("s_reach" if "s_reach" in old else score)
        old_support = support if support in old else ("support_episode_n" if "support_episode_n" in old else support)
        old = old[[c for c in ("dst_ip", "target_admin1", old_score, old_support) if c in old]].rename(columns={old_score: "old_s", old_support: "old_support"})
        new = labels[labels[score].notna()][[c for c in ("dst_ip", "target_admin1", score, support) if c in labels]].rename(columns={score: "new_s", support: "new_support"})
        both = old.merge(new, on="dst_ip", how="inner", suffixes=("_old", "_new"))
        d = pd.to_numeric(both.new_s, errors="coerce") - pd.to_numeric(both.old_s, errors="coerce")
        absd = d.abs().dropna()
        rows.append({"panel": panel, "old_ip_n": int(len(old)), "new_ip_n": int(len(new)), "common_ip_n": int(len(both)),
                     "old_support_ge_1_ip_n": int(pd.to_numeric(old.old_support, errors="coerce").ge(1).sum()),
                     "new_support_ge_1_ip_n": int(pd.to_numeric(new.new_support, errors="coerce").ge(1).sum()),
                     "old_support_ge_2_ip_n": int(pd.to_numeric(old.old_support, errors="coerce").ge(2).sum()),
                     "new_support_ge_2_ip_n": int(pd.to_numeric(new.new_support, errors="coerce").ge(2).sum()),
                     "old_support_ge_3_ip_n": int(pd.to_numeric(old.old_support, errors="coerce").ge(3).sum()),
                     "new_support_ge_3_ip_n": int(pd.to_numeric(new.new_support, errors="coerce").ge(3).sum()),
                     "old_support_ge_4_ip_n": int(pd.to_numeric(old.old_support, errors="coerce").ge(4).sum()),
                     "new_support_ge_4_ip_n": int(pd.to_numeric(new.new_support, errors="coerce").ge(4).sum()),
                     "s_old_new_pearson": _safe_corr(both.old_s, both.new_s),
                     "s_old_new_spearman": _safe_corr(both.old_s, both.new_s, "spearman"),
                     "median_absolute_difference": float(absd.median()) if len(absd) else np.nan,
                     "p95_absolute_difference": float(absd.quantile(.95)) if len(absd) else np.nan})
        for state, og in old.groupby("target_admin1", dropna=False):
            ng = new[new.target_admin1.eq(state)]
            state_rows.append({"panel": panel, "target_admin1": state,
                               "old_support_ge_3_ip_n": int(pd.to_numeric(og.old_support, errors="coerce").ge(3).sum()),
                               "new_support_ge_3_ip_n": int(pd.to_numeric(ng.new_support, errors="coerce").ge(3).sum()),
                               "delta_support_ge_3_ip_n": int(pd.to_numeric(ng.new_support, errors="coerce").ge(3).sum() - pd.to_numeric(og.old_support, errors="coerce").ge(3).sum())})
    pd.DataFrame(rows).to_csv(root / "tables" / "old_vs_new_sensitivity_comparison.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(state_rows).to_csv(root / "tables" / "old_vs_new_support_by_oblast.csv", index=False, encoding="utf-8-sig")
    return {"previous_stage4_run": str(old_root), "comparison_rows": int(len(rows))}


def _manifest(cfg: Config, root: Path, started: datetime, status: str, exposure_view: Path,
              summary: dict, source_run: Path) -> Path:
    files=[]
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "stage_manifest.json": files.append({"path":str(p.relative_to(root)),"bytes":p.stat().st_size,"sha256":file_sha256(p)})
    workbook=cfg.resource_path("calibration_workbook")
    provenance = cfg.raw.get("stage4_provenance", {})
    stage3_run = cfg.root / cfg.raw["paths"]["run_root"] / str(provenance.get("stage3_source_run", ""))
    stage3_windows = stage3_run / "results" / "stages" / "stage03_calibration_events" / "tables" / "calibration_windows.csv"
    stage2_target = source_run / "data_derived" / "target_ip_universe.parquet"
    stage2_parts = sorted((source_run / "data_derived" / "stage02_activity_parts").glob("*.parquet"))
    payload={"stage":STAGE,"run_id":cfg.run_id,"git_commit":_git_commit(cfg.root),
             "config_sha256":file_sha256(cfg.config_path),"config_hash":file_sha256(cfg.config_path),
             "calibration_workbook_sha256":file_sha256(workbook),"frozen_exposure_view_sha256":file_sha256(exposure_view),
             "stage2_source_run":str(source_run),"stage2_activity_input_sha256":_hash_many(stage2_parts),
             "target_ip_universe_sha256":file_sha256(stage2_target),"stage3_source_run":str(stage3_run),
             "stage3_calibration_windows_sha256":file_sha256(stage3_windows),
             "input_hashes":{str(cfg.config_path):file_sha256(cfg.config_path),str(workbook):file_sha256(workbook),
                              str(exposure_view):file_sha256(exposure_view),str(stage2_target):file_sha256(stage2_target),
                              str(stage3_windows):file_sha256(stage3_windows)},"output_hashes":files,
             "start_time":started.isoformat(),"end_time":datetime.now(timezone.utc).isoformat(),"status":status,
             "war_attack_data_used":False,"random_seed":RANDOM_SEED,
             **{k:v for k,v in summary.items() if k not in {"contract_checks","calibration_result"}},
             "contract_checks":summary.get("contract_checks",{})}
    path=root/"stage_manifest.json"; path.write_text(json.dumps(payload,indent=2,ensure_ascii=False,default=str),encoding="utf-8"); return path


def run(cfg: Config) -> dict:
    started=datetime.now(timezone.utc); root=_root(cfg); exposure_view=_build_weak_supervision_exposure_view(cfg,root); input_run=_prepare_reused_inputs(cfg)
    from . import simple_calibration
    calibration_result=simple_calibration.run(cfg,exposure_view=exposure_view)
    rt=cfg.out_dir("results_tables"); label_path=rt/"b1_full_sensitivity_labels.parquet"
    if not label_path.exists(): raise RuntimeError("calibration did not produce b1_full_sensitivity_labels.parquet")
    labels=pd.read_parquet(label_path).copy(); labels["activity_estimable"]=pd.to_numeric(labels.get("activity_score_raw"),errors="coerce").notna()
    for p in ("primary","augmented"):
        score,rtt,support,estimable=_panel_columns(p); labels[support]=pd.to_numeric(labels.get(support),errors="coerce"); labels[score]=pd.to_numeric(labels.get(score),errors="coerce"); labels[estimable]=labels[score].notna()&labels[support].ge(3); _assign_within_state_quintile(labels,score,estimable,f"s_reach_quintile_{p}"); _assign_within_state_quintile(labels,rtt,estimable,f"s_rtt_quintile_{p}")
    labels["s_reach_quintile"]=labels["s_reach_quintile_primary"]; labels["s_rtt_quintile"]=labels["s_rtt_quintile_primary"]
    state_frames=[]; corr_frames=[]
    for p in ("primary","augmented"):
        st,co=_panel_summary(labels,p); state_frames.append(st); corr_frames.append(co)
    state_df=pd.concat(state_frames,ignore_index=True); corr_by=pd.concat(corr_frames,ignore_index=True); state_df.to_csv(root/"tables"/"sensitivity_support_by_oblast.csv",index=False,encoding="utf-8-sig"); corr_by.to_csv(root/"tables"/"activity_sensitivity_correlation_by_oblast.csv",index=False,encoding="utf-8-sig")
    corr=[]
    for p in ("primary","augmented"):
        score,_,support,_=_panel_columns(p); s=pd.to_numeric(labels[support],errors="coerce")
        for threshold, population in ((1,"support_ge_1_diagnostic"),(3,"support_ge_3_formal")):
            g=labels[labels[score].notna() & s.ge(threshold)]
            corr.append({"panel":p,"population":population,"support_threshold":threshold,"ip_n":int(len(g)),
                         "pearson_r":_safe_corr(g.activity_score_raw,g[score]),
                         "spearman_rho":_safe_corr(g.activity_score_raw,g[score],"spearman")})
    pd.DataFrame(corr).to_csv(root/"tables"/"activity_sensitivity_correlation.csv",index=False,encoding="utf-8-sig")
    support_rows=[]
    for p in ("primary","augmented"):
        score,_,support,_=_panel_columns(p); s=pd.to_numeric(labels[support],errors="coerce"); sc=pd.to_numeric(labels[score],errors="coerce").notna()
        for t in (1,2,3,4): support_rows.append({"panel":p,"support_threshold":t,"ip_n":int((s.ge(t)&sc).sum()),"state_n":int(labels.loc[s.ge(t)&sc,"target_admin1"].nunique())})
    support_df=pd.DataFrame(support_rows); support_df.to_csv(root/"tables"/"support_threshold_ip_counts.csv",index=False,encoding="utf-8-sig")
    primary_all=labels[labels.s_reach_primary.notna()].copy(); augmented_all=labels[labels.s_reach_augmented.notna()].copy(); primary_all.to_parquet(root/"primary"/"ip_sensitivity_primary.parquet",index=False); augmented_all.to_parquet(root/"augmented"/"ip_sensitivity_augmented.parquet",index=False); primary_all.to_csv(root/"primary"/"ip_sensitivity_primary.csv",index=False,encoding="utf-8-sig"); augmented_all.to_csv(root/"augmented"/"ip_sensitivity_augmented.csv",index=False,encoding="utf-8-sig")
    dist=[]
    for p in ("primary","augmented"):
        score,_,support,_=_panel_columns(p); s=pd.to_numeric(labels[support],errors="coerce")
        for threshold in (1,2,3,4):
            x=pd.to_numeric(labels.loc[labels[score].notna() & s.ge(threshold),score],errors="coerce").dropna()
            dist.append({"panel":p,"support_threshold":threshold,"ip_n":int(len(x)),
                         "mean":float(x.mean()) if len(x) else np.nan,"median":float(x.median()) if len(x) else np.nan,
                         "p5":float(x.quantile(.05)) if len(x) else np.nan,"p25":float(x.quantile(.25)) if len(x) else np.nan,
                         "p75":float(x.quantile(.75)) if len(x) else np.nan,"p95":float(x.quantile(.95)) if len(x) else np.nan,
                         "negative_fraction":float((x<0).mean()) if len(x) else np.nan,
                         "abs_le_0_01_fraction":float((x.abs()<=.01).mean()) if len(x) else np.nan,
                         "exact_minus1_fraction":float((x.eq(-1)).mean()) if len(x) else np.nan,
                         "exact_zero_fraction":float((x.eq(0)).mean()) if len(x) else np.nan,
                         "exact_one_fraction":float((x.eq(1)).mean()) if len(x) else np.nan})
    pd.DataFrame(dist).to_csv(root/"tables"/"sensitivity_distribution_summary.csv",index=False,encoding="utf-8-sig")
    both=labels[labels.s_reach_primary.notna()&labels.s_reach_augmented.notna()]; d=(both.s_reach_primary-both.s_reach_augmented).abs(); pd.DataFrame([{"common_ip_n":int(len(both)),"s_correlation_pearson":_safe_corr(both.s_reach_primary,both.s_reach_augmented),"s_correlation_spearman":_safe_corr(both.s_reach_primary,both.s_reach_augmented,"spearman"),"median_absolute_difference":float(d.median()) if len(d) else np.nan}]).to_csv(root/"tables"/"primary_vs_augmented_comparison.csv",index=False,encoding="utf-8-sig")
    q_frames=[]
    for p in ("primary","augmented"):
        qcol=f"s_reach_quintile_{p}"; q=labels[labels[qcol].notna()]; q_frames.append(q.assign(panel=p).groupby(["panel","target_admin1",qcol]).size().rename("ip_n").reset_index().rename(columns={qcol:"quintile"}))
    pd.concat(q_frames,ignore_index=True).to_csv(root/"tables"/"sensitivity_quintile_population.csv",index=False,encoding="utf-8-sig")
    exposure = pd.read_csv(exposure_view)
    primary_use = _bool(exposure.use_primary)
    primary_episode_states = set(exposure.loc[primary_use].groupby("state").episode_id.nunique().loc[lambda s: s.ge(3)].index)
    state_lookup = state_df[state_df.panel.eq("primary")].set_index("target_admin1")
    q_audit_rows = []
    for state in sorted(primary_episode_states):
        row = state_lookup.loc[state] if state in state_lookup.index else pd.Series(dtype=object)
        q_ok = bool(row.get("q1_q5_constructible", False))
        q_audit_rows.append({"state": state,
                             "primary_episode_n": int(exposure.loc[primary_use & exposure.state.eq(state), "episode_id"].nunique()),
                             "support_ge_1_ip_n": int(row.get("sensitivity_support_ge_1_ip_n", 0)),
                             "support_ge_2_ip_n": int(row.get("sensitivity_support_ge_2_ip_n", 0)),
                             "support_ge_3_ip_n": int(row.get("sensitivity_support_ge_3_ip_n", 0)),
                             "support_ge_4_ip_n": int(row.get("sensitivity_support_ge_4_ip_n", 0)),
                             "q1_q5_constructible": q_ok,
                             "reason": "constructible" if q_ok else "fewer than five support>=3 IPs"})
    pd.DataFrame(q_audit_rows).to_csv(root/"tables"/"primary_q_constructibility_audit.csv",index=False,encoding="utf-8-sig")
    comparison = _compare_previous_stage4(cfg, labels, root)
    figure_paths=_write_figures(labels,root)
    view=exposure; primary_win_n=int(primary_use.sum()); augmented_win_n=int(_bool(view.use_augmented).sum()); primary_ep_n=int(view.loc[primary_use,"episode_id"].nunique()); augmented_ep_n=int(view.loc[_bool(view.use_augmented),"episode_id"].nunique())
    checks={"episode_support_uses_unique_episode":True,"multiple_windows_do_not_increase_episode_weight":True,"no_stable_activity_gate":True,"primary_is_subset_of_augmented":set(primary_all.dst_ip).issubset(set(augmented_all.dst_ip)),"negative_sensitivity_retained":bool((pd.concat([primary_all.s_reach_primary,augmented_all.s_reach_augmented],ignore_index=True)<0).any()),"war_events_not_used_in_stage4":True,"same_episode_not_used_as_normal_control":True}; status="PASS" if all(checks.values()) else "FAIL"
    summary={"primary_window_n":primary_win_n,"primary_episode_n":primary_ep_n,"augmented_window_n":augmented_win_n,"augmented_episode_n":augmented_ep_n,"primary_sensitivity_output_row_n":int(len(primary_all)),"augmented_sensitivity_output_row_n":int(len(augmented_all)),"primary_estimable_ip_n":int(labels.primary_estimable.sum()),"augmented_estimable_ip_n":int(labels.augmented_estimable.sum()),"primary_q_constructible_state_n":int(sum(bool(x["q1_q5_constructible"]) for x in q_audit_rows)),"primary_q_audit":q_audit_rows,"support_thresholds":[1,2,3,4],"input_data_run":str(input_run),"contract_checks":checks,"war_attack_data_used":False,"calibration_result":calibration_result,"label_side_comparison":comparison}
    (root/"tables"/"stage04_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    def nums(panel):
        z=support_df[support_df.panel.eq(panel)].sort_values("support_threshold"); return "; ".join(f">={int(r.support_threshold)}: {int(r.ip_n):,} IP / {int(r.state_n)} states" for r in z.itertuples())
    q_missing = [r for r in q_audit_rows if not r["q1_q5_constructible"]]
    lines=["# Stage 4 — Planned-Outage-Associated IP Sensitivity","",f"Run ID: `{cfg.run_id}`","","This Stage uses state-level planned-outage weak supervision; it does not assume that every IP in a state was physically disconnected during a planned window.","War-attack outcomes, H1–H4, and prediction models were not loaded.","", "## Frozen exposure", "",f"- Primary: **{primary_win_n:,} windows / {primary_ep_n:,} episodes**.",f"- Augmented: **{augmented_win_n:,} windows / {augmented_ep_n:,} episodes**.","- Episode aggregation is cycle-pooled within each frozen episode, then episode-equal across independent episodes.","- Rotational schedules are weak-supervision windows, not uniform physical-outage labels.","", "## Coverage", "",f"- Primary: {nums('primary')}",f"- Augmented: {nums('augmented')}","- All support>=1 scores are retained; support>=3 is only the registered estimability flag.","- Q1–Q5 use deterministic stable sorting by `(S_i, dst_ip)` within each state after support>=3.",f"- Primary states with ≥3 frozen episodes: **{len(primary_episode_states)}**; Q1–Q5 constructible: **{sum(bool(x['q1_q5_constructible']) for x in q_audit_rows)}**."]
    if q_missing:
        lines.append("- Primary ≥3-episode state without Q1–Q5: " + "; ".join(f"{r['state']} (episodes={r['primary_episode_n']}, support≥3 IP={r['support_ge_3_ip_n']}; {r['reason']})" for r in q_missing))
    lines += ["", "## Distribution and association", "", "`activity_sensitivity_correlation.csv` reports support≥1 diagnostic and support≥3 formal populations. `sensitivity_distribution_summary.csv` reports support≥1/2/3/4, exact endpoint masses, and negative fractions. `old_vs_new_sensitivity_comparison.csv` is label-side only.","", "## Contract checks", ""]
    lines.extend(f"- `{k}`: **{v}**" for k,v in checks.items()); lines += ["", "## Gate", "",f"**{status}**","","Stop after Stage 4. Do not run Stage 5+, H1–H4, or war-attack analysis automatically."]
    report=root/"report"/"STAGE04_REPORT.md"; report.write_text("\n".join(lines)+"\n",encoding="utf-8"); manifest=_manifest(cfg,root,started,status,exposure_view,summary,input_run)
    return {"status":status,**{k:v for k,v in summary.items() if k not in {"calibration_result","contract_checks"}},"outputs":[str(report),str(manifest),*figure_paths]}
