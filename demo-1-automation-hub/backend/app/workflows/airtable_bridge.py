"""Airtable -> automation bridge for the Airtable Free plan.

On Airtable Free, automations cannot run scripts, so they cannot call a webhook. Airtable's
Webhooks API works on every plan: Airtable pings our endpoint, we pull the changed records and
dispatch them (to the Make.com webhook when configured, otherwise to the local orchestrator).
New rows are onboarded once Name, Services and Account Manager are filled in and Status is
"New"; Status changed to "Churned" starts off-boarding.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.context import Context
from app.db import kv_store, upsert, utcnow
from app.services.airtable import changed_record_ids
from app.services.automation_log import log_and_alert, new_run_id
from app.workflows.clients import find_client, normalize_services
from app.workflows.onboarding import offboard_client, run_onboarding

log = logging.getLogger(__name__)
STATE_KEY = "airtable_webhook"


def kv_get(ctx: Context, key: str) -> Any:
    with ctx.engine.connect() as conn:
        return conn.execute(select(kv_store.c.value).where(kv_store.c.key == key)).scalar()


def kv_set(ctx: Context, key: str, value: Any) -> None:
    with ctx.engine.begin() as conn:
        upsert(conn, kv_store, [{"key": key, "value": value, "updated_at": utcnow()}], ["key"], ["value", "updated_at"])


def record_to_payload(record: dict[str, Any]) -> dict[str, Any]:
    f = record.get("fields", {})
    return {
        "airtable_record_id": record.get("id"),
        "name": (f.get("Name") or "").strip(),
        "website": f.get("Website"),
        "industry": f.get("Industry") or "",
        "services": normalize_services(f.get("Services")),
        "manager": f.get("Account Manager") or "",
        "manager_email": f.get("Manager Email"),
        "monthly_budget": f.get("Monthly Budget"),
        "status": (f.get("Status") or "New").strip(),
        "source": f.get("Source") or "",
        "simulate_failure": bool(f.get("Simulate Failure")),
    }


def ready_for_onboarding(p: dict[str, Any]) -> bool:
    return bool(p["name"] and p["services"] and p["manager"] and p["status"].lower() == "new" and p["source"] != "Hub form")


def dispatch(ctx: Context, payload: dict[str, Any], *, event: str) -> None:
    payload = {**payload, "run_id": new_run_id()}
    url = ctx.settings.make_onboarding_webhook_url if event == "client.created" else ctx.settings.make_offboarding_webhook_url
    if url:
        try:
            resp = httpx.post(url, json={"event": event, **payload}, timeout=15)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log_and_alert(ctx.engine, ctx.notifier, workflow="airtable_bridge", status="failure", source="airtable", error=f"Make webhook failed: {exc}", run_id=payload["run_id"])
        return
    try:
        if event == "client.created":
            run_onboarding(ctx, payload, source="airtable", run_id=payload["run_id"])
        else:
            offboard_client(ctx, airtable_record_id=payload["airtable_record_id"], source="airtable", run_id=payload["run_id"])
    except Exception:  # noqa: BLE001 - AutomationRun already logged and alerted
        log.exception("airtable-triggered workflow failed")


def process_payloads(ctx: Context) -> dict[str, int]:
    state = kv_get(ctx, STATE_KEY)
    if not state:
        return {"created": 0, "churned": 0}
    cursor = state.get("cursor") or 1
    changed: set[str] = set()
    for _ in range(20):  # follow pagination, bounded
        page = ctx.airtable.list_payloads(state["id"], cursor)
        created_ids, updated_ids = changed_record_ids(page)
        changed |= created_ids | updated_ids
        cursor = page.get("cursor", cursor)
        if not page.get("mightHaveMore"):
            break
    kv_set(ctx, STATE_KEY, {**state, "cursor": cursor})

    created = churned = 0
    for record_id in sorted(changed):
        try:
            payload = record_to_payload(ctx.airtable.get_record(record_id))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read Airtable record %s: %s", record_id, exc)
            continue
        existing = find_client(ctx, airtable_record_id=record_id)
        if payload["status"].lower() == "churned":
            if existing and existing["status"] != "archived":
                dispatch(ctx, payload, event="client.churned")
                churned += 1
        elif ready_for_onboarding(payload) and not (existing and existing["status"] in ("onboarding", "active")):
            dispatch(ctx, payload, event="client.created")
            created += 1
    return {"created": created, "churned": churned}
