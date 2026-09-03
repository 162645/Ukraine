#!/usr/bin/env python3
"""Audit whether B2 event-level membership can be recovered without a core rerun."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--output", default="")
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    patterns = ["**/ip_sensor_scores_by_training_event/*.parquet",
                "**/exp_a_training_event_ip_scores*.parquet",
                "**/exp_a_training_event_ip_scores*.csv"]
    hits = sorted({str(path) for pattern in patterns for path in run_dir.glob(pattern)})
    aggregate = (list(run_dir.glob("**/ip_sensor_scores_parts/*.parquet")) +
                 list(run_dir.glob("**/ip_sensor_selected_parts/*.parquet")))
    status = ("estimable_from_saved_per_event_artifacts" if hits else
              "not_estimable_without_calibration_only_reconstruction")
    report = {
        "status": status,
        "per_event_artifacts": hits,
        "aggregated_score_parts_n": len(aggregate),
        "scientific_action": (
            "Estimate the preregistered cross-event IP membership stability."
            if hits else
            "Report as a frozen-run limitation. Do not reconstruct it from the merged "
            "score or attack outcomes; a future version may rerun calibration only."),
    }
    out = Path(args.output) if args.output else run_dir / "b2_event_stability_estimability.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
