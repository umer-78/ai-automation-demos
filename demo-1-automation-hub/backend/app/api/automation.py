"""Server-to-server endpoints called by the Make.com scenarios (and cron).
Protected by the X-Automation-Key header (AUTOMATION_API_KEY).

Make sends values as query-string parameters (Make URL-encodes them, so names with quotes or
emoji never break a hand-built JSON body); JSON bodies are accepted too. Responses include a
ready-to-post `slack_payload` string so the scenario can post to Slack without re-encoding text.

In Make mode the scenario owns the run log: its final module posts a success row to
/api/automation/log and every error route posts the failure there (which also alerts Slack).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from app.api.deps import ClientIn, get_ctx, require_automation_key
from app.context import Context
from app.services.airtable import AirtableError
from app.services.automation_log import StepRecorder, finish_live_run, log_and_alert, new_run_id
from app.services.llm import LLMError
from app.workflows.clients import NotFound, ROUTER_ORDER, get_client, set_status, upsert_client
from app.workflows.metrics_pipeline import PipelineError, run_daily_metrics
from app.workflows.onboarding import (
    DeliberateFailure,
    brief_to_text,
    build_brief,
    create_checklist,
    offboard_client,
    run_onboarding,
    save_brief,
    welcome_text,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/automation", dependencies=[Depends(require_automation_key)], tags=["make.com"])
RunId = Field(default=None, pattern=r"^[A-Za-z0-9_-]{6,40}$")
M = TypeVar("M", bound=BaseModel)


class ChecklistIn(BaseModel):
    client_id: int
    service: Literal["SEO", "Paid Ads", "Web Design", "General"]
    run_id: str | None = RunId


class BriefIn(BaseModel):
    client_id: int
    run_id: str | None = RunId
    simulate_failure: bool = False


class OffboardIn(BaseModel):
    client_id: int | None = None
    airtable_record_id: str | None = Field(default=None, pattern=r"^rec[A-Za-z0-9]{14}$")
    run_id: str | None = RunId


class LogIn(BaseModel):
    workflow: str = Field(min_length=2, max_length=80)
    status: Literal["success", "failure"]
    error: str | None = Field(default=None, max_length=4000)
    run_id: str | None = RunId
    client_id: int | None = None
    module: str | None = Field(default=None, max_length=120)
    details: dict[str, Any] | None = None


async def request_params(request: Request) -> dict[str, Any]:
    """Merge a JSON body (if any) with query-string parameters; empty strings count as missing."""
    data: dict[str, Any] = {}
    raw = await request.body()
    if raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(400, "body must be JSON (or send the values as query parameters)")
        if not isinstance(parsed, dict):
            raise HTTPException(400, "JSON body must be an object")
        data.update(parsed)
    for key, value in request.query_params.multi_items():
        data[key] = value
    return {k: v for k, v in data.items() if v not in ("", None)}


def parse(model: type[M], data: dict[str, Any]) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, json.loads(exc.json(include_url=False)))


def slack_payload(text: str) -> str:
    return json.dumps({"text": text})


def _client_or_404(ctx: Context, client_id: int) -> dict[str, Any]:
    try:
        return get_client(ctx, client_id)
    except NotFound:
        raise HTTPException(404, f"client {client_id} not found")


@router.post("/clients/sync")
def sync_client(params: dict[str, Any] = Depends(request_params), ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Step 1 of the Make onboarding scenario: upsert the client from the Airtable row."""
    body = parse(ClientIn, params)
    payload = body.model_dump()
    run_id = payload.get("run_id") or new_run_id()
    with StepRecorder("client_onboarding", run_id) as run:
        client = upsert_client(ctx, payload)
        client = set_status(ctx, client["id"], "onboarding")
        general = create_checklist(ctx, client["id"], "General")
        run.step("client_synced", client_id=client["id"], orchestrator="make")
    return {
        "run_id": run_id,
        "client_id": client["id"],
        "name": client["name"],
        "services": client["services"],
        "has_seo": "SEO" in client["services"],
        "has_paid_ads": "Paid Ads" in client["services"],
        "has_web_design": "Web Design" in client["services"],
        "manager": client.get("manager"),
        "manager_email": client.get("manager_email"),
        "general_tasks": len(general),
        "simulate_failure": bool(payload.get("simulate_failure")),
    }


