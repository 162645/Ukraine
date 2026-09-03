#!/usr/bin/env python3
"""Run the no-ClickHouse first stage of the outage-label closure audit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uresil.label_precision import (audit_timestamp_pairs, package_root,
                                    precision_feasibility, relabel_cached_national)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="paper_v24_real_01")
    ap.add_argument("--output", default="analysis_outputs/v25_label_precision_audit")
    args = ap.parse_args()
    pack = package_root(ROOT)
    norm = pack / "normalized"
    run = ROOT / "runs" / args.run_id
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)

    national = pd.read_csv(norm / "national_dispatch_segments_official.csv")
    updates = pd.read_csv(norm / "oblast_execution_updates_official.csv")
    queues = pd.read_csv(norm / "khmelnytskyi_published_queue_schedule.csv")
    targets = pd.read_parquet(run / "data_derived" / "target_ip_universe.parquet",
                              columns=["target_admin1", "regional_eligible"])
    obs = pd.read_csv(run / "results" / "tables" / "exp_a_validation_long.csv")

    audits = []
    for name, table in (("national", national), ("oblast_updates", updates),
                        ("queue_schedule", queues)):
        a = audit_timestamp_pairs(table)
        a.insert(0, "source_table", name)
        audits.append(a)
    time_audit = pd.concat(audits, ignore_index=True)
    time_audit.to_csv(out / "timezone_pair_audit.csv", index=False)

    feasibility = precision_feasibility(targets, updates, queues)
    feasibility.to_csv(out / "label_precision_feasibility.csv", index=False)
    relabeled = relabel_cached_national(obs, national)
    relabeled.to_csv(out / "validation_long_national_corrected.csv", index=False)

    metrics = []
    for label_col in ("label_original", "label_refined"):
        z = relabeled[relabeled["refined_supported"].eq(1)].dropna(subset=[label_col, "score"])
        for event_id, event in z.groupby("event_id"):
            values = {}
            for method, group in event.groupby("method"):
                values[method] = (average_precision_score(group[label_col], group["score"])
                                  if group[label_col].nunique() > 1 else float("nan"))
            metrics.append({"label_version": label_col, "event_id": event_id,
                            "auprc_B1": values.get("B1"), "auprc_B2": values.get("B2"),
                            "delta_b2_vs_b1": values.get("B2", float("nan")) - values.get("B1", float("nan")),
                            "n_cycle": event.cycle_id.nunique()})
    pd.DataFrame(metrics).to_csv(out / "national_corrected_event_metrics.csv", index=False)

    q0 = relabeled[relabeled["label_refined"].eq(0) & relabeled["method"].isin(["B1", "B2"])]
    drift = (q0.groupby(["event_id", "method"], as_index=False)
             .agg(mean_q0_deficit=("score", "mean"), median_q0_deficit=("score", "median"),
                  n_cycle=("cycle_id", "nunique"), n_admin1=("target_admin1", "nunique")))
    drift.to_csv(out / "q0_false_positive_drift.csv", index=False)

    summary = {
        "run_id": args.run_id,
        "timezone_conversion_pairs": int(len(time_audit)),
        "timezone_conversion_mismatch_rows": int(time_audit.timestamp_pair_valid.eq(0).sum()),
        "timezone_validation_scope": (
            "internal conversion consistency only: package local civil-time columns were "
            "converted with Europe/Kyiv IANA rules and compared with package UTC columns; "
            "this does not independently authenticate the source event time"
        ),
        "cached_validation_rows": int(len(obs)),
        "national_relabel_changed_rows": int((relabeled.label_original != relabeled.label_refined).fillna(False).sum()),
        "clickhouse_required_for": [
            "per-calibration-event IP sensitivity scores and B2 membership overlap",
            "new IP-level responder counts for cycles absent from the frozen validation cache",
            "new city/queue analysis only if a more precise geolocation key exists in an upstream table",
        ],
        "clickhouse_not_required_for": [
            "timezone and provenance audit", "national final-label correction on cached cycles",
            "Admin1 evidence coverage audit", "existing B1/B2 q0 drift diagnosis",
        ],
    }
    (out / "audit_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 1 if summary["timezone_conversion_mismatch_rows"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
