"""Demo data or real data.

The hub starts in demo mode: five sample clients whose numbers follow published 2026 industry
medians (see app/workflows/synthetic.py). Switching to real data deletes every demo row, stops
the sample generator for good, and from then on numbers only come from your CSV imports and the
ad accounts you connect. Saved API keys are kept.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, desc, select

from app.context import Context
from app.db import as_utc, automation_log, client_accounts, kv_store, upsert, utcnow

MODE_KEY = "data_mode"
PLATFORM_LABEL = {"google_ads": "Google Ads", "meta_ads": "Meta Ads", "search_console": "Search Console", "ga4": "Google Analytics"}


def _kv(ctx: Context, key: str) -> Any:
    with ctx.engine.connect() as conn:
        return conn.execute(select(kv_store.c.value).where(kv_store.c.key == key)).scalar()


def _set_kv(ctx: Context, key: str, value: Any) -> None:
    with ctx.engine.begin() as conn:
        upsert(conn, kv_store, [{"key": key, "value": value, "updated_at": utcnow()}], ["key"], ["value", "updated_at"])


def get_mode(ctx: Context) -> str:
    return "real" if _kv(ctx, MODE_KEY) == "real" else "demo"


def set_mode(ctx: Context, mode: str) -> None:
    _set_kv(ctx, MODE_KEY, "real" if mode == "real" else "demo")


def platform_ready(ctx: Context, platform: str) -> bool:
    s = ctx.settings
    return {"google_ads": s.google_ads_live, "meta_ads": s.meta_live, "search_console": s.google_live, "ga4": s.google_live}.get(platform, False)


def mapped_platforms(ctx: Context) -> set[str]:
    with ctx.engine.connect() as conn:
        return {r.platform for r in conn.execute(select(client_accounts.c.platform).distinct())}


def live_sources(ctx: Context) -> list[str]:
    """Platforms that have working credentials and at least one client mapped to them."""
    mapped = mapped_platforms(ctx)
    return [PLATFORM_LABEL[p] for p in PLATFORM_LABEL if p in mapped and platform_ready(ctx, p)]


def live_available(ctx: Context) -> bool:
    return bool(live_sources(ctx))


def last_run(ctx: Context, *sources: str) -> dict[str, Any] | None:
    q = select(automation_log.c.created_at, automation_log.c.status, automation_log.c.source).where(automation_log.c.workflow == "daily_metrics_pipeline")
    if sources:
        q = q.where(automation_log.c.source.in_(sources))
    with ctx.engine.connect() as conn:
        row = conn.execute(q.order_by(desc(automation_log.c.created_at)).limit(1)).first()
    return {"at": as_utc(row.created_at).isoformat(), "status": row.status, "source": row.source} if row else None


def status(ctx: Context) -> dict[str, Any]:
    mode = get_mode(ctx)
    sources = live_sources(ctx) if mode == "real" else []
    imported = last_run(ctx, "import")
    if mode == "demo":
        label = "Demo data"
    elif sources:
        label = "Live data"
    elif imported:
        label = "Your data"
    else:
        label = "No data yet"
    return {
        "mode": mode,
        "label": label,
        "live_sources": sources,
        "last_sync": last_run(ctx, "live", "schedule", "dashboard", "cron") if mode == "real" else None,
        "last_import": imported,
        "currency": ctx.settings.report_currency.upper(),
        "sync_minutes": ctx.settings.live_sync_minutes,
    }


def start_real_data(ctx: Context) -> None:
    """Delete every demo client, metric, run, draft and message; keep saved keys."""
    from app.seed import reset_all

    reset_all(ctx)
    with ctx.engine.begin() as conn:
        conn.execute(delete(client_accounts))
    set_mode(ctx, "real")


def back_to_demo(ctx: Context) -> dict[str, Any]:
    from app.seed import seed_demo

    with ctx.engine.begin() as conn:
        conn.execute(delete(client_accounts))
    set_mode(ctx, "demo")
    return seed_demo(ctx, reset=True)
