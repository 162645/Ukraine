from __future__ import annotations

import argparse
import json

from uresil.config import load_config
from uresil.label_robustness_stage import run


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--mode", default="real", choices=["real", "demo"])
    a = p.parse_args()
    cfg = load_config(run_id=a.run_id, mode=a.mode)
    print(json.dumps(run(cfg), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
