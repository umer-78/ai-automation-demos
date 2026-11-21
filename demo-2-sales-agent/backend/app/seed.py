"""Seed the mock CRM from the CSV files (50 fictional accounts and their activity)."""

from __future__ import annotations

from sqlalchemy import func, select, text

from app.context import Context
from app.db import accounts
from app.workflows.crm import load_csv

RESET_ORDER = ("feedback", "drafts", "leads", "activity", "accounts", "agent_runs", "icp_versions", "automation_log", "notifications", "kv_store")


def is_empty(ctx: Context) -> bool:
    with ctx.engine.connect() as conn:
        return not conn.execute(select(func.count()).select_from(accounts)).scalar()


def seed_demo(ctx: Context) -> dict[str, int]:
    return load_csv(ctx.engine, ctx.settings.crm_accounts_csv, ctx.settings.crm_activity_csv)


def reset_demo(ctx: Context) -> dict[str, int]:
    """Delete everything and reload the CRM. Used by the admin reset endpoint and the CLI."""
    with ctx.engine.begin() as conn:
        for table in RESET_ORDER:
            conn.execute(text(f"DELETE FROM {table}"))
    return seed_demo(ctx)
