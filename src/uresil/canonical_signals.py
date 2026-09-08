"""Canonical IPS/FBS signals independent of endpoint labels.

The functions in this module operate on response observations only.  They are
deliberately free of Activity, B1, sensitivity, or attack labels so macro
signals cannot silently inherit an endpoint-analysis sample restriction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_canonical_ips(responses: pd.DataFrame) -> pd.DataFrame:
    """Count distinct responsive IPs by UTC two-hour cycle and Admin1."""
    required = {"measure_time", "dst_ip", "admin1"}
    missing = required - set(responses.columns)
    if missing:
        raise ValueError(f"missing columns for IPS: {sorted(missing)}")
    d = responses.copy()
    d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True)
    d = d.dropna(subset=["measure_time", "dst_ip", "admin1"])
    d = d.drop_duplicates(["measure_time", "admin1", "dst_ip"])
    return (d.groupby(["measure_time", "admin1"], as_index=False)
             .agg(IPS=("dst_ip", "nunique")))


def eligible_blocks(responses: pd.DataFrame, min_monthly_ips: int = 3) -> pd.DataFrame:
    """Return month-by-/24 eligibility using distinct responsive IPs."""
    required = {"measure_time", "prefix24"}
    missing = required - set(responses.columns)
    if missing:
        raise ValueError(f"missing columns for FBS eligibility: {sorted(missing)}")
    d = responses.copy()
    d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True)
    d["month"] = d.measure_time.dt.to_period("M").astype(str)
    d = d.dropna(subset=["month", "prefix24", "dst_ip"])
    out = (d.groupby(["month", "prefix24"], as_index=False)
             .agg(ever_responsive_ips=("dst_ip", "nunique")))
    out["eligible"] = out.ever_responsive_ips.ge(int(min_monthly_ips))
    return out


def compute_canonical_fbs(responses: pd.DataFrame, block_admin1: pd.DataFrame,
                          min_monthly_ips: int = 3) -> pd.DataFrame:
    """Count active eligible /24 blocks by cycle and Admin1.

    ``block_admin1`` must be a frozen modal mapping with columns
    ``prefix24, admin1``.  A block is active when at least one mapped IP
    responds in the cycle.
    """
    required = {"measure_time", "prefix24", "dst_ip"}
    if required - set(responses.columns):
        raise ValueError(f"missing columns for FBS: {sorted(required - set(responses.columns))}")
    if {"prefix24", "admin1"} - set(block_admin1.columns):
        raise ValueError("block_admin1 must contain prefix24 and admin1")
    d = responses.copy()
    d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True)
    d = d.merge(block_admin1[["prefix24", "admin1"]].drop_duplicates("prefix24"),
                on="prefix24", how="inner", validate="many_to_one")
    elig = eligible_blocks(responses, min_monthly_ips)
    d["month"] = d.measure_time.dt.to_period("M").astype(str)
    d = d.merge(elig.loc[elig.eligible, ["month", "prefix24"]],
                on=["month", "prefix24"], how="inner")
    d = d.drop_duplicates(["measure_time", "admin1", "prefix24"])
    return (d.groupby(["measure_time", "admin1"], as_index=False)
             .agg(FBS=("prefix24", "nunique")))


def add_rolling_ratios(signals: pd.DataFrame, days: int = 7,
                       cycle_hours: int = 2, ips_threshold: float = .90,
                       fbs_threshold: float = .95) -> pd.DataFrame:
    """Add strictly retrospective moving means and IPS/FBS outage flags."""
    d = signals.copy()
    d["measure_time"] = pd.to_datetime(d["measure_time"], utc=True)
    n = int(days * 24 / cycle_hours)
    d = d.sort_values(["admin1", "measure_time"])
    for sig, threshold in (("IPS", .90), ("FBS", .95)):
        if sig not in d:
            d[sig] = np.nan
        mean_col = f"{sig}_7d_mean"
        ratio_col = f"{sig}_ratio"
        d[mean_col] = d.groupby("admin1")[sig].transform(
            lambda x: x.shift(1).rolling(n, min_periods=n).mean())
        d[ratio_col] = d[sig] / d[mean_col].replace(0, np.nan)
    d["ips_outage"] = d["IPS_ratio"].lt(float(ips_threshold)) & d["IPS_7d_mean"].notna()
    d["fbs_outage"] = (d["FBS_ratio"].lt(float(fbs_threshold)) & d["IPS_ratio"].lt(float(fbs_threshold))
                       & d["FBS_7d_mean"].notna() & d["IPS_7d_mean"].notna())
    return d.reset_index(drop=True)
