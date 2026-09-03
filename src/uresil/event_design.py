"""Event-stage aware estimands for energy shocks and scheduled outages.

The key distinction is between three times that must never be collapsed:
1. the earliest credible treatment boundary (attack may already have started),
2. the power-outage anchor used for the confirmatory energy-to-network estimand,
3. an independently observed network-anomaly anchor used only for replication.

All pretrend and matching covariates are taken from a clean interval ending before
*any* credible treatment has started.  The attack-to-outage interval is therefore
reported as a transition phase rather than mislabelled as untreated pretrend.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .events import split_admin1


@dataclass(frozen=True)
class EventEstimand:
    event_id: str
    estimand_id: str
    claim_scope: str
    anchor_type: str
    anchor_utc: pd.Timestamp
    treatment_start_utc: pd.Timestamp
    treated_admin1: tuple[str, ...]
    confirmatory: bool


def _ts(row: pd.Series, key: str) -> pd.Timestamp:
    return pd.to_datetime(row.get(key), utc=True, errors="coerce")


def _valid_times(row: pd.Series, keys: Iterable[str]) -> list[pd.Timestamp]:
    out = [_ts(row, k) for k in keys]
    return [x for x in out if pd.notna(x)]


def earliest_treatment_start(row: pd.Series) -> pd.Timestamp:
    """Earliest time at which the event may already affect the network.

    ``anchor_lower_utc`` is included because it is the registered lower bound of
    an uncertain primary anchor.  Attack start dominates later outage/network
    anchors when it is available.
    """
    keys = ("attack_start_utc", "anchor_lower_utc", "outage_start_utc",
            "network_anomaly_start_utc", "primary_anchor_utc")
    times = _valid_times(row, keys)
    return min(times) if times else pd.NaT


def clean_baseline_interval(row: pd.Series, cfg) -> tuple[pd.Timestamp, pd.Timestamp]:
    treatment = earliest_treatment_start(row)
    if pd.isna(treatment):
        return pd.NaT, pd.NaT
    lookback = float(cfg.event_windows.get("clean_baseline_lookback_h", 168))
    buffer_h = float(cfg.event_windows.get("clean_baseline_buffer_h", 6))
    end = treatment - pd.Timedelta(hours=buffer_h)
    start = end - pd.Timedelta(hours=lookback)
    return start, end


def _scope(row: pd.Series, field: str) -> tuple[str, ...]:
    values = split_admin1(row.get(field))
    return tuple(values)


def _make(row: pd.Series, estimand_id: str, claim_scope: str, anchor_type: str,
          scope_field: str, confirmatory: bool) -> EventEstimand | None:
    anchor = _ts(row, anchor_type)
    treated = _scope(row, scope_field)
    if pd.isna(anchor) or not treated:
        return None
    treatment = earliest_treatment_start(row)
    return EventEstimand(
        event_id=str(row["event_id"]), estimand_id=estimand_id,
        claim_scope=claim_scope, anchor_type=anchor_type,
        anchor_utc=anchor, treatment_start_utc=treatment,
        treated_admin1=treated, confirmatory=confirmatory,
    )


def build_estimands(row: pd.Series) -> list[EventEstimand]:
    """Build non-circular estimands from the frozen event registry.

    Confirmatory estimand
    ---------------------
    Scheduled outages and energy attacks use the independently registered power
    exposure geography and outage start.  If outage start is unavailable, attack
    start is used.  The external network-observed geography never defines this
    estimand.

    Diagnostic estimands
    --------------------
    Attack-onset estimates describe the transition from physical attack to later
    outage.  Network-replication estimates test whether the self-measurement can
    recover a third-party network signal, and are explicitly non-causal.
    """
    family = str(row.get("event_family", ""))
    out: list[EventEstimand] = []

    if family == "planned_outage":
        e = _make(row, "confirmatory_power", "scheduled_power_exposure",
                  "outage_start_utc", "power_affected_admin1", True)
        if e is not None:
            out.append(e)
        return out

    # The causal/power estimand is independent of third-party network observations.
    anchor_field = "outage_start_utc" if pd.notna(_ts(row, "outage_start_utc")) else "attack_start_utc"
    e = _make(row, "confirmatory_power", "power_exposure",
              anchor_field, "power_affected_admin1", True)
    if e is None:
        # Backward-compatible fallback to the registry's analysis geography.
        e = _make(row, "confirmatory_power", "registered_primary_exposure",
                  "primary_anchor_utc", "analysis_treated_admin1", True)
    if e is not None:
        out.append(e)

    attack = _make(row, "attack_onset", "descriptive_attack_transition",
                   "attack_start_utc", "power_affected_admin1", False)
    if attack is not None and all(attack.anchor_utc != x.anchor_utc for x in out):
        out.append(attack)

    network = _make(row, "network_replication", "external_network_replication",
                    "network_anomaly_start_utc", "network_observed_admin1", False)
    if network is not None:
        out.append(network)

    return out


def primary_estimand(row: pd.Series) -> EventEstimand:
    estimands = build_estimands(row)
    for e in estimands:
        if e.confirmatory:
            return e
    # This should only occur for a malformed registry and is intentionally loud.
    raise ValueError(f"No confirmatory estimand for event {row.get('event_id')}")


def event_panel_interval(row: pd.Series, cfg) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Absolute interval required by all estimands, clean baseline, and recovery."""
    b0, _ = clean_baseline_interval(row, cfg)
    estimands = build_estimands(row)
    starts = [x.anchor_utc for x in estimands if pd.notna(x.anchor_utc)]
    if pd.notna(b0):
        starts.append(b0)
    ends = [
        _ts(row, "outage_end_utc"), _ts(row, "power_recovery_end_utc"),
        _ts(row, "network_recovery_end_utc"),
    ]
    ends = [x for x in ends if pd.notna(x)]
    for e in estimands:
        ends.append(e.anchor_utc + pd.Timedelta(days=float(cfg.event_windows["recovery_window_days"])))
    if not starts or not ends:
        raise ValueError(f"Incomplete event timing for {row.get('event_id')}")
    return min(starts), max(ends)


def stage_for_time(ts: pd.Timestamp, estimand: EventEstimand, row: pd.Series, cfg) -> str:
    b0, b1 = clean_baseline_interval(row, cfg)
    t = pd.to_datetime(ts, utc=True)
    if pd.notna(b0) and b0 <= t <= b1:
        return "clean_baseline"
    if t < estimand.treatment_start_utc:
        return "pre_treatment_gap"
    if t < estimand.anchor_utc:
        return "transition"
    recovery = _ts(row, "network_recovery_end_utc")
    if pd.isna(recovery):
        recovery = _ts(row, "power_recovery_end_utc")
    if pd.notna(recovery) and t > recovery:
        return "post_recovery"
    return "outcome"
