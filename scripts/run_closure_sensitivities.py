#!/usr/bin/env python3
"""Run only the frozen v2.4 closure checks on an existing core run."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from uresil.closure_sensitivity import run
from uresil.config import load_config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config, run_id=args.run_id, mode="real")
    result = run(cfg)
    print(result)
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
