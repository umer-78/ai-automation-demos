"""Demo 1 — Agency Automation Hub (Northwind Digital). FastAPI service + the built 3D front end.

    uvicorn app.main:create_app --factory --reload      # from demo-1-automation-hub/backend
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import checks, importer, mockdata, reporting, seed, sites
from .config import Settings, get_settings
from .db import automation_log, clients, email_drafts, jdump, jload, make_engine, metadata, now_utc, summaries, tasks, tx
from .llm import OFFLINE, offline_summary
from .onboarding import (BadRequest, Deps, NotFound, alert_failure, client_dict, create_client, forced_failure,
                         run_offboarding, run_onboarding, upsert_client_from_airtable)
from .security import PREVIEW_CSP, RateLimiter, SecurityHeaders, require_token

Service = Literal["SEO", "Paid Ads", "Web Design"]


class NewClient(BaseModel):
    name: str = Field(max_length=120)
    website: str | None = Field(default=None, max_length=300)
    industry: str | None = Field(default=None, max_length=200)
    services: list[Service] = Field(min_length=1, max_length=3)
    manager: str | None = Field(default=None, max_length=120)
    manager_email: str | None = Field(default=None, max_length=200)
    onboard: bool = True


class OnboardReq(BaseModel):
    client_id: str = Field(max_length=40)
    service: Service


class JobReq(BaseModel):
    source: Literal["mock-api", "csv"] = "mock-api"


class SummaryReq(BaseModel):
    refresh: bool = False


class SiteReq(BaseModel):
    business_name: str = Field(max_length=80)
    industry: str = Field(max_length=80)
    tone: str = Field(default="confident", max_length=20)
    services: list[str] = Field(min_length=3, max_length=3)
    colour: str = Field(default="#4f46e5", max_length=7)
    client_id: str | None = Field(default=None, max_length=40)


class RegenReq(BaseModel):
    section: Literal["hero", "services", "proof", "cta"]
    instructions: str = Field(default="", max_length=500)


class MakeClient(BaseModel):
    record_id: str = Field(max_length=40)
    name: str = Field(max_length=120)
    website: str | None = None
    industry: str | None = None
    services: list[str] | str = Field(default_factory=list)
    manager: str | None = None
    manager_email: str | None = None
    service: Service


class MakeRecord(BaseModel):
    record_id: str = Field(max_length=40)


class MakeFailure(BaseModel):
    scenario: str = Field(max_length=120)
    error: str = Field(max_length=1000)
    detail: str = Field(default="", max_length=1000)


def create_app(settings: Settings | None = None, today_fn: Callable[[], date] = date.today) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    deps = Deps.build(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    app = FastAPI(title="Northwind Digital — Agency Automation Hub", version="2.0.0",
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.add_middleware(SecurityHeaders)
    app.state.engine, app.state.deps, app.state.settings = engine, deps, settings

    metadata.create_all(engine)
    with tx(engine) as conn:
        empty = conn.execute(select(func.count()).select_from(clients)).scalar_one() == 0
    if empty:
        seed.reset(engine, today_fn())

    def ensure_fresh() -> None:
        today = today_fn()
        with tx(engine) as conn:
            latest = reporting.latest_metric_date(conn)
            if latest is None or latest < today:
                reporting.run_daily_job(conn, today, source="mock ad API (catch-up on page load)")

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(BadRequest)
    async def _br(_: Request, exc: BadRequest):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ---------------- read endpoints ----------------
    @app.get("/api/status")
    def status():
        with tx(engine) as conn:
            latest = reporting.latest_metric_date(conn)
            n_clients = conn.execute(select(func.count()).select_from(clients)).scalar_one()
        return {"ok": True, "today": today_fn().isoformat(), "engine": deps.llm.label, "live_model": deps.llm.live,
                "database": settings.database_kind, "latest_data": latest.isoformat() if latest else None,
                "clients": n_clients, "integrations": {
                    "airtable": settings.airtable_enabled, "make_webhooks": bool(settings.hub_api_token),
                    "slack": settings.slack_enabled, "supabase_storage": settings.storage_enabled,
                    "email": settings.smtp_enabled}}

    @app.get("/api/dashboard")
    def dashboard():
        ensure_fresh()
        with tx(engine) as conn:
            return reporting.dashboard(conn, today_fn())

    @app.get("/api/clients")
    def list_clients():
        with tx(engine) as conn:
            out = [client_dict(r) for r in conn.execute(select(clients).order_by(clients.c.created_at, clients.c.id))]
            counts = {(r.client_id, r.status): r.n for r in conn.execute(
                select(tasks.c.client_id, tasks.c.status, func.count().label("n")).group_by(tasks.c.client_id, tasks.c.status))}
        for c in out:
            c["open_tasks"], c["closed_tasks"] = counts.get((c["id"], "open"), 0), counts.get((c["id"], "closed"), 0)
        return out

    @app.get("/api/clients/{client_id}")
    def get_client(client_id: str):
        with tx(engine) as conn:
            row = conn.execute(select(clients).where(clients.c.id == client_id)).first()
            if not row:
                raise NotFound("client not found")
            c = client_dict(row)
            c["tasks"] = [dict(r._mapping) | {"created_at": r.created_at.isoformat(),
                                               "closed_at": r.closed_at.isoformat() if r.closed_at else None}
                          for r in conn.execute(select(tasks).where(tasks.c.client_id == client_id).order_by(tasks.c.id))]
            c["emails"] = [dict(r._mapping) | {"created_at": r.created_at.isoformat()} for r in conn.execute(
                select(email_drafts).where(email_drafts.c.client_id == client_id).order_by(email_drafts.c.id.desc()).limit(5))]
        return c

    @app.get("/api/log")
    def get_log(limit: int = Query(30, ge=1, le=200)):
        with tx(engine) as conn:
            rs = conn.execute(select(automation_log).order_by(automation_log.c.id.desc()).limit(limit)).mappings().all()
        return [dict(r) | {"created_at": r["created_at"].isoformat()} for r in rs]

    @app.get("/api/mock/ad-platform/performance")
    def mock_ad_api(day: date = Query(alias="date")):
        """The mock ad platform the daily job reads (spec Module B, step 2)."""
        today = today_fn()
        if day > today:
            raise BadRequest("No data for future dates.")
        with tx(engine) as conn:
            ids = reporting.reportable_client_ids(conn)
        return {"date": day.isoformat(), "rows": [r | {"date": r["date"].isoformat()} for r in mockdata.ad_rows_for(day, today, ids)]}

    @app.get("/api/integrity")
    def integrity():
        return checks.integrity(engine, today_fn(), deps.llm.label)

    @app.get("/api/lineage")
    def lineage():
        return {"today": today_fn().isoformat(), "metrics": checks.lineage(engine, today_fn())}

    @app.get("/api/training-data")
    def training_data():
        return PlainTextResponse(checks.training_data(engine), media_type="application/x-ndjson",
                                 headers={"Content-Disposition": "attachment; filename=hub-training-data.jsonl"})

    # ---------------- Module A ----------------
    @app.post("/api/clients", status_code=201)
    def add_client(req: NewClient, request: Request):
        limiter.check(request)
        result = create_client(engine, deps, req.model_dump())
        runs = []
        # With Airtable connected, the Airtable automation + Make.com run onboarding; otherwise run it directly.
        if req.onboard and not result["airtable"].get("record_id"):
            runs = [run_onboarding(engine, deps, result["client"]["id"], s, "direct") for s in result["client"]["services"]]
        return {**result, "onboarding": runs,
                "mode": "airtable+make" if result["airtable"].get("record_id") else "direct"}

    @app.post("/api/onboarding")
    def onboarding(req: OnboardReq, request: Request):
        limiter.check(request, cost=2)
        return run_onboarding(engine, deps, req.client_id, req.service, "direct")

    @app.post("/api/clients/{client_id}/churn")
    def churn(client_id: str, request: Request):
        limiter.check(request)
        return run_offboarding(engine, deps, client_id, "dashboard")

    @app.post("/api/test/forced-failure")
    def test_failure(request: Request):
        limiter.check(request)
        return forced_failure(engine, deps)

    # ---------------- Module B ----------------
    @app.post("/api/reporting/job")
    def reporting_job(req: JobReq, request: Request):
        limiter.check(request)
        today = today_fn()
        source_rows = None
        if req.source == "csv":
            source_rows = [r for r in mockdata.read_csv(seed.SAMPLE_CSV)] if seed.SAMPLE_CSV.exists() else []
        with tx(engine) as conn:
            return reporting.run_daily_job(conn, today, source_rows,
                                           "sample CSV" if req.source == "csv" else "mock ad API")

    @app.post("/api/reporting/import")
    async def import_ad_export(request: Request, channel: str | None = Query(default=None, max_length=20)):
        """Upload a real Google Ads or Meta export (CSV text). Rows are upserted, so re-importing never double counts."""
        limiter.check(request, cost=3)
        body = await request.body()
        if len(body) > importer.MAX_BYTES:
            raise HTTPException(413, "The file is over 2 MB. Export a shorter date range.")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "Save the export as UTF-8 CSV and try again.") from None
        today = today_fn()
        with tx(engine) as conn:
            known = [{"id": r.id, "name": r.name} for r in conn.execute(select(clients.c.id, clients.c.name)
                                                                       .where(clients.c.status != "Archived"))]
            try:
                rows_in, report = importer.parse(text, known, channel, today)
            except importer.ImportError_ as exc:
                raise HTTPException(422, str(exc)) from None
            job = reporting.run_daily_job(conn, today, rows_in, "uploaded ad export")
        return {**report, "upserted": job["upserted"], "duplicate_rows": job["duplicate_rows"]}

    @app.post("/api/reporting/weekly-summary")
    def weekly_summary(req: SummaryReq, request: Request):
        limiter.check(request, cost=3)
        ensure_fresh()
        today = today_fn()
        with tx(engine) as conn:
            numbers = reporting.client_week_numbers(conn, reporting.Windows(today))
            cached = {} if req.refresh else {r.client_id: r for r in conn.execute(
                select(summaries).where(summaries.c.week_end == today))}
        if numbers and all(n["client_id"] in cached and cached[n["client_id"]].engine == deps.llm.label for n in numbers):
            texts = {cid: jload(r.sentences, []) for cid, r in cached.items()}
            engine_label = deps.llm.label + " (cached today)"
        else:
            try:
                texts, engine_label = deps.llm.weekly_summaries(numbers)
            except Exception as exc:  # noqa: BLE001
                alert_failure(engine, deps, "weekly_summary", str(exc)[:300], "fell back to the offline engine")
                texts = {n["client_id"]: offline_summary(n) for n in numbers}
                engine_label = f"{OFFLINE.split(' (')[0]} (Claude error, fell back)"
            with tx(engine) as conn:
                conn.execute(summaries.delete().where(summaries.c.week_end == today))
                for n in numbers:
                    conn.execute(summaries.insert().values(client_id=n["client_id"], week_end=today,
                                                           sentences=jdump(texts[n["client_id"]]), engine=engine_label,
                                                           created_at=now_utc()))
        return {"engine": engine_label, "week": reporting.Windows(today).cur7[0].isoformat() + " to " + today.isoformat(),
                "clients": [{**n, "sentences": texts.get(n["client_id"], [])} for n in numbers]}

    # ---------------- Module C ----------------
    @app.post("/api/sites", status_code=201)
    def new_site(req: SiteReq, request: Request):
        limiter.check(request, cost=3)
        return sites.generate(engine, deps, req.model_dump())

    @app.get("/api/sites/{site_id}")
    def get_site(site_id: str):
        return {**sites.latest(engine, site_id), "versions": sites.versions(engine, site_id)}

    @app.post("/api/sites/{site_id}/regenerate")
    def regen(site_id: str, req: RegenReq, request: Request):
        limiter.check(request, cost=2)
        return sites.regenerate(engine, deps, site_id, req.section, req.instructions)

    @app.get("/api/sites/{site_id}/preview", response_class=HTMLResponse)
    def preview(site_id: str, v: int | None = None):
        d = sites.latest(engine, site_id, v)
        return HTMLResponse(d["html"], headers={"Content-Security-Policy": PREVIEW_CSP, "X-Frame-Options": "SAMEORIGIN"})

    # ---------------- demo controls ----------------
    @app.post("/api/demo/reset")
    def demo_reset(request: Request):
        limiter.check(request, cost=5)
        return seed.reset(engine, today_fn())

    # ---------------- integration hooks (Make.com, cron) ----------------
    @app.post("/api/hooks/make/onboarding")
    def hook_onboarding(req: MakeClient, request: Request):
        require_token(request, settings.hub_api_token)
        cid = upsert_client_from_airtable(engine, deps, req.model_dump())
        return run_onboarding(engine, deps, cid, req.service, "make")

    @app.post("/api/hooks/make/offboarding")
    def hook_offboarding(req: MakeRecord, request: Request):
        require_token(request, settings.hub_api_token)
        with tx(engine) as conn:
            row = conn.execute(select(clients.c.id).where(clients.c.airtable_record_id == req.record_id)).first()
        if not row:
            raise NotFound("no client for that Airtable record")
        return run_offboarding(engine, deps, row[0], "make")

    @app.post("/api/hooks/make/failure")
    def hook_failure(req: MakeFailure, request: Request):
        require_token(request, settings.hub_api_token)
        slack = alert_failure(engine, deps, f"make:{req.scenario}", req.error, req.detail or "reported by Make.com error route")
        return {"logged": True, "slack": slack}

    @app.post("/api/hooks/cron/daily-report")
    def hook_cron(request: Request):
        require_token(request, settings.hub_api_token)
        with tx(engine) as conn:
            return reporting.run_daily_job(conn, today_fn(), source="mock ad API (scheduled)")

    # ---------------- the 3D front end ----------------
    dist = Path(settings.frontend_dist)
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def no_frontend():
            return {"detail": "API is running. Build the front end (npm run build in ../frontend) to serve the UI.",
                    "docs": "/api/docs"}

    @app.exception_handler(404)
    async def _not_found(request: Request, exc: HTTPException):
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)

    return app
