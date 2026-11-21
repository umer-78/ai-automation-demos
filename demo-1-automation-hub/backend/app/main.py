"""FastAPI entry point: `uvicorn app.main:app --reload` (run from the backend/ folder)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import __version__, seo
from app.api import data as data_api
from app.api import settings as settings_api
from app.api.settings import access_problem
from app.api import actions, automation, dashboard, integrations
from app.config import Settings, get_settings
from app.db import today_utc
from app.services import data_mode, secrets
from app.context import Context, build_context, apply_settings
from app.seed import is_empty, seed_demo
from app.services.ratelimit import RateLimiter
from app.workflows.metrics_pipeline import run_daily_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("northwind")
STATIC_DIR = Path(__file__).resolve().parent / "static"
RESERVED_PREFIXES = ("api/", "sites/", "mock-api/", "docs", "redoc", "openapi.json")


class ImmutableAssets(StaticFiles):
    """Built files have a content hash in their name, so browsers may keep them for a year."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


class _FileCache:
    """Re-reads a build file only when it changes, so a rebuild never needs a server restart."""

    def __init__(self, path: Path, parse):
        self.path, self.parse = path, parse
        self.mtime: float | None = None
        self.value = None

    def get(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return None
        if mtime != self.mtime:
            self.mtime, self.value = mtime, self.parse(self.path)
        return self.value


def create_app(settings: Settings | None = None, *, llm_client=None, context: Context | None = None, static_dir: Path | None = None) -> FastAPI:
    settings = settings or get_settings()
    static_dir = (static_dir or STATIC_DIR).resolve()

    async def live_sync_loop(app: FastAPI) -> None:
        """Real-data mode: pull fresh numbers from the connected ad accounts every few minutes."""
        ctx = app.state.ctx
        full_pull_on: date | None = None
        while True:
            await asyncio.sleep(max(1, settings.live_sync_minutes) * 60)
            try:
                if not await run_in_threadpool(lambda: data_mode.get_mode(ctx) == "real" and data_mode.live_available(ctx)):
                    continue
                first_today = full_pull_on != today_utc()
                days = await run_in_threadpool(lambda: data_mode.sync_days(ctx, full=first_today))
                await run_in_threadpool(lambda: run_daily_metrics(ctx, source="live", days=days, run_source="schedule", post_alerts=first_today))
                full_pull_on = today_utc()
            except asyncio.CancelledError:
                raise
            except Exception:  # the run log and Slack already carry the failure
                log.exception("live sync failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_seed and is_empty(app.state.ctx):
            result = seed_demo(app.state.ctx)
            log.info("seeded demo data: %s", {k: v for k, v in result.items() if k != "metrics"})
        task = asyncio.create_task(live_sync_loop(app)) if settings.live_sync_minutes > 0 else None
        yield
        if task:
            task.cancel()
        app.state.ctx.engine.dispose()

    app = FastAPI(
        title="Northwind Digital Automation Hub",
        version=__version__,
        description="Client onboarding, campaign reporting and AI website drafts for a marketing agency (demo with synthetic data).",
        lifespan=lifespan,
    )
    app.state.ctx = context or build_context(settings, llm_client=llm_client)
    app.state.base_settings = settings
    if context is None and llm_client is None:  # keys saved from the Settings page override the environment
        saved = secrets.load_saved(app.state.ctx.engine, settings)
        if saved:
            apply_settings(app.state.ctx, secrets.effective(settings, saved))
    app.state.limiter = RateLimiter(settings.rate_limit_per_hour)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Automation-Key", "X-Admin-Token", "X-Owner-Token"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=800)

    open_api = ("/api/health", "/api/status")
    self_guarded = ("/api/settings", "/api/data/", "/api/admin/", "/api/webhooks/")

    @app.middleware("http")
    async def real_data_lock(request: Request, call_next):
        """Once real client numbers are in, reading them needs the owner (or viewer) access code."""
        path = request.url.path
        guarded = (
            path.startswith("/api/")
            and request.method != "OPTIONS"
            and path not in open_api
            and not path.startswith(self_guarded)
            and not (path.startswith("/api/automation/") and request.method != "GET")  # Make.com and cron use their key
        )
        if guarded:
            ctx = request.app.state.ctx
            if await run_in_threadpool(data_mode.get_mode, ctx) == "real":
                problem = access_problem(request.app.state.base_settings, ctx, request.headers.get("x-owner-token"))
                if problem:
                    return JSONResponse(status_code=problem[0], content={"detail": problem[1], "locked": True})
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if "content-security-policy" not in response.headers:  # previews set frame-ancestors instead
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - last-resort guard
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal error. It has been logged."})

    app.include_router(dashboard.router)
    app.include_router(actions.router)
    app.include_router(automation.router)
    app.include_router(integrations.router)
    app.include_router(settings_api.router)
    app.include_router(data_api.router)

    # ------------------------------------------------------------- search engines and the site
    template = _FileCache(static_dir / "index.html", lambda p: p.read_text(encoding="utf-8"))
    seo_config = _FileCache(static_dir / "seo-routes.json", lambda p: seo.load(p.parent))

    def public_base(request: Request) -> str:
        return seo.base_url_for(settings.public_base_url, str(request.base_url), request.url.hostname)

    @app.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
    async def robots(request: Request):
        return PlainTextResponse(seo.robots_txt(public_base(request)), headers={"Cache-Control": "public, max-age=3600"})

    @app.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
    async def sitemap(request: Request):
        body = seo.sitemap_xml(seo_config.get(), public_base(request))
        return Response(body, media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"})

    if (static_dir / "index.html").exists():
        if (static_dir / "assets").is_dir():
            app.mount("/assets", ImmutableAssets(directory=static_dir / "assets"), name="assets")

        @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa(full_path: str, request: Request):
            if full_path.startswith(RESERVED_PREFIXES):
                raise HTTPException(404, "not found")
            if full_path and full_path != "index.html":
                candidate = (static_dir / full_path).resolve()
                if candidate.is_file() and static_dir in candidate.parents:
                    return FileResponse(candidate, headers={"Cache-Control": "public, max-age=3600"})
            body, status = seo.render_index(template.get() or "", seo_config.get(), full_path, public_base(request))
            return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
