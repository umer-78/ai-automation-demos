"""Client records: create/update from Airtable or the dashboard form, lookups, status changes."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import case, func, select

from app.context import Context
from app.db import client_tasks, clients, row_to_dict, rows_to_dicts, utcnow

SERVICE_ALIASES = {
    "seo": "SEO",
    "search engine optimisation": "SEO",
    "search engine optimization": "SEO",
    "paid ads": "Paid Ads",
    "paid media": "Paid Ads",
    "ppc": "Paid Ads",
    "ads": "Paid Ads",
    "google ads": "Paid Ads",
    "meta ads": "Paid Ads",
    "web design": "Web Design",
    "website": "Web Design",
    "web": "Web Design",
    "website design": "Web Design",
}
ROUTER_ORDER = ("SEO", "Paid Ads", "Web Design")
STATUSES = ("new", "onboarding", "active", "churned", "archived")


class NotFound(LookupError):
    pass


def normalize_services(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = re.split(r"[,;|/]", raw)
    else:
        items = list(raw)
    out: list[str] = []
    for item in items:
        key = str(item).strip().lower()
        if not key:
            continue
        canonical = SERVICE_ALIASES.get(key)
        if canonical and canonical not in out:
            out.append(canonical)
    return [s for s in ROUTER_ORDER if s in out]


def get_client(ctx: Context, client_id: int) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = conn.execute(select(clients).where(clients.c.id == client_id)).first()
    if not row:
        raise NotFound(f"client {client_id} not found")
    return row_to_dict(row)


def find_client(ctx: Context, *, client_id: int | None = None, airtable_record_id: str | None = None, name: str | None = None) -> dict[str, Any] | None:
    with ctx.engine.connect() as conn:
        if client_id:
            row = conn.execute(select(clients).where(clients.c.id == client_id)).first()
            if row:
                return row_to_dict(row)
        if airtable_record_id:
            row = conn.execute(select(clients).where(clients.c.airtable_record_id == airtable_record_id)).first()
            if row:
                return row_to_dict(row)
        if name:
            row = conn.execute(select(clients).where(func.lower(clients.c.name) == name.strip().lower())).first()
            if row:
                return row_to_dict(row)
    return None


def list_clients(ctx: Context, *, include_archived: bool = True) -> list[dict[str, Any]]:
    task_counts = (
        select(
            client_tasks.c.client_id,
            func.count().label("tasks_total"),
            func.sum(case((client_tasks.c.status == "open", 1), else_=0)).label("tasks_open"),
        )
        .group_by(client_tasks.c.client_id)
        .subquery()
    )
    stmt = (
        select(clients, task_counts.c.tasks_total, task_counts.c.tasks_open)
        .select_from(clients.outerjoin(task_counts, task_counts.c.client_id == clients.c.id))
        .order_by(clients.c.created_at.desc(), clients.c.id.desc())
    )
    if not include_archived:
        stmt = stmt.where(clients.c.status != "archived")
    with ctx.engine.connect() as conn:
        items = rows_to_dicts(conn.execute(stmt))
    for item in items:
        item["tasks_total"] = int(item.get("tasks_total") or 0)
        item["tasks_open"] = int(item.get("tasks_open") or 0)
    return items


def upsert_client(ctx: Context, payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update a client from an Airtable row / form submission. Matching order:
    Airtable record id, then name (case-insensitive)."""
    services = normalize_services(payload.get("services"))
    values = {
        "name": payload["name"].strip(),
        "website": (payload.get("website") or "").strip() or None,
        "industry": (payload.get("industry") or "").strip() or None,
        "services": services,
        "manager": (payload.get("manager") or "").strip() or None,
        "manager_email": (payload.get("manager_email") or "").strip() or None,
        "monthly_budget": payload.get("monthly_budget"),
        "updated_at": utcnow(),
    }
    record_id = (payload.get("airtable_record_id") or "").strip() or None
    existing = find_client(ctx, airtable_record_id=record_id, name=values["name"])
    with ctx.engine.begin() as conn:
        if existing:
            update = {k: v for k, v in values.items() if v is not None}
            if not services:
                update.pop("services", None)  # partial payloads must not wipe the service list
            if record_id:
                update["airtable_record_id"] = record_id
            if existing["status"] in ("archived", "churned"):
                update["status"] = "new"  # re-onboarding a former client
                update["archived_at"] = None
            conn.execute(clients.update().where(clients.c.id == existing["id"]).values(**update))
            client_id = existing["id"]
        else:
            result = conn.execute(
                clients.insert().values(
                    **values,
                    airtable_record_id=record_id,
                    status="new",
                    created_at=utcnow(),
                )
            )
            client_id = result.inserted_primary_key[0]
    return get_client(ctx, client_id)


def set_status(ctx: Context, client_id: int, status: str, **extra: Any) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid status {status}")
    with ctx.engine.begin() as conn:
        conn.execute(clients.update().where(clients.c.id == client_id).values(status=status, updated_at=utcnow(), **extra))
    return get_client(ctx, client_id)


def client_tasks_for(ctx: Context, client_id: int) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        rows = conn.execute(
            select(client_tasks)
            .where(client_tasks.c.client_id == client_id)
            .order_by(client_tasks.c.service, client_tasks.c.position)
        )
        return rows_to_dicts(rows)
