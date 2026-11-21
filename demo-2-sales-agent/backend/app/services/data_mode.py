"""Sample CRM or your CRM.

The app starts on Acme's sample CRM: 50 fictional accounts and Acme's own product notes, while the
leads it researches are real companies with real sources. Switching to real data deletes the
sample accounts, runs, leads and drafts; from then on accounts come only from your CSV imports or
HubSpot, and the agent reads the product notes you write in Settings. Saved keys and notes stay.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, select, text

from app.context import Context
from app.db import accounts, as_utc, automation_log, kv_store, upsert, utcnow

MODE_KEY = "data_mode"
SOURCE_KEY = "crm_source"  # csv | hubspot
WIPE = ("feedback", "drafts", "leads", "activity", "accounts", "agent_runs", "icp_versions", "automation_log", "notifications")


def _kv(ctx: Context, key: str) -> Any:
    with ctx.engine.connect() as conn:
        return conn.execute(select(kv_store.c.value).where(kv_store.c.key == key)).scalar()


def set_kv(ctx: Context, key: str, value: Any) -> None:
    with ctx.engine.begin() as conn:
        upsert(conn, kv_store, [{"key": key, "value": value, "updated_at": utcnow()}], ["key"], ["value", "updated_at"])


def get_mode(ctx: Context) -> str:
    return "real" if _kv(ctx, MODE_KEY) == "real" else "demo"


def _wipe(ctx: Context) -> None:
    with ctx.engine.begin() as conn:
        for table in WIPE:
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM kv_store WHERE key NOT LIKE 'knowledge:%'"))


def start_real_data(ctx: Context) -> None:
    _wipe(ctx)
    set_kv(ctx, MODE_KEY, "real")


def back_to_demo(ctx: Context) -> dict[str, int]:
    from app.seed import seed_demo

    _wipe(ctx)
    return seed_demo(ctx)


def last_sync(ctx: Context) -> dict[str, Any] | None:
    q = select(automation_log.c.created_at, automation_log.c.status, automation_log.c.workflow).where(automation_log.c.workflow.in_(("crm_import", "hubspot_sync")))
    with ctx.engine.connect() as conn:
        row = conn.execute(q.order_by(desc(automation_log.c.created_at)).limit(1)).first()
    return {"at": as_utc(row.created_at).isoformat(), "status": row.status, "kind": row.workflow} if row else None


NEEDS_TEXT = {
    "product": "your product notes (Settings, Your company notes)",
    "anthropic": "a Claude API key: the offline planner only knows the Acme demo",
    "tavily": "a Tavily key: the cached research was gathered for Acme's ideal customer",
}


def run_blockers(ctx: Context) -> list[str]:
    """What a real-data agent run still needs. The demo needs nothing."""
    from app.services.knowledge import missing_notes

    if get_mode(ctx) != "real":
        return []
    out = list(missing_notes(ctx.engine))
    if not ctx.settings.llm_live:
        out.append("anthropic")
    if not ctx.settings.research_live:
        out.append("tavily")
    return out


def status(ctx: Context) -> dict[str, Any]:
    mode = get_mode(ctx)
    source = _kv(ctx, SOURCE_KEY) if mode == "real" else "sample"
    with ctx.engine.connect() as conn:
        n = conn.execute(select(func.count()).select_from(accounts)).scalar() or 0
    label = "Sample CRM" if mode == "demo" else "Live from HubSpot" if source == "hubspot" and ctx.settings.hubspot_live else "Your CRM" if n else "No CRM data yet"
    return {
        "mode": mode,
        "label": label,
        "crm_source": source,
        "accounts": n,
        "last_sync": last_sync(ctx) if mode == "real" else None,
        "needs": run_blockers(ctx),
        "research": "live web search" if ctx.settings.research_live else "cached research (real companies, real sources)",
        "ai": "live" if ctx.settings.llm_live else "offline planner",
        "sync_minutes": ctx.settings.hubspot_sync_minutes,
    }
