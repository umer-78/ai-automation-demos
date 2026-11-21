"""Shared FastAPI dependencies: context access, API keys, rate limiting, request models."""

from __future__ import annotations

import hmac
import logging
import re
from typing import Any

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.context import Context
from app.workflows.clients import normalize_services

log = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def require_automation_key(request: Request, x_automation_key: str | None = Header(default=None)) -> None:
    ctx = get_ctx(request)
    _check_secret(ctx.settings.automation_api_key, x_automation_key, name="X-Automation-Key", production=ctx.settings.is_production)


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    ctx = get_ctx(request)
    if not ctx.settings.admin_token:
        raise HTTPException(403, "admin endpoints are disabled (set ADMIN_TOKEN)")
    _check_secret(ctx.settings.admin_token, x_admin_token, name="X-Admin-Token", production=True)


def rate_limit(request: Request, x_automation_key: str | None = Header(default=None)) -> None:
    ctx = get_ctx(request)
    key = ctx.settings.automation_api_key
    if key and x_automation_key and hmac.compare_digest(x_automation_key.encode(), key.encode()):
        return  # trusted automation traffic is not rate limited
    allowed, retry = request.app.state.limiter.allow(client_ip(request))
    if not allowed:
        raise HTTPException(
            429,
            f"Demo limit reached for this hour. Try again in about {max(1, retry // 60)} minute(s).",
            headers={"Retry-After": str(retry)},
        )


# --------------------------------------------------------------------------- request models
class ClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    website: str | None = Field(default=None, max_length=300)
    industry: str = Field(min_length=2, max_length=120)
    services: list[str] | str = Field(description="Any of: SEO, Paid Ads, Web Design")
    manager: str = Field(min_length=2, max_length=80)
    manager_email: str | None = Field(default=None, max_length=200)
    monthly_budget: float | None = Field(default=None, ge=0, le=10_000_000)
    airtable_record_id: str | None = Field(default=None, pattern=r"^rec[A-Za-z0-9]{14}$")
    simulate_failure: bool = False
    run_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{6,40}$")

    @field_validator("services")
    @classmethod
    def _services(cls, value: Any) -> list[str]:
        services = normalize_services(value)
        if not services:
            raise ValueError("choose at least one service: SEO, Paid Ads or Web Design")
        return services

    @field_validator("manager_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not EMAIL_RE.match(value):
            raise ValueError("invalid email address")
        return value

    @field_validator("website")
    @classmethod
    def _website(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        if not re.match(r"^(https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/.*)?$", value):
            raise ValueError("website must look like example.com or https://example.com")
        return value if value.startswith("http") else f"https://{value}"

    @field_validator("name", "industry", "manager")
    @classmethod
    def _strip(cls, value: str) -> str:
        return " ".join(value.split())


class SiteIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=80)
    industry: str = Field(min_length=2, max_length=80)
    tone: str = Field(min_length=2, max_length=60)
    services: list[str] = Field(min_length=3, max_length=3)
    colour: str = Field(min_length=2, max_length=40)
    client_id: int | None = None

    @field_validator("services")
    @classmethod
    def _services(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(s.split())[:60] for s in value]
        if any(len(s) < 2 for s in cleaned):
            raise ValueError("each service needs at least 2 characters")
        return cleaned


class RegenerateIn(BaseModel):
    section: str = Field(pattern=r"^(hero|services|proof|cta)$")
    instruction: str = Field(default="", max_length=300)
