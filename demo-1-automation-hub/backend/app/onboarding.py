"""Module A: client onboarding and off-boarding pipelines, with logged failures and Slack alerts."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine

from .config import Settings
from .db import clients, email_drafts, jdump, jload, log_event, now_utc, tasks, tx
from .integrations import Airtable, Mailer, Slack, Storage, fetch_site_text
from .llm import LLM, OFFLINE, as_text, offline_brief
from .mockdata import CHECKLISTS, SERVICES, WELCOME


@dataclass
class Deps:
    settings: Settings
    llm: LLM
    slack: Slack
    airtable: Airtable
    storage: Storage
    mailer: Mailer

    @classmethod
    def build(cls, settings: Settings) -> "Deps":
        return cls(settings, LLM(settings), Slack(settings), Airtable(settings), Storage(settings), Mailer(settings))


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


def client_dict(row) -> dict:  # noqa: ANN001
    d = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    d["services"] = jload(d.get("services"), [])
    d["brief"] = jload(d.get("brief"), None)
    for k in ("created_at", "archived_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def get_client(conn: Connection, client_id: str) -> dict | None:
    row = conn.execute(select(clients).where(clients.c.id == client_id)).first()
    return client_dict(row) if row else None


def alert_failure(engine: Engine, deps: Deps, workflow: str, error: str, detail: str) -> dict:
    """Write the failure in its own committed transaction, then alert Slack."""
    with tx(engine) as conn:
        log_event(conn, workflow, "failure", detail=detail, error=error)
    return deps.slack.post(f":warning: *{workflow} failed* — {error}\n{detail}")


def validate_new_client(data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not 2 <= len(name) <= 120:
        raise BadRequest("Name must be 2-120 characters.")
    services = [s for s in data.get("services") or [] if s in SERVICES]
    if not services:
        raise BadRequest(f"Pick at least one service: {', '.join(SERVICES)}.")
    website = (data.get("website") or "").strip()
    if website and not re.match(r"^https?://[^\s/$.?#].[^\s]*$", website):
        raise BadRequest("Website must start with http:// or https://")
    email = (data.get("manager_email") or "").strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise BadRequest("Manager email is not valid.")
    return {"name": name, "website": website or None, "industry": (data.get("industry") or "").strip()[:200] or None,
            "services": services, "manager": (data.get("manager") or "").strip()[:120] or None,
            "manager_email": email or None}


def create_client(engine: Engine, deps: Deps, data: dict, airtable_record_id: str | None = None) -> dict:
    clean = validate_new_client(data)
    at = {"sent": False, "detail": "came from Airtable", "record_id": airtable_record_id}
    if not airtable_record_id:
        at = deps.airtable.create_client(clean)
    cid = "cl-" + uuid.uuid4().hex[:8]
    with tx(engine) as conn:
        conn.execute(clients.insert().values(id=cid, name=clean["name"], website=clean["website"],
                                             industry=clean["industry"], services=jdump(clean["services"]),
                                             manager=clean["manager"], manager_email=clean["manager_email"],
                                             status="Active", airtable_record_id=at.get("record_id"),
                                             created_at=now_utc()))
        log_event(conn, "client_created", "success", f"{clean['name']} ({', '.join(clean['services'])}); "
                                                      f"Airtable: {at['detail']}")
        return {"client": get_client(conn, cid), "airtable": at}


def upsert_client_from_airtable(engine: Engine, deps: Deps, payload: dict) -> str:
    """Make.com sends the Airtable record; create or update the matching client."""
    record_id = (payload.get("record_id") or "").strip()
    if not record_id:
        raise BadRequest("record_id is required")
    services = payload.get("services")
    if isinstance(services, str):
        services = [s.strip() for s in services.split(",")]
    data = {**payload, "services": services or []}
    with tx(engine) as conn:
        row = conn.execute(select(clients.c.id).where(clients.c.airtable_record_id == record_id)).first()
        if row:
            clean = validate_new_client(data)
            conn.execute(update(clients).where(clients.c.id == row[0]).values(
                name=clean["name"], website=clean["website"], industry=clean["industry"],
                services=jdump(clean["services"]), manager=clean["manager"], manager_email=clean["manager_email"]))
            return row[0]
    return create_client(engine, deps, data, airtable_record_id=record_id)["client"]["id"]


def run_onboarding(engine: Engine, deps: Deps, client_id: str, service: str, source: str = "direct") -> dict:
    """The full onboarding flow. `source` is 'make' when Make.com called us, else 'direct'."""
    t0 = time.monotonic()
    with tx(engine) as conn:
        client = get_client(conn, client_id)
    if not client:
        alert_failure(engine, deps, "onboarding", f"client {client_id} not found", f"source={source}")
        raise NotFound("client not found")
    if service not in client["services"]:
        alert_failure(engine, deps, "onboarding", f"{service} is not one of {client['name']}'s services",
                      f"source={source}")
        raise BadRequest(f"{service} is not one of this client's services")

    via_make = source == "make"
    steps = [
        {"name": "Airtable webhook", "status": "ok" if via_make else "skipped",
         "detail": "row received from Airtable via Make.com" if via_make else "started from the dashboard"},
        {"name": f"Make router → {service}", "status": "ok" if via_make else "skipped",
         "detail": "branch chosen in Make.com" if via_make else "routed by the Python service"},
    ]
    try:
        checklist = CHECKLISTS[service]
        with tx(engine) as conn:
            open_titles = {r[0] for r in conn.execute(select(tasks.c.title).where(
                (tasks.c.client_id == client_id) & (tasks.c.service == service) & (tasks.c.status == "open")))}
            new = [t for t in checklist if t not in open_titles]
            for title in new:
                conn.execute(tasks.insert().values(client_id=client_id, service=service, title=title, status="open",
                                                   created_at=now_utc()))
        steps.append({"name": "Create task checklist", "status": "ok",
                      "detail": f"{len(new)} tasks created" + (f", {len(checklist) - len(new)} already open" if len(new) < len(checklist) else "")})

        slack_text = WELCOME[service].format(name=client["name"], n=len(checklist), manager=client.get("manager") or "unassigned")
        slack = deps.slack.post(slack_text)
        steps.append({"name": "Post Slack welcome", "status": "ok" if slack["sent"] else "skipped", "detail": slack["detail"]})

        site_text, site_note = fetch_site_text(client.get("website"))
        try:
            brief, engine_label = deps.llm.write_brief(client, service, site_text)
        except Exception as exc:  # noqa: BLE001 - any Claude failure falls back, and is logged
            alert_failure(engine, deps, "claude_brief", str(exc)[:300], f"{client['name']}, {service}")
            brief, engine_label = offline_brief(client, service), f"{OFFLINE.split(' (')[0]} (Claude error, fell back)"
        steps.append({"name": "Claude client brief", "status": "ok", "detail": f"{engine_label}; website: {site_note}"})

        brief_text = as_text(brief)
        with tx(engine) as conn:
            conn.execute(update(clients).where(clients.c.id == client_id).values(
                brief=jdump({**brief, "service": service, "engine": engine_label})))
        at = deps.airtable.update(client.get("airtable_record_id"), {"Brief": brief_text, "Status": "Onboarded"})
        steps.append({"name": "Save brief", "status": "ok", "detail": f"database; Airtable: {at['detail']}"})

        subject = f"[Draft] {service} onboarding brief — {client['name']}"
        body = (f"Hi {client.get('manager') or 'team'},\n\nThe {service} onboarding for {client['name']} is ready.\n\n"
                f"{brief_text}\n\nChecklist:\n" + "\n".join(f"  - {t}" for t in checklist) +
                "\n\nReview and edit before sending anything to the client.\n— Northwind automation hub")
        mail = deps.mailer.send(client.get("manager_email"), subject, body)
        with tx(engine) as conn:
            conn.execute(email_drafts.insert().values(client_id=client_id, to_addr=client.get("manager_email"),
                                                      subject=subject, body=body, delivery=mail["detail"],
                                                      created_at=now_utc()))
        steps.append({"name": "Email account manager (draft)", "status": "ok" if mail["sent"] else "saved",
                      "detail": mail["detail"]})
    except Exception as exc:  # noqa: BLE001
        alert_failure(engine, deps, "onboarding", str(exc)[:300], f"{client['name']}, {service}, source {source}")
        raise

    elapsed = round(time.monotonic() - t0, 2)
    with tx(engine) as conn:
        log_event(conn, "onboarding", "success", f"{client['name']} onboarded for {service} in {elapsed}s via {'Make' if via_make else 'the dashboard'}")
    return {"client": client["name"], "client_id": client_id, "service": service, "steps": steps,
            "checklist": checklist, "slack": {"text": slack_text, **slack}, "brief": brief, "engine": engine_label,
            "email": {"to": client.get("manager_email"), "subject": subject, "body": body, **mail},
            "elapsed_s": elapsed}


def run_offboarding(engine: Engine, deps: Deps, client_id: str, source: str = "direct") -> dict:
    with tx(engine) as conn:
        client = get_client(conn, client_id)
        if not client:
            raise NotFound("client not found")
        if client["status"] == "Archived":
            raise BadRequest("client is already archived")
        res = conn.execute(update(tasks).where((tasks.c.client_id == client_id) & (tasks.c.status == "open"))
                           .values(status="closed", closed_at=now_utc()))
        closed = res.rowcount or 0
        conn.execute(update(clients).where(clients.c.id == client_id).values(status="Archived", archived_at=now_utc()))
    summary = (f":wave: *{client['name']}* churned and was archived. {closed} open tasks closed. "
               f"AM: {client.get('manager') or 'unassigned'}.")
    slack = deps.slack.post(summary)
    at = deps.airtable.update(client.get("airtable_record_id"), {"Status": "Archived"})
    with tx(engine) as conn:
        log_event(conn, "offboarding", "success", f"{client['name']}: {closed} tasks closed, via {source}")
    return {"client": client["name"], "tasks_closed": closed, "slack": {"text": summary, **slack}, "airtable": at}


def forced_failure(engine: Engine, deps: Deps) -> dict:
    """The spec's deliberate failure: an upstream Airtable webhook timing out mid-onboarding."""
    error = "Upstream: Airtable webhook timed out after 3 retries"
    slack = alert_failure(engine, deps, "onboarding", error, "forced-failure test from the dashboard")
    return {"logged": True, "error": error, "slack": slack}
