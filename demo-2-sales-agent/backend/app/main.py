"""Acme Cloud Security sales agent: API and static site (FastAPI).

Run: uvicorn app.main:create_app --factory --port 8000
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from . import agent, approvals, crm, crm_import, report
from .config import Settings, get_settings
from .db import accounts, activity_log, agent_runs, as_dict, drafts, jload, leads, make_engine, meta, run_events, tx
from .research import SNAPSHOT, Research
from .security import RateLimiter, SecurityHeaders
from .seed import ensure_seeded, reset

mimetypes.add_type("application/manifest+json", ".webmanifest")


class IcpIn(BaseModel):
    summary: str = Field(max_length=600)
    industries: list[str] = Field(default_factory=list, max_length=12)
    size_min: int
    size_max: int
    regions: list[str] = Field(default_factory=list, max_length=12)
    signals: list[str] = Field(default_factory=list, max_length=12)
    exclusions: list[str] = Field(default_factory=list, max_length=12)


class EditIn(BaseModel):
    subject: str = Field(max_length=300)
    body: str = Field(max_length=5000)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


def _lead(row: dict) -> dict:
    d = as_dict(row)
    d["signals"] = jload(d.get("signals"), [])
    d["score_parts"] = jload(d.get("score_parts"), {})
    d.pop("company_key", None)
    return d


def _run(row: dict) -> dict:
    d = as_dict(row)
    calls = jload(d.get("tools_called"), [])
    d["tools_called"] = calls
    d["tool_counts"] = {name: calls.count(name) for name in dict.fromkeys(calls)}
    return d


def create_app(settings: Settings | None = None, today_fn: Callable[[], date] = date.today) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    ensure_seeded(engine, today_fn())
    agent.mark_stale_runs(engine)
    if settings.seed_first_run:
        agent.seed_first_run(engine, settings, today_fn())
    limiter = RateLimiter(settings.rate_limit_per_minute)

    app = FastAPI(title="Acme Cloud Security sales agent", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.add_middleware(SecurityHeaders)
    app.state.engine = engine
    app.state.settings = settings

    def today() -> date:
        d = today_fn()
        with tx(engine) as conn:
            crm.roll_forward(conn, d)
        return d

    for exc_type, code in ((approvals.NotFound, 404), (approvals.Conflict, 409), (approvals.BadRequest, 422),
                           (agent.ToolError, 422)):
        app.add_exception_handler(exc_type, lambda _r, e, c=code: JSONResponse({"detail": str(e)}, status_code=c))
    app.add_exception_handler(agent.AlreadyRunning, lambda _r, _e: JSONResponse(
        {"detail": "A run is already in progress. Watch it below, or wait for it to finish."}, status_code=409))

    # ------------------------------------------------------------------ status and profile
    @app.get("/api/status")
    def status():
        d = today()
        research = Research(settings)
        with engine.connect() as conn:
            running = conn.execute(select(agent_runs.c.id).where(agent_runs.c.status == "running")
                                   .order_by(agent_runs.c.id.desc())).scalar()
            crm_source = conn.execute(select(meta.c.value).where(meta.c.key == "crm_source")).scalar() or "sample"
            counts = {
                "leads": conn.execute(select(func.count()).select_from(leads)).scalar() or 0,
                "accounts": conn.execute(select(func.count()).select_from(accounts)).scalar() or 0,
                "waiting": conn.execute(select(func.count()).select_from(drafts)
                                        .where(drafts.c.status.in_(approvals.OPEN))).scalar() or 0,
                "runs": conn.execute(select(func.count()).select_from(agent_runs)).scalar() or 0,
            }
        return {"engine": f"live Claude ({settings.claude_model})" if settings.live_model else agent.OFFLINE_ENGINE,
                "live_model": settings.live_model, "research": research.label, "live_search": research.live,
                "snapshot_date": SNAPSHOT["taken_on"], "database": settings.database_kind, "slack": settings.slack_enabled,
                "today": d.isoformat(), "running_run": running, "counts": counts, "crm_source": crm_source}

    @app.get("/api/icp")
    def get_icp():
        with engine.connect() as conn:
            return {"icp": agent.get_icp(conn), "default": agent.DEFAULT_ICP}

    @app.put("/api/icp")
    def put_icp(body: IcpIn, request: Request):
        limiter.check(request)
        with tx(engine) as conn:
            saved = agent.save_icp_row(conn, body.model_dump(), "rep")
        return {"icp": saved}

    # ------------------------------------------------------------------------ agent runs
    @app.post("/api/agent/run")
    def run_agent(request: Request):
        limiter.check(request, cost=5)
        return {"run_id": agent.start_run(engine, settings, today())}

    @app.get("/api/agent/runs")
    def runs():
        with engine.connect() as conn:
            return [_run(r) for r in conn.execute(select(agent_runs).order_by(agent_runs.c.id.desc()).limit(20)).mappings()]

    @app.get("/api/agent/runs/{run_id}")
    def run_detail(run_id: int):
        with engine.connect() as conn:
            row = conn.execute(select(agent_runs).where(agent_runs.c.id == run_id)).mappings().first()
            if not row:
                raise HTTPException(404, "No such run.")
            events = [as_dict(e) for e in conn.execute(select(run_events).where(run_events.c.run_id == run_id)
                                                       .order_by(run_events.c.seq)).mappings()]
        return {**_run(row), "events": events}

    @app.get("/api/agent/runs/{run_id}/events")
    async def run_stream(run_id: int, request: Request, after: int = 0):
        """Server-sent events: one message per tool call, then an "end" event."""
        after = max(after, int(request.headers.get("last-event-id") or 0))

        def fetch(last: int):
            with engine.connect() as conn:
                st = conn.execute(select(agent_runs.c.status).where(agent_runs.c.id == run_id)).scalar()
                rows = conn.execute(select(run_events).where(run_events.c.run_id == run_id, run_events.c.seq > last)
                                    .order_by(run_events.c.seq)).mappings().all()
            return st, [as_dict(r) for r in rows]

        first_status, _ = await run_in_threadpool(fetch, after)
        if first_status is None:
            raise HTTPException(404, "No such run.")

        async def stream():
            last, started = after, time.monotonic()
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    return
                st, rows = await run_in_threadpool(fetch, last)
                for e in rows:
                    last = e["seq"]
                    yield f"id: {last}\ndata: {json.dumps(e)}\n\n"
                if st != "running" and not rows:
                    yield f"event: end\ndata: {json.dumps({'status': st})}\n\n"
                    return
                if time.monotonic() - started > 300:
                    return
                await asyncio.sleep(0.35)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ----------------------------------------------------------------- leads and accounts
    @app.get("/api/leads")
    def list_leads():
        with engine.connect() as conn:
            rows = [_lead(r) for r in conn.execute(select(leads).order_by(leads.c.score.desc(), leads.c.id)).mappings()]
            latest = {}
            for d in conn.execute(select(drafts.c.lead_id, drafts.c.status, drafts.c.id).where(
                    drafts.c.lead_id.is_not(None), drafts.c.status != "superseded").order_by(drafts.c.id)).mappings():
                latest[d["lead_id"]] = d["status"]
        for r in rows:
            r["draft_status"] = latest.get(r["id"])
        return rows

    @app.get("/api/leads/{lead_id}")
    def lead_detail(lead_id: int):
        with engine.connect() as conn:
            row = conn.execute(select(leads).where(leads.c.id == lead_id)).mappings().first()
            if not row:
                raise HTTPException(404, "No such lead.")
            return {**_lead(row), "drafts": approvals.list_drafts(conn, "all", lead_id=lead_id)}

    @app.get("/api/accounts")
    def list_accounts():
        d = today()
        with engine.connect() as conn:
            accts = crm.all_accounts(conn, d)
            summary = crm.summary(conn, d)
            waiting = {r["account_id"] for r in conn.execute(select(drafts.c.account_id).where(
                drafts.c.account_id.is_not(None), drafts.c.status.in_(approvals.OPEN))).mappings()}
        for a in accts:
            a["score"], a["score_reason"] = crm.account_score(a, d)
            a["followup_waiting"] = a["id"] in waiting
        accts.sort(key=lambda a: (-a["score"], a["id"]))
        return {"summary": summary, "accounts": [as_dict(a) for a in accts]}

    @app.post("/api/crm/import")
    async def import_crm(request: Request):
        """Replace the sample CRM with a real export (CSV text). Dates are kept exactly as exported."""
        limiter.check(request, cost=3)
        body = await request.body()
        if len(body) > crm_import.MAX_BYTES:
            raise HTTPException(413, "The file is over 2 MB.")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "Save the export as UTF-8 CSV and try again.") from None
        with engine.connect() as conn:
            if conn.execute(select(agent_runs.c.id).where(agent_runs.c.status == "running")).first():
                raise HTTPException(409, "Wait for the current run to finish before importing.")
        try:
            rows_in, rep = crm_import.parse(text, today_fn())
        except crm_import.CrmImportError as exc:
            raise HTTPException(422, str(exc)) from None
        return crm_import.replace_crm(engine, rows_in, rep)

    @app.get("/api/accounts/{account_id}")
    def account_detail(account_id: str):
        d = today()
        with engine.connect() as conn:
            row = conn.execute(select(accounts).where(accounts.c.id == account_id)).mappings().first()
            if not row:
                raise HTTPException(404, "No such account.")
            a = dict(row)
            a["flags"] = crm.flags(a, d)
            a["score"], a["score_reason"] = crm.account_score(a, d)
            return {**as_dict(a), "drafts": approvals.list_drafts(conn, "all", account_id=account_id)}

    # ------------------------------------------------------------------- approval queue
    @app.get("/api/drafts")
    def list_drafts(which: str = "queue"):
        if which not in ("queue", "all", "approved", "rejected", "edited", "pending"):
            raise HTTPException(422, "Unknown filter.")
        with engine.connect() as conn:
            return approvals.list_drafts(conn, which)

    @app.post("/api/drafts/{draft_id}/approve")
    def approve(draft_id: int, request: Request):
        limiter.check(request)
        return approvals.approve(engine, draft_id)

    @app.post("/api/drafts/{draft_id}/edit")
    def edit(draft_id: int, body: EditIn, request: Request):
        limiter.check(request)
        return approvals.edit(engine, draft_id, body.subject, body.body)

    @app.post("/api/drafts/{draft_id}/reject")
    def reject(draft_id: int, body: RejectIn, request: Request):
        limiter.check(request)
        return approvals.reject(engine, draft_id, body.reason)

    @app.get("/api/drafts/{draft_id}/eml")
    def export_eml(draft_id: int):
        name, text = approvals.eml(engine, draft_id)
        return Response(text, media_type="message/rfc822", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/feedback")
    def recent_feedback():
        with engine.connect() as conn:
            items = agent.feedback_context(conn)
        return {"items": [as_dict(i) for i in items], "lines": agent.feedback_lines(items)}

    @app.get("/api/proof")
    def before_after():
        with engine.connect() as conn:
            return approvals.proof(conn)

    # ------------------------------------------------------------------- report and ops
    @app.get("/api/report")
    def weekly_report():
        d = today()
        with engine.connect() as conn:
            return report.build(conn, d)

    @app.get("/api/log")
    def activity(limit: int = 30):
        with engine.connect() as conn:
            rows = conn.execute(select(activity_log).order_by(activity_log.c.id.desc()).limit(max(1, min(limit, 100)))).mappings()
            return [as_dict(r) for r in rows]

    @app.post("/api/demo/reset")
    def demo_reset(request: Request):
        limiter.check(request, cost=5)
        with engine.connect() as conn:
            if conn.execute(select(agent_runs.c.id).where(agent_runs.c.status == "running")).first():
                raise HTTPException(409, "Wait for the current run to finish before resetting.")
        return reset(engine, today_fn())

    dist = Path(settings.frontend_dist)
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="site")
    return app
