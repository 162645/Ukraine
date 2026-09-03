"""Experiment E — conservative AS/ASGeo forwarding adaptation among surviving traces.

The unit is a high-confidence *adjacent observed hop relation*.  The code does
not interpolate through `*`, ASN 0, private addresses, or unknown geography,
and it never interprets an ASGeo edge as a physical cable route.  Path results
are conditional on `reached_target == 1`; reachability loss itself is analysed
in Experiments A/B.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import pickle
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import sqlutil as S
from .config import Config
from .db import CHClient
from .events import Events
from .geo import Admin1Canonicalizer
from .progress import get_logger, pbar, step
from .provenance import source_tree_sha256
from .sensor_panels import choose_primary_method
from .stats import jensen_shannon, jsd_multinomial_test, shannon_entropy

UNKNOWN = {"", "UNKNOWN", "Unknown", "unknown", "未知", "N/A", "None", "null", None}
UA_ALIASES = {"Ukraine", "UA", "UKR", "乌克兰", "Україна", "Украина"}


def build_reserved_nets(cfg: Config):
    return [ipaddress.ip_network(x, strict=False) for x in cfg.quality.get("reserved_cidrs", [])]


def is_reserved(ip: str, nets) -> bool:
    try:
        x = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    return x.is_private or x.is_reserved or x.is_loopback or x.is_link_local or any(x in n for n in nets)


def _iter_hops(hop_path):
    if hop_path is None:
        return
    for h in hop_path:
        if isinstance(h, (list, tuple, np.ndarray)):
            yield h[0] if len(h) else None
        else:
            yield h


def classify_hop(ip, ip2map: dict, nets) -> dict:
    if ip is None or str(ip) in {"", "*", "None"}:
        return {"kind": "GAP"}
    ip = str(ip)
    if is_reserved(ip, nets):
        return {"kind": "SOURCE_INTERNAL", "ip": ip}
    m = ip2map.get(ip, {})
    asn = int(m.get("asn", 0) or 0)
    country = str(m.get("country", "UNKNOWN") or "UNKNOWN")
    admin1 = str(m.get("admin1", "UNKNOWN") or "UNKNOWN")
    return {"kind": "PUBLIC", "ip": ip, "asn": asn,
            "country": country if country not in UNKNOWN else "UNKNOWN",
            "admin1": admin1 if admin1 not in UNKNOWN else "UNKNOWN"}


def _known_as(n): return n.get("kind") == "PUBLIC" and int(n.get("asn", 0)) > 0

def _known_geo(n):
    return _known_as(n) and n.get("country") not in UNKNOWN and n.get("admin1") not in UNKNOWN


def as_key(e) -> str: return f"AS{e[0]}=>AS{e[1]}"


def asgeo_key(e) -> str:
    a, b = e
    return f"AS{a[0]}|{a[1]}|{a[2]}=>AS{b[0]}|{b[1]}|{b[2]}"


def extract_edges(hop_path, ip2map: dict, nets) -> dict:
    nodes = [classify_hop(ip, ip2map, nets) for ip in _iter_hops(hop_path)]
    responded_public = [n for n in nodes if n["kind"] == "PUBLIC"]
    known_as_n = sum(_known_as(n) for n in responded_public)
    known_geo_n = sum(_known_geo(n) for n in responded_public)
    direct_as, direct_geo, ingress = [], [], None
    known_adjacent_pairs = 0
    possible_pairs = max(len(nodes) - 1, 0)
    for a, b in zip(nodes[:-1], nodes[1:]):
        if _known_as(a) and _known_as(b):
            known_adjacent_pairs += 1
            if a["asn"] != b["asn"]:
                direct_as.append((a["asn"], b["asn"]))
                if _known_geo(a) and _known_geo(b):
                    ge = ((a["asn"], a["country"], a["admin1"]),
                          (b["asn"], b["country"], b["admin1"]))
                    direct_geo.append(ge)
                    if a["country"] not in UA_ALIASES and b["country"] in UA_ALIASES and ingress is None:
                        ingress = ge
    denom = len(responded_public)
    return {
        "direct_as": direct_as, "direct_asgeo": direct_geo, "ingress": ingress,
        "c_as": known_as_n / denom if denom else np.nan,
        "c_geo": known_geo_n / denom if denom else np.nan,
        "c_edge": known_adjacent_pairs / possible_pairs if possible_pairs else np.nan,
        "responded_public": denom, "direct_edge_n": len(direct_as),
    }


class MappingCache:
    def __init__(self, cfg: Config, ch: CHClient, batch: int = 5000):
        self.cfg, self.ch, self.batch = cfg, ch, batch
        self.cache: dict[str, dict] = {}
        self.canon = Admin1Canonicalizer(cfg.resource_path("admin1_aliases"), cfg.quality["unknown_labels"],
                                         cfg.quality["valid_country_aliases"],
                                         cfg.quality.get("country_only_admin1_labels", cfg.quality["valid_country_aliases"]))

    def resolve(self, ips) -> None:
        missing = [str(x) for x in set(ips) if x and str(x) not in self.cache and str(x) not in {"*", "None"}]
        for i in range(0, len(missing), self.batch):
            chunk = missing[i:i + self.batch]
            if not chunk:
                continue
            manifest = self.cfg.load_mapping_manifest()
            snapshot = manifest.get("freeze", {}).get("snapshot_date")
            cutoff_value = str(snapshot).replace(" UTC", "")[:19] if snapshot else ""
            cutoff = f"AND updated_at <= toDateTime('{cutoff_value}', 'UTC')" if cutoff_value else ""
            q = self.ch.query_df(S.render("06_ip_mapping_lookup", mapping=self.cfg.table("mapping"),
                                          ip_in=S.str_list(chunk), mapping_cutoff_clause=cutoff))
            for _, r in q.iterrows():
                asn = int(r["asn"]) if pd.notna(r.get("asn")) else 0
                country = str(r.get("country") or "UNKNOWN")
                admin1 = str(r.get("admin1") or "UNKNOWN")
                if country in UA_ALIASES:
                    country, admin1 = self.canon.canonical_country(country), self.canon.canonical_admin1(country, admin1)
                self.cache[str(r["ip"])] = {"asn": asn, "country": country, "admin1": admin1}
            for ip in chunk:
                self.cache.setdefault(ip, {"asn": 0, "country": "UNKNOWN", "admin1": "UNKNOWN"})


def _event_prefixes(cfg: Config, event: pd.Series, targets: pd.DataFrame,
                    matches: pd.DataFrame) -> list[str]:
    treated = Events.treated_admin1(event)
    if treated == ["ALL"]:
        # National path analysis is disabled by default because it is too large and has no regional control.
        return []
    p = cfg.out_dir("data_derived") / "sensor_event_panel" / f"{event['event_id']}.parquet"
    if not p.exists():
        return []
    panel = pd.read_parquet(p, columns=["prefix24", "target_admin1", "method"])
    panel = panel[panel["method"].eq(choose_primary_method(cfg))]
    prefixes = set(panel.loc[panel["target_admin1"].isin(treated), "prefix24"].astype(str))
    if not matches.empty:
        m = matches[matches["event_id"].eq(event["event_id"])]
        prefixes |= set(m.get("treated_prefix", pd.Series(dtype=str)).dropna().astype(str))
        prefixes |= set(m.get("control_prefix", pd.Series(dtype=str)).dropna().astype(str))
    valid = set(targets.loc[targets["regional_eligible"].eq(1), "prefix24"].astype(str))
    return sorted(prefixes & valid)


def _phase(ts: pd.Timestamp, anchor: pd.Timestamp, cfg: Config) -> str | None:
    h = (ts - anchor).total_seconds() / 3600
    if -float(cfg.path["baseline_hours"]) <= h < 0:
        return "baseline"
    if 0 <= h < float(cfg.path["event_hours"]):
        return "event"
    if float(cfg.path["event_hours"]) <= h < float(cfg.path["event_hours"] + cfg.path["recovery_hours"]):
        return "recovery"
    return None


def _new_acc():
    return {"n_trace_all": 0, "n_trace_reached": 0, "as": Counter(), "geo": Counter(),
            "ingress": Counter(), "c_as": [], "c_geo": [], "c_edge": [],
            "target_ip_ids": set(),
            "edge_windows": defaultdict(set), "edge_ips": defaultdict(set), "edge_prefixes": defaultdict(set)}


def _target_ip_id(ip: str) -> int | str:
    """Compact stable identifier for target-overlap diagnostics."""
    try:
        return int(ipaddress.ip_address(str(ip)))
    except ValueError:
        return str(ip)


def _without(counter: Counter, excluded: set[str]) -> Counter:
    return Counter({k: v for k, v in counter.items() if k not in excluded and v > 0})


def process_event(cfg: Config, ch: CHClient, event: pd.Series, prefixes: list[str],
                  target_map: dict[str, dict], cache: MappingCache) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    logger = get_logger(cfg.out_dir("logs"))
    if not prefixes:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    event_id = str(event["event_id"])
    anchor = Events.anchor_time(event)
    lo = anchor - pd.Timedelta(hours=float(cfg.path["baseline_hours"]))
    hi = anchor + pd.Timedelta(hours=float(cfg.path["event_hours"] + cfg.path["recovery_hours"]))
    win_h = int(cfg.path["window_hours"])
    nets = build_reserved_nets(cfg)
    acc = defaultdict(_new_acc)  # (group, phase)
    window_rows = defaultdict(_new_acc)  # (group, phase, window)

    batch_size = int(cfg.runtime.get("trace_prefix_batch", 300))
    batches = [prefixes[i:i + batch_size] for i in range(0, len(prefixes), batch_size)]
    start_batch = 0
    if _event_progress_valid(cfg, event_id, prefixes):
        acc, window_rows, start_batch = _load_event_progress(cfg, event_id)
        logger.info("Reuse Experiment E batch checkpoints: %s next_batch=%d/%d",
                    event_id, start_batch, len(batches))
    for batch_idx in pbar(range(start_batch, len(batches)), desc=f"E {event_id}", unit="batch"):
        pb = batches[batch_idx]
        batch_acc, batch_windows = _process_prefix_subset(
            cfg, ch, event_id=event_id, lo=lo, hi=hi, prefixes=pb,
            target_map=target_map, cache=cache, anchor=anchor, win_h=win_h,
            nets=nets, logger=logger,
        )
        _merge_accumulators(acc, dict(batch_acc))
        _merge_accumulators(window_rows, dict(batch_windows))
        _write_event_progress(cfg, event_id, prefixes, next_batch_idx=batch_idx + 1,
                              acc=acc, window_rows=window_rows)

    window_out = []
    for (group, phase, w), a in window_rows.items():
        tm = next((v for v in target_map.values() if v["group"] == group), None) or {}
        window_out.append({"event_id": event["event_id"], "group": group, "phase": phase,
                           "window_start": w, "target_asn": tm.get("target_asn"),
                           "target_country": tm.get("target_country"), "target_admin1": tm.get("target_admin1"),
                           "n_trace": a["n_trace_reached"], "as_edge_n": sum(a["as"].values()),
                           "asgeo_edge_n": sum(a["geo"].values()),
                           "c_as": np.nanmean(a["c_as"]) if a["c_as"] else np.nan,
                           "c_geo": np.nanmean(a["c_geo"]) if a["c_geo"] else np.nan,
                           "c_edge": np.nanmean(a["c_edge"]) if a["c_edge"] else np.nan})

    phase_out = []
    groups = sorted({g for g, _ in acc})
    group_meta = {}
    for v in target_map.values():
        group_meta.setdefault(v["group"], v)

    # Frankfurt/source-side changes can appear for nearly every Ukrainian target.
    # Edges present in a preregistered fraction of baseline groups are removed in
    # a target-specific sensitivity estimate; raw JSD is retained separately.
    common_fraction = float(cfg.path.get("source_common_group_fraction", 0.70))
    eligible_for_common = [g for g in groups
                           if acc[(g, "baseline")]["n_trace_reached"] >= int(cfg.path["min_traces_group_phase"])]
    as_support, geo_support = Counter(), Counter()
    for g in eligible_for_common:
        as_support.update(set(acc[(g, "baseline")]["as"]))
        geo_support.update(set(acc[(g, "baseline")]["geo"]))
    denom_common = max(len(eligible_for_common), 1)
    source_common_as = {e for e, n in as_support.items() if n / denom_common >= common_fraction}
    source_common_geo = {e for e, n in geo_support.items() if n / denom_common >= common_fraction}

    for group in groups:
        base, evt, rec = acc[(group, "baseline")], acc[(group, "event")], acc[(group, "recovery")]
        tm = group_meta.get(group, {})
        min_trace = int(cfg.path["min_traces_group_phase"])
        min_edge = int(cfg.path["min_direct_edges_group_phase"])
        base_c_as = np.nanmean(base["c_as"]) if base["c_as"] else np.nan
        base_c_geo = np.nanmean(base["c_geo"]) if base["c_geo"] else np.nan
        base_c_edge = np.nanmean(base["c_edge"]) if base["c_edge"] else np.nan
        c_as = np.nanmean(evt["c_as"]) if evt["c_as"] else np.nan
        c_geo = np.nanmean(evt["c_geo"]) if evt["c_geo"] else np.nan
        c_edge = np.nanmean(evt["c_edge"]) if evt["c_edge"] else np.nan
        quality_ok = (
            base["n_trace_reached"] >= min_trace and evt["n_trace_reached"] >= min_trace and
            sum(base["as"].values()) >= min_edge and sum(evt["as"].values()) >= min_edge and
            base_c_as >= float(cfg.path["strict_min_as_completeness"]) and
            base_c_geo >= float(cfg.path["strict_min_geo_completeness"]) and
            base_c_edge >= float(cfg.path["strict_min_edge_completeness"]) and
            c_as >= float(cfg.path["strict_min_as_completeness"]) and
            c_geo >= float(cfg.path["strict_min_geo_completeness"]) and
            c_edge >= float(cfg.path["strict_min_edge_completeness"])
        )
        as_jsd, as_p, as_null = jsd_multinomial_test(base["as"], evt["as"],
            int(cfg.path["jsd_permutations"]), int(cfg.runtime["random_seed"]))
        geo_jsd, geo_p, geo_null = jsd_multinomial_test(base["geo"], evt["geo"],
            int(cfg.path["jsd_permutations"]), int(cfg.runtime["random_seed"]) + 1)
        base_as_specific, evt_as_specific = _without(base["as"], source_common_as), _without(evt["as"], source_common_as)
        base_geo_specific, evt_geo_specific = _without(base["geo"], source_common_geo), _without(evt["geo"], source_common_geo)
        as_jsd_specific, as_p_specific, _ = jsd_multinomial_test(
            base_as_specific, evt_as_specific, int(cfg.path["jsd_permutations"]),
            int(cfg.runtime["random_seed"]) + 11)
        geo_jsd_specific, geo_p_specific, _ = jsd_multinomial_test(
            base_geo_specific, evt_geo_specific, int(cfg.path["jsd_permutations"]),
            int(cfg.runtime["random_seed"]) + 12)
        bset, eset = set(base["geo"]), set(evt["geo"])
        common_target_ips = base["target_ip_ids"] & evt["target_ip_ids"]
        common_target_ip_n = len(common_target_ips)
        common_target_share_baseline = common_target_ip_n / len(base["target_ip_ids"]) if base["target_ip_ids"] else np.nan
        common_target_share_event = common_target_ip_n / len(evt["target_ip_ids"]) if evt["target_ip_ids"] else np.nan
        same_target_overlap_ready = int(common_target_ip_n >= int(cfg.path.get("min_common_target_ip", 20)))
        retention = len(bset & eset) / len(bset) if bset else np.nan
        persistent_new = [e for e in eset - bset
                          if len(evt["edge_windows"][e]) >= int(cfg.path["new_edge_min_windows"])
                          and len(evt["edge_ips"][e]) >= int(cfg.path["new_edge_min_support_ip"])
                          and len(evt["edge_prefixes"][e]) >= int(cfg.path["new_edge_min_support_prefix"])]
        activation = len(persistent_new) / len(eset) if eset else np.nan
        phase_out.append({
            "event_id": event["event_id"], "group": group,
            "target_asn": tm.get("target_asn"), "target_country": tm.get("target_country"),
            "target_admin1": tm.get("target_admin1"),
            "n_trace_baseline": base["n_trace_reached"], "n_trace_event": evt["n_trace_reached"],
            "n_trace_recovery": rec["n_trace_reached"],
            "event_reached_rate": evt["n_trace_reached"] / evt["n_trace_all"] if evt["n_trace_all"] else np.nan,
            "baseline_c_as": base_c_as, "baseline_c_geo": base_c_geo, "baseline_c_edge": base_c_edge,
            "c_as": c_as, "c_geo": c_geo, "c_edge": c_edge,
            "as_jsd": as_jsd, "as_jsd_p": as_p, "as_jsd_null_median": as_null,
            "asgeo_jsd": geo_jsd, "asgeo_jsd_p": geo_p, "asgeo_jsd_null_median": geo_null,
            "as_jsd_target_specific": as_jsd_specific,
            "as_jsd_target_specific_p": as_p_specific,
            "asgeo_jsd_target_specific": geo_jsd_specific,
            "asgeo_jsd_target_specific_p": geo_p_specific,
            "source_common_as_edge_n": len(source_common_as),
            "source_common_asgeo_edge_n": len(source_common_geo),
            "source_common_group_fraction": common_fraction,
            "common_target_ip_n": common_target_ip_n,
            "common_target_ip_share_baseline": common_target_share_baseline,
            "common_target_ip_share_event": common_target_share_event,
            "same_target_overlap_ready": same_target_overlap_ready,
            "baseline_retention": retention, "new_edge_activation": activation,
            "persistent_new_edge_n": len(persistent_new),
            "ingress_entropy_baseline": shannon_entropy(base["ingress"]),
            "ingress_entropy_event": shannon_entropy(evt["ingress"]),
            "quality_ok": int(quality_ok), "quality": "admissible" if quality_ok else "diagnostic_only",
            "path_condition": "reached_target_only",
        })

    # Normalised ingress table, retaining event identity and phase denominator.
    ingress_rows = []
    for (group, phase), a in acc.items():
        denom = a["n_trace_reached"]
        for edge, count in a["ingress"].items():
            ingress_rows.append({"event_id": event["event_id"], "group": group, "phase": phase,
                                 "edge": edge, "count": count, "n_trace": denom,
                                 "share": count / denom if denom else np.nan,
                                 "per_1000_trace": 1000 * count / denom if denom else np.nan})
    _clear_event_progress(cfg, event_id)
    return pd.DataFrame(window_out), pd.DataFrame(phase_out), pd.DataFrame(ingress_rows)


def _force_recompute(cfg: Config) -> bool:
    return bool(cfg.raw.get("_runtime_flags", {}).get("force_stage_recompute", False))


def _event_cache_dir(cfg: Config) -> Path:
    p = cfg.out_dir("data_derived") / "exp_e_event_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _event_cache_paths(cfg: Config, event_id: str) -> dict[str, Path]:
    base = _event_cache_dir(cfg)
    return {
        "window": base / f"window_{event_id}.parquet",
        "result": base / f"result_{event_id}.parquet",
        "ingress": base / f"ingress_{event_id}.parquet",
        "done": base / f"done_{event_id}.json",
    }


def _event_cache_meta(cfg: Config, event_id: str, prefixes: list[str]) -> dict:
    return {
        "event_id": event_id,
        "run_id": cfg.run_id,
        "frozen_hashes": cfg.frozen_hashes(),
        "source_tree_sha256": source_tree_sha256(cfg.root),
        "trace_prefix_batch": int(cfg.runtime.get("trace_prefix_batch", 300)),
        "prefix_count": len(prefixes),
        "prefixes_sha256": hashlib.sha256("\n".join(prefixes).encode("utf-8")).hexdigest(),
    }


def _event_cache_valid(cfg: Config, event_id: str, prefixes: list[str]) -> bool:
    if _force_recompute(cfg):
        return False
    paths = _event_cache_paths(cfg, event_id)
    if not all(p.exists() and p.stat().st_size > 0 for p in paths.values()):
        return False
    try:
        meta = json.loads(paths["done"].read_text(encoding="utf-8"))
    except Exception:
        return False
    return meta == _event_cache_meta(cfg, event_id, prefixes)


def _write_event_cache(cfg: Config, event_id: str, prefixes: list[str],
                       window_df: pd.DataFrame, result_df: pd.DataFrame,
                       ingress_df: pd.DataFrame) -> None:
    paths = _event_cache_paths(cfg, event_id)
    for key, df in (("window", window_df), ("result", result_df), ("ingress", ingress_df)):
        tmp = paths[key].with_suffix(paths[key].suffix + ".tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(paths[key])
    done_tmp = paths["done"].with_suffix(".json.tmp")
    done_tmp.write_text(json.dumps(_event_cache_meta(cfg, event_id, prefixes), ensure_ascii=False, indent=2), encoding="utf-8")
    done_tmp.replace(paths["done"])


def _load_event_cache(cfg: Config, event_id: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    paths = _event_cache_paths(cfg, event_id)
    return (pd.read_parquet(paths["window"]),
            pd.read_parquet(paths["result"]),
            pd.read_parquet(paths["ingress"]))


def _event_progress_paths(cfg: Config, event_id: str) -> dict[str, Path]:
    base = _event_cache_dir(cfg)
    return {
        "state": base / f"state_{event_id}.pkl",
        "meta": base / f"progress_{event_id}.json",
    }


def _merge_bucket(dst: dict, src: dict) -> None:
    dst["n_trace_all"] += int(src.get("n_trace_all", 0))
    dst["n_trace_reached"] += int(src.get("n_trace_reached", 0))
    dst["as"].update(src.get("as", {}))
    dst["geo"].update(src.get("geo", {}))
    dst["ingress"].update(src.get("ingress", {}))
    dst["c_as"].extend(src.get("c_as", []))
    dst["c_geo"].extend(src.get("c_geo", []))
    dst["c_edge"].extend(src.get("c_edge", []))
    dst["target_ip_ids"].update(src.get("target_ip_ids", set()))
    for key, vals in src.get("edge_windows", {}).items():
        dst["edge_windows"][key].update(vals)
    for key, vals in src.get("edge_ips", {}).items():
        dst["edge_ips"][key].update(vals)
    for key, vals in src.get("edge_prefixes", {}).items():
        dst["edge_prefixes"][key].update(vals)


def _merge_accumulators(dst: defaultdict, src: dict) -> None:
    for key, bucket in src.items():
        _merge_bucket(dst[key], bucket)


def _event_progress_meta(cfg: Config, event_id: str, prefixes: list[str], *, next_batch_idx: int) -> dict:
    meta = _event_cache_meta(cfg, event_id, prefixes)
    meta["next_batch_idx"] = int(next_batch_idx)
    return meta


def _event_progress_valid(cfg: Config, event_id: str, prefixes: list[str]) -> bool:
    if _force_recompute(cfg):
        return False
    paths = _event_progress_paths(cfg, event_id)
    if not all(p.exists() and p.stat().st_size > 0 for p in paths.values()):
        return False
    try:
        meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    except Exception:
        return False
    expected = _event_cache_meta(cfg, event_id, prefixes)
    return all(meta.get(k) == v for k, v in expected.items()) and int(meta.get("next_batch_idx", 0)) >= 0


def _write_event_progress(cfg: Config, event_id: str, prefixes: list[str], *, next_batch_idx: int,
                          acc: defaultdict, window_rows: defaultdict) -> None:
    paths = _event_progress_paths(cfg, event_id)
    state_tmp = paths["state"].with_suffix(".pkl.tmp")
    with state_tmp.open("wb") as f:
        pickle.dump({
            "acc": dict(acc),
            "window_rows": dict(window_rows),
        }, f, protocol=pickle.HIGHEST_PROTOCOL)
    state_tmp.replace(paths["state"])
    meta_tmp = paths["meta"].with_suffix(".json.tmp")
    meta_tmp.write_text(
        json.dumps(_event_progress_meta(cfg, event_id, prefixes, next_batch_idx=next_batch_idx),
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_tmp.replace(paths["meta"])


def _load_event_progress(cfg: Config, event_id: str) -> tuple[defaultdict, defaultdict, int]:
    paths = _event_progress_paths(cfg, event_id)
    with paths["state"].open("rb") as f:
        state = pickle.load(f)
    meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    return (
        defaultdict(_new_acc, state.get("acc", {})),
        defaultdict(_new_acc, state.get("window_rows", {})),
        int(meta.get("next_batch_idx", 0)),
    )


def _clear_event_progress(cfg: Config, event_id: str) -> None:
    for path in _event_progress_paths(cfg, event_id).values():
        if path.exists():
            path.unlink()


def _process_prefix_subset(cfg: Config, ch: CHClient, *, event_id: str, lo, hi,
                           prefixes: list[str], target_map: dict[str, dict],
                           cache: MappingCache, anchor: pd.Timestamp, win_h: int,
                           nets, logger) -> tuple[defaultdict, defaultdict]:
    local_acc = defaultdict(_new_acc)
    local_windows = defaultdict(_new_acc)
    if not prefixes:
        return local_acc, local_windows
    try:
        sql = S.render("05_path_trace_window", trace=cfg.table("trace"),
                       win_start=lo.strftime("%Y-%m-%d %H:%M:%S"),
                       win_end=hi.strftime("%Y-%m-%d %H:%M:%S"),
                       dc=cfg.study["data_center"], prefix_in=S.str_list(prefixes))
        for block in ch.stream_df(sql, desc=f"trace {event_id}"):
            if block.empty:
                continue
            all_ips = [ip for hp in block["hop_path"] for ip in _iter_hops(hp)
                       if ip and str(ip) not in {"*", "None"}]
            cache.resolve(all_ips)
            for _, r in block.iterrows():
                prefix = str(r["prefix24"])
                tm = target_map.get(str(r["dst_ip"]))
                if not tm:
                    continue
                group = tm["group"]
                ts = pd.to_datetime(r["measure_time"], utc=True)
                phase = _phase(ts, anchor, cfg)
                if phase is None:
                    continue
                a = local_acc[(group, phase)]
                a["n_trace_all"] += 1
                if int(r.get("reached_target", 0)) != 1:
                    continue
                a["n_trace_reached"] += 1
                if bool(cfg.path.get("track_target_overlap", True)):
                    a["target_ip_ids"].add(_target_ip_id(str(r["dst_ip"])))
                info = extract_edges(r["hop_path"], cache.cache, nets)
                w = ts.floor(f"{win_h}h")
                b = local_windows[(group, phase, w)]
                b["n_trace_all"] += 1; b["n_trace_reached"] += 1
                for key in ["c_as", "c_geo", "c_edge"]:
                    a[key].append(info[key]); b[key].append(info[key])
                for e in info["direct_as"]:
                    k = as_key(e); a["as"][k] += 1; b["as"][k] += 1
                for e in info["direct_asgeo"]:
                    k = asgeo_key(e); a["geo"][k] += 1; b["geo"][k] += 1
                    a["edge_windows"][k].add(w); a["edge_ips"][k].add(str(r["dst_ip"])); a["edge_prefixes"][k].add(prefix)
                if info["ingress"]:
                    k = asgeo_key(info["ingress"]); a["ingress"][k] += 1; b["ingress"][k] += 1
        return local_acc, local_windows
    except Exception as e:  # noqa: BLE001
        if len(prefixes) <= 1 or not ch._is_reconnectable_error(e):
            raise
        logger.warning("E %s prefix batch failed with %d prefixes: %s; splitting",
                       event_id, len(prefixes), e)
        mid = max(1, len(prefixes) // 2)
        left_acc, left_windows = _process_prefix_subset(
            cfg, ch, event_id=event_id, lo=lo, hi=hi, prefixes=prefixes[:mid],
            target_map=target_map, cache=cache, anchor=anchor, win_h=win_h, nets=nets,
            logger=logger,
        )
        right_acc, right_windows = _process_prefix_subset(
            cfg, ch, event_id=event_id, lo=lo, hi=hi, prefixes=prefixes[mid:],
            target_map=target_map, cache=cache, anchor=anchor, win_h=win_h, nets=nets,
            logger=logger,
        )
        _merge_accumulators(local_acc, dict(left_acc))
        _merge_accumulators(local_acc, dict(right_acc))
        _merge_accumulators(local_windows, dict(left_windows))
        _merge_accumulators(local_windows, dict(right_windows))
        return local_acc, local_windows


def run(cfg: Config) -> dict:
    logger = get_logger(cfg.out_dir("logs"))
    targets_path = cfg.out_dir("data_derived") / "target_ip_universe.parquet"
    features_path = cfg.out_dir("data_derived") / "group_event_features.parquet"
    if not targets_path.exists() or not features_path.exists():
        raise FileNotFoundError("Experiment E requires audit target universe and group-event features")
    targets = pd.read_parquet(targets_path)
    targets = targets[targets["regional_eligible"].eq(1)].drop_duplicates("dst_ip")
    target_map = targets.set_index("dst_ip")[["group", "target_asn", "target_country", "target_admin1"]].to_dict("index")
    matches_path = cfg.out_dir("results_tables") / "exp_b_matches.csv"
    matches = pd.read_csv(matches_path) if matches_path.exists() and matches_path.stat().st_size else pd.DataFrame()
    features = pd.read_parquet(features_path)
    ev = Events(cfg)
    enabled = set(cfg.path["enabled_events"])
    events = ev.available_df[ev.available_df["event_id"].isin(enabled)]

    windows, results, ingress = [], [], []
    with step("Experiment E: high-confidence AS/ASGeo adaptation", logger), CHClient(cfg) as ch:
        cache = MappingCache(cfg, ch)
        for _, event in events.iterrows():
            event_id = str(event["event_id"])
            prefixes = _event_prefixes(cfg, event, targets, matches)
            logger.info("E %s: %d treated/control prefixes", event_id, len(prefixes))
            if not prefixes:
                continue
            if _event_cache_valid(cfg, event_id, prefixes):
                logger.info("Reuse Experiment E cache: %s", event_id)
                w, r, ing = _load_event_cache(cfg, event_id)
            else:
                w, r, ing = process_event(cfg, ch, event, prefixes, target_map, cache)
                _write_event_cache(cfg, event_id, prefixes, w, r, ing)
            if not w.empty: windows.append(w)
            if not r.empty: results.append(r)
            if not ing.empty: ingress.append(ing)

    window_df = pd.concat(windows, ignore_index=True) if windows else pd.DataFrame()
    result_df = pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    ingress_df = pd.concat(ingress, ignore_index=True) if ingress else pd.DataFrame()
    if not result_df.empty:
        auc = features[["event_id", "group", "deficit_auc_full", "max_deficit"]].rename(
            columns={"deficit_auc_full": "auc"})
        result_df = result_df.merge(auc, on=["event_id", "group"], how="left")

    # Family-wise path claims are corrected across all quality-admissible
    # group-event tests.  Raw p-values remain available for diagnostics.
    if not result_df.empty:
        for pcol, qcol in [("as_jsd_target_specific_p", "as_jsd_target_specific_q"),
                           ("asgeo_jsd_target_specific_p", "asgeo_jsd_target_specific_q")]:
            result_df[qcol] = np.nan
            mask = result_df["quality_ok"].eq(1) & pd.to_numeric(result_df.get(pcol), errors="coerce").notna()
            z = result_df.loc[mask, [pcol]].copy().sort_values(pcol)
            if not z.empty:
                m = len(z); raw = pd.to_numeric(z[pcol], errors="coerce").to_numpy(float)
                q = np.ones(m); prev = 1.0
                for i in range(m - 1, -1, -1):
                    prev = min(prev, raw[i] * m / (i + 1)); q[i] = prev
                result_df.loc[z.index, qcol] = q
        alpha = float(cfg.path.get("fdr_alpha", cfg.inference.get("fdr_alpha", 0.05)))
        result_df["asgeo_path_fdr_significant"] = (
            pd.to_numeric(result_df.get("asgeo_jsd_target_specific_q"), errors="coerce") <= alpha).fillna(False).astype("int8")

    table_dir = cfg.out_dir("results_tables")
    window_df.to_parquet(cfg.out_dir("data_derived") / "path_edge_window.parquet", index=False)
    result_df.to_csv(table_dir / "exp_e_path_results.csv", index=False)
    quadrant = result_df[result_df.get("quality_ok", pd.Series(dtype=int)).eq(1) & result_df.get("auc", pd.Series(dtype=float)).notna()].copy() if not result_df.empty else pd.DataFrame()
    if not quadrant.empty:
        jsd_col = "asgeo_jsd_target_specific" if "asgeo_jsd_target_specific" in quadrant else "asgeo_jsd"
        quadrant["jsd"] = quadrant[jsd_col]
        quadrant = quadrant[
            ["group", "event_id", "auc", "max_deficit", "jsd", "n_trace_event", "quality",
             "c_as", "c_geo", "c_edge", "asgeo_jsd_p", "asgeo_jsd_target_specific_p",
             "asgeo_jsd_target_specific_q", "asgeo_path_fdr_significant",
             "common_target_ip_n", "common_target_ip_share_event", "same_target_overlap_ready"]]
    quadrant.to_csv(table_dir / "f11_quadrant.csv", index=False)

    # F12: event-specific, quality-admissible and normalised ingress edges.
    # Ranking uses per-trace rates, never pooled raw counts from unequal windows.
    if not ingress_df.empty and not result_df.empty:
        admissible_keys = result_df.loc[result_df["quality_ok"].eq(1), ["event_id", "group"]].drop_duplicates()
        f12 = ingress_df.merge(admissible_keys, on=["event_id", "group"], how="inner")
        if not f12.empty:
            rank = (f12.groupby(["event_id", "edge"])["per_1000_trace"].max()
                    .groupby(level=0, group_keys=False).nlargest(int(cfg.path["top_ingress_edges"]))
                    .reset_index()[["event_id", "edge"]])
            f12 = f12.merge(rank.drop_duplicates(), on=["event_id", "edge"], how="inner")
    else:
        f12 = pd.DataFrame(columns=list(ingress_df.columns) if not ingress_df.empty else
                           ["event_id","group","phase","edge","count","n_trace","share","per_1000_trace"])
    f12.to_csv(table_dir / "f12_ingress.csv", index=False)
    summary = pd.DataFrame([{
        "n_group_event": len(result_df), "n_admissible": int(result_df["quality_ok"].sum()) if not result_df.empty else 0,
        "admissible_share": float(result_df["quality_ok"].mean()) if not result_df.empty else np.nan,
        "n_quadrant": len(quadrant),
        "n_same_target_overlap_ready": int(result_df.get("same_target_overlap_ready", pd.Series(dtype=int)).sum()) if not result_df.empty else 0,
        "n_asgeo_fdr_significant": int(result_df.get("asgeo_path_fdr_significant", pd.Series(dtype=int)).sum()) if not result_df.empty else 0,
        "path_claim_scope": "conditional_on_reached_target; target-specific JSD excludes source-common baseline edges",
    }])
    summary.to_csv(table_dir / "exp_e_summary.csv", index=False)
    return {"status": "ok" if len(quadrant) else "diagnostic_only_no_admissible_group",
            "outputs": [str(table_dir / x) for x in ["exp_e_path_results.csv", "f11_quadrant.csv", "f12_ingress.csv"]]}
