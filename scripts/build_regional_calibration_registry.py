#!/usr/bin/env python3
"""Build the cache-first regional calibration registry and estimability gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uresil.label_precision import package_root
from uresil.regional_calibration import (apply_conflict_masks, build_regional_event_registry,
                                         regional_capacity)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="paper_v24_real_01")
    ap.add_argument("--output", default="analysis_outputs/v25_regional_calibration")
    args = ap.parse_args()
    norm = package_root(ROOT) / "normalized"
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    updates = pd.read_csv(norm / "oblast_execution_updates_official.csv")
    queues = pd.read_csv(norm / "khmelnytskyi_published_queue_schedule.csv")
    national = pd.read_csv(norm / "national_dispatch_segments_official.csv")
    conflicts = pd.read_csv(norm / "published_schedule_vs_final_dispatch_conflicts.csv")
    targets = pd.read_parquet(ROOT / "runs" / args.run_id / "data_derived" /
                              "target_ip_universe.parquet",
                              columns=["dst_ip", "target_admin1", "regional_eligible"])
    queues = apply_conflict_masks(queues, conflicts, national)
    queues.to_csv(out / "queue_schedule_dispatch_intersection.csv", index=False)
    registry = build_regional_event_registry(updates, queues)
    capacity = regional_capacity(registry, targets)
    registry.to_csv(out / "regional_exposure_registry.csv", index=False)
    capacity.to_csv(out / "regional_calibration_capacity.csv", index=False)
    summary = {
        "mapped_oblast_n": int(capacity.mapped_ip_n.gt(0).sum()),
        "exploratory_repeated_event_ready_oblast_n": int(capacity.exploratory_region_calibration_ready.sum()),
        "confirmatory_loo_ready_oblast_n": int(capacity.confirmatory_loo_ready.sum()),
        "confirmatory_rule": ">=3 independent region-usable official schedule dates + >=1 held-out date; execution evidence tier is reported separately",
        "next_action": ("query ClickHouse once for the cycle/IP cells in the frozen regional registry, "
                        "cache per-event IP scores as Parquet, then run all selection/LOO locally"),
    }
    (out / "regional_calibration_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
