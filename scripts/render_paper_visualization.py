#!/usr/bin/env python3
"""Standalone visualization-only entry point; never calls run_all or ClickHouse."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from uresil.paper_figures_current import main

if __name__ == "__main__":
    main()
