"""Seed the mock CRM from data/crm_accounts.csv. Dates are placed relative to the day it runs.

Run: python -m app.seed
"""
from __future__ import annotations

import csv
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine

from .config import DATA_DIR, get_settings
from .db import ALL_TABLES, accounts, log_activity, make_engine, meta, metadata, tx

CSV_PATH = DATA_DIR / "crm_accounts.csv"


def load_accounts(today: date) -> list[dict]:
    rows = []
    with CSV_PATH.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["id"], "company": r["company"], "industry": r["industry"], "size": int(r["size"]),
                "stage": r["stage"], "deal_value": int(r["deal_value"]), "owner": r["owner"],
                "last_contact": today - timedelta(days=int(r["last_contact_days_ago"])),
                "stage_changed": today - timedelta(days=int(r["stage_changed_days_ago"])),
                "notes": r["notes"], "expansion_signal": r["expansion_signal"] or None,
            })
    return rows


def reset(engine: Engine, today: date) -> dict:
    metadata.create_all(engine)
    rows = load_accounts(today)
    with tx(engine) as conn:
        for table in ALL_TABLES:
            conn.execute(delete(table))
        conn.execute(accounts.insert(), rows)
        conn.execute(meta.insert().values(key="crm_anchor", value=today.isoformat()))
        log_activity(conn, "seed", "success", f"Demo reset: {len(rows)} CRM accounts seeded relative to {today.isoformat()}")
    return {"accounts": len(rows)}


def ensure_seeded(engine: Engine, today: date) -> None:
    metadata.create_all(engine)
    with engine.connect() as conn:
        empty = not conn.execute(select(func.count()).select_from(accounts)).scalar()
    if empty:
        reset(engine, today)


if __name__ == "__main__":
    print(reset(make_engine(get_settings().database_url), date.today()))
