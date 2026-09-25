#!/usr/bin/env python3
"""Rebuild own-traceroute intermediate-hop evidence from ClickHouse.

This is a read-only validation experiment.  It never modifies the frozen
manuscript master, labels, models, figures, or event definitions.  The actual
measured ``hop_path`` arrays in ClickHouse are authoritative; the historical
CSV files are used only to explain agreement or disagreement with the frozen
``own_traceroute_intermediate`` field.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import ipaddress
import json
import math
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


DATABASE = "active_measurement"
TABLE = "UKRAINE__quarter-traceroute_AWS_frankfurt_2024-06-22"
TABLE_SQL = f"`{TABLE}`"

# Deterministic IPv4 special-purpose exclusions.  The order gives each
# excluded address one stable audit reason.
EXCLUDED_NETWORKS = [
    ("this_network", ipaddress.ip_network("0.0.0.0/8")),
    ("private_10", ipaddress.ip_network("10.0.0.0/8")),
    ("shared_cgnat", ipaddress.ip_network("100.64.0.0/10")),
    ("loopback", ipaddress.ip_network("127.0.0.0/8")),
    ("link_local", ipaddress.ip_network("169.254.0.0/16")),
    ("private_172", ipaddress.ip_network("172.16.0.0/12")),
    ("ietf_protocol_assignments", ipaddress.ip_network("192.0.0.0/24")),
    ("documentation_192", ipaddress.ip_network("192.0.2.0/24")),
    ("deprecated_6to4_relay", ipaddress.ip_network("192.88.99.0/24")),
    ("private_192", ipaddress.ip_network("192.168.0.0/16")),
    ("benchmark", ipaddress.ip_network("198.18.0.0/15")),
    ("documentation_198", ipaddress.ip_network("198.51.100.0/24")),
    ("documentation_203", ipaddress.ip_network("203.0.113.0/24")),
    ("multicast", ipaddress.ip_network("224.0.0.0/4")),
    ("reserved", ipaddress.ip_network("240.0.0.0/4")),
]


@dataclass(frozen=True)
class Inputs:
    master: Path
    target_universe: Path
    legacy_dir: Path
    frozen_renderer: Path


def input_paths(root: Path) -> Inputs:
    return Inputs(
        master=root / "power_availability_infrastructure_final_validation_v2/data/ip_power_availability_master_v2.parquet",
        target_universe=root / "runs/paper_final_v2_episode_fix_20260910/data_derived/target_ip_universe.parquet",
        legacy_dir=root / "feasibility_imc2027_v2/data_processed/traceroute",
        frozen_renderer=root / "render_current_manuscript_figures_v3_fixed.py",
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "UNKNOWN"


def classify_ipv4(value: object) -> tuple[str | None, str]:
    """Return canonical IPv4 and a deterministic public/exclusion class."""
    try:
        ip = ipaddress.ip_address(str(value))
    except ValueError:
        return None, "invalid_ipv4"
    if not isinstance(ip, ipaddress.IPv4Address):
        return None, "not_ipv4"
    for reason, network in EXCLUDED_NETWORKS:
        if ip in network:
            return str(ip), reason
    return str(ip), "public"


def month_starts(start: str, end: str) -> list[pd.Timestamp]:
    values = pd.period_range(start=start, end=end, freq="M")
    return [p.start_time.tz_localize("UTC") for p in values]


def extraction_query(start: pd.Timestamp, end: pd.Timestamp) -> str:
    start_text = start.strftime("%Y-%m-%d %H:%M:%S")
    end_text = end.strftime("%Y-%m-%d %H:%M:%S")
    return f"""
SELECT
  hop.1 AS ip,
  min(measure_time) AS first_seen,
  max(measure_time) AS last_seen,
  count() AS observed_response_n,
  countIf(hop_position < path_length AND hop.1 != dst_ip) AS intermediate_observation_n,
  countIf(hop_position = path_length AND hop.1 != dst_ip) AS terminal_non_target_observation_n,
  countIf(hop.1 = dst_ip) AS target_address_observation_n,
  min(hop_position) AS hop_position_min,
  max(hop_position) AS hop_position_max
