"""FastAPI entry point: `uvicorn app.main:app --reload` (run from the backend/ folder)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import __version__, seo
from app.api import agent, automation, core, data, drafts, insights, records
from app.api import settings as settings_api
from app.api.settings import access_problem
from app.config import Settings, get_settings
from app.context import Context, apply_settings, build_context
from app.seed import is_empty, seed_demo
from app.services import data_mode, secrets
from app.services.ratelimit import RateLimiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("acme")
STATIC_DIR = Path(__file__).resolve().parent / "static"
RESERVED_PREFIXES = ("api/", "docs", "redoc", "openapi.json")


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


def create_app(
    settings: Settings | None = None,
    *,
    llm_client=None,
    http=None,
    context: Context | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    static_dir = (static_dir or STATIC_DIR).resolve()

    async def hubspot_loop(app: FastAPI) -> None:
        """Real-data mode with HubSpot connected: read the CRM again every few minutes."""
        ctx = app.state.ctx
        while True:
            await asyncio.sleep(max(1, settings.hubspot_sync_minutes) * 60)
            try:
                if ctx.settings.hubspot_live and await run_in_threadpool(data_mode.get_mode, ctx) == "real":
                    await run_in_threadpool(data.sync_hubspot, ctx, "schedule")
            except asyncio.CancelledError:
                raise
            except Exception:  # logged and alerted by sync_hubspot
                log.exception("HubSpot sync failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = app.state.ctx
        if settings.auto_seed and data_mode.get_mode(ctx) == "demo" and is_empty(ctx):
            log.info("seeded mock CRM: %s", seed_demo(ctx))
        task = asyncio.create_task(hubspot_loop(app)) if settings.hubspot_sync_minutes > 0 else None
        yield
        if task:
            task.cancel()
        ctx.engine.dispose()

    app = FastAPI(
        title="Acme Cloud Security Sales Agent",
        version=__version__,
        description="An AI sales agent that researches leads, analyses a mock CRM, scores and drafts outreach. "
        "A person approves every message; the app has no way to send email.",
        lifespan=lifespan,
    )
    app.state.ctx = context or build_context(settings, llm_client=llm_client, http=http)
    app.state.base_settings = settings
    saved = secrets.load_saved(app.state.ctx.engine, settings)
    if saved:
        apply_settings(app.state.ctx, secrets.effective(settings, saved))
    app.state.run_limiter = RateLimiter(settings.agent_runs_per_hour)
    app.state.review_limiter = RateLimiter(settings.review_actions_per_hour)

    app.add_middleware(GZipMiddleware, minimum_size=800)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Automation-Key", "X-Admin-Token", "X-Owner-Token"],
    )

    open_api = ("/api/health",)
    self_guarded = ("/api/settings", "/api/data/", "/api/admin/")

    @app.middleware("http")
    async def real_data_lock(request: Request, call_next):
        """Once your own CRM is loaded, reading it needs the owner (or viewer) access code."""
        path = request.url.path
        guarded = (
            path.startswith("/api/")
            and request.method != "OPTIONS"
            and path not in open_api
            and not path.startswith(self_guarded)
            and not path.startswith("/api/automation/")  # cron and Make use X-Automation-Key
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
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - last-resort guard
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal error. It has been logged."})

    for module in (core, agent, records, drafts, insights, automation, settings_api, data):
        app.include_router(module.router)

    # ------------------------------------------------------------- search engines and the dashboard
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
