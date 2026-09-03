"""Experiment C — repeatable and prospectively predictable ASN × Admin1 resilience.

The experiment is deliberately *prospective*:
- a test event is never used to build its own features;
- all history features are lagged by event time;
- evaluation is rolling-origin by whole event, never random row splitting;
- the output includes an explicit leakage audit and permutation benchmark.

Primary question
----------------
Do the same ASN × first-level administrative-region groups show repeatable
observable resilience across externally registered power shocks, and can only
pre-event information predict impact in a later, completely held-out event?
"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .config import Config
from .progress import HeartbeatProgress, get_logger, step
from .stats import spearman

TARGET_MAP = {
    "max_deficit": "max_deficit",
    "deficit_auc_full": "deficit_auc_full",
    "t90_h": "t90_h",
}
MODEL_NAMES = ["M0_global", "M1_admin1", "M2_asn", "M3_group",
               "M4_ridge_history", "M5_gbdt_history"]


def _group_label(df: pd.DataFrame) -> pd.Series:
    return (df["target_asn"].astype("Int64").astype(str) + "|" +
            df["target_country"].fillna("UNKNOWN").astype(str) + "|" +
            df["target_admin1"].fillna("UNKNOWN").astype(str))


def prepare_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Attach event time/order and build strictly lagged group history features."""
    d = raw.copy()
    d["event_anchor_utc"] = pd.to_datetime(d["event_anchor_utc"], utc=True, errors="coerce")
    d["group"] = _group_label(d)
    d = d.sort_values(["event_anchor_utc", "event_id", "group"]).reset_index(drop=True)

    outcomes = ["immediate_drop", "max_deficit", "deficit_auc_24h",
                "deficit_auc_full", "onset_delay_h", "t50_h", "t90_h"]
    for c in outcomes + ["baseline_level", "eligible_prefix_n", "pretrend_slope"]:
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")

    # Each group-event is one row. History is built from earlier event timestamps only.
    g = d.groupby("group", sort=False)
    d["hist_n"] = g.cumcount()
    d["last_feature_event_utc"] = g["event_anchor_utc"].shift(1)
    for c in outcomes:
        if c not in d:
            continue
        shifted = g[c].shift(1)
        d[f"hist_{c}_last"] = shifted
        # Transform instead of apply preserves row order/index.
        d[f"hist_{c}_mean"] = shifted.groupby(d["group"]).transform(
            lambda s: s.expanding(min_periods=1).mean())
        d[f"hist_{c}_median"] = shifted.groupby(d["group"]).transform(
            lambda s: s.expanding(min_periods=1).median())
    return d


def event_pair_repeatability(df: pd.DataFrame, target: str, min_common: int,
                             n_boot: int = 1000, seed: int = 0) -> pd.DataFrame:
    """Pairwise rank repeatability with group bootstrap confidence intervals.

    The input is already restricted to groups independently registered as
    exposed in each event.  Unexposed zero-effect rows are never allowed to
    create artificial repeatability.
    """
    piv = df.pivot_table(index="group", columns="event_id", values=target, aggfunc="mean")
    rows = []; rng = np.random.default_rng(seed)
    for a, b in combinations(piv.columns, 2):
        z = piv[[a, b]].dropna(); admissible = len(z) >= min_common
        rho = spearman(z[a].to_numpy(float), z[b].to_numpy(float)) if admissible else np.nan
        boots = []
        if admissible and n_boot > 0:
            x = z[[a,b]].to_numpy(float)
            for _ in range(n_boot):
                q = x[rng.integers(0, len(x), len(x))]
                r = spearman(q[:,0], q[:,1])
                if np.isfinite(r): boots.append(r)
        rows.append({"target": target, "event_a": a, "event_b": b,
                     "n_common_group": len(z), "spearman_rho": rho,
                     "rho_ci_lo": float(np.quantile(boots,.025)) if boots else np.nan,
                     "rho_ci_hi": float(np.quantile(boots,.975)) if boots else np.nan,
                     "admissible": int(admissible)})
    return pd.DataFrame(rows)


