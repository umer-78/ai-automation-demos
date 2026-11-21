"""Shared FastAPI dependencies: context access, API keys and rate limits."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request

from app.context import Context


def get_ctx(request: Request) -> Context:
    return request.app.state.ctx


def client_ip(request: Request) -> str:
    ctx: Context = request.app.state.ctx
    if ctx.settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_secret(expected: str, provided: str | None, *, name: str, production: bool) -> None:
    if not expected:
        if production:
            raise HTTPException(503, f"{name} must be configured in production")
        return
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(401, f"invalid or missing {name}")


def _trusted(request: Request, key: str | None) -> bool:
    expected = get_ctx(request).settings.automation_api_key
    return bool(expected and key and hmac.compare_digest(key.encode(), expected.encode()))


def require_automation_key(request: Request, x_automation_key: str | None = Header(default=None)) -> None:
    ctx = get_ctx(request)
    _check_secret(ctx.settings.automation_api_key, x_automation_key, name="X-Automation-Key", production=ctx.settings.is_production)


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    ctx = get_ctx(request)
    if not ctx.settings.admin_token:
        raise HTTPException(403, "admin endpoints are disabled (set ADMIN_TOKEN)")
    _check_secret(ctx.settings.admin_token, x_admin_token, name="X-Admin-Token", production=True)


def _limit(request: Request, limiter_name: str, what: str) -> None:
    allowed, retry = getattr(request.app.state, limiter_name).allow(client_ip(request))
    if not allowed:
        raise HTTPException(
            429,
            f"Demo limit reached for {what}. Try again in about {max(1, retry // 60)} minute(s).",
            headers={"Retry-After": str(retry)},
        )


def limit_agent_runs(request: Request, x_automation_key: str | None = Header(default=None)) -> None:
    if not _trusted(request, x_automation_key):
        _limit(request, "run_limiter", "agent runs this hour")


def limit_reviews(request: Request, x_automation_key: str | None = Header(default=None)) -> None:
    if not _trusted(request, x_automation_key):
        _limit(request, "review_limiter", "review actions this hour")
