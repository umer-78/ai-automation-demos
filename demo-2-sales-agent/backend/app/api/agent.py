"""Start the agent, follow a run live, and see exactly what the next run will be told."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.agent.prompts import build_system_prompt
from app.agent.runner import RunInProgress
from app.api.deps import get_ctx, limit_agent_runs
from app.context import Context
from app.db import agent_runs, row_to_dict, rows_to_dicts, utcnow
from app.services.automation_log import live_run
from app.workflows import icp as icp_store
from app.workflows import learning

router = APIRouter(prefix="/api")


@router.post("/agent/run", status_code=202, dependencies=[Depends(limit_agent_runs)])
def run_agent(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    from app.services.data_mode import NEEDS_TEXT, run_blockers

    needs = run_blockers(ctx)
    if needs:
        raise HTTPException(409, "Before a run on your own data, add " + "; ".join(NEEDS_TEXT[n] for n in needs) + ".")
    try:
        run_id = ctx.runner.start("manual")
    except RunInProgress as exc:
        raise HTTPException(409, {"message": "An agent run is already in progress.", "run_id": exc.run_id}) from None
    return {"run_id": run_id, "status": "running"}


@router.get("/runs")
def runs(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    cols = [c for c in agent_runs.c if c.name not in ("tools_called", "context_feedback", "lessons")]
    with ctx.engine.connect() as conn:
        return rows_to_dicts(conn.execute(select(*cols).order_by(agent_runs.c.started_at.desc()).limit(50)))


@router.get("/runs/{run_id}")
def run_detail(run_id: str, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = conn.execute(select(agent_runs).where(agent_runs.c.id == run_id)).first()
    if not row:
        raise HTTPException(404, "Run not found")
    run = row_to_dict(row)
    live = live_run(run_id)
    run["live_steps"] = live["steps"] if live else []
    return run


@router.get("/agent/context")
def next_run_context(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """What the next run will receive: the last N feedback items, the rules derived from them and the ICP."""
    settings = ctx.settings
    fb = learning.build_context(ctx.engine, settings.feedback_context_size)
    icp = icp_store.active_icp(ctx.engine)
    prompt = build_system_prompt(
        settings=settings, run_id="(next run)", today=utcnow().date(), icp=icp["criteria"], icp_version=icp["version"],
        icp_author=icp["author"], rep_edited=icp_store.rep_has_edited(ctx.engine), feedback_block=fb["block"],
        feedback_count=len(fb["feedback_ids"]), lessons=fb["lessons"],
    )
    return {
        "feedback_ids": fb["feedback_ids"],
        "feedback_block": fb["block"],
        "lessons": fb["lessons"].as_dict(),
        "icp_version": icp["version"],
        "system_prompt": prompt,
        "mode": "live" if ctx.llm.live else "offline",
    }
