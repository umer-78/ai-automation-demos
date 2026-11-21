"""Public demo actions (rate limited): onboarding form, churn, forced failure, pipeline run,
weekly AI summary, website drafts."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import ClientIn, RegenerateIn, SiteIn, get_ctx, rate_limit
from app.context import Context
from app.services.airtable import AirtableError
from app.services.automation_log import log_and_alert, new_run_id
from app.services.llm import LLMError
from app.workflows.clients import NotFound, find_client, get_client, set_status
from app.workflows.metrics_pipeline import PipelineError, run_daily_metrics
from app.workflows.onboarding import offboard_client, run_onboarding
from app.workflows.site_generator import SiteError, generate_site, regenerate_section
from app.workflows.weekly_summary import generate_weekly_summary

log = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(rate_limit)])

FAILURE_TEST_CLIENT = {
    "name": "Forced Failure Test Co",
    "website": "https://forced-failure.example",
    "industry": "QA test record",
    "services": ["SEO"],
    "manager": "Automation QA",
    "manager_email": "qa@northwind-digital.example",
    "simulate_failure": True,
}


def _safe(fn, *args, **kwargs) -> None:
    """Background wrapper: AutomationRun already logged + alerted, so just keep the worker alive."""
    try:
        fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        log.exception("background workflow failed (already written to automation_log)")


def dispatch_to_make(ctx: Context, url: str, payload: dict[str, Any], *, workflow: str) -> None:
    try:
        resp = httpx.post(url, json=payload, timeout=15)
        if resp.status_code >= 300:
            raise RuntimeError(f"Make webhook returned HTTP {resp.status_code}: {resp.text[:200]}")
    except (httpx.HTTPError, RuntimeError) as exc:
        log_and_alert(ctx.engine, ctx.notifier, workflow=workflow, status="failure", source="api", error=f"Could not reach Make.com: {exc}", run_id=payload.get("run_id"))
        raise HTTPException(502, "Could not reach the Make.com webhook; the failure was logged and alerted") from exc


@router.post("/api/clients", status_code=202)
def submit_client(body: ClientIn, background: BackgroundTasks, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Onboarding form. Creates the Airtable row (if connected), then hands off to Make.com
    (if connected) or to the local orchestrator that mirrors the Make scenario."""
    payload = body.model_dump()
    run_id = payload.get("run_id") or new_run_id()
    payload["run_id"] = run_id
    if ctx.airtable.live and not payload.get("airtable_record_id"):
        try:
            rec = ctx.airtable.create_record(
                {
                    "Name": payload["name"],
                    "Website": payload.get("website") or "",
                    "Industry": payload["industry"],
                    "Services": payload["services"],
                    "Account Manager": payload["manager"],
                    "Manager Email": payload.get("manager_email") or "",
                    "Status": "Onboarding",
                    "Source": "Hub form",
                }
            )
            payload["airtable_record_id"] = rec.get("id")
        except AirtableError as exc:
            log_and_alert(ctx.engine, ctx.notifier, workflow="client_onboarding", status="failure", source="api", run_id=run_id, error=f"Airtable create failed: {exc}")
            raise HTTPException(502, "Airtable rejected the new client row; the failure was logged and alerted")
    if ctx.settings.make_live:
        dispatch_to_make(ctx, ctx.settings.make_onboarding_webhook_url, {"event": "client.created", **payload}, workflow="client_onboarding")
        return {"run_id": run_id, "mode": "make", "message": "Sent to the Make.com onboarding scenario"}
    background.add_task(_safe, run_onboarding, ctx, payload, source="dashboard", run_id=run_id)
    return {"run_id": run_id, "mode": "local", "message": "Onboarding started"}


@router.post("/api/clients/{client_id}/churn", status_code=202)
def churn_client(client_id: int, background: BackgroundTasks, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    try:
        client = get_client(ctx, client_id)
    except NotFound:
        raise HTTPException(404, "client not found")
    if client["status"] == "archived":
        raise HTTPException(409, "client is already archived")
    run_id = new_run_id()
    if ctx.airtable.live and client.get("airtable_record_id"):
        try:
            ctx.airtable.update_record(client["airtable_record_id"], {"Status": "Churned"})
        except AirtableError as exc:
            log.warning("Airtable status update failed: %s", exc)
    if ctx.settings.make_offboarding_webhook_url:
        dispatch_to_make(
            ctx,
            ctx.settings.make_offboarding_webhook_url,
            {"event": "client.churned", "client_id": client_id, "airtable_record_id": client.get("airtable_record_id"), "run_id": run_id},
            workflow="client_offboarding",
        )
        set_status(ctx, client_id, "churned")
        return {"run_id": run_id, "mode": "make"}
    background.add_task(_safe, offboard_client, ctx, client_id=client_id, source="dashboard", run_id=run_id)
    return {"run_id": run_id, "mode": "local"}


@router.post("/api/demo/forced-failure")
def forced_failure(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Runs onboarding for a QA record that fails on purpose at the brief step, proving that the
    failure lands in automation_log and triggers a Slack alert. Demo mode only."""
    from app.services.data_mode import get_mode

    if get_mode(ctx) == "real":
        raise HTTPException(409, "The forced failure is a demo; it is off while the hub runs on real data.")
    run_id = new_run_id()
    if ctx.settings.make_live:
        dispatch_to_make(ctx, ctx.settings.make_onboarding_webhook_url, {"event": "client.created", **FAILURE_TEST_CLIENT, "run_id": run_id}, workflow="client_onboarding")
        return {"run_id": run_id, "mode": "make", "status": "dispatched"}
    try:
        run_onboarding(ctx, dict(FAILURE_TEST_CLIENT), source="dashboard", run_id=run_id)
    except Exception as exc:  # expected
        client = find_client(ctx, name=FAILURE_TEST_CLIENT["name"])
        return {"run_id": run_id, "mode": "local", "status": "failure", "error": str(exc), "client_id": client["id"] if client else None}
    raise HTTPException(500, "the forced failure did not fail")  # pragma: no cover


@router.post("/api/jobs/daily-metrics")
def run_pipeline(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    try:
        return run_daily_metrics(ctx, run_source="dashboard")
    except PipelineError as exc:
        raise HTTPException(502, f"Pipeline failed (logged and alerted): {exc}")


@router.post("/api/summaries/weekly")
def weekly_summary(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    try:
        return generate_weekly_summary(ctx, source="dashboard")
    except LLMError as exc:
        raise HTTPException(502, f"AI summary failed (logged and alerted): {exc}")


@router.post("/api/sites", status_code=201)
def create_site(body: SiteIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    try:
        return generate_site(ctx, body.model_dump(), source="dashboard")
    except (LLMError, SiteError) as exc:
        raise HTTPException(502, f"Site generation failed (logged and alerted): {exc}")


@router.post("/api/sites/{group_id}/regenerate")
def regenerate(group_id: str, body: RegenerateIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    try:
        return regenerate_section(ctx, group_id, body.section, instruction=body.instruction, source="dashboard")
    except SiteError as exc:
        raise HTTPException(404 if "not found" in str(exc) else 400, str(exc))
    except LLMError as exc:
        raise HTTPException(502, f"Section regeneration failed (logged and alerted): {exc}")