@router.post("/onboarding/checklist")
def checklist(params: dict[str, Any] = Depends(request_params), ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """One Make router branch: create the service checklist and return the Slack welcome."""
    body = parse(ChecklistIn, params)
    client = _client_or_404(ctx, body.client_id)
    with StepRecorder("client_onboarding", body.run_id) as run:
        tasks = create_checklist(ctx, client["id"], body.service)
        run.step("branch_done", service=body.service, tasks=len(tasks), orchestrator="make")
    text = welcome_text(client, body.service, len(tasks))
    return {
        "service": body.service,
        "tasks": len(tasks),
        "titles": [t["title"] for t in tasks],
        "welcome_text": text,
        "slack_payload": slack_payload(text),
    }


@router.post("/onboarding/brief")
def brief(params: dict[str, Any] = Depends(request_params), ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """AI brief -> save to Airtable + database -> email the account manager a draft."""
    body = parse(BriefIn, params)
    client = _client_or_404(ctx, body.client_id)
    with StepRecorder("client_onboarding", body.run_id) as run:
        try:
            data = build_brief(ctx, client, simulate_failure=body.simulate_failure)
            saved = save_brief(ctx, client, data, run_id=run.run_id)
        except DeliberateFailure as exc:
            raise HTTPException(500, str(exc))
        except (LLMError, AirtableError) as exc:
            raise HTTPException(502, str(exc))
        client = set_status(ctx, client["id"], "active")
        run.step("brief_saved", generated_by=data["generated_by"], airtable=saved["airtable"], orchestrator="make")
    services = [s for s in ROUTER_ORDER if s in (client.get("services") or [])]
    summary = (
        f":white_check_mark: Onboarding complete for *{client['name']}* ({', '.join(services)}). "
        f"Brief saved to Airtable and emailed to {client.get('manager') or 'the account manager'} as a draft."
    )
    return {
        "client_id": client["id"],
        "generated_by": data["generated_by"],
        "brief_text": brief_to_text(client, data),
        "quick_wins": data["quick_wins"],
        "airtable": saved["airtable"],
        "email_status": saved["email_status"],
        "summary_text": summary,
        "slack_payload": slack_payload(summary),
    }


@router.post("/offboarding")
def offboarding(params: dict[str, Any] = Depends(request_params), ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    body = parse(OffboardIn, params)
    if not body.client_id and not body.airtable_record_id:
        raise HTTPException(422, "client_id or airtable_record_id is required")
    try:
        result = offboard_client(
            ctx,
            client_id=body.client_id,
            airtable_record_id=body.airtable_record_id,
            source="make",
            run_id=body.run_id,
            managed_by_make=True,
        )
    except NotFound as exc:
        raise HTTPException(404, str(exc))
    except AirtableError as exc:
        raise HTTPException(502, str(exc))
    text = result.get("slack_text") or f"{result['client']['name']} was already archived; nothing to do."
    return {**result, "slack_payload": slack_payload(text)}


@router.post("/log")
def write_automation_log(params: dict[str, Any] = Depends(request_params), ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Make.com error routes (and final success modules) write here. Failures also alert Slack."""
    body = parse(LogIn, params)
    details = dict(body.details or {})
    if body.module:
        details["module"] = body.module
    row = log_and_alert(
        ctx.engine,
        ctx.notifier,
        workflow=body.workflow,
        status=body.status,
        run_id=body.run_id,
        source="make",
        error=body.error,
        details=details,
        client_id=body.client_id,
    )
    finish_live_run(body.run_id, body.status, body.error)
    return {"id": row["id"], "run_id": row["run_id"], "status": row["status"], "alerted": body.status == "failure"}


@router.post("/onboarding/run")
def onboarding_run(params: dict[str, Any] = Depends(request_params), ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Whole onboarding flow in one call (for Zapier or a one-module Make scenario)."""
    body = parse(ClientIn, params)
    try:
        return run_onboarding(ctx, body.model_dump(), source="make", run_id=body.run_id)
    except DeliberateFailure as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:  # already logged + alerted by AutomationRun
        raise HTTPException(502, f"Onboarding failed (logged and alerted): {exc}")


@router.post("/jobs/daily-metrics")
def cron_daily_metrics(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Same pipeline as the CLI job; lets an external scheduler (GitHub Actions, cron-job.org) run it."""
    try:
        return run_daily_metrics(ctx, run_source="cron")
    except PipelineError as exc:
        raise HTTPException(502, f"Pipeline failed (logged and alerted): {exc}")