FROM
(
  SELECT measure_time, dst_ip, hop_path, length(hop_path) AS path_length
  FROM {TABLE_SQL}
  WHERE measure_time >= toDateTime64('{start_text}', 6, 'UTC')
    AND measure_time < toDateTime64('{end_text}', 6, 'UTC')
)
ARRAY JOIN hop_path AS hop, arrayEnumerate(hop_path) AS hop_position
WHERE hop.1 != '*'
  AND IPv4StringToNumOrNull(hop.1) IS NOT NULL
GROUP BY ip
HAVING intermediate_observation_n > 0
    OR terminal_non_target_observation_n > 0
ORDER BY ip
SETTINGS
  max_threads = 6,
  max_memory_usage = 6442450944,
  max_bytes_before_external_group_by = 1073741824
FORMAT CSVWithNames
""".strip() + "\n"


def clickhouse_query_to_file(
    url: str,
    user: str,
    password: str,
    query: str,
    destination: Path,
    timeout: int = 7200,
) -> None:
    endpoint = url.rstrip("/") + "/?" + urllib.parse.urlencode({"database": DATABASE})
    request = urllib.request.Request(endpoint, data=query.encode("utf-8"), method="POST")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    partial = destination.with_suffix(destination.suffix + ".partial")
    with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as f:
        shutil.copyfileobj(response, f, length=1024 * 1024)
    os.replace(partial, destination)


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, center - half), min(1.0, center + half)


def frozen_edges(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy()
    return np.unique(np.r_[0.0, np.histogram_bin_edges(values, bins="fd"), 1.0])


def descriptive_bins(master: pd.DataFrame, label: str, source: str, edges: np.ndarray) -> pd.DataFrame:
    q = master[["ip", "power_availability", label]].dropna().copy()
    rows: list[dict[str, object]] = []
    for index, (left, right) in enumerate(zip(edges[:-1], edges[1:]), start=1):
        in_bin = q["power_availability"].ge(left) & (
            q["power_availability"].le(right)
            if right == edges[-1]
            else q["power_availability"].lt(right)
        )
        z = q.loc[in_bin]
        if z.empty:
            continue
        n = len(z)
        k = int(pd.to_numeric(z[label], errors="coerce").fillna(0).astype(int).sum())
        low, high = wilson(k, n)
        rows.append({
            "label_source": source,
            "bin_index": index,
            "bin_left": float(left),
            "bin_right": float(right),
            "right_closed": bool(right == edges[-1]),
            "mean_power_availability": float(z["power_availability"].mean()),
            "ip_n": n,
            "positive_ip_n": k,
            "positive_prevalence": k / n,
            "wilson_95_low": low,
            "wilson_95_high": high,
        })
    return pd.DataFrame(rows)


def aggregate_monthly(files: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    filter_rows = []
    for path in files:
        d = pd.read_csv(path, low_memory=False)
        canonical = [classify_ipv4(v) for v in d["ip"]]
        d["canonical_ip"] = [x[0] for x in canonical]
        d["address_class"] = [x[1] for x in canonical]
        filter_rows.extend({"month_file": path.name, "address_class": k, "unique_ip_n": int(v)}
                           for k, v in d.groupby("address_class").size().items())
        d = d[d["canonical_ip"].notna()].copy()
        d["month_file"] = path.name
        frames.append(d)
    all_months = pd.concat(frames, ignore_index=True)
    numeric_sum = [
        "observed_response_n", "intermediate_observation_n",
        "terminal_non_target_observation_n", "target_address_observation_n",
    ]
    for col in numeric_sum + ["hop_position_min", "hop_position_max"]:
        all_months[col] = pd.to_numeric(all_months[col], errors="coerce").fillna(0)
    ledger = all_months.groupby("canonical_ip", as_index=False).agg(
        first_seen=("first_seen", "min"),
        last_seen=("last_seen", "max"),
        observed_response_n=("observed_response_n", "sum"),
        intermediate_observation_n=("intermediate_observation_n", "sum"),
        terminal_non_target_observation_n=("terminal_non_target_observation_n", "sum"),
        target_address_observation_n=("target_address_observation_n", "sum"),
        hop_position_min=("hop_position_min", "min"),
        hop_position_max=("hop_position_max", "max"),
        observed_month_n=("month_file", "nunique"),
        address_class=("address_class", "first"),
    ).rename(columns={"canonical_ip": "ip"})
    # The canonical IPv4 classifier is deterministic, so variants cannot carry
    # conflicting classes.  Keep only actual, public, pre-terminal observations.
    filter_qa = pd.DataFrame(filter_rows)
    return ledger, filter_qa


def difference_reason(
    row: pd.Series,
    legacy_union: set[str],
) -> str:
    frozen = int(row["frozen_own_traceroute_intermediate"])
    rebuilt = int(row["rebuilt_own_traceroute_intermediate"])
    ip = str(row["ip"])
    terminal_n = int(row.get("terminal_non_target_observation_n", 0) or 0)
    intermediate_n = int(row.get("intermediate_observation_n", 0) or 0)
    if frozen == 1 and rebuilt == 0:
        if terminal_n > 0 and intermediate_n == 0:
            return "observed_only_as_terminal_endpoint_under_strict_rule"
        if ip in legacy_union:
            return "legacy_csv_positive_not_rebuilt_from_current_clickhouse"
        return "frozen_positive_without_legacy_union_member"
    if frozen == 0 and rebuilt == 1:
        if ip not in legacy_union:
            return "clickhouse_intermediate_absent_from_legacy_csv_union"
        return "legacy_union_member_but_frozen_label_zero"
    return "no_difference"


def write_input_manifest(out: Path, inputs: Inputs, legacy_files: list[Path]) -> None:
    paths = [inputs.master, inputs.target_universe, inputs.frozen_renderer, *legacy_files]
    rows = [{
        "input_name": p.name,
        "path": str(p),
        "bytes": p.stat().st_size,
        "sha256": sha256(p),
    } for p in paths]
    pd.DataFrame(rows).to_csv(out / "INPUT_FILE_MANIFEST.csv", index=False)


def run(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    out = args.output.resolve()
    work = args.work_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    inputs = input_paths(root)
    required = [inputs.master, inputs.target_universe, inputs.frozen_renderer]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing frozen inputs:\n" + "\n".join(missing))
    legacy_files = sorted(inputs.legacy_dir.glob("intermediate_ipv4_*.csv"))
    if not legacy_files:
        raise FileNotFoundError(f"No legacy intermediate-hop CSVs in {inputs.legacy_dir}")
    write_input_manifest(out, inputs, legacy_files)

    password = os.environ.get(args.clickhouse_password_env, "")
    if not password:
        raise RuntimeError(f"Missing environment variable {args.clickhouse_password_env}")

    monthly_files: list[Path] = []
    export_rows = []
    starts = month_starts(args.start_month, args.end_month)
    for start in starts:
        end = start + pd.offsets.MonthBegin(1)
        month = start.strftime("%Y%m")
        query = extraction_query(start, end)
        destination = work / f"observed_hops_{month}.csv"
        if not destination.exists() or destination.stat().st_size == 0:
            clickhouse_query_to_file(
                args.clickhouse_url, args.clickhouse_user, password,
                query, destination, args.clickhouse_timeout,
            )
        with destination.open("r", encoding="utf-8", newline="") as f:
            row_n = max(0, sum(1 for _ in f) - 1)
        monthly_files.append(destination)
        export_rows.append({
            "month": month,
            "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
            "file": str(destination),
            "bytes": destination.stat().st_size,
            "row_n": row_n,
            "sha256": sha256(destination),
        })
    export_manifest = pd.DataFrame(export_rows)
    export_manifest.to_csv(out / "CLICKHOUSE_MONTHLY_EXPORT_MANIFEST.csv", index=False)
    source_digest = hashlib.sha256(
        "\n".join(f"{r['month']}:{r['sha256']}" for r in export_rows).encode()
    ).hexdigest()

    legacy_by_month = {
        path.stem.rsplit("_", 1)[-1]: path
        for path in legacy_files
    }
    monthly_identity_rows = []
    monthly_difference_rows = []
    for month, rebuilt_path in zip((r["month"] for r in export_rows), monthly_files):
        rebuilt_month_set = set(pd.read_csv(rebuilt_path, usecols=["ip"])["ip"].dropna().astype(str))
        legacy_path = legacy_by_month.get(month)
        legacy_month_set = (
            set(pd.read_csv(legacy_path, usecols=["ip"])["ip"].dropna().astype(str))
            if legacy_path is not None else set()
        )
        legacy_only_month = legacy_month_set - rebuilt_month_set
        rebuilt_only_month = rebuilt_month_set - legacy_month_set
        monthly_identity_rows.append({
            "month": month,
            "legacy_ip_n": len(legacy_month_set),
            "rebuilt_clickhouse_ip_n": len(rebuilt_month_set),
            "intersection_ip_n": len(legacy_month_set & rebuilt_month_set),
            "legacy_only_ip_n": len(legacy_only_month),
            "rebuilt_only_ip_n": len(rebuilt_only_month),
            "status": "PASS" if not legacy_only_month and not rebuilt_only_month else "DIFFERENT",
        })
        monthly_difference_rows.extend(
            {"month": month, "ip": ip, "set_side": "legacy_only"}
            for ip in sorted(legacy_only_month)
        )
        monthly_difference_rows.extend(
            {"month": month, "ip": ip, "set_side": "rebuilt_clickhouse_only"}
            for ip in sorted(rebuilt_only_month)
        )
    monthly_identity = pd.DataFrame(monthly_identity_rows)
    monthly_identity.to_csv(out / "LEGACY_MONTHLY_SET_IDENTITY_QA.csv", index=False)
    pd.DataFrame(
        monthly_difference_rows,
        columns=["month", "ip", "set_side"],
    ).to_csv(out / "LEGACY_MONTHLY_SET_DIFFERENCES.csv", index=False)

    ledger, filter_qa = aggregate_monthly(monthly_files)
    # Recompute the class after monthly aggregation to make the global QA easy
    # to audit independently of monthly row multiplicity.
    classes = [classify_ipv4(v)[1] for v in ledger["ip"]]
    ledger["address_class"] = classes
    global_filter = ledger.groupby("address_class", as_index=False).agg(
        unique_observed_ip_n=("ip", "nunique"),
        total_observed_response_n=("observed_response_n", "sum"),
        intermediate_observation_n=("intermediate_observation_n", "sum"),
        terminal_non_target_observation_n=("terminal_non_target_observation_n", "sum"),
        target_address_observation_n=("target_address_observation_n", "sum"),
    )
    global_filter.to_csv(out / "IP_ADDRESS_FILTER_QA.csv", index=False)
    filter_qa.to_csv(out / "IP_ADDRESS_FILTER_BY_MONTH_QA.csv", index=False)

    public = ledger[
        ledger["address_class"].eq("public")
        & ledger["intermediate_observation_n"].gt(0)
    ].copy()

    target = pd.read_parquet(
        inputs.target_universe,
        columns=["dst_ip", "target_country", "valid_target_admin1"],
    )
    ukraine_registry = set(target.loc[
        target["target_country"].astype(str).eq("Ukraine")
        & pd.to_numeric(target["valid_target_admin1"], errors="coerce").fillna(0).eq(1),
        "dst_ip",
    ].astype(str))

    master = pd.read_parquet(inputs.master, columns=[
        "ip", "prefix24", "oblast", "power_availability", "normal_availability",
        "itdk_202408_T", "own_traceroute_intermediate",
    ])
    master["ip"] = master["ip"].astype(str)
    master_ip = set(master["ip"])
    caida = set(master.loc[pd.to_numeric(master["itdk_202408_T"], errors="coerce").fillna(0).eq(1), "ip"])
    frozen_own = set(master.loc[pd.to_numeric(master["own_traceroute_intermediate"], errors="coerce").fillna(0).eq(1), "ip"])

    legacy_union: set[str] = set()
    for path in legacy_files:
        legacy_union.update(pd.read_csv(path, usecols=["ip"])["ip"].dropna().astype(str))

    rebuilt_all = set(public["ip"])
    rebuilt_ukraine = rebuilt_all & ukraine_registry
    rebuilt_main = rebuilt_all & master_ip

    public["in_frozen_ukraine_target_registry"] = public["ip"].isin(ukraine_registry).astype(int)
    public["in_main_analysis_sample"] = public["ip"].isin(master_ip).astype(int)
    public["caida_itdk_202408_transit"] = public["ip"].isin(caida).astype(int)
    public["frozen_own_traceroute_intermediate"] = public["ip"].isin(frozen_own).astype(int)
    public.sort_values("ip").to_csv(out / "OWN_TRACEROUTE_PUBLIC_INTERMEDIATE_IPS.csv", index=False)
    public[public["ip"].isin(rebuilt_ukraine)].sort_values("ip").to_csv(
        out / "OWN_TRACEROUTE_UKRAINE_MAPPED_IPS.csv", index=False,
    )

    main = master.merge(
        public[[
            "ip", "first_seen", "last_seen", "intermediate_observation_n",
            "terminal_non_target_observation_n", "target_address_observation_n",
            "hop_position_min", "hop_position_max",
        ]],
        on="ip", how="left",
    )
    count_cols = [
        "intermediate_observation_n", "terminal_non_target_observation_n",
        "target_address_observation_n",
    ]
    for col in count_cols:
        main[col] = pd.to_numeric(main[col], errors="coerce").fillna(0).astype("int64")
    main["frozen_own_traceroute_intermediate"] = pd.to_numeric(
        main["own_traceroute_intermediate"], errors="coerce"
    ).fillna(0).astype(int)
    main["rebuilt_own_traceroute_intermediate"] = main["ip"].isin(rebuilt_main).astype(int)
    main["caida_itdk_202408_transit"] = pd.to_numeric(
        main["itdk_202408_T"], errors="coerce"
    ).fillna(0).astype(int)
    main.loc[main["rebuilt_own_traceroute_intermediate"].eq(1)].sort_values("ip").to_csv(
        out / "OWN_TRACEROUTE_MAIN_SAMPLE_IPS.csv", index=False,
    )

    different = main[
        main["frozen_own_traceroute_intermediate"].ne(main["rebuilt_own_traceroute_intermediate"])
    ].copy()
    different["difference_reason"] = different.apply(
        difference_reason, axis=1, legacy_union=legacy_union,
    )
    different.sort_values(["difference_reason", "ip"]).to_csv(
        out / "OWN_TRACEROUTE_LABEL_DIFFERENCES.csv", index=False,
    )
    reason_counts = different.groupby("difference_reason", as_index=False).agg(
        ip_n=("ip", "nunique")
    ) if len(different) else pd.DataFrame(columns=["difference_reason", "ip_n"])
    reason_counts.to_csv(out / "OWN_TRACEROUTE_DIFFERENCE_REASON_COUNTS.csv", index=False)

    both = rebuilt_main & caida
    own_only = rebuilt_main - caida
    caida_only = caida - rebuilt_main
    union = rebuilt_main | caida
    neither = master_ip - union
    overlap = pd.DataFrame([{
        "main_sample_ip_n": len(master_ip),
        "caida_positive_ip_n": len(caida),
        "rebuilt_own_positive_ip_n": len(rebuilt_main),
        "both_positive_ip_n": len(both),
        "caida_only_ip_n": len(caida_only),
        "rebuilt_own_only_ip_n": len(own_only),
        "neither_positive_ip_n": len(neither),
        "union_positive_ip_n": len(union),
        "p_own_given_caida": len(both) / len(caida) if caida else math.nan,
        "p_caida_given_own": len(both) / len(rebuilt_main) if rebuilt_main else math.nan,
    }])
    overlap.to_csv(out / "OWN_TRACEROUTE_CAIDA_OVERLAP.csv", index=False)

    frozen_only = frozen_own - rebuilt_main
    rebuilt_only = rebuilt_main - frozen_own
    identity = pd.DataFrame([{
        "check": "rebuilt_clickhouse_vs_frozen_own_traceroute_intermediate",
        "frozen_positive_ip_n": len(frozen_own),
        "rebuilt_positive_ip_n": len(rebuilt_main),
        "intersection_ip_n": len(frozen_own & rebuilt_main),
        "frozen_only_ip_n": len(frozen_only),
        "rebuilt_only_ip_n": len(rebuilt_only),
        "status": "PASS" if not frozen_only and not rebuilt_only else "FAIL_NO_AUTOMATIC_MUTATION",
    }])
    identity.to_csv(out / "OWN_TRACEROUTE_LABEL_IDENTITY_QA.csv", index=False)

    edges = frozen_edges(main["power_availability"])
    frozen_bins = descriptive_bins(
        main, "frozen_own_traceroute_intermediate", "frozen_master", edges,
    )
    rebuilt_bins = descriptive_bins(
        main, "rebuilt_own_traceroute_intermediate", "rebuilt_clickhouse", edges,
    )
    bins = pd.concat([frozen_bins, rebuilt_bins], ignore_index=True)
    bins.to_csv(out / "OWN_TRACEROUTE_S2_DESCRIPTIVE_BINS.csv", index=False)

    def endpoint_delta(d: pd.DataFrame) -> float:
        ordered = d.sort_values("bin_index")
        return float(ordered.iloc[-1]["positive_prevalence"] - ordered.iloc[0]["positive_prevalence"])

    frozen_delta = endpoint_delta(frozen_bins)
    rebuilt_delta = endpoint_delta(rebuilt_bins)
    direction = pd.DataFrame([{
        "comparison": "last_existing_fd_bin_minus_first_existing_fd_bin",
        "frozen_endpoint_prevalence_difference": frozen_delta,
        "rebuilt_endpoint_prevalence_difference": rebuilt_delta,
        "frozen_direction": "higher_at_high_availability" if frozen_delta > 0 else ("lower_at_high_availability" if frozen_delta < 0 else "equal"),
        "rebuilt_direction": "higher_at_high_availability" if rebuilt_delta > 0 else ("lower_at_high_availability" if rebuilt_delta < 0 else "equal"),
        "same_direction": bool(np.sign(frozen_delta) == np.sign(rebuilt_delta)),
        "interpretation": "descriptive_only_no_model_no_new_threshold",
    }])
    direction.to_csv(out / "OWN_TRACEROUTE_S2_DIRECTION_QA.csv", index=False)

    summary = {
        "status": "PASS" if identity.iloc[0]["status"] == "PASS" else "PASS_WITH_FROZEN_LABEL_DIFFERENCE",
        "implementation_git_commit": git_head(Path(__file__).resolve().parents[1]),
        "scientific_input_git_commit": git_head(root),
        "source_database": DATABASE,
        "source_table": TABLE,
        "clickhouse_monthly_export_content_sha256": source_digest,
        "measurement_months": [s.strftime("%Y-%m") for s in starts],
        "all_unique_public_intermediate_ip_n": len(rebuilt_all),
        "ukraine_mapped_unique_intermediate_ip_n": len(rebuilt_ukraine),
        "main_sample_unique_intermediate_ip_n": len(rebuilt_main),
        "main_sample_coverage": len(rebuilt_main) / len(master_ip),
        "caida_positive_ip_n": len(caida),
        "both_positive_ip_n": len(both),
        "caida_only_ip_n": len(caida_only),
        "own_only_ip_n": len(own_only),
        "union_positive_ip_n": len(union),
        "p_own_given_caida": len(both) / len(caida) if caida else None,
        "p_caida_given_own": len(both) / len(rebuilt_main) if rebuilt_main else None,
        "frozen_own_positive_ip_n": len(frozen_own),
        "frozen_only_ip_n": len(frozen_only),
        "rebuilt_only_ip_n": len(rebuilt_only),
        "label_identity_status": identity.iloc[0]["status"],
        "legacy_monthly_sets_all_exact": bool(monthly_identity["status"].eq("PASS").all()),
        "legacy_monthly_total_difference_rows": int(
            monthly_identity["legacy_only_ip_n"].sum()
            + monthly_identity["rebuilt_only_ip_n"].sum()
        ),
        "s2_same_endpoint_direction": bool(direction.iloc[0]["same_direction"]),
        "frozen_s2_endpoint_prevalence_difference": frozen_delta,
        "rebuilt_s2_endpoint_prevalence_difference": rebuilt_delta,
        "frozen_master_modified": False,
        "model_fitted": False,
        "figure_generated": False,
    }
    (out / "OWN_TRACEROUTE_REBUILD_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    relation_text = (
        "The fixed-bin endpoint direction is retained."
        if summary["s2_same_endpoint_direction"]
        else "The fixed-bin endpoint direction is not retained; inspect the complete bin table."
    )
    identity_text = (
        "The direct ClickHouse set exactly matches the frozen field."
        if identity.iloc[0]["status"] == "PASS"
        else "The direct ClickHouse set differs from the frozen field. The frozen master was not modified; all differing IPs and reasons are listed."
    )
    report = f"""# Own-traceroute intermediate-hop evidence rebuild

