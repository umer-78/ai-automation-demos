"""Create the schema and load the demo state: 5 fake clients, 60 days x 3 channels of metrics.

    python -m app.seed               # seed the database in DATABASE_URL (default: local SQLite)
    python -m app.seed --csv         # also rewrite data/ad_performance_sample.csv
"""
from __future__ import annotations

import argparse
from datetime import date

from sqlalchemy.engine import Engine

from . import mockdata
from .config import BACKEND_DIR, get_settings
from .db import ALL_TABLES, clients, jdump, log_event, make_engine, metadata, now_utc, tx
from .reporting import upsert_metrics

SAMPLE_CSV = BACKEND_DIR / "data" / "ad_performance_sample.csv"


def reset(engine: Engine, today: date | None = None) -> dict:
    today = today or date.today()
    metadata.create_all(engine)
    ids = [c["id"] for c in mockdata.SEED_CLIENTS]
    rows = mockdata.window_rows(today, 60, ids)
    with tx(engine) as conn:
        for t in ALL_TABLES:  # children first
            conn.execute(t.delete())
        for c in mockdata.SEED_CLIENTS:
            conn.execute(clients.insert().values(**{**c, "services": jdump(c["services"])}, status="Active",
                                                 created_at=now_utc()))
        n = upsert_metrics(conn, rows)
        log_event(conn, "seed", "success", f"Demo reset: {len(ids)} clients, {n} metric rows ending {today.isoformat()}")
    return {"clients": len(ids), "metric_rows": n, "today": today.isoformat()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", action="store_true", help="also write the sample CSV export")
    args = ap.parse_args()
    settings = get_settings()
    engine = make_engine(settings.database_url)
    result = reset(engine)
    print(f"seeded {settings.database_kind}: {result}")
    if args.csv:
        mockdata.write_csv(SAMPLE_CSV, mockdata.window_rows(date.today(), 60, [c["id"] for c in mockdata.SEED_CLIENTS]))
        print(f"wrote {SAMPLE_CSV}")


if __name__ == "__main__":
    main()
