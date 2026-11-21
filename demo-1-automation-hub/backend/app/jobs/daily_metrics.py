"""Daily reporting job (run by Railway/Render cron or GitHub Actions).

    python -m app.jobs.daily_metrics                  # default source + lookback window
    python -m app.jobs.daily_metrics --source csv     # load the sample CSV instead
    python -m app.jobs.daily_metrics --days 60        # backfill
    python -m app.jobs.daily_metrics --simulate-failure

Exit code 1 on failure (the failure is also written to automation_log and alerted on Slack).
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config import get_settings
from app.context import build_context
from app.workflows.metrics_pipeline import run_daily_metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load ad performance into campaign_metrics (idempotent upsert).")
    parser.add_argument("--source", choices=["mock", "http", "csv"], default=None)
    parser.add_argument("--days", type=int, default=None, help="lookback window in days")
    parser.add_argument("--simulate-failure", action="store_true", help="prove the failure path (log + alert)")
    args = parser.parse_args(argv)

    ctx = build_context(get_settings())
    try:
        result = run_daily_metrics(ctx, source=args.source, days=args.days, run_source="cron", simulate_failure=args.simulate_failure)
    except Exception as exc:  # noqa: BLE001 - already logged + alerted by AutomationRun
        print(json.dumps({"status": "failure", "error": str(exc)}))
        return 1
    print(json.dumps(result, default=str, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