## Scope and non-mutation rule

This experiment reads the authoritative ClickHouse table `{DATABASE}.{TABLE}` and the frozen manuscript master. It does not modify the frozen master, fit a model, select a threshold, or generate/replace a figure.

An observed intermediate-hop IP is a syntactically valid public IPv4 address returned in `hop_path`, strictly before the final recorded path element, and unequal to `dst_ip`. `*` is ignored. Missing hops are not imputed and adjacency across missing hops is never inferred. Ukraine mapping means membership in the frozen Ukraine target registry; it is not a new geolocation claim.

## Three manuscript questions

1. **How many network-side IPs does own traceroute add inside the main sample?** {len(rebuilt_main):,} of {len(master_ip):,} frozen main-sample IPs ({len(rebuilt_main) / len(master_ip):.6%}) were directly observed as public pre-terminal traceroute hops.
2. **How many are not covered by CAIDA 2024-08 transit evidence?** {len(own_only):,} are own-traceroute-only; {len(both):,} are observed by both; {len(caida_only):,} are CAIDA-only; the union is {len(union):,} IPs. `P(own | CAIDA)` is {len(both) / len(caida):.6%}; `P(CAIDA | own)` is {len(both) / len(rebuilt_main):.6%}.
3. **Does the existing descriptive S2 relationship remain?** {relation_text} The complete result uses the exact frozen Freedman-Diaconis availability bins and Wilson intervals in `OWN_TRACEROUTE_S2_DESCRIPTIVE_BINS.csv`; no new model or threshold is introduced.

