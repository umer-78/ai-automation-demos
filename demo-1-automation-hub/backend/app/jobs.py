"""The scheduled daily reporting job (spec Module B, step 1).

Runs from GitHub Actions every day against the production database:

    python -m app.jobs daily --source api --api-url https://<your-app>.onrender.com/api/mock/ad-platform/performance
    python -m app.jobs daily --source csv --csv data/ad_performance_sample.csv
    python -m app.jobs daily                      # built-in mock generator, no network
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from . import mockdata, reporting
from .config import get_settings
from .db import make_engine, metadata, tx
from .onboarding import Deps, alert_failure


def fetch_from_api(url: str, today: date, days: int) -> list[dict]:
    out: list[dict] = []
    with httpx.Client(timeout=httpx.Timeout(90.0, connect=60.0)) as client:  # a sleeping free-tier host can take ~1 min
        for back in range(days - 1, -1, -1):
            day = today - timedelta(days=back)
            for attempt in range(3):
                try:
                    r = client.get(url, params={"date": day.isoformat()})
                    r.raise_for_status()
                    break
                except httpx.HTTPError:
                    if attempt == 2:
                        raise
                    time.sleep(5 * (attempt + 1))
            for row in r.json()["rows"]:
                out.append({**row, "date": date.fromisoformat(row["date"])})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job", choices=["daily"])
    ap.add_argument("--source", choices=["builtin", "api", "csv"], default="builtin")
    ap.add_argument("--api-url", default="")
    ap.add_argument("--csv", default="")
    args = ap.parse_args(argv)

    settings = get_settings()
    engine = make_engine(settings.database_url)
    metadata.create_all(engine)
    today = date.today()
    try:
        if args.source == "api":
            if not args.api_url:
                ap.error("--api-url is required with --source api")
            rows, label = fetch_from_api(args.api_url, today, reporting.RESTATE_DAYS), f"mock ad API ({args.api_url})"
        elif args.source == "csv":
            rows, label = mockdata.read_csv(Path(args.csv)), f"CSV ({args.csv})"
        else:
            rows, label = None, "mock ad API (built in)"
        with tx(engine) as conn:
            result = reporting.run_daily_job(conn, today, rows, f"{label}, scheduled")
        print(f"daily job ok: {result}")
        return 0
    except Exception as exc:  # noqa: BLE001 - every failure is logged and alerted
        slack = alert_failure(engine, Deps.build(settings), "reporting", f"{exc.__class__.__name__}: {exc}"[:300],
                              f"scheduled daily job, source={args.source}")
        print(f"daily job FAILED: {exc} (slack: {slack['detail']})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