def icc_oneway(values: Iterable[float], groups: Iterable[str]) -> float:
    """One-way random-effects ICC(1,1), with unbalanced-group correction."""
    z = pd.DataFrame({"v": pd.to_numeric(pd.Series(values), errors="coerce"),
                      "g": pd.Series(groups, dtype=str)}).dropna()
    n, k = len(z), z["g"].nunique()
    if k < 2 or n <= k:
        return np.nan
    grp = z.groupby("g")["v"]
    n_i, means = grp.size(), grp.mean()
    grand = z["v"].mean()
    ss_b = float((n_i * (means - grand) ** 2).sum())
    ss_w = float(((z["v"] - z["g"].map(means)) ** 2).sum())
    ms_b, ms_w = ss_b / (k - 1), ss_w / (n - k)
    n0 = (n - float((n_i ** 2).sum()) / n) / (k - 1)
    var_b = max(0.0, (ms_b - ms_w) / n0) if n0 > 0 else 0.0
    return float(var_b / (var_b + ms_w)) if var_b + ms_w > 0 else np.nan


def _history_mean(train: pd.DataFrame, test: pd.DataFrame, key: list[str], target: str) -> np.ndarray:
    global_mean = float(train[target].mean())
    means = train.groupby(key, dropna=False)[target].mean()
    if len(key) == 1:
        return test[key[0]].map(means).fillna(global_mean).to_numpy(float)
    idx = pd.MultiIndex.from_frame(test[key])
    pred = means.reindex(idx).to_numpy(float)
    return np.where(np.isfinite(pred), pred, global_mean)


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    candidates = [
        "hist_n", "baseline_level", "eligible_prefix_n", "pretrend_slope",
        "hist_immediate_drop_last", "hist_immediate_drop_mean",
        "hist_max_deficit_last", "hist_max_deficit_mean",
        "hist_deficit_auc_full_last", "hist_deficit_auc_full_mean",
        "hist_t90_h_last", "hist_t90_h_mean",
        "hist_onset_delay_h_mean",
    ]
    return [c for c in candidates if c in df.columns]


def _fit_ml(train: pd.DataFrame, test: pd.DataFrame, target: str, cfg: Config,
            kind: str, seed: int) -> np.ndarray:
    """Fit a leakage-safe model using only categorical identity + lagged/pre-event features."""
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    cat = ["target_asn", "target_admin1"]
    num = _numeric_columns(train)
    # Hard guard: current-event outcomes are never legal predictors.
    forbidden = {"immediate_drop", "max_deficit", "deficit_auc_24h", "deficit_auc_full",
                 "onset_delay_h", "t50_h", "t90_h", target}
    assert not forbidden.intersection(cat + num), "Outcome leakage in feature list"

    if kind == "ridge":
        pre = ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=2), cat),
            ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                              ("scale", StandardScaler())]), num),
        ])
        model = Pipeline([("pre", pre),
                          ("model", Ridge(alpha=float(cfg.prediction["ridge_alpha"])))])
    else:
        # Dense one-hot is acceptable at the group-event sample scale and avoids unsafe target encoding.
        try:
            ohe = OneHotEncoder(handle_unknown="ignore", min_frequency=2, sparse_output=False)
        except TypeError:  # scikit-learn <1.2
            ohe = OneHotEncoder(handle_unknown="ignore", min_frequency=2, sparse=False)
        pre = ColumnTransformer([
            ("cat", ohe, cat),
            ("num", SimpleImputer(strategy="median"), num),
        ])
        model = Pipeline([("pre", pre),
                          ("model", HistGradientBoostingRegressor(
                              max_iter=int(cfg.prediction["gbdt_estimators"]),
                              max_depth=int(cfg.prediction["gbdt_max_depth"]),
                              random_state=seed, l2_regularization=1.0))])
    model.fit(train[cat + num], train[target].to_numpy(float))
    return model.predict(test[cat + num]).astype(float)


def _average_precision(y: np.ndarray, score: np.ndarray, threshold: float) -> float:
    from sklearn.metrics import average_precision_score
    label = np.asarray(y >= threshold, int)
    if np.unique(label).size < 2:
        return np.nan
    return float(average_precision_score(label, score))


