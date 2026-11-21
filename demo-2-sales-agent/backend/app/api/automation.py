"""Endpoints for schedulers (GitHub Actions / Render cron) and the admin reset."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.agent.runner import RunInProgress
from app.api.deps import get_ctx, limit_reviews, require_admin, require_automation_key
from app.context import Context
from app.seed import reset_demo
from app.services.automation_log import AutomationRun
from app.workflows import report

router = APIRouter(prefix="/api")


@router.post("/automation/run-agent", status_code=202, dependencies=[Depends(require_automation_key)])
def scheduled_run(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    try:
        return {"run_id": ctx.runner.start("schedule"), "status": "running"}
    except RunInProgress as exc:
        raise HTTPException(409, {"message": "An agent run is already in progress.", "run_id": exc.run_id}) from None


@router.post("/automation/weekly-report", dependencies=[Depends(require_automation_key)])
def post_weekly_report(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Build the report from live data and post the headline to the internal Slack channel."""
    with AutomationRun(ctx.engine, ctx.notifier, "weekly_report", source="cron") as run:
        data = report.build(ctx.engine)
        run.step("report_built", leads=data["leads"]["total"], pending=len(data["pending_drafts"]))
        link = f"{ctx.settings.public_base_url.rstrip('/')}/report"
        note = ctx.notifier.slack(
            ":bar_chart: *Weekly sales report*\n" + "\n".join(f"• {line}" for line in data["headline"]) + f"\n<{link}|Open the full report>",
            kind="report", run_id=run.run_id,
        )
        run.step("slack_posted", status=note["status"])
    return {"run_id": run.run_id, "headline": data["headline"], "slack": note["status"]}


@router.post("/automation/test-failure", dependencies=[Depends(limit_reviews)])
def forced_failure(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Deliberate failure: proves that a failing automation is logged and raises an alert."""
    run_id = None
    try:
        with AutomationRun(ctx.engine, ctx.notifier, "forced_failure_check", source="api") as run:
            run_id = run.run_id
            run.step("about_to_fail")
            raise RuntimeError("Deliberate test failure: the CRM export endpoint returned HTTP 503")
    except RuntimeError as exc:
        return {"run_id": run_id, "logged": True, "error": str(exc), "slack": "simulated" if not ctx.settings.slack_live else "sent"}
    return {"run_id": run_id, "logged": False}  # pragma: no cover


@router.post("/admin/reset", dependencies=[Depends(require_admin)])
def reset(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    if ctx.runner.current:
        raise HTTPException(409, "An agent run is in progress; try again in a minute.")
    return {"reset": True, **reset_demo(ctx)}
