"""Oblast-specific outage supervision and repeated-sensitivity selection.

The regional sensor is a context-specific construct: ``B2_<oblast>``.  This
module never promotes an oblast/municipality geolocation to queue/address truth.
It also separates published schedules from confirmed DSO execution.
"""
from __future__ import annotations

import itertools
import re

import numpy as np
import pandas as pd


ACTIVE = {"activated", "activated_from", "actual_start_report", "schedule_shifted",
          "two_queues_commanded_from", "restriction_window_published",
          "restriction_window_initial"}
CANCELLED = {"cancelled", "cancelled_from"}


def _slug(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").upper()).strip("_")
    return text or "UNKNOWN"


def assign_independence_episodes(registry: pd.DataFrame,
                                 max_gap_days: int = 3) -> pd.DataFrame:
    """Assign independent episodes within Admin1 x power-operator x label class.

    Consecutive schedule dates are not independent experiments.  A new episode
    begins only after more than ``max_gap_days`` without a schedule in the same
    spatial/operator stratum.
    """
    if registry.empty:
        out = registry.copy()
        out["episode_id"] = pd.Series(dtype=str)
        return out
    out = registry.copy()
    out["_episode_date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["_label_class"] = np.where(
        out["regional_state"].isin({"restriction_active", "published_queue_schedule",
                                    "queue_specific_active"}),
        "POS", "NEG")
    episode = pd.Series("", index=out.index, dtype=object)
    keys = ["target_admin1", "operator", "_label_class"]
    for key, group in out.groupby(keys, dropna=False, sort=True):
        unique_dates = sorted(group["_episode_date"].dropna().unique())
        current_start = None
        date_to_episode: dict[pd.Timestamp, str] = {}
        previous = None
        for raw_date in unique_dates:
            date = pd.Timestamp(raw_date)
            if previous is None or (date - previous).days > int(max_gap_days):
                current_start = date
            date_to_episode[date] = (
                f"EP_{_slug(key[0])}_{_slug(key[1])}_{key[2]}_{current_start:%Y%m%d}"
            )
            previous = date
        episode.loc[group.index] = group["_episode_date"].map(date_to_episode).fillna("")
    out["episode_id"] = episode
    return out.drop(columns=["_episode_date", "_label_class"])


def build_v4_regional_event_registry(schedule: pd.DataFrame,
                                     valid_admin1: set[str] | None = None,
                                     max_episode_gap_days: int = 3) -> pd.DataFrame:
    """Convert the v4 merged schedule into auditable regional exposure rows.

    The DSO/operator service-area scope is an Admin1 proxy unless ``admin2`` is
    explicitly supplied.  ISP/ASN fields describe network operators and are
    intentionally not treated as power-operator identifiers.
    """
    d = schedule.copy()
    if "analysis_eligible" in d:
        d = d[pd.to_numeric(d["analysis_eligible"], errors="coerce").fillna(0).eq(1)]
    valid = set(valid_admin1 or [])
    rows: list[dict] = []
    for _, r in d.iterrows():
        scope = str(r.get("scope_type_norm", r.get("scope_type", ""))).strip().lower()
        if scope == "national":
            continue
        tokens: set[str] = set()
        for field in ("admin1", "affected_admin1"):
            value = str(r.get(field, "") or "")
            tokens.update(x.strip() for x in value.replace(";", "|").split("|") if x.strip())
        tokens -= {"ALL", "MULTIPLE_UNSPECIFIED", "multiple unspecified oblasts"}
        if valid:
            tokens &= valid
        if not tokens:
            continue

        positive = bool(r.get("schedule_positive", False))
        actual_start = pd.to_datetime(r.get("actual_start_utc"), utc=True, errors="coerce")
        actual_end = pd.to_datetime(r.get("actual_end_utc"), utc=True, errors="coerce")
        has_actual = pd.notna(actual_start) and pd.notna(actual_end) and actual_end > actual_start
        planned_start = pd.to_datetime(r.get("start_utc", r.get("planned_start_utc")),
                                       utc=True, errors="coerce")
        planned_end = pd.to_datetime(r.get("end_utc", r.get("planned_end_utc")),
                                     utc=True, errors="coerce")
        start, end = (actual_start, actual_end) if positive and has_actual else (planned_start, planned_end)
        if pd.isna(start) or pd.isna(end) or end <= start:
            continue

        restriction = str(r.get("restriction_type", "")).strip().lower()
        status = str(r.get("status_norm", r.get("status", ""))).strip().lower()
        if positive:
            state = "restriction_active" if has_actual else "published_queue_schedule"
        elif restriction == "no_restriction" or status == "no_restriction":
            state = "no_restriction"
        else:
            state = "restriction_cancelled"
        q = pd.to_numeric(pd.Series([r.get("queue_count")]), errors="coerce").iloc[0]
        fraction = (min(max(float(q) / 6.0, 0.0), 1.0)
                    if positive and pd.notna(q) and q > 0 else (0.0 if not positive else np.nan))
        confound_free = int(pd.to_numeric(pd.Series([r.get("confound_free", 0)]),
                                          errors="coerce").fillna(0).iloc[0])
        publication = int(pd.to_numeric(pd.Series([r.get("publication_eligible", 0)]),
                                        errors="coerce").fillna(0).iloc[0])
        precision = str(r.get("geo_scope_precision", "") or "")
        if not precision:
            precision = ("L2_admin2_named_ip_city_unresolved" if str(r.get("admin2", "") or "").strip()
                         else "L2_operator_admin1_proxy" if scope == "operator_service_area"
                         else "L2_admin1")
        for admin1 in sorted(tokens):
            operator = str(r.get("operator", "") or "").strip() or "UNKNOWN_POWER_OPERATOR"
            rows.append({
                "regional_event_id": f"{admin1}|{r.get('event_date')}|{r.get('record_id')}",
                "date": str(r.get("event_date")), "target_admin1": admin1,
                "admin2": str(r.get("admin2", "") or "").strip(),
                "operator": operator, "exposure_unit_id": f"{admin1}|{operator}",
                "start_utc": start, "end_utc": end,
                "planned_start_utc": planned_start, "planned_end_utc": planned_end,
                "actual_start_utc": actual_start, "actual_end_utc": actual_end,
                "queue": str(r.get("queue_id", r.get("queue_ids_merged", "")) or ""),
                "regional_state": state,
                "region_binary_usable": int(has_actual and scope in {"oblast", "city"}),
                "estimated_exposed_fraction": fraction,
                "evidence_level": r.get("source_grade"),
                "execution_interpretation": r.get("actual_time_semantics"),
                "source_url": r.get("verified_source_url") or r.get("source_url"),
                "source_kind": "v4_actual_execution" if has_actual else "v4_schedule",
                "ip_level_power_truth": 0,
                "record_id": r.get("record_id"), "scope_type": scope,
                "exposure_precision": precision,
                "calibration_eligible": int(positive and confound_free and publication),
                "negative_control_eligible": int((not positive) and confound_free and publication),
                "label_uses_actual_time": int(positive and has_actual),
                "isp_control_required": 1,
            })
    if not rows:
        return pd.DataFrame(columns=["regional_event_id", "episode_id", "date",
                                     "target_admin1", "operator", "start_utc",
                                     "end_utc", "regional_state"])
    out = assign_independence_episodes(pd.DataFrame(rows), max_gap_days=max_episode_gap_days)
    return out.sort_values(
        ["target_admin1", "episode_id", "start_utc", "regional_event_id"]
    ).reset_index(drop=True)


def build_v3_regional_event_registry(schedule: pd.DataFrame,
                                     valid_admin1: set[str] | None = None) -> pd.DataFrame:
    """Convert the unified v3 registry into oblast-date exposure intervals.

    National dispatch rows are deliberately excluded from regional sensor
    discovery: they do not identify which oblast was treated.  Only explicit
    oblast/city/operator-service-area/multi-oblast rows can train B2_region.
    """
    d = schedule.copy()
    if "record_role" in d:
        d = d[d["record_role"].isin({"planned_or_final_dispatch", "final_dispatch",
                                      "execution_override"})]
    if "analysis_eligible" in d:
        d = d[pd.to_numeric(d["analysis_eligible"], errors="coerce").fillna(0).eq(1)]
    if "schedule_positive" in d:
        d = d[d["schedule_positive"].astype(bool)]
    valid = set(valid_admin1 or [])
    rows = []
    for _, r in d.iterrows():
        scope = str(r.get("scope_type_norm", r.get("scope_type", ""))).strip().lower()
        if scope == "national":
            continue
        tokens = set()
        for field in ("admin1", "affected_admin1"):
            value = str(r.get(field, "") or "")
            tokens.update(x.strip() for x in value.replace(";", "|").split("|") if x.strip())
        if valid:
            tokens &= valid
        tokens -= {"ALL", "MULTIPLE_UNSPECIFIED", "multiple unspecified oblasts"}
        start = pd.to_datetime(r.get("start_utc"), utc=True, errors="coerce")
        end = pd.to_datetime(r.get("end_utc"), utc=True, errors="coerce")
        if pd.isna(start) or pd.isna(end) or end <= start:
            continue
        q = pd.to_numeric(pd.Series([r.get("queue_count")]), errors="coerce").iloc[0]
        fraction = min(max(float(q) / 6.0, 0.0), 1.0) if pd.notna(q) and q > 0 else np.nan
        execution = str(r.get("record_role", "")) == "execution_override"
        for admin1 in sorted(tokens):
            rows.append({
                "regional_event_id": f"{admin1}|{r.get('event_date')}|{r.get('record_id')}",
                "date": str(r.get("event_date")), "target_admin1": admin1,
                "operator": r.get("operator"), "start_utc": start, "end_utc": end,
                "queue": str(r.get("queue_id", "") or ""),
                "regional_state": "restriction_active" if execution else "published_queue_schedule",
                "region_binary_usable": int(execution and scope in {"oblast", "city"}),
                "estimated_exposed_fraction": fraction,
                "evidence_level": r.get("source_grade"),
                "execution_interpretation": r.get("actual_time_semantics"),
                "source_url": r.get("source_url"),
                "source_kind": "execution_override" if execution else "v3_schedule",
                "ip_level_power_truth": 0,
                "record_id": r.get("record_id"),
            })
    if not rows:
        return pd.DataFrame(columns=["regional_event_id", "date", "target_admin1",
                                     "start_utc", "end_utc", "regional_state"])
    return pd.DataFrame(rows).sort_values(
        ["target_admin1", "date", "start_utc", "regional_event_id"]).reset_index(drop=True)


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
    strata = ["target_admin1"]
    if "exposure_unit_id" in d:
        strata.append("exposure_unit_id")
    out = (d.groupby([*strata, "dst_ip"], as_index=False)
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
    strata = ["target_admin1"] + (["exposure_unit_id"] if "exposure_unit_id" in event_scores else [])
    for key, d in event_scores.groupby(strata):
        key = key if isinstance(key, tuple) else (key,)
        admin1 = key[0]
        exposure_unit_id = key[1] if len(key) > 1 else admin1
        members = {str(e): set(g.loc[pd.to_numeric(g["S_lo"], errors="coerce").gt(0), "dst_ip"])
                   for e, g in d.groupby("event_id")}
        for a, b in itertools.combinations(sorted(members), 2):
            ma, mb = members[a], members[b]
            union = ma | mb
            rows.append({"target_admin1": admin1, "exposure_unit_id": exposure_unit_id,
                         "event_a": a, "event_b": b,
                         "n_a": len(ma), "n_b": len(mb),
                         "intersection_n": len(ma & mb),
                         "jaccard": len(ma & mb) / len(union) if union else np.nan,
                         "retention_a_to_b": len(ma & mb) / len(ma) if ma else np.nan,
                         "retention_b_to_a": len(ma & mb) / len(mb) if mb else np.nan})
    return pd.DataFrame(rows)


def leave_one_event_out_splits(event_scores: pd.DataFrame, min_train_events: int = 3) -> list[dict]:
    """Return frozen within-oblast train/holdout event IDs."""
    splits = []
    strata = ["target_admin1"] + (["exposure_unit_id"] if "exposure_unit_id" in event_scores else [])
    for key, d in event_scores.groupby(strata):
        key = key if isinstance(key, tuple) else (key,)
        admin1 = key[0]
        exposure_unit_id = key[1] if len(key) > 1 else admin1
        events = sorted(d["event_id"].astype(str).unique())
        for holdout in events:
            train = [e for e in events if e != holdout]
            if len(train) >= min_train_events:
                splits.append({"target_admin1": admin1, "exposure_unit_id": exposure_unit_id,
                               "train_event_ids": train,
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
    eligible = registry["regional_state"].isin(active_states)
    if "calibration_eligible" in registry:
        eligible &= pd.to_numeric(registry["calibration_eligible"], errors="coerce").fillna(0).eq(1)
    selected_registry = registry[
        registry["target_admin1"].isin(regions) &
        registry["date"].astype(str).isin(dates) & eligible
    ].copy()
    group_keys = ["target_admin1", "episode_id"] if "episode_id" in selected_registry else ["target_admin1", "date"]
    for group_key, d in selected_registry.groupby(group_keys):
        admin1 = str(group_key[0])
        episode_id = str(group_key[1])
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
        x["date"] = "|".join(sorted(d["date"].astype(str).unique()))
        x["episode_id"] = episode_id
        x["operator"] = "|".join(sorted(d["operator"].dropna().astype(str).unique()))
        x["exposure_unit_id"] = "|".join(sorted(
            d.get("exposure_unit_id", pd.Series(admin1, index=d.index)).astype(str).unique()))
        x["exposure_precision"] = "|".join(sorted(
            d.get("exposure_precision", pd.Series("L2_admin1", index=d.index)).astype(str).unique()))
        x["event_id"] = f"REG_{_slug(episode_id)}__TBUF{transition_buffer_minutes}"
        if not x.empty:
            result[x.event_id.iloc[0]] = x
    return result
