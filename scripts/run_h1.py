from __future__ import annotations

import argparse
import json

from uresil.config import load_config
from uresil.h1_endpoint_heterogeneity import run


def main() -> None:
    p = argparse.ArgumentParser(description="Run only frozen-label H1 endpoint heterogeneity")
    p.add_argument("--run-id", required=True)
    p.add_argument("--mode", choices=["real", "demo"], default="real")
    a = p.parse_args()
    if a.mode != "real":
        raise SystemExit("H1 is a real-data stage; demo mode is not accepted")
    print(json.dumps(run(load_config(run_id=a.run_id, mode=a.mode)), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
