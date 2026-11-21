"""Seed the demo: 5 fake clients, their onboarding checklists and 60 days of ad metrics across
Google Ads, Meta Ads and SEO (GreenLeaf Organics gets a Meta Ads CPA spike in the last week).

The metrics are loaded through the real daily pipeline (60-day backfill), so the seed itself
shows up in automation_log like any other run.
"""

from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from app.context import Context
from app.db import (
    automation_log,
    campaign_metrics,
    client_tasks,
    clients,
    kv_store,
    notifications,
    site_drafts,
    today_utc,
    utcnow,
    weekly_summaries,
)
from app.workflows.metrics_pipeline import run_daily_metrics
from app.workflows.onboarding import offline_brief, brief_to_text, create_checklist
from app.workflows.synthetic import SEED_CLIENTS, synth_rows

SEED_TENURE_DAYS = (210, 160, 120, 95, 75)


def is_empty(ctx: Context) -> bool:
    with ctx.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(clients)).scalar_one() == 0


def reset_all(ctx: Context) -> None:
    with ctx.engine.begin() as conn:
        for table in (weekly_summaries, site_drafts, campaign_metrics, client_tasks, notifications, automation_log, clients):
            conn.execute(delete(table))
        conn.execute(delete(kv_store).where(kv_store.c.key != "airtable_webhook"))


def seed_demo(ctx: Context, *, reset: bool = False, days: int = 60) -> dict[str, Any]:
    from app.services.data_mode import get_mode

    if reset:
        reset_all(ctx)
    elif get_mode(ctx) == "real":
        return {"seeded": False, "reason": "this hub runs on real data; sample clients stay off"}
    elif not is_empty(ctx):
        return {"seeded": False, "reason": "database already has clients"}

    now = utcnow()
    created_ids = []
    with ctx.engine.begin() as conn:
        for spec, tenure in zip(SEED_CLIENTS, SEED_TENURE_DAYS):
            result = conn.execute(
                clients.insert().values(
                    name=spec["name"],
                    website=spec["website"],
                    industry=spec["industry"],
                    services=spec["services"],
                    manager=spec["manager"],
                    manager_email=spec["manager_email"],
                    monthly_budget=spec["monthly_budget"],
                    status="active",
                    created_at=now - timedelta(days=tenure),
                    updated_at=now - timedelta(days=tenure),
                )
            )
            created_ids.append(result.inserted_primary_key[0])

    for client_id, spec in zip(created_ids, SEED_CLIENTS):
        client = {**spec, "id": client_id}
        brief = offline_brief(client, None)
        with ctx.engine.begin() as conn:
            conn.execute(clients.update().where(clients.c.id == client_id).values(brief=brief_to_text(client, brief), brief_data=brief))
        for service in ["General", *spec["services"]]:
            create_checklist(ctx, client_id, service)
        with ctx.engine.begin() as conn:  # long-standing clients have finished their kickoff tasks
            conn.execute(client_tasks.update().where(client_tasks.c.client_id == client_id).values(status="done"))

    result = run_daily_metrics(ctx, source="mock", days=days, run_source="seed", post_alerts=False)
    history = seed_history(ctx, created_ids) if ctx.settings.seed_history else 0
    return {"seeded": True, "clients": len(created_ids), "metrics": result, "history": history}


def seed_history(ctx: Context, client_ids: list[int]) -> int:
    """A week of real runs, so the run log, Slack feed and site builder are not empty on first visit.

    Every entry comes from running the actual workflow offline; only the timestamps are spread
    back over the past days afterwards.
    """
    from app.workflows.onboarding import run_onboarding
    from app.workflows.site_generator import generate_site

    run_onboarding(
        ctx,
        {
            "name": "Lakeside Bakery",
            "website": "https://lakeside-bakery.example",
            "industry": "Bakery and cafe",
            "services": ["SEO", "Web Design"],
            "manager": "Priya Shah",
            "manager_email": "priya@northwind-digital.example",
            "monthly_budget": 2500,
        },
        source="seed",
    )
    shop = next(i for i, c in enumerate(SEED_CLIENTS) if c["name"] == "GreenLeaf Organics")
    generate_site(
        ctx,
        {
            "business_name": SEED_CLIENTS[shop]["name"],
            "industry": SEED_CLIENTS[shop]["industry"],
            "tone": "warm",
            "services": ["Organic produce boxes", "Farm-to-door delivery", "Seasonal recipes"],
            "colour": "green",
            "client_id": client_ids[shop] if len(client_ids) > shop else None,
        },
        source="seed",
    )
    for _ in range(3):
        run_daily_metrics(ctx, source="mock", days=1, run_source="schedule", post_alerts=False)
    run_daily_metrics(ctx, source="mock", days=1, run_source="schedule", post_alerts=True)

    with ctx.engine.begin() as conn:
        rows = conn.execute(select(automation_log.c.id).order_by(automation_log.c.id.desc())).fetchall()
        now = utcnow()
        for i, (row_id,) in enumerate(rows):
            conn.execute(automation_log.update().where(automation_log.c.id == row_id).values(created_at=now - timedelta(hours=7 * i + 1)))
        notes = conn.execute(select(notifications.c.id).order_by(notifications.c.id.desc())).fetchall()
        for i, (row_id,) in enumerate(notes):
            conn.execute(notifications.update().where(notifications.c.id == row_id).values(created_at=now - timedelta(hours=7 * i + 1)))
    return len(rows)


def write_sample_csv(ctx: Context, path: Path, days: int = 60) -> int:
    """Export the same synthetic data as a CSV (for METRICS_SOURCE=csv)."""
    anchor = today_utc()
    rows = synth_rows(SEED_CLIENTS, anchor - timedelta(days=days), anchor - timedelta(days=1), anchor=anchor)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "client", "channel", "impressions", "clicks", "spend", "conversions"])
        writer.writeheader()
        for r in rows:
            writer.writerow({**{k: r[k] for k in ("client", "channel", "impressions", "clicks", "spend", "conversions")}, "date": r["date"].isoformat()})
    return len(rows)
