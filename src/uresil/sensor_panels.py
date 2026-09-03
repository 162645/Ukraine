"""Build zero-inclusive event panels from frozen B1/B2 endpoint sensor sets.

Endpoint geography remains at IP resolution.  A /24 may therefore contribute
separate analysis units to different ASN/Admin1 groups; numerators and denominators
are keyed by ``analysis_unit_id = prefix24|ASN|country|Admin1`` to prevent one
prefix's responders from being duplicated across groups.
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

from . import sqlutil as S
from .config import Config
from .db import CHClient
from .events import Events
from .progress import HeartbeatProgress, get_logger, pbar, step

METHODS = ("B1", "B2")


def _force_recompute(cfg: Config) -> bool:
    return bool(cfg.raw.get("_runtime_flags", {}).get("force_stage_recompute", False))


def _readable_parquet(path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0 and pd.read_parquet(path) is not None
    except Exception:
        return False


def _query_response_window(cfg: Config, ch: CHClient, *, event_id: str, lo, hi,
                           prefixes: list[str], cycle_seconds: int, logger) -> pd.DataFrame:
    if not prefixes:
        return pd.DataFrame(columns=["cycle_id", "dst_ip", "prefix24", "rtt_ms"])
    q = S.render("07_ping_response_window", ping=cfg.table("ping"), dc=cfg.study["data_center"],
                 start=lo.strftime("%Y-%m-%d %H:%M:%S"),
                 end=(hi + pd.Timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"),
                 prefix_in=S.str_list(prefixes), cycle_seconds=cycle_seconds)
    try:
        return ch.query_df(q)
    except Exception as e:  # noqa: BLE001
        if len(prefixes) <= 1:
            raise
        logger.warning("sensor response batch failed for %s with %d prefixes: %s; splitting",
                       event_id, len(prefixes), e)
        mid = max(1, len(prefixes) // 2)
        left = _query_response_window(cfg, ch, event_id=event_id, lo=lo, hi=hi,
                                      prefixes=prefixes[:mid], cycle_seconds=cycle_seconds,
                                      logger=logger)
        right = _query_response_window(cfg, ch, event_id=event_id, lo=lo, hi=hi,
                                       prefixes=prefixes[mid:], cycle_seconds=cycle_seconds,
                                       logger=logger)
        if left.empty:
            return right
        if right.empty:
            return left
        return pd.concat([left, right], ignore_index=True)


def score_parts(cfg: Config) -> list[str]:
    return sorted(glob.glob(str(cfg.out_dir("data_derived") / "ip_sensor_scores_parts" / "part_*.parquet")))


def choose_primary_method(cfg: Config) -> str:
    p = cfg.out_dir("results_tables") / "exp_a_summary.csv"
    if p.exists() and p.stat().st_size:
        d = pd.read_csv(p)
        if "calibration_success" in d and d["calibration_success"].astype(str).str.lower().isin(["true", "1"]).any():
            return "B2"
    return "B1"


def build_denominators(cfg: Config, parts: list[str]) -> pd.DataFrame:
    rows = []
    cols = ["prefix24", "target_asn", "target_country", "target_admin1", "pN", "in_B1", "in_B2"]
    for p in pbar(parts, desc="sensor denominators", unit="part"):
        d = pd.read_parquet(p, columns=cols)
        for m in METHODS:
            z = d[d[f"in_{m}"]]
            if z.empty:
                continue
            rows.append(z.groupby(["prefix24", "target_asn", "target_country", "target_admin1"])
                        .agg(sensor_n=("pN", "size"), expected_response_n=("pN", "sum"))
                        .reset_index().assign(method=m))
    if not rows:
        return pd.DataFrame()
    out = (pd.concat(rows, ignore_index=True)
           .groupby(["prefix24", "target_asn", "target_country", "target_admin1", "method"])
           .agg(sensor_n=("sensor_n", "sum"), expected_response_n=("expected_response_n", "sum"))
           .reset_index())
    out["group"] = (out.target_asn.astype(str) + "|" + out.target_country.astype(str)
                    + "|" + out.target_admin1.astype(str))
    out["analysis_unit_id"] = out.prefix24.astype(str) + "|" + out.group
    out["regional_eligible"] = (~out.target_admin1.isin(
        ["COUNTRY_ONLY_UA", "UNKNOWN_ADMIN1", "UNMAPPED_UA_ADMIN1"])).astype("int8")
    return out


def _event_responses(cfg: Config, ch: CHClient, event: pd.Series, parts: list[str]) -> pd.DataFrame:
    logger = get_logger(cfg.out_dir("logs"))
    ev = Events(cfg)
    lo, hi = ev.event_window(event)
    h = int(cfg.study["expected_cycle_interval_hours"])
    num = []
    cols = ["dst_ip", "prefix24", "target_asn", "target_country", "target_admin1", "in_B1", "in_B2"]
    for p in pbar(parts, desc=f"sensor responses {event['event_id']}", unit="part"):
        sensors = pd.read_parquet(p, columns=cols)
        sensors = sensors[sensors.in_B1 | sensors.in_B2]
        if sensors.empty:
            continue
        sensors["group"] = (sensors.target_asn.astype(str) + "|" + sensors.target_country.astype(str)
                            + "|" + sensors.target_admin1.astype(str))
        sensors["analysis_unit_id"] = sensors.prefix24.astype(str) + "|" + sensors.group
        prefixes = sensors.prefix24.drop_duplicates().astype(str).tolist()
        r = _query_response_window(cfg, ch, event_id=str(event["event_id"]), lo=lo, hi=hi,
                                   prefixes=prefixes, cycle_seconds=h * 3600, logger=logger)
        if r.empty:
            continue
        r = r.merge(sensors, on=["dst_ip", "prefix24"], how="inner")
        key = ["cycle_id", "prefix24", "target_asn", "target_country", "target_admin1",
               "group", "analysis_unit_id"]
        for m in METHODS:
            z = r[r[f"in_{m}"]]
            if not z.empty:
                num.append(z.groupby(key).agg(
                    responders=("dst_ip", "nunique"), rtt_median=("rtt_ms", "median"))
                           .reset_index().assign(method=m))
    if not num:
        return pd.DataFrame(columns=["cycle_id", "analysis_unit_id", "method", "responders", "rtt_median"])
    key = ["cycle_id", "prefix24", "target_asn", "target_country", "target_admin1",
           "group", "analysis_unit_id", "method"]
    return (pd.concat(num, ignore_index=True).groupby(key)
            .agg(responders=("responders", "sum"), rtt_median=("rtt_median", "median")).reset_index())


def build_event_panel(cfg: Config, event: pd.Series, denom: pd.DataFrame,
                      numer: pd.DataFrame, cq: pd.DataFrame) -> pd.DataFrame:
    denom = denom.copy()
    numer = numer.copy()
    if "group" not in denom:
        denom["group"] = (denom.target_asn.astype(str) + "|" + denom.target_country.astype(str)
                          + "|" + denom.target_admin1.astype(str))
    if "analysis_unit_id" not in denom:
        denom["analysis_unit_id"] = denom.prefix24.astype(str) + "|" + denom.group.astype(str)
    if "regional_eligible" not in denom:
        denom["regional_eligible"] = (~denom.target_admin1.isin(
            ["COUNTRY_ONLY_UA", "UNKNOWN_ADMIN1", "UNMAPPED_UA_ADMIN1"])).astype("int8")
    if not numer.empty and "analysis_unit_id" not in numer:
        # Backward-compatible test/legacy path: infer the unique unit for each prefix.
        lookup = denom[["prefix24", "analysis_unit_id"]].drop_duplicates()
        if lookup["prefix24"].duplicated().any():
            raise ValueError("Legacy numerator lacks analysis_unit_id for a prefix split across multiple groups")
        numer = numer.merge(lookup, on="prefix24", how="left", validate="many_to_one")
    ev = Events(cfg)
    grid = ev.build_cycle_grid(cq)
    lo, hi = ev.event_window(event)
    cycles = grid[(grid.measure_time >= lo) & (grid.measure_time <= hi) & grid.is_complete.eq(1)][
        ["cycle_id", "measure_time", "slot"]]
    chunks = []
    for m in METHODS:
        dm = denom[(denom.method.eq(m)) & (denom.sensor_n >= 1)]
        if dm.empty:
            continue
        nm = numer[numer.method.eq(m)] if not numer.empty else numer
        keys = ["cycle_id", "analysis_unit_id", "method"]
        x = cycles.merge(dm, how="cross").merge(
            nm[[*keys, "responders", "rtt_median"]] if not nm.empty else nm,
            on=keys, how="left")
        x["responders"] = x.responders.fillna(0)
        if "rtt_median" not in x:
            x["rtt_median"] = np.nan
        x["sensor_reach"] = x.responders / x.sensor_n.replace(0, np.nan)
        x["normalized_reach"] = x.responders / x.expected_response_n.replace(0, np.nan)
        x["event_id"] = event.event_id
        chunks.append(x)
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    parts = score_parts(cfg)
    if not parts:
        raise RuntimeError("Run Experiment A first; no endpoint score parts")
    cq = pd.read_parquet(cfg.out_dir("data_derived") / "cycle_quality.parquet")
    ev = Events(cfg)
    with step("Build frozen endpoint-sensor event panels", logger):
        denom_path = cfg.out_dir("data_derived") / "sensor_denominators.parquet"
        if not _force_recompute(cfg) and _readable_parquet(denom_path):
            logger.info("Reuse existing sensor denominators: %s", denom_path.name)
            denom = pd.read_parquet(denom_path)
        else:
            denom = build_denominators(cfg, parts)
            if denom.empty:
                raise RuntimeError("No B1/B2 sensors")
            denom.to_parquet(denom_path, index=False)
        outdir = cfg.out_dir("data_derived") / "sensor_event_panel"
        outdir.mkdir(exist_ok=True)
        written = []
        available_ids = set(ev.available_df.event_id)
        available_events = [event for _, event in ev.df.iterrows()
                            if event.event_id in available_ids]
        progress = HeartbeatProgress(logger, "sensorPanels.events", total=len(available_events),
                                     unit="event", log_every_n=1, log_every_s=45.0)
        progress.start(total_parts=len(parts))
        with CHClient(cfg) as ch:
            for index, event in enumerate(available_events, start=1):
                path = outdir / f"{event.event_id}.parquet"
                if not _force_recompute(cfg) and _readable_parquet(path):
                    logger.info("Reuse sensor event panel: %s", path.name)
                    written.append(str(path))
                    progress.mark_cached()
                    progress.advance(current=str(event.event_id), event_index=index,
                                     written=len(written), cached=progress.cached)
                    continue
                logger.info("sensorPanels event start: %s (%d/%d)", event.event_id, index, len(available_events))
                event_t0 = pd.Timestamp.utcnow()
                num = _event_responses(cfg, ch, event, parts)
                panel = build_event_panel(cfg, event, denom, num, cq)
                if panel.empty:
                    progress.mark_failed()
                    progress.advance(current=str(event.event_id), event_index=index,
                                     written=len(written), note="empty_panel")
                    continue
                panel.to_parquet(path, index=False)
                written.append(str(path))
                elapsed_s = (pd.Timestamp.utcnow() - event_t0).total_seconds()
                logger.info("sensorPanels event done: %s rows=%d elapsed=%.1fs output=%s",
                            event.event_id, len(panel), elapsed_s, path.name)
                progress.advance(current=str(event.event_id), event_index=index,
                                 written=len(written), cached=progress.cached)
        progress.finish(written=len(written), cached=progress.cached, failed=progress.failed)
        primary = choose_primary_method(cfg)
        pd.DataFrame([{
            "primary_sensor_method": primary,
            "calibration_positive": int(primary == "B2"),
            "n_B1_sensor": int(denom.loc[denom.method.eq("B1"), "sensor_n"].sum()),
            "n_B2_sensor": int(denom.loc[denom.method.eq("B2"), "sensor_n"].sum()),
            "n_B1_regional_sensor": int(denom.loc[denom.method.eq("B1") & denom.regional_eligible.eq(1), "sensor_n"].sum()),
            "n_B2_regional_sensor": int(denom.loc[denom.method.eq("B2") & denom.regional_eligible.eq(1), "sensor_n"].sum()),
            "n_event_panel": len(written),
        }]).to_csv(cfg.out_dir("results_tables") / "sensor_panel_summary.csv", index=False)
    return {"status": "ok", "outputs": [str(cfg.out_dir("data_derived") / "sensor_denominators.parquet")] + written}