def rolling_origin_predict(df: pd.DataFrame, target: str, cfg: Config, *, logger=None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Prospective event-level prediction with explicit model-fit status.

    A failed ML fit is never silently credited to M4/M5.  We retain a fallback
    prediction for diagnostics, but mark it ``fallback_failed`` and exclude it
    from the positive predictive-closure gate.
    """
    seed = int(cfg.runtime["random_seed"])
    min_train_events = int(cfg.prediction["min_train_events"])
    test_roles = {"attack_national", "attack_regional", "blind_test", "stress_test"}
    all_events = (df[["event_id", "event_anchor_utc", "analysis_role"]]
                  .drop_duplicates().sort_values("event_anchor_utc"))
    attack_events = all_events[all_events["analysis_role"].isin(test_roles)]

    pred_rows, audit_rows = [], []
    progress = None
    if logger is not None:
        progress = HeartbeatProgress(logger, f"expC.heldout_events.{target}", total=len(attack_events),
                                     unit="event", log_every_n=1, log_every_s=45.0)
        progress.start()
    for _, ev in attack_events.iterrows():
        test_time = ev["event_anchor_utc"]
        earlier_attack_ids = all_events[(all_events["event_anchor_utc"] < test_time) &
                                        (all_events["analysis_role"].isin(test_roles))]["event_id"].tolist()
        if len(earlier_attack_ids) < min_train_events:
            if progress is not None:
                progress.advance(current=str(ev["event_id"]), note="insufficient_train_events")
            continue
        train = df[df["event_id"].isin(earlier_attack_ids) & df["is_treated"].eq(1)].dropna(subset=[target]).copy()
        test = df[df["event_id"].eq(ev["event_id"]) & df["is_treated"].eq(1)].dropna(subset=[target]).copy()
        if train.empty or test.empty:
            if progress is not None:
                progress.advance(current=str(ev["event_id"]), note="empty_train_or_test")
            continue

        max_feature_time = pd.to_datetime(test["last_feature_event_utc"], utc=True, errors="coerce").max()
        time_safe = bool(pd.isna(max_feature_time) or max_feature_time < test_time)
        if not time_safe:
            raise RuntimeError(f"Feature time leakage for {ev['event_id']}")

        y = test[target].to_numpy(float)
        predictions: dict[str, tuple[np.ndarray, str, str]] = {
            "M0_global": (np.full(len(test), float(train[target].mean())), "ok_baseline", ""),
            "M1_admin1": (_history_mean(train, test, ["target_admin1"], target), "ok_baseline", ""),
            "M2_asn": (_history_mean(train, test, ["target_asn"], target), "ok_baseline", ""),
            "M3_group": (_history_mean(train, test, ["target_asn", "target_admin1"], target), "ok_baseline", ""),
        }
        fit_audit = {}
        for model_name, kind in [("M4_ridge_history", "ridge"), ("M5_gbdt_history", "gbdt")]:
            try:
                predictions[model_name] = (_fit_ml(train, test, target, cfg, kind, seed), "ok", "")
                fit_audit[f"{model_name}_fit_status"] = "ok"
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                get_logger().warning("C %s %s failed; diagnostic fallback to M3: %s",
                                     ev["event_id"], model_name, err)
                predictions[model_name] = (predictions["M3_group"][0], "fallback_failed", err)
                fit_audit[f"{model_name}_fit_status"] = "fallback_failed"

        audit_rows.append({
            "target": target, "test_event": ev["event_id"], "test_anchor_utc": test_time,
            "n_train_event": len(earlier_attack_ids), "n_train_row": len(train), "n_test_row": len(test),
            "max_feature_event_utc": max_feature_time, "feature_time_safe": int(time_safe),
            "row_split_used": 0, "current_event_outcome_feature_used": 0,
            **fit_audit,
        })

        test_reset = test.reset_index(drop=True)
        for model_name, (pred, fit_status, fit_error) in predictions.items():
            for i, (_, row) in enumerate(test_reset.iterrows()):
                pred_rows.append({
                    "target": target, "model": model_name, "event_id": ev["event_id"],
                    "event_anchor_utc": test_time, "group": row["group"],
                    "target_asn": row["target_asn"], "target_admin1": row["target_admin1"],
                    "pred": float(pred[i]), "actual": float(y[i]),
                    "train_event_n": len(earlier_attack_ids),
                    "fit_status": fit_status, "fit_error": fit_error,
                })
        if progress is not None:
            failed_models = sum(1 for _, fit_status, _ in predictions.values() if fit_status != "ok")
            progress.advance(current=str(ev["event_id"]), train_events=len(earlier_attack_ids),
                             failed_models=failed_models)

    if progress is not None:
        progress.finish(prediction_rows=len(pred_rows))
    predictions = pd.DataFrame(pred_rows)
    if predictions.empty:
        return predictions, pd.DataFrame(), pd.DataFrame(audit_rows)

    metrics = []
    thresholds = list(map(float, cfg.prediction.get("binary_thresholds", {}).get(target, [])))
    for (tgt, model, event_id), z in predictions.groupby(["target", "model", "event_id"]):
        failed = int((z["fit_status"] == "fallback_failed").any())
        row = {"target": tgt, "model": model, "event_id": event_id, "n": len(z),
               "fit_status": "fallback_failed" if failed else str(z["fit_status"].iloc[0]),
               "fit_failure_n": failed,
               "mae": float(np.mean(np.abs(z["pred"] - z["actual"]))),
               "rmse": float(np.sqrt(np.mean((z["pred"] - z["actual"]) ** 2)))}
        for threshold in thresholds:
            row[f"auprc_ge_{threshold:g}"] = _average_precision(
                z["actual"].to_numpy(float), z["pred"].to_numpy(float), threshold)
        metrics.append(row)
    per_event = pd.DataFrame(metrics)

    agg = []
    for (tgt, model), z in per_event.groupby(["target", "model"]):
        failure_n = int(z["fit_failure_n"].sum())
        row = {"target": tgt, "model": model, "event_id": "EVENT_EQUAL",
               "n": int(z["n"].sum()), "n_test_event": len(z),
               "fit_status": "fallback_failed" if failure_n else "ok",
               "fit_failure_n": failure_n,
               "mae": float(z["mae"].mean()), "rmse": float(z["rmse"].mean())}
        for threshold in thresholds:
            c = f"auprc_ge_{threshold:g}"
            row[c] = float(z[c].mean()) if z[c].notna().any() else np.nan
        agg.append(row)
    perf = pd.concat([per_event, pd.DataFrame(agg)], ignore_index=True)
    return predictions, perf, pd.DataFrame(audit_rows)

def permutation_benchmark(df: pd.DataFrame, target: str, cfg: Config,
                          observed_perf: pd.DataFrame, *, logger=None) -> pd.DataFrame:
    """Joint within-event outcome-vector permutation null for primary M4.

    A single row permutation is applied to every current-event outcome column.
    This preserves correlations among deficit depth, AUC, onset, and recovery,
    while breaking the persistent mapping between a group and its outcomes.
    """
    n_perm = int(cfg.prediction["permutation_repetitions"])
    if n_perm <= 0:
        return pd.DataFrame()
    obs = observed_perf[(observed_perf["target"] == target) &
                        (observed_perf["model"] == "M4_ridge_history") &
                        (observed_perf["event_id"] == "EVENT_EQUAL") &
                        (observed_perf.get("fit_failure_n", 0) == 0)]
    if obs.empty:
        return pd.DataFrame()
    observed = float(obs.iloc[0]["mae"])
    rng = np.random.default_rng(int(cfg.runtime["random_seed"]))
    null = []
    progress = None
    if logger is not None:
        progress = HeartbeatProgress(logger, f"expC.permutation.{target}", total=n_perm,
                                     unit="perm", log_every_n=max(1, n_perm // 10), log_every_s=45.0)
        progress.start(observed_mae=observed)
    history_cols = [c for c in df.columns if c.startswith("hist_") or c == "last_feature_event_utc"]
    base = df.drop(columns=history_cols, errors="ignore").copy()
    outcome_cols = [c for c in ["immediate_drop", "max_deficit", "deficit_auc_24h",
                                  "deficit_auc_full", "onset_delay_h", "t50_h", "t90_h"]
                    if c in base.columns]
    for idx in range(n_perm):
        q = base.copy()
        for _, rows in q.groupby("event_id", sort=False).groups.items():
            rows = np.asarray(list(rows))
            perm = rng.permutation(rows)
            q.loc[rows, outcome_cols] = base.loc[perm, outcome_cols].to_numpy()
        q = prepare_features(q)
        _, p, _ = rolling_origin_predict(q, target, cfg)
        x = p[(p["model"] == "M4_ridge_history") &
              (p["event_id"] == "EVENT_EQUAL") &
              (p.get("fit_failure_n", 0) == 0)]
        if not x.empty:
            null.append(float(x.iloc[0]["mae"]))
        if progress is not None:
            progress.advance(current=f"perm_{idx+1}", valid=len(null))
    if progress is not None:
        progress.finish(valid=len(null))
    p_value = ((1 + sum(x <= observed for x in null)) / (1 + len(null))) if null else np.nan
    return pd.DataFrame({"target": [target], "model": ["M4_ridge_history"],
                         "observed_mae": [observed], "null_mean_mae": [np.mean(null) if null else np.nan],
                         "null_q05": [np.quantile(null, .05) if null else np.nan],
                         "null_q95": [np.quantile(null, .95) if null else np.nan],
                         "p_value_better_than_null": [p_value], "n_permutation": [len(null)],
                         "permutation_unit": ["joint_outcome_vector_within_event"]})

def variance_decomposition(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """Crossed random-effect variance decomposition with explicit failure status."""
    z = df.dropna(subset=[target]).copy()
    z["asn"] = z["target_asn"].astype(str)
    z["admin1"] = z["target_admin1"].astype(str)
    z["interaction"] = z["asn"] + "|" + z["admin1"]
    z["event"] = z["event_id"].astype(str)
    components = ["event", "asn", "admin1", "interaction", "residual"]
    if len(z) < 30 or min(z[c].nunique() for c in ["event", "asn", "admin1"]) < 2:
        return pd.DataFrame({"target": target, "component": components, "frac": np.nan,
                             "status": "insufficient", "method": "crossed_mixedlm"})
    try:
        import statsmodels.formula.api as smf
        z["all"] = "all"
        model = smf.mixedlm(
            f"Q('{target}') ~ C(event)", z, groups=z["all"], re_formula="0",
            vc_formula={"asn": "0 + C(asn)", "admin1": "0 + C(admin1)",
                        "interaction": "0 + C(interaction)"})
        fit = model.fit(reml=True, method="lbfgs", maxiter=500, disp=False)
        # statsmodels keeps vcomp in insertion/alphabetical order; map via model.exog_vc.names.
        names = list(getattr(model.exog_vc, "names", ["admin1", "asn", "interaction"]))
        vc = dict(zip(names, np.asarray(fit.vcomp, float)))
        event_fit = np.asarray(fit.model.exog @ fit.fe_params, float)
        event_var = float(np.var(event_fit))
        raw = {"event": event_var, "asn": vc.get("asn", 0.0),
               "admin1": vc.get("admin1", 0.0), "interaction": vc.get("interaction", 0.0),
               "residual": float(fit.scale)}
        total = sum(max(0.0, x) for x in raw.values())
        return pd.DataFrame({"target": target, "component": components,
                             "frac": [raw[c] / total if total > 0 else np.nan for c in components],
                             "status": "ok", "method": "crossed_mixedlm"})
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame({"target": target, "component": components, "frac": np.nan,
                             "status": f"failed:{type(exc).__name__}", "method": "crossed_mixedlm"})


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    source = cfg.out_dir("data_derived") / "group_event_features.parquet"
    if not source.exists():
        raise FileNotFoundError(source)
    with step("Experiment C: repeatability and prospective prediction", logger):
        raw = pd.read_parquet(source)
        df = prepare_features(raw)
        table_dir = cfg.out_dir("results_tables")
        df.to_parquet(cfg.out_dir("data_derived") / "group_event_history_features.parquet", index=False)

        # Figure heatmap source: attack outcomes only, valid geography only.
        attacks = df[df["analysis_role"].isin(
            ["attack_national", "attack_regional", "blind_test", "stress_test"]) &
            df["is_treated"].eq(1)].copy()
        attacks[["group", "event_id", "target_asn", "target_country", "target_admin1",
                 "deficit_auc_full", "t90_h", "max_deficit", "eligible_prefix_n"]].rename(
            columns={"deficit_auc_full": "auc", "t90_h": "t90"}).to_csv(
            table_dir / "f7_heatmap.csv", index=False)

        repeat_parts, pred_parts, perf_parts, audit_parts, perm_parts, var_parts = [], [], [], [], [], []
        targets = [TARGET_MAP.get(target_name, target_name) for target_name in cfg.prediction["targets"]]
        target_progress = HeartbeatProgress(logger, "expC.targets", total=len(targets),
                                            unit="target", log_every_n=1, log_every_s=45.0)
        target_progress.start()
        for target in targets:
            if target not in df.columns:
                target_progress.advance(current=target, note="missing_column")
                continue
            logger.info("expC target start: %s", target)
            repeat_parts.append(event_pair_repeatability(
                attacks.dropna(subset=[target]), target,
                int(cfg.group_admission["min_common_groups_for_repeatability"]),
                n_boot=int(cfg.prediction.get("repeatability_bootstrap", 1000)),
                seed=int(cfg.runtime["random_seed"])))
            pred, perf, audit = rolling_origin_predict(df, target, cfg, logger=logger)
            if not pred.empty:
                pred_parts.append(pred)
            if not perf.empty:
                perf_parts.append(perf)
            if not audit.empty:
                audit_parts.append(audit)
            # Permutation is expensive; run for primary AUC target only.
            if target == "deficit_auc_full" and not perf.empty:
                perm_parts.append(permutation_benchmark(df, target, cfg, perf, logger=logger))
            var_parts.append(variance_decomposition(attacks, target))
            target_progress.advance(current=target, pred_rows=len(pred), perf_rows=len(perf))
        target_progress.finish(pred_tables=len(pred_parts), perf_tables=len(perf_parts))

        predictions = pd.concat(pred_parts, ignore_index=True) if pred_parts else pd.DataFrame()
        performance = pd.concat(perf_parts, ignore_index=True) if perf_parts else pd.DataFrame()
        leakage = pd.concat(audit_parts, ignore_index=True) if audit_parts else pd.DataFrame()
        repeatability = pd.concat(repeat_parts, ignore_index=True) if repeat_parts else pd.DataFrame()
        permutation = pd.concat(perm_parts, ignore_index=True) if perm_parts else pd.DataFrame()
        variance = pd.concat(var_parts, ignore_index=True) if var_parts else pd.DataFrame()

        predictions.to_csv(table_dir / "f8_pred_scatter.csv", index=False)
        performance.to_csv(table_dir / "f8_model_perf.csv", index=False)
        leakage.to_csv(table_dir / "prediction_feature_audit.csv", index=False)
        repeatability.to_csv(table_dir / "exp_c_repeatability.csv", index=False)
        permutation.to_csv(table_dir / "exp_c_permutation.csv", index=False)
        variance.to_csv(table_dir / "f9_variance.csv", index=False)

        leakage_alert = int(not leakage.empty and
                            ((leakage["feature_time_safe"] != 1).any() or
                             (leakage["current_event_outcome_feature_used"] != 0).any() or
                             (leakage["row_split_used"] != 0).any()))
        primary_target = "deficit_auc_full"
        primary_model = str(cfg.prediction.get("primary_model", "M4_ridge_history"))
        baseline_model = str(cfg.prediction.get("simple_baseline_model", "M3_group"))
        event_equal = performance[(performance.get("target") == primary_target) &
                                  (performance.get("event_id") == "EVENT_EQUAL")] if not performance.empty else pd.DataFrame()
        def _metric(model, col):
            z = event_equal[event_equal["model"].eq(model)] if not event_equal.empty else pd.DataFrame()
            return float(z.iloc[0][col]) if not z.empty and col in z and pd.notna(z.iloc[0][col]) else np.nan
        model_mae = _metric(primary_model, "mae")
        baseline_mae = _metric(baseline_model, "mae")
        relative_improvement = ((baseline_mae - model_mae) / baseline_mae
                                if np.isfinite(model_mae) and np.isfinite(baseline_mae) and baseline_mae > 0 else np.nan)
        perm_p = (float(permutation.loc[(permutation["target"] == primary_target) &
                                        (permutation["model"] == primary_model),
                                        "p_value_better_than_null"].iloc[0])
                  if not permutation.empty and ((permutation["target"] == primary_target) &
                                                (permutation["model"] == primary_model)).any() else np.nan)
        primary_rep = (repeatability[(repeatability["target"] == primary_target) &
                                     (repeatability["admissible"] == 1)]
                       if not repeatability.empty else pd.DataFrame())
        rep_rho = float(primary_rep["spearman_rho"].median()) if not primary_rep.empty else np.nan
        rep_ci_lo = float(primary_rep["rho_ci_lo"].median()) if not primary_rep.empty and primary_rep["rho_ci_lo"].notna().any() else np.nan
        rep_pairs = int(primary_rep["spearman_rho"].notna().sum()) if not primary_rep.empty else 0
        primary_icc = icc_oneway(attacks[primary_target], attacks["group"]) if primary_target in attacks else np.nan
        primary_fit_failures = int(
            predictions.loc[predictions["model"].eq(primary_model) &
                            predictions["fit_status"].ne("ok"), "event_id"].nunique()
        ) if not predictions.empty and "fit_status" in predictions else 0
        per_primary = performance[(performance.get("target") == primary_target) &
                                  (performance.get("model") == primary_model) &
                                  (performance.get("event_id") != "EVENT_EQUAL")] if not performance.empty else pd.DataFrame()
        per_base = performance[(performance.get("target") == primary_target) &
                              (performance.get("model") == baseline_model) &
                              (performance.get("event_id") != "EVENT_EQUAL")] if not performance.empty else pd.DataFrame()
        wins = per_primary[["event_id","mae"]].merge(per_base[["event_id","mae"]], on="event_id", suffixes=("_primary","_baseline")) if not per_primary.empty and not per_base.empty else pd.DataFrame()
        event_win_fraction = float((wins["mae_primary"] < wins["mae_baseline"]).mean()) if not wins.empty else np.nan
        prediction_success = bool(
            not predictions.empty and leakage_alert == 0 and
            predictions["event_id"].nunique() >= int(cfg.prediction.get("min_test_events_for_claim", 3)) and
            primary_fit_failures == 0
        )
        prediction_success = bool(prediction_success and np.isfinite(relative_improvement) and
                                  relative_improvement >= float(cfg.prediction.get("min_relative_mae_improvement", 0)) and
                                  np.isfinite(event_win_fraction) and event_win_fraction >= float(cfg.prediction.get("min_event_win_fraction", .67)) and
                                  np.isfinite(perm_p) and perm_p <= float(cfg.prediction.get("permutation_alpha", .05)))
        repeatability_success = bool(
            rep_pairs >= int(cfg.prediction.get("min_repeatability_pairs", 3)) and
            np.isfinite(rep_rho) and rep_rho >= float(cfg.prediction.get("min_repeatability_rho", .2)) and
            np.isfinite(rep_ci_lo) and rep_ci_lo > 0 and
            np.isfinite(primary_icc) and primary_icc >= float(cfg.prediction.get("min_repeatability_icc", .1)))
        summary = pd.DataFrame([{
            "n_group_event": len(df), "n_attack_group_event": len(attacks),
            "n_prediction_row": len(predictions),
            "n_test_event": predictions["event_id"].nunique() if not predictions.empty else 0,
            "leakage_alert": leakage_alert,
            "primary_target": primary_target, "primary_model": primary_model,
            "simple_baseline_model": baseline_model, "primary_model_mae": model_mae,
            "simple_baseline_mae": baseline_mae,
            "relative_mae_improvement": relative_improvement, "event_win_fraction": event_win_fraction,
            "permutation_p": perm_p, "primary_model_fit_failures": primary_fit_failures,
            "prediction_success": int(prediction_success),
            "primary_repeatability_rho": rep_rho, "primary_repeatability_ci_lo": rep_ci_lo,
            "repeatability_admissible_pairs": rep_pairs,
            "primary_icc": primary_icc, "repeatability_success": int(repeatability_success),
        }])
        summary.to_csv(table_dir / "exp_c_summary.csv", index=False)

    return {"status": "ok" if not leakage_alert else "failed_leakage_audit",
            "n_predictions": len(predictions), "leakage_alert": leakage_alert,
            "outputs": [str(table_dir / x) for x in ["f7_heatmap.csv", "f8_pred_scatter.csv",
                         "f8_model_perf.csv", "f9_variance.csv", "prediction_feature_audit.csv",
                         "exp_c_repeatability.csv", "exp_c_permutation.csv", "exp_c_summary.csv"]]}
