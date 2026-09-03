"""Oblast-specific outage supervision and repeated-sensitivity selection.

The regional sensor is a context-specific construct: ``B2_<oblast>``.  This
module never promotes an oblast/municipality geolocation to queue/address truth.
It also separates published schedules from confirmed DSO execution.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd


ACTIVE = {"activated", "activated_from", "actual_start_report", "schedule_shifted",
          "two_queues_commanded_from", "restriction_window_published",
          "restriction_window_initial"}
CANCELLED = {"cancelled", "cancelled_from"}


def build_regional_event_registry(updates: pd.DataFrame,
                                  queue_schedule: pd.DataFrame | None = None) -> pd.DataFrame:
    """Normalize official rows into region-event exposure evidence.

    ``region_binary_usable`` means the record identifies whether restrictions
    were active somewhere in the oblast.  It is *not* per-IP power truth.
    Queue-specific cancellations stay ambiguous without an IP-to-queue key.
    """
    rows: list[dict] = []
    d = updates.copy()
    for c in ("start_utc", "end_utc"):
        d[c] = pd.to_datetime(d[c], utc=True, errors="coerce")
    for _, r in d.iterrows():
        queue = str(r.get("queue", "")).strip()
        status = str(r.get("status", "")).strip()
        full = str(r.get("coverage", "")) == "full_oblast"
        all_queues = queue.upper() == "ALL"
        active = status in ACTIVE
        if (status == "restriction_window_initial" and
                str(r.get("execution_interpretation", "")) == "superseded_initial_plan"):
            active = False
        cancelled = status in CANCELLED
        if all_queues and full and active:
            state, usable, fraction = "restriction_active", 1, np.nan
        elif all_queues and full and cancelled:
            state, usable, fraction = "restriction_cancelled", 1, 0.0
        elif queue and queue.upper() != "ALL" and (active or cancelled):
            state, usable = "queue_specific_active" if active else "queue_specific_cancelled", 0
            fraction = np.nan
        else:
            state, usable, fraction = "ambiguous", 0, np.nan
        rows.append({
            "regional_event_id": f"{r.get('oblast')}|{r.get('date')}",
            "date": str(r.get("date")), "target_admin1": r.get("oblast"),
            "operator": r.get("operator"), "start_utc": r.get("start_utc"),
            "end_utc": r.get("end_utc"), "queue": queue, "regional_state": state,
            "region_binary_usable": usable, "estimated_exposed_fraction": fraction,
            "evidence_level": r.get("evidence_level"),
            "execution_interpretation": r.get("execution_interpretation"),
            "source_url": r.get("source_url"), "source_kind": "operator_update",
            "ip_level_power_truth": 0,
        })
    if queue_schedule is not None and not queue_schedule.empty:
        q = queue_schedule.copy()
        for c in ("start_utc", "end_utc"):
            q[c] = pd.to_datetime(q[c], utc=True, errors="coerce")
        for (date, oblast, start, end), g in q.groupby(
                ["date", "oblast", "start_utc", "end_utc"], dropna=False):
            queues = sorted(set(g["queue"].astype(str)))
            rows.append({
                "regional_event_id": f"{oblast}|{date}", "date": str(date),
                "target_admin1": oblast, "operator": "DSO published schedule",
                "start_utc": start, "end_utc": end, "queue": "|".join(queues),
                "regional_state": "published_queue_schedule",
                "region_binary_usable": 0,
                "estimated_exposed_fraction": len(queues) / 6.0,
                "evidence_level": g["evidence_level"].iloc[0],
                "execution_interpretation": "published_not_execution_truth",
                "source_url": "", "source_kind": "published_schedule",
                "ip_level_power_truth": 0,
            })
    return pd.DataFrame(rows).sort_values(
        ["target_admin1", "date", "start_utc", "source_kind"]).reset_index(drop=True)


def regional_capacity(registry: pd.DataFrame, targets: pd.DataFrame,
                      min_train_events: int = 3, min_holdout_events: int = 1) -> pd.DataFrame:
    mapped = (targets[targets["regional_eligible"].eq(1)]
              .groupby("target_admin1")["dst_ip"].nunique())
    rows = []
    for admin1, d in registry.groupby("target_admin1"):
        operator_dates = d.loc[d["source_kind"].eq("operator_update"), "date"].nunique()
        binary_dates = d.loc[d["region_binary_usable"].eq(1), "date"].nunique()
        published_dates = d.loc[d["source_kind"].eq("published_schedule"), "date"].nunique()
        confirmatory = binary_dates >= min_train_events + min_holdout_events
        # One region-event can describe a response but cannot identify a
        # repeatable regional sensor. Require at least two dates even for the
        # explicitly exploratory selector.
        exploratory = (operator_dates >= 2 or published_dates >= 2) and mapped.get(admin1, 0) > 0
        rows.append({
            "target_admin1": admin1, "mapped_ip_n": int(mapped.get(admin1, 0)),
            "operator_event_date_n": int(operator_dates),
            "binary_usable_event_date_n": int(binary_dates),
            "published_schedule_date_n": int(published_dates),
            "exploratory_region_calibration_ready": int(exploratory),
            "confirmatory_loo_ready": int(confirmatory),
            "blocking_reason": "" if confirmatory else
                f"needs >= {min_train_events + min_holdout_events} independent operator-confirmed region-event dates",
        })
    return pd.DataFrame(rows).sort_values(
        ["confirmatory_loo_ready", "exploratory_region_calibration_ready", "mapped_ip_n"],
        ascending=[False, False, False]).reset_index(drop=True)


def apply_conflict_masks(queue_schedule: pd.DataFrame, conflicts: pd.DataFrame,
                         national: pd.DataFrame) -> pd.DataFrame:
    """Intersect published queue rows with final national dispatch and hard masks.

    Result remains probabilistic region exposure (fraction of six queues), never
    per-IP queue truth.
    """
    q = queue_schedule.copy()
    for c in ("start_utc", "end_utc"):
        q[c] = pd.to_datetime(q[c], utc=True, errors="coerce")
    n = national.copy()
    for c in ("start_utc", "end_utc"):
        n[c] = pd.to_datetime(n[c], utc=True, errors="coerce")
    n = n[pd.to_numeric(n["queue_count"], errors="coerce").gt(0)]
    rows = []
    for _, r in q.iterrows():
        day = str(r["date"])
        for _, s in n[n["date"].astype(str).eq(day)].iterrows():
            start, end = max(r.start_utc, s.start_utc), min(r.end_utc, s.end_utc)
            if pd.notna(start) and pd.notna(end) and end > start:
                z = r.to_dict(); z["start_utc"] = start; z["end_utc"] = end
                z["dispatch_intersection_applied"] = 1
                rows.append(z)
    out = pd.DataFrame(rows)
    if out.empty or conflicts.empty:
        return out
    # The dispatch intersection already removes conflict portions outside the
    # final national window. Preserve an explicit audit bit for affected rows.
    keys = set(zip(conflicts["date"].astype(str), conflicts["oblast"].astype(str),
                   conflicts["queue"].astype(str)))
    out["source_conflict_masked"] = [int((str(d), str(o), str(qv)) in keys)
                                     for d, o, qv in zip(out.date, out.oblast, out.queue)]
    return out


def select_repeated_sensitive(event_scores: pd.DataFrame, *, min_events: int = 2,
                              min_positive_fraction: float = 2 / 3) -> pd.DataFrame:
    """Select B2_region using repeated event-level evidence only.

    Input is one row per IP and independent training event with ``in_B1``, ``S``
    and ``S_lo``.  A large single-event score cannot satisfy this selector.
    """
    required = {"target_admin1", "dst_ip", "event_id", "in_B1", "S", "S_lo"}
    missing = required - set(event_scores)
    if missing:
        raise ValueError(f"missing regional event-score columns: {sorted(missing)}")
    d = event_scores.copy()
    d["event_positive"] = pd.to_numeric(d["S_lo"], errors="coerce").gt(0)
    out = (d.groupby(["target_admin1", "dst_ip"], as_index=False)
           .agg(training_event_n=("event_id", "nunique"),
                positive_event_n=("event_positive", "sum"),
                median_S=("S", "median"), min_S=("S", "min"),
                stable_all_events=("in_B1", "all")))
    out["positive_event_fraction"] = out["positive_event_n"] / out["training_event_n"]
    out["in_B1_region"] = out["stable_all_events"].astype(bool)
    out["in_B2_region"] = (out["in_B1_region"] &
                            out["training_event_n"].ge(min_events) &
                            out["positive_event_fraction"].ge(min_positive_fraction) &
                            out["median_S"].gt(0))
    return out


def membership_stability(event_scores: pd.DataFrame) -> pd.DataFrame:
    """Pairwise per-oblast overlap for event-specific S_lo>0 memberships."""
    rows = []
    for admin1, d in event_scores.groupby("target_admin1"):
        members = {str(e): set(g.loc[pd.to_numeric(g["S_lo"], errors="coerce").gt(0), "dst_ip"])
                   for e, g in d.groupby("event_id")}
        for a, b in itertools.combinations(sorted(members), 2):
            ma, mb = members[a], members[b]
            union = ma | mb
            rows.append({"target_admin1": admin1, "event_a": a, "event_b": b,
                         "n_a": len(ma), "n_b": len(mb),
                         "intersection_n": len(ma & mb),
                         "jaccard": len(ma & mb) / len(union) if union else np.nan,
                         "retention_a_to_b": len(ma & mb) / len(ma) if ma else np.nan,
                         "retention_b_to_a": len(ma & mb) / len(mb) if mb else np.nan})
    return pd.DataFrame(rows)


def leave_one_event_out_splits(event_scores: pd.DataFrame, min_train_events: int = 3) -> list[dict]:
    """Return frozen within-oblast train/holdout event IDs."""
    splits = []
    for admin1, d in event_scores.groupby("target_admin1"):
        events = sorted(d["event_id"].astype(str).unique())
        for holdout in events:
            train = [e for e in events if e != holdout]
            if len(train) >= min_train_events:
                splits.append({"target_admin1": admin1, "train_event_ids": train,
                               "holdout_event_id": holdout})
    return splits


def regional_event_cycles(registry: pd.DataFrame, grid: pd.DataFrame, *,
                          regions: list[str], dates: list[str], cycle_hours: float = 2.0,
                          min_overlap_fraction: float = 0.5,
                          transition_buffer_minutes: int = 30) -> dict[str, pd.DataFrame]:
    """Map region exposure intervals to UTC measurement cycles.

    Queue-specific or published schedules indicate a probabilistic regional
    restriction environment only. They do not identify which IP lost power.
    """
    active_states = {"restriction_active", "queue_specific_active",
                     "published_queue_schedule"}
    g = grid.copy()
    g["measure_time"] = pd.to_datetime(g["measure_time"], utc=True)
    if "is_complete" not in g:
        g["is_complete"] = 1
    cycle_delta = pd.Timedelta(hours=cycle_hours)
    buffer = pd.Timedelta(minutes=transition_buffer_minutes)
    result = {}
    for (admin1, date), d in registry[
            registry["target_admin1"].isin(regions) & registry["date"].astype(str).isin(dates) &
            registry["regional_state"].isin(active_states)].groupby(["target_admin1", "date"]):
        overlap = pd.Series(0.0, index=g.index)
        dose = pd.Series(0.0, index=g.index)
        for _, row in d.iterrows():
            start = pd.to_datetime(row["start_utc"], utc=True, errors="coerce")
            end = pd.to_datetime(row["end_utc"], utc=True, errors="coerce")
            if pd.isna(start) or pd.isna(end):
                continue
            start, end = start + buffer, end - buffer
            if end <= start:
                continue
            left = g.measure_time.where(g.measure_time > start, start)
            right = (g.measure_time + cycle_delta).where(g.measure_time + cycle_delta < end, end)
            hours = ((right - left).dt.total_seconds() / 3600).clip(lower=0)
            # Union-like coverage, capped later; dose is an audit covariate.
            overlap += hours
            fraction = row.get("estimated_exposed_fraction")
            fraction = float(fraction) if pd.notna(fraction) else 1.0 / 6.0
            dose += hours * fraction
        covered = overlap.clip(upper=cycle_hours)
        keep = (covered.div(cycle_hours).ge(min_overlap_fraction) & g["is_complete"].astype(bool))
        x = g.loc[keep, ["cycle_id", "measure_time", "slot"]].copy()
        x["regional_exposure_fraction"] = dose.loc[keep].div(overlap.loc[keep].replace(0, np.nan)).clip(0, 1).to_numpy()
        x["target_admin1"] = admin1
        x["date"] = str(date)
        x["event_id"] = ("REG_" + admin1.upper().replace(" ", "_") + "_" +
                         str(date).replace("-", "") + f"__TBUF{transition_buffer_minutes}")
        if not x.empty:
            result[x.event_id.iloc[0]] = x
    return result
