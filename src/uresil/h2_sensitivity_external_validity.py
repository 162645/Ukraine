"""H2: external validity of frozen planned-outage Sensitivity labels.

This module deliberately consumes frozen Stage 4/4.5 labels and the frozen H1
endpoint outcome artifact.  It never queries ClickHouse and never recomputes
event sensitivity.  H2 is an association/external-validity analysis, not a
causal test and not a predictive model.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr


CORE_EVENTS = [
    "E2024_0826_ATTACK",
    "E2024_0917_SUMY",
    "E2024_1117_ATTACK",
    "E2024_1128_ATTACK",
    "E2024_1213_ATTACK",
    "E2024_1225_ATTACK",
]
QUINTILES = ["Q1", "Q2", "Q3", "Q4", "Q5"]
SEED = 20260910


@dataclass(frozen=True)
class Panel:
    key: str
    label: str
    source: str
    score: str
    support: str
    threshold: int


PANELS = {
    "MAIN": Panel("MAIN", "AUGMENTED_STRICT_SUPPORT3", "stage45", "s_reach_augmented", "support_episode_n_augmented", 3),
    "A": Panel("A", "PRIMARY_STRICT_SUPPORT3", "stage45", "s_reach_primary", "support_episode_n_primary", 3),
    "B": Panel("B", "AUGMENTED_WEAK_SUPPORT3", "stage4", "s_reach_augmented", "support_episode_n_augmented", 3),
    "C": Panel("C", "AUGMENTED_STRICT_SUPPORT2", "stage45", "s_reach_augmented", "support_episode_n_augmented", 2),
    "D": Panel("D", "AUGMENTED_STRICT_SUPPORT4", "stage45", "s_reach_augmented", "support_episode_n_augmented", 4),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _q_labels(df: pd.DataFrame, score: str, support: str, threshold: int) -> pd.DataFrame:
    """Assign frozen-rule state-wise Q1--Q5 labels from frozen S_i values.

    This is only a deterministic label projection: S_i itself is never
    re-estimated.  Stable IP ordering resolves ties without randomisation.
    """
    out = df.copy()
    ok = out[score].notna() & out[support].ge(threshold) & out["target_admin1"].notna()
    out["estimable"] = ok
    out["q"] = pd.Series(pd.NA, index=out.index, dtype="string")
    if not ok.any():
        return out
    x = out.loc[ok, ["dst_ip", "target_admin1", score]].copy()
    x = x.sort_values(["target_admin1", score, "dst_ip"], kind="mergesort")
    pos = x.groupby("target_admin1", sort=False).cumcount()
    n = x.groupby("target_admin1", sort=False)["dst_ip"].transform("size")
    qi = np.minimum(4, np.floor(pos.to_numpy() * 5 / n.to_numpy()).astype(int))
    x["q"] = pd.Categorical.from_codes(qi, QUINTILES, ordered=True)
    out.loc[x.index, "q"] = x["q"].astype("string")
    return out


def _load_outcomes(h1_dir: Path) -> pd.DataFrame:
    cols = ["dst_ip", "target_admin1", "event_id", "pre_attack_reach", "attack_reach", "reach_drop", "outcome_valid"]
    x = pd.read_parquet(h1_dir / "h1_ip_level_outcomes.parquet", columns=cols)
    x = x[x["event_id"].isin(CORE_EVENTS)].copy()
    x = x[x["outcome_valid"].fillna(False).astype(bool)].copy()
    x["reach_drop"] = pd.to_numeric(x["reach_drop"], errors="coerce")
    x = x[x["reach_drop"].notna()]
    return x


def _load_labels(stage45: Path, stage4: Path) -> dict[str, pd.DataFrame]:
    cols = ["dst_ip", "target_admin1", "activity_score_smoothed", "s_reach_primary", "support_episode_n_primary", "s_reach_augmented", "support_episode_n_augmented"]
    a = pd.read_parquet(stage45 / "b1_full_sensitivity_labels.parquet", columns=cols)
    b = pd.read_parquet(stage4 / "b1_full_sensitivity_labels.parquet", columns=["dst_ip", "target_admin1", "activity_score_smoothed", "s_reach_augmented", "support_episode_n_augmented"])
    return {"stage45": a, "stage4": b}


def _panel_rows(outcomes: pd.DataFrame, labels: dict[str, pd.DataFrame], panel: Panel) -> pd.DataFrame:
    l = labels[panel.source].copy()
    l = _q_labels(l, panel.score, panel.support, panel.threshold)
    keep = ["dst_ip", "target_admin1", "activity_score_smoothed", panel.score, panel.support, "estimable", "q"]
    l = l[keep].rename(columns={panel.score: "sensitivity", panel.support: "support_episode_n", "q": "quintile"})
    x = outcomes.merge(l, on=["dst_ip", "target_admin1"], how="inner", validate="many_to_one")
    x = x[x["estimable"]].copy()
    x["panel"] = panel.key
    return x


def _metrics(v: pd.Series) -> dict[str, float]:
    a = pd.to_numeric(v, errors="coerce").dropna().to_numpy()
    if not len(a):
        return {"n": 0, "mean": np.nan, "median": np.nan, "p25": np.nan, "p75": np.nan,
                "frac_gt0": np.nan, "frac_ge010": np.nan, "frac_ge025": np.nan, "frac_ge050": np.nan}
    return {"n": int(len(a)), "mean": float(np.mean(a)), "median": float(np.median(a)),
            "p25": float(np.quantile(a, .25)), "p75": float(np.quantile(a, .75)),
            "frac_gt0": float(np.mean(a > 0)), "frac_ge010": float(np.mean(a >= .10)),
            "frac_ge025": float(np.mean(a >= .25)), "frac_ge050": float(np.mean(a >= .50))}


def _state_event_summary(x: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (event, state, q), g in x.groupby(["event_id", "target_admin1", "quintile"], observed=True):
        m = _metrics(g["reach_drop"])
        m.update({"event_id": event, "target_admin1": state, "quintile": q,
                  "activity_mean": float(g["activity_score_smoothed"].mean()),
                  "activity_median": float(g["activity_score_smoothed"].median()),
                  "sensitivity_mean": float(g["sensitivity"].mean()),
                  "sensitivity_median": float(g["sensitivity"].median())})
        rows.append(m)
    return pd.DataFrame(rows)


def _event_q_means(se: pd.DataFrame) -> pd.DataFrame:
    if se.empty:
        return pd.DataFrame()
    a = se.groupby(["event_id", "quintile"], observed=True)["mean"].mean().reset_index(name="state_equal_mean_drop")
    med = se.groupby(["event_id", "quintile"], observed=True)["median"].mean().reset_index(name="state_equal_median_drop")
    a = a.merge(med, on=["event_id", "quintile"])
    return a


def _bootstrap_effect(x: pd.DataFrame, n_boot: int = 1000) -> tuple[float, float, float]:
    """State-within-event then event-equal bootstrap CI for Q5-Q1 mean effect."""
    rng = np.random.default_rng(SEED)
    state = x.groupby(["event_id", "target_admin1", "quintile"], observed=True)["reach_drop"].mean().reset_index()
    wide = state.pivot_table(index=["event_id", "target_admin1"], columns="quintile", values="reach_drop")
    wide = wide.dropna(subset=["Q1", "Q5"])
    if wide.empty:
        return np.nan, np.nan, np.nan
    evs = wide.index.get_level_values(0).unique().tolist()
    observed = float(wide.assign(eff=wide["Q5"] - wide["Q1"]).groupby(level=0)["eff"].mean().mean())
    vals = []
    for _ in range(n_boot):
        e_sample = rng.choice(evs, size=len(evs), replace=True)
        effs = []
        for e in e_sample:
            g = wide.xs(e, level=0)
            if len(g):
                gs = g.iloc[rng.integers(0, len(g), size=len(g))]
                effs.append(float((gs["Q5"] - gs["Q1"]).mean()))
        if effs:
            vals.append(float(np.mean(effs)))
    if not vals:
        return observed, np.nan, np.nan
    return observed, float(np.quantile(vals, .025)), float(np.quantile(vals, .975))


def _bootstrap_risk_ratio(x: pd.DataFrame, threshold: float = .25, n_boot: int = 1000) -> tuple[float, float, float]:
    rng = np.random.default_rng(SEED + 7)
    x = x.copy()
    x["severe"] = x["reach_drop"] >= threshold
    state = x.groupby(["event_id", "target_admin1", "quintile"], observed=True)["severe"].mean().reset_index()
    wide = state.pivot_table(index=["event_id", "target_admin1"], columns="quintile", values="severe").dropna(subset=["Q1", "Q5"])
    if wide.empty:
        return np.nan, np.nan, np.nan
    evs = wide.index.get_level_values(0).unique().tolist()
    def ratio(w):
        den = w.groupby(level=0)["Q1"].mean().mean(); num = w.groupby(level=0)["Q5"].mean().mean()
        return float(num / den) if den > 0 else np.nan
    observed = ratio(wide)
    vals = []
    for _ in range(n_boot):
        e_sample = rng.choice(evs, size=len(evs), replace=True)
        parts = []
        for e in e_sample:
            g = wide.xs(e, level=0)
            if len(g):
                parts.append(g.iloc[rng.integers(0, len(g), size=len(g))])
        if parts:
            vals.append(ratio(pd.concat(parts, keys=range(len(parts)), names=["event_boot", "state"])))
    vals = np.asarray(vals, dtype=float); vals = vals[np.isfinite(vals)]
    return observed, (float(np.quantile(vals, .025)) if len(vals) else np.nan), (float(np.quantile(vals, .975)) if len(vals) else np.nan)


def _event_effects(x: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    se = _state_event_summary(x)
    rows = []
    for event, g in se.groupby("event_id"):
        means = g.groupby("quintile", observed=True)["mean"].mean()
        med = g.groupby("quintile", observed=True)["median"].mean()
        q1, q5 = means.get("Q1", np.nan), means.get("Q5", np.nan)
        m1, m5 = med.get("Q1", np.nan), med.get("Q5", np.nan)
        z = x[x.event_id.eq(event)]
        rho = spearmanr(z["sensitivity"], z["reach_drop"]).statistic if len(z) >= 3 and z["sensitivity"].nunique() > 1 and z["reach_drop"].nunique() > 1 else np.nan
        e = float(q5 - q1) if np.isfinite(q1) and np.isfinite(q5) else np.nan
        direction = "POSITIVE" if e > 1e-12 else ("NEGATIVE" if e < -1e-12 else "NEUTRAL") if np.isfinite(e) else "NOT_ESTIMABLE"
        rows.append({"event_id": event, "q1_mean_drop": q1, "q5_mean_drop": q5, "q5_q1_mean_effect": e,
                     "q1_median_drop": m1, "q5_median_drop": m5,
                     "q5_q1_median_effect": float(m5 - m1) if np.isfinite(m1) and np.isfinite(m5) else np.nan,
                     "spearman_rho": rho, "direction": direction,
                     "state_n_with_q1_q5": int(g.groupby("event_id").size().iloc[0])})
    return pd.DataFrame(rows), {"state_event": se}


def _continuous(x: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    bins = []
    for event, g in x.groupby("event_id"):
        rho = spearmanr(g["sensitivity"], g["reach_drop"]).statistic if len(g) >= 3 and g.sensitivity.nunique() > 1 and g.reach_drop.nunique() > 1 else np.nan
        pr = pearsonr(g["sensitivity"], g["reach_drop"])[0] if len(g) >= 3 and g.sensitivity.nunique() > 1 and g.reach_drop.nunique() > 1 else np.nan
        rows.append({"event_id": event, "valid_ip_n": len(g), "state_n": g.target_admin1.nunique(), "spearman_rho": rho, "pearson_r": pr})
        for state, s in g.groupby("target_admin1"):
            if len(s) < 5 or s.sensitivity.nunique() < 2:
                continue
            r = s.sort_values("sensitivity").copy(); r["bin"] = np.minimum(9, (np.arange(len(r)) * 10 // len(r)))
            z = r.groupby("bin", as_index=False).agg(sensitivity=("sensitivity", "mean"), reach_drop=("reach_drop", "mean"), n=("reach_drop", "size"))
            z["event_id"] = event; z["target_admin1"] = state; bins.append(z)
    return pd.DataFrame(rows), (pd.concat(bins, ignore_index=True) if bins else pd.DataFrame())


def _figure_dir(out: Path) -> Path:
    p = out / "figures"; p.mkdir(parents=True, exist_ok=True); return p


def _savefig(fig, path: Path):
    fig.savefig(path.with_suffix(".png"), dpi=220, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def _figures(out: Path, se: pd.DataFrame, effects: pd.DataFrame, cont_bins: pd.DataFrame, x: pd.DataFrame):
    fd = _figure_dir(out)
    q = _event_q_means(se)
    # H2-1: common scale, event-equal means with event-level spread.
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    vals = q.pivot(index="event_id", columns="quintile", values="state_equal_mean_drop").reindex(columns=QUINTILES)
    m = vals.mean(axis=0); lo = vals.quantile(.025, axis=0); hi = vals.quantile(.975, axis=0)
    ax.plot(QUINTILES, m, color="#1f4e79", marker="o", lw=2)
    ax.fill_between(np.arange(5), lo.to_numpy(), hi.to_numpy(), color="#9ecae1", alpha=.35, label="event-level 95% interval")
    ax.axhline(0, color="0.35", lw=.8); ax.set(xlabel="Frozen state-wise Sensitivity quintile", ylabel="Reach drop (pre − attack)", title="Higher planned-outage Sensitivity is associated with larger war-attack reach loss")
    ax.legend(frameon=False, fontsize=8); ax.grid(axis="y", alpha=.2); fig.tight_layout(); _savefig(fig, fd / "H2-1_quintile_gradient")
    # H2-2 event effects.
    fig, ax = plt.subplots(figsize=(7, 4.2)); e = effects.sort_values("event_id"); y=np.arange(len(e));
    ax.axvline(0,color="0.35",lw=.8); ax.errorbar(e.q5_q1_mean_effect,y,fmt="o",color="#b2182b"); ax.set_yticks(y,e.event_id); ax.set_xlabel("Q5 − Q1 mean reach-drop (state equal)"); ax.set_title("Q5 − Q1 effect by held-out attack"); ax.grid(axis="x",alpha=.2); fig.tight_layout(); _savefig(fig, fd / "H2-2_event_effects")
    # H2-3 binned curve (state/event aggregation, not raw scatter).
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    if not cont_bins.empty:
        z=cont_bins.groupby("bin").agg(sensitivity=("sensitivity","mean"), reach_drop=("reach_drop","mean"), n=("reach_drop","size"))
        ax.plot(z.sensitivity,z.reach_drop,marker="o",color="#762a83");
    ax.axhline(0,color="0.35",lw=.8); ax.set(xlabel="Frozen continuous Sensitivity $S_i$",ylabel="Mean reach drop",title="Continuous Sensitivity and war-attack reach loss"); ax.grid(alpha=.2); fig.tight_layout(); _savefig(fig, fd / "H2-3_continuous_sensitivity")
    # H2-4 severe risk.
    sr=x.assign(severe=x.reach_drop>=.25).groupby("quintile",observed=True).severe.mean().reindex(QUINTILES)
    fig, ax = plt.subplots(figsize=(6.5,4.2)); ax.plot(QUINTILES,sr,color="#d7301f",marker="o",lw=2); ax.set(xlabel="Frozen Sensitivity quintile",ylabel="Pr(reach drop ≥ 0.25)",title="Severe reach degradation risk by Sensitivity quintile"); ax.grid(axis="y",alpha=.2); fig.tight_layout(); _savefig(fig, fd / "H2-4_severe_risk")
    # H2-5 heatmap.
    h=se.pivot_table(index="event_id",columns="quintile",values="mean",aggfunc="mean").reindex(columns=QUINTILES)
    fig, ax = plt.subplots(figsize=(7.5,4.3)); im=ax.imshow(h.to_numpy(),aspect="auto",cmap="RdBu_r",vmin=np.nanmin(h),vmax=np.nanmax(h)); ax.set_xticks(range(5),QUINTILES); ax.set_yticks(range(len(h)),h.index); ax.set_xlabel("Sensitivity quintile"); ax.set_title("Mean reach drop by held-out attack and Sensitivity quintile"); fig.colorbar(im,ax=ax,label="State-equal mean reach drop"); fig.tight_layout(); _savefig(fig, fd / "H2-5_event_quintile_heatmap")


def _report(out: Path, panel: Panel, x: pd.DataFrame, se: pd.DataFrame, effects: pd.DataFrame, cont: pd.DataFrame, robust: pd.DataFrame, main_ci: tuple[float,float,float], rr25: tuple[float,float,float], rr50: tuple[float,float,float], run_id: str) -> str:
    qmeans = se.groupby("quintile",observed=True)["mean"].mean().reindex(QUINTILES)
    qmed = se.groupby("quintile",observed=True)["median"].mean().reindex(QUINTILES)
    effect, lo, hi = main_ci
    directions = int((effects.direction == "POSITIVE").sum())
    monotonic = bool(np.all(np.diff(qmeans.dropna().to_numpy()) >= -1e-12)) if qmeans.notna().all() else False
    rho = float(cont.spearman_rho.mean()) if not cont.empty else np.nan
    # Verdict intentionally effect/consistency based, not p-value based.
    if len(effects) < 4 or not np.isfinite(effect): verdict = "NOT_ESTIMABLE"
    elif monotonic and directions >= 4 and effect > 0 and np.isfinite(rho) and rho > 0: verdict = "SUPPORTED"
    elif directions >= 3 and effect > 0: verdict = "PARTIALLY_SUPPORTED"
    else: verdict = "NOT_SUPPORTED"
    lines=[f"# H2 Sensitivity External Validity Report", "", f"Run: `{run_id}`", "", "## Scope", "", "Only the six frozen held-out war attacks are in the core analysis. H2 reuses the frozen H1 outcome artifact and frozen Stage 4/4.5 Sensitivity scores; it does not query ClickHouse, alter events, or control for Activity. Results are association/external validity, not causation.", "", "## Main panel", "", f"- Label: `{panel.label}`; valid war-outcome IPs: **{len(x):,}**; states: **{x.target_admin1.nunique()}**; events: **{x.event_id.nunique()}**.", f"- State-wise/event-equal Q5−Q1 mean effect: **{effect:.4f}** (95% CI {lo:.4f}, {hi:.4f}).", f"- Q5/Q1 severe-drop risk ratio (drop ≥0.25): **{rr25[0]:.3f}** (95% CI {rr25[1]:.3f}, {rr25[2]:.3f}).", f"- Q5/Q1 severe-drop risk ratio (drop ≥0.50): **{rr50[0]:.3f}** (95% CI {rr50[1]:.3f}, {rr50[2]:.3f}).", f"- Q5 > Q1 in **{directions}/{len(effects)}** events; monotonic Q1→Q5: **{monotonic}**; event-equal Spearman mean: **{rho:.4f}**.", "", "## Quintile summary", "", "```", pd.DataFrame({"quintile":QUINTILES,"mean_drop":qmeans.values,"median_drop":qmed.values}).to_string(index=False), "```", "", "## Event consistency", "", "```", effects.to_string(index=False), "```", "", "## Frozen robustness", "", "```", robust.to_string(index=False), "```", "", f"## H2 verdict: **{verdict}**", "", "The verdict combines monotonicity, effect magnitude, event direction consistency, continuous association, and frozen robustness. It is not based on IP-level naive p-values. Activity summaries are descriptive only; H3 is not run.", "", "## Run boundary", "", "H3 and H4 were not run. H1 was not rerun or modified. No planned-outage registry or war-event definition was changed.", ""]
    (out/"H2_SENSITIVITY_EXTERNAL_VALIDITY_REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    return verdict


def run(run_id: str, root: Path, h1_dir: Path, stage45: Path, stage4: Path, git_commit: str = "unknown") -> dict:
    out = root / "runs" / run_id / "results" / "stages" / "stage_h2_sensitivity_external_validity"
    out.mkdir(parents=True, exist_ok=True)
    outcomes = _load_outcomes(h1_dir)
    labels = _load_labels(stage45, stage4)
    panel_rows = {k: _panel_rows(outcomes, labels, p) for k,p in PANELS.items()}
    main = panel_rows["MAIN"]
    se = _state_event_summary(main)
    effects, extra = _event_effects(main)
    cont, bins = _continuous(main)
    main_ci = _bootstrap_effect(main); rr25 = _bootstrap_risk_ratio(main,.25); rr50 = _bootstrap_risk_ratio(main,.50)
    se.to_csv(out/"h2_state_event_summary.csv",index=False)
    # Main quintile summary includes event-equal state summaries and activity diagnostics.
    qs = se.groupby("quintile",observed=True).agg(ip_n=("n","sum"), mean_reach_drop=("mean","mean"), median_reach_drop=("median","mean"), p25=("p25","mean"), p75=("p75","mean"), frac_gt0=("frac_gt0","mean"), frac_ge010=("frac_ge010","mean"), frac_ge025=("frac_ge025","mean"), frac_ge050=("frac_ge050","mean"), activity_mean=("activity_mean","mean"), activity_median=("activity_median","mean"), state_event_cells=("mean","size")).reindex(QUINTILES).reset_index()
    qs.to_csv(out/"h2_main_quintile_summary.csv",index=False); effects.to_csv(out/"h2_event_effects.csv",index=False); cont.to_csv(out/"h2_continuous_sensitivity.csv",index=False)
    severe=main.assign(severe025=main.reach_drop>=.25,severe050=main.reach_drop>=.50).groupby(["event_id","quintile"],observed=True).agg(ip_n=("dst_ip","size"), severe025_prob=("severe025","mean"), severe050_prob=("severe050","mean")).reset_index(); severe.to_csv(out/"h2_severe_drop_risk.csv",index=False)
    # Robustness one-row summaries, with the same event/state-equal metrics.
    rrows=[]
    for k in ["A","B","C","D"]:
        z=panel_rows[k]; se_z=_state_event_summary(z); eff_z, _=_event_effects(z); c_z,_=_continuous(z); ci_z=_bootstrap_effect(z); rr_z=_bootstrap_risk_ratio(z,.25)
        rrows.append({"panel":k,"label":PANELS[k].label,"valid_ip_n":len(z),"state_n":z.target_admin1.nunique(),"event_n":z.event_id.nunique(),"q5_q1_mean_effect":ci_z[0],"q5_q1_ci_low":ci_z[1],"q5_q1_ci_high":ci_z[2],"severe_rr025":rr_z[0],"severe_rr025_ci_low":rr_z[1],"severe_rr025_ci_high":rr_z[2],"event_equal_spearman":c_z.spearman_rho.mean() if not c_z.empty else np.nan,"positive_event_n":int((eff_z.direction=="POSITIVE").sum()),"event_direction_n":len(eff_z)})
    robust=pd.DataFrame(rrows); robust.to_csv(out/"h2_robustness_summary.csv",index=False)
    _figures(out,se,effects,bins,main)
    verdict=_report(out,PANELS["MAIN"],main,se,effects,cont,robust,main_ci,rr25,rr50,run_id)
    # Intermediate panel data are parquet, never giant CSVs.
    for k,z in panel_rows.items(): z.to_parquet(out/f"h2_ip_level_{k.lower()}.parquet",index=False)
    manifest={"stage":"H2_SENSITIVITY_EXTERNAL_VALIDITY","run_id":run_id,"git_commit":git_commit,"random_seed":SEED,"main_label":PANELS["MAIN"].label,"main_expected_sensitivity_population":{"ip_n":700012,"state_n":17},"main_valid_war_outcome_ip_n":int(len(main),),"main_valid_state_n":int(main.target_admin1.nunique()),"main_event_n":int(main.event_id.nunique()),"final_sensitivity_freeze_version":"final_sensitivity_freeze_v1_augmented_strict_support3","war_event_registry_version":"frozen_core_6_heldout_attacks","h1_artifact":str(h1_dir),"stage45_artifact":str(stage45),"stage4_artifact":str(stage4),"h2_verdict":verdict,"h3_h4_run":False,"h1_rerun":False,"figures":[str(p.name) for p in (_figure_dir(out)).glob("H2-*.png")]}
    (out/"h2_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return {"output_dir":str(out),"verdict":verdict,"main_ip_n":len(main),"main_state_n":int(main.target_admin1.nunique()),"effects":effects.to_dict("records"),"manifest":manifest}


def main(argv=None):
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--run-id",default="h2_sensitivity_external_validity_20260910"); ap.add_argument("--root",default="/home/wsl/XiaoLunWen_doc_complete_20260908"); ap.add_argument("--h1-dir",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity"); ap.add_argument("--stage45",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/stage4_5_label_robustness_20260910/results/tables"); ap.add_argument("--stage4",default="/home/wsl/XiaoLunWen_doc_complete_20260908/runs/stage4_sensitivity_frozen_v2_20260910/results/tables"); ap.add_argument("--git-commit",default=os.environ.get("GIT_COMMIT","unknown")); a=ap.parse_args(); print(json.dumps(run(a.run_id,Path(a.root),Path(a.h1_dir),Path(a.stage45),Path(a.stage4),a.git_commit),indent=2,default=str))


if __name__ == "__main__": main()
