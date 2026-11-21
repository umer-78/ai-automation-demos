"""Seed (or reset) the demo database and optionally write the sample CSV.

    python -m scripts.seed            # seed only if empty
    python -m scripts.seed --reset    # wipe demo tables and reseed
    python -m scripts.seed --csv      # also write sample_data/ad_performance_sample.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import BACKEND_DIR, get_settings
from app.context import build_context
from app.seed import seed_demo, write_sample_csv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete existing demo rows first")
    parser.add_argument("--csv", action="store_true", help="write the sample CSV for METRICS_SOURCE=csv")
    args = parser.parse_args()
    ctx = build_context(get_settings())
    result = seed_demo(ctx, reset=args.reset)
    if args.csv:
        path = BACKEND_DIR / "sample_data" / "ad_performance_sample.csv"
        result["csv_rows"] = write_sample_csv(ctx, Path(path))
        result["csv_path"] = str(path)
    print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()
