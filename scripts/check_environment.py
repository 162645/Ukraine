#!/usr/bin/env python3
"""Fail fast when the scientific Python environment is incomplete."""
from __future__ import annotations

import importlib
import platform
import sys

PACKAGES = [
    ("numpy", "numpy"),
    ("pandas", "pandas"),
    ("scipy", "scipy"),
    ("sklearn", "scikit-learn"),
    ("statsmodels", "statsmodels"),
    ("pyarrow", "pyarrow"),
    ("matplotlib", "matplotlib"),
    ("clickhouse_connect", "clickhouse-connect"),
    ("clickhouse_driver", "clickhouse-driver"),
    ("yaml", "PyYAML"),
]


def main() -> int:
    print(f"Python {platform.python_version()} ({sys.executable})")
    failures: list[str] = []
    for module, label in PACKAGES:
        try:
            obj = importlib.import_module(module)
            version = getattr(obj, "__version__", "installed")
            print(f"PASS {label}: {version}")
        except Exception as exc:  # pragma: no cover - operational utility
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
            print(f"FAIL {label}: {exc}")
    if failures:
        print("\nMissing or broken dependencies:")
        for item in failures:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
