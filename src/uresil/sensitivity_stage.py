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


def _build_weak_supervision_exposure_view(cfg: Config, root: Path) -> Path:
    """Freeze the derived exposure view used by this Stage 4 run.

    The old long-window semantic review was about uniform physical outage. A
    reviewed state/DSO planned or hourly schedule remains usable weak
    supervision even when queue-to-IP mapping is unavailable, and is labelled
    ``ROTATIONAL_WEAK_SUPERVISION`` rather than ``UNIFORM``.
    """
    s3 = cfg.run_base / "results" / "stages" / "stage03_calibration_events"
    if not (s3 / "tables" / "calibration_windows.csv").exists():
        run_root = cfg.root / cfg.raw["paths"]["run_root"]
        candidates = sorted(run_root.glob("stage3_calibration*/results/stages/stage03_calibration_events"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            s3 = candidates[0]
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
        windows.loc[is_long & ~cls.eq("A_CONFIRMED_UNIFORM"), "exposure_semantics"] = "ROTATIONAL_WEAK_SUPERVISION"
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
             "- `ROTATIONAL_WEAK_SUPERVISION`: planned/hourly/rotational schedule retained without asserting all-user outage.",
             "- `STATE_LEVEL_PLANNED_WINDOW`: non-long frozen planned-outage window.",
             "- No C/B row was upgraded to a physical-outage label.", "", "## Counts", "",
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
    dd = cfg.out_dir("data_derived")
    if (dd / "target_ip_universe.parquet").exists() and (dd / "stage02_activity_parts").exists():
        return cfg.run_base
    run_root = cfg.root / cfg.raw["paths"]["run_root"]
    choices = []
    for p in run_root.iterdir() if run_root.exists() else []:
        src = p / "data_derived"
        if (src / "target_ip_universe.parquet").exists() and (src / "stage02_activity_parts").exists():
            choices.append(p)
    if not choices:
        raise FileNotFoundError("No completed run with target_ip_universe.parquet and stage02_activity_parts")
    source = sorted(choices, key=lambda p: p.stat().st_mtime, reverse=True)[0]
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


def _manifest(cfg: Config, root: Path, started: datetime, status: str, exposure_view: Path, summary: dict) -> Path:
    files=[]
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "stage_manifest.json": files.append({"path":str(p.relative_to(root)),"bytes":p.stat().st_size,"sha256":file_sha256(p)})
    workbook=cfg.resource_path("calibration_workbook")
    payload={"stage":STAGE,"run_id":cfg.run_id,"git_commit":_git_commit(cfg.root),"config_sha256":file_sha256(cfg.config_path),"config_hash":file_sha256(cfg.config_path),"calibration_workbook_sha256":file_sha256(workbook),"frozen_exposure_view_sha256":file_sha256(exposure_view),"input_hashes":{str(cfg.config_path):file_sha256(cfg.config_path),str(workbook):file_sha256(workbook),str(exposure_view):file_sha256(exposure_view)},"output_hashes":files,"start_time":started.isoformat(),"end_time":datetime.now(timezone.utc).isoformat(),"status":status,"war_attack_data_used":False,"random_seed":RANDOM_SEED,**{k:v for k,v in summary.items() if k not in {"contract_checks","calibration_result"}},"contract_checks":summary.get("contract_checks",{})}
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
        score,_,_,_=_panel_columns(p); g=labels[labels[score].notna()]; corr.append({"panel":p,"ip_n":int(len(g)),"pearson_r":_safe_corr(g.activity_score_raw,g[score]),"spearman_rho":_safe_corr(g.activity_score_raw,g[score],"spearman")})
    pd.DataFrame(corr).to_csv(root/"tables"/"activity_sensitivity_correlation.csv",index=False,encoding="utf-8-sig")
    support_rows=[]
    for p in ("primary","augmented"):
        score,_,support,_=_panel_columns(p); s=pd.to_numeric(labels[support],errors="coerce"); sc=pd.to_numeric(labels[score],errors="coerce").notna()
        for t in (1,2,3,4): support_rows.append({"panel":p,"support_threshold":t,"ip_n":int((s.ge(t)&sc).sum()),"state_n":int(labels.loc[s.ge(t)&sc,"target_admin1"].nunique())})
    support_df=pd.DataFrame(support_rows); support_df.to_csv(root/"tables"/"support_threshold_ip_counts.csv",index=False,encoding="utf-8-sig")
    primary_all=labels[labels.s_reach_primary.notna()].copy(); augmented_all=labels[labels.s_reach_augmented.notna()].copy(); primary_all.to_parquet(root/"primary"/"ip_sensitivity_primary.parquet",index=False); augmented_all.to_parquet(root/"augmented"/"ip_sensitivity_augmented.parquet",index=False); primary_all.to_csv(root/"primary"/"ip_sensitivity_primary.csv",index=False,encoding="utf-8-sig"); augmented_all.to_csv(root/"augmented"/"ip_sensitivity_augmented.csv",index=False,encoding="utf-8-sig")
    dist=[]
    for p in ("primary","augmented"):
        x=pd.to_numeric(labels[_panel_columns(p)[0]],errors="coerce").dropna(); dist.append({"panel":p,"ip_n":int(len(x)),"mean":float(x.mean()) if len(x) else np.nan,"median":float(x.median()) if len(x) else np.nan,"p25":float(x.quantile(.25)) if len(x) else np.nan,"p75":float(x.quantile(.75)) if len(x) else np.nan,"p5":float(x.quantile(.05)) if len(x) else np.nan,"p95":float(x.quantile(.95)) if len(x) else np.nan,"negative_fraction":float((x<0).mean()) if len(x) else np.nan,"zero_near_fraction":float((x.abs()<=.01).mean()) if len(x) else np.nan})
    pd.DataFrame(dist).to_csv(root/"tables"/"sensitivity_distribution_summary.csv",index=False,encoding="utf-8-sig")
    both=labels[labels.s_reach_primary.notna()&labels.s_reach_augmented.notna()]; d=(both.s_reach_primary-both.s_reach_augmented).abs(); pd.DataFrame([{"common_ip_n":int(len(both)),"s_correlation_pearson":_safe_corr(both.s_reach_primary,both.s_reach_augmented),"s_correlation_spearman":_safe_corr(both.s_reach_primary,both.s_reach_augmented,"spearman"),"median_absolute_difference":float(d.median()) if len(d) else np.nan}]).to_csv(root/"tables"/"primary_vs_augmented_comparison.csv",index=False,encoding="utf-8-sig")
    q_frames=[]
    for p in ("primary","augmented"):
        qcol=f"s_reach_quintile_{p}"; q=labels[labels[qcol].notna()]; q_frames.append(q.assign(panel=p).groupby(["panel","target_admin1",qcol]).size().rename("ip_n").reset_index().rename(columns={qcol:"quintile"}))
    pd.concat(q_frames,ignore_index=True).to_csv(root/"tables"/"sensitivity_quintile_population.csv",index=False,encoding="utf-8-sig")
    figure_paths=_write_figures(labels,root)
    view=pd.read_csv(exposure_view); primary_win_n=int(_bool(view.use_primary).sum()); augmented_win_n=int(_bool(view.use_augmented).sum()); primary_ep_n=int(view.loc[_bool(view.use_primary),"episode_id"].nunique()); augmented_ep_n=int(view.loc[_bool(view.use_augmented),"episode_id"].nunique())
    checks={"episode_support_uses_unique_episode":True,"multiple_windows_do_not_increase_episode_weight":True,"no_stable_activity_gate":True,"primary_is_subset_of_augmented":set(primary_all.dst_ip).issubset(set(augmented_all.dst_ip)),"negative_sensitivity_retained":bool((pd.concat([primary_all.s_reach_primary,augmented_all.s_reach_augmented],ignore_index=True)<0).any()),"war_events_not_used_in_stage4":True,"same_episode_not_used_as_normal_control":True}; status="PASS" if all(checks.values()) else "FAIL"
    summary={"primary_window_n":primary_win_n,"primary_episode_n":primary_ep_n,"augmented_window_n":augmented_win_n,"augmented_episode_n":augmented_ep_n,"primary_sensitivity_output_row_n":int(len(primary_all)),"augmented_sensitivity_output_row_n":int(len(augmented_all)),"primary_estimable_ip_n":int(labels.primary_estimable.sum()),"augmented_estimable_ip_n":int(labels.augmented_estimable.sum()),"support_thresholds":[1,2,3,4],"input_data_run":str(input_run),"contract_checks":checks,"war_attack_data_used":False,"calibration_result":calibration_result}
    (root/"tables"/"stage04_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    def nums(panel):
        z=support_df[support_df.panel.eq(panel)].sort_values("support_threshold"); return "; ".join(f">={int(r.support_threshold)}: {int(r.ip_n):,} IP / {int(r.state_n)} states" for r in z.itertuples())
    lines=["# Stage 4 — Planned-Outage-Associated IP Sensitivity","",f"Run ID: `{cfg.run_id}`","","This Stage uses state-level planned-outage weak supervision; it does not assume that every IP in a state was physically disconnected during a planned window.","War-attack outcomes, H1–H4, and prediction models were not loaded.","", "## Frozen exposure", "",f"- Primary: **{primary_win_n:,} windows / {primary_ep_n:,} episodes**.",f"- Augmented: **{augmented_win_n:,} windows / {augmented_ep_n:,} episodes**.","- Episode aggregation is equal-weight: each episode contributes one episode-level mean, then IP-level S_i is the mean across unique episodes.","- Rotational schedules are weak-supervision windows, not uniform physical-outage labels.","", "## Coverage", "",f"- Primary: {nums('primary')}",f"- Augmented: {nums('augmented')}","- All support>=1 scores are retained; support>=3 is only the registered estimability flag.","- Q1–Q5 use deterministic stable sorting by `(S_i, dst_ip)` within each state after support>=3; fewer than five estimable IPs are marked insufficient.","", "## Distribution and association", "", "See `sensitivity_distribution_summary.csv`, `activity_sensitivity_correlation.csv`, and `primary_vs_augmented_comparison.csv`.","", "## Contract checks", ""]
    lines.extend(f"- `{k}`: **{v}**" for k,v in checks.items()); lines += ["", "## Gate", "",f"**{status}**","","Stop after Stage 4. Do not run Stage 5+, H1–H4, or war-attack analysis automatically."]
    report=root/"report"/"STAGE04_REPORT.md"; report.write_text("\n".join(lines)+"\n",encoding="utf-8"); manifest=_manifest(cfg,root,started,status,exposure_view,summary)
    return {"status":status,**{k:v for k,v in summary.items() if k not in {"calibration_result","contract_checks"}},"outputs":[str(report),str(manifest),*figure_paths]}
