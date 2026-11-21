"""Your CRM and your company notes: sample data, CSV imports or a live HubSpot sync."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import get_ctx, limit_reviews
from app.api.settings import require_owner
from app.context import Context
from app.services import data_mode, hubspot, knowledge
from app.services.automation_log import log_and_alert
from app.workflows import crm, crm_import
from app.agent.scoring import CATEGORIES, REGIONS, normalize_icp
from app.workflows.icp import active_icp
from app.db import utcnow

router = APIRouter()
MAX_BYTES = 5_000_000


class ImportIn(BaseModel):
    csv: str = Field(min_length=10)


class NoteIn(BaseModel):
    text: str = Field(default="", max_length=knowledge.MAX_CHARS)


# Until the agent has written your ideal customer from your product notes, fit is scored evenly:
# every category, size and region counts the same, so only stage, value and recency rank accounts.
NEUTRAL_ICP = {
    "summary": "No ideal customer yet: run the agent once your product notes are saved.",
    "target_categories": [c for c in CATEGORIES if c != "other"],
    "adjacent_categories": ["other"],
    "excluded_categories": [],
    "employee_min": 1,
    "employee_max": 1_000_000,
    "regions": [r for r in REGIONS if r != "unknown"],
}


def _analyze(ctx: Context) -> dict[str, Any]:
    icp = active_icp(ctx.engine)
    criteria = normalize_icp(NEUTRAL_ICP) if icp["version"] == 0 and data_mode.get_mode(ctx) == "real" else icp["criteria"]
    result = crm.analyze_all(ctx.engine, criteria)
    return {"analyzed": result["analyzed"], "counts": result["counts"]}


@router.get("/api/data/status")
def status(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return data_mode.status(ctx)


@router.get("/api/data/template.csv", include_in_schema=False)
def template() -> Response:
    return Response(crm_import.TEMPLATE, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="crm-import-template.csv"'})


@router.post("/api/data/real", dependencies=[Depends(require_owner)])
def use_real_data(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Delete the sample CRM, runs, leads and drafts. Saved keys and notes stay."""
    data_mode.start_real_data(ctx)
    return data_mode.status(ctx)


@router.post("/api/data/demo", dependencies=[Depends(require_owner)])
def use_demo_data(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    data_mode.back_to_demo(ctx)
    return data_mode.status(ctx)


@router.post("/api/data/import", dependencies=[Depends(require_owner), Depends(limit_reviews)])
def import_crm(body: ImportIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    if len(body.csv.encode()) > MAX_BYTES:
        raise HTTPException(413, "That file is over 5 MB. Export fewer columns or split it.")
    started = time.monotonic()
    try:
        rows, problems = crm_import.parse_csv(body.csv, utcnow())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not rows:
        raise HTTPException(422, problems[0] if problems else "No usable rows in the file.")
    switched = data_mode.get_mode(ctx) == "demo"
    if switched:
        data_mode.start_real_data(ctx)
    counts = crm_import.upsert_accounts(ctx.engine, rows)
    data_mode.set_kv(ctx, data_mode.SOURCE_KEY, "csv")
    analysis = _analyze(ctx)
    log_and_alert(
        ctx.engine,
        ctx.notifier,
        workflow="crm_import",
        status="success",
        source="api",
        details={**counts, "skipped": len(problems), "counts": analysis["counts"]},
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {**counts, "rows": len(rows), "skipped": problems[:20], "skipped_count": len(problems), "flags": analysis["counts"], "sample_removed": switched}


def sync_hubspot(ctx: Context, source: str = "api") -> dict[str, Any]:
    started = time.monotonic()
    try:
        rows, skipped = hubspot.fetch_accounts(ctx.settings, utcnow())
    except (hubspot.HubSpotError, OSError) as exc:
        log_and_alert(ctx.engine, ctx.notifier, workflow="hubspot_sync", status="failure", source=source, error=str(exc))
        raise
    counts = crm_import.upsert_accounts(ctx.engine, rows)
    data_mode.set_kv(ctx, data_mode.SOURCE_KEY, "hubspot")
    analysis = _analyze(ctx)
    log_and_alert(
        ctx.engine,
        ctx.notifier,
        workflow="hubspot_sync",
        status="success",
        source=source,
        details={**counts, "skipped": skipped, "counts": analysis["counts"]},
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return {**counts, "accounts": len(rows), "skipped": skipped, "flags": analysis["counts"]}


@router.post("/api/data/hubspot/sync", dependencies=[Depends(require_owner), Depends(limit_reviews)])
def hubspot_sync(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    if not ctx.settings.hubspot_live:
        raise HTTPException(409, "Save a HubSpot private app token first.")
    if data_mode.get_mode(ctx) == "demo":
        data_mode.start_real_data(ctx)
    try:
        return sync_hubspot(ctx)
    except hubspot.HubSpotError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/api/data/notes", dependencies=[Depends(require_owner)])
def notes(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    saved = knowledge.saved_notes(ctx.engine)
    return {
        "docs": [
            {"name": name, "title": title, "text": saved.get(name, {}).get("text", ""), "updated_at": (saved.get(name) or {}).get("updated_at")}
            for name, title in knowledge.DOCS.items()
        ]
    }


@router.put("/api/data/notes/{name}", dependencies=[Depends(require_owner), Depends(limit_reviews)])
def save_note(name: str, body: NoteIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    if name not in knowledge.DOCS:
        raise HTTPException(404, "Unknown note.")
    knowledge.save_note(ctx.engine, name, body.text)
    return notes(ctx)