## Scale

- All unique public observed intermediate-hop IPs: **{len(rebuilt_all):,}**
- Ukraine-mapped under the frozen target registry: **{len(rebuilt_ukraine):,}**
- Intersecting the frozen 1,170,227-IP main sample: **{len(rebuilt_main):,}**

## Frozen-label identity

{identity_text}

- Frozen positives: {len(frozen_own):,}
- Rebuilt positives: {len(rebuilt_main):,}
- Frozen-only: {len(frozen_only):,}
- Rebuilt-only: {len(rebuilt_only):,}

The old monthly CSV sets are compared independently in `LEGACY_MONTHLY_SET_IDENTITY_QA.csv`; every differing address is retained in `LEGACY_MONTHLY_SET_DIFFERENCES.csv`.

## Interpretation boundary

These are IPs actually observed in intermediate positions on own traceroute paths, not infrastructure ground truth. CAIDA remains the external primary topology source; own traceroute is a measurement-period- and vantage-aligned secondary source that is not fully independent of the active-measurement environment.
"""
    (out / "OWN_TRACEROUTE_REBUILD_REPORT.md").write_text(report, encoding="utf-8")

    query_template = extraction_query(
        pd.Timestamp("2000-01-01", tz="UTC"),
        pd.Timestamp("2000-02-01", tz="UTC"),
    ).replace("2000-01-01 00:00:00", "{MONTH_START_UTC}").replace(
        "2000-02-01 00:00:00", "{NEXT_MONTH_START_UTC}",
    )
    (out / "CLICKHOUSE_EXTRACTION_QUERY_TEMPLATE.sql").write_text(query_template, encoding="utf-8")

    output_rows = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "OUTPUT_FILE_MANIFEST.csv"):
        output_rows.append({
            "file": path.relative_to(out).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    pd.DataFrame(output_rows).to_csv(out / "OUTPUT_FILE_MANIFEST.csv", index=False)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--clickhouse-url", required=True)
    parser.add_argument("--clickhouse-user", required=True)
    parser.add_argument("--clickhouse-password-env", default="CLICKHOUSE_PASSWORD")
    parser.add_argument("--clickhouse-timeout", type=int, default=7200)
    parser.add_argument("--start-month", default="2024-06")
    parser.add_argument("--end-month", default="2025-01")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
