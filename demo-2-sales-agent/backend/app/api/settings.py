"""Settings page: add, replace, test and remove API keys without redeploying."""

from __future__ import annotations

import hmac
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_ctx
from app.api.deps import limit_reviews as rate_limit
from app.context import Context, apply_settings
from app.services import hubspot, secrets

router = APIRouter()


class KeysIn(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


def require_owner(request: Request, x_owner_token: str | None = Header(default=None)) -> None:
    ctx: Context = get_ctx(request)
    base = request.app.state.base_settings
    if not base.owner_token:
        if base.is_production:
            raise HTTPException(403, "Saving keys is turned off. Set OWNER_TOKEN on the server to turn it on.")
        return  # local development: anyone on this machine is the owner
    if not x_owner_token or not hmac.compare_digest(x_owner_token.encode(), base.owner_token.encode()):
        raise HTTPException(401, "Owner token is missing or wrong.")
    del ctx


def access_problem(base, ctx: Context, given: str | None) -> tuple[int, str] | None:
    """Why this request may not read real client data, or None when it may."""
    codes = [c for c in (base.owner_token, base.viewer_token) if c]
    if not codes:
        return (403, "This app holds your real CRM data. Set OWNER_TOKEN on the server to open it.") if base.is_production else None
    if given and any(hmac.compare_digest(given.encode(), c.encode()) for c in codes):
        return None
    return 401, "This app holds your real CRM data. Enter your access code."


@router.get("/api/settings")
def get_settings_page(request: Request, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    base = request.app.state.base_settings
    saved = secrets.load_saved(ctx.engine, base)
    ok, why = secrets.can_store(base)
    return {
        "owner_token_required": bool(base.owner_token) or base.is_production,
        "can_store": ok,
        "store_note": why,
        "providers": secrets.describe(base, ctx.settings, saved),
    }


@router.put("/api/settings/{provider}", dependencies=[Depends(require_owner), Depends(rate_limit)])
def save_keys(provider: str, body: KeysIn, request: Request, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    p = next((x for x in secrets.PROVIDERS if x.id == provider), None)
    if not p:
        raise HTTPException(404, "Unknown provider.")
    base = request.app.state.base_settings
    ok, why = secrets.can_store(base)
    if not ok:
        raise HTTPException(409, why)
    allowed = {f.key for f in p.fields}
    values = {k: v for k, v in body.values.items() if k in allowed}
    if not values:
        raise HTTPException(422, "Nothing to save.")
    if any(len(v) > 2000 for v in values.values()):
        raise HTTPException(422, "That value is too long.")
    secrets.save(ctx.engine, base, values)
    apply_settings(ctx, secrets.effective(base, secrets.load_saved(ctx.engine, base)))
    return get_settings_page(request, ctx)


@router.delete("/api/settings/{provider}", dependencies=[Depends(require_owner)])
def remove_keys(provider: str, request: Request, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    p = next((x for x in secrets.PROVIDERS if x.id == provider), None)
    if not p:
        raise HTTPException(404, "Unknown provider.")
    base = request.app.state.base_settings
    secrets.save(ctx.engine, base, {f.key: "" for f in p.fields})
    apply_settings(ctx, secrets.effective(base, secrets.load_saved(ctx.engine, base)))
    return get_settings_page(request, ctx)


@router.post("/api/settings/{provider}/test", dependencies=[Depends(require_owner), Depends(rate_limit)])
def test_keys(provider: str, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    s = ctx.settings
    try:
        if provider == "company":
            return {"ok": True, "message": f"Emails are signed {s.rep_name}, {s.rep_title}, {s.seller_company}."}
        if provider == "anthropic":
            if not s.anthropic_api_key:
                return {"ok": False, "message": "No key saved."}
            r = httpx.get("https://api.anthropic.com/v1/models", headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"}, timeout=10)
            return {"ok": r.status_code == 200, "message": "Claude answered." if r.status_code == 200 else f"Claude refused the key (HTTP {r.status_code})."}
        if provider == "tavily":
            if not s.tavily_api_key:
                return {"ok": False, "message": "No key saved."}
            r = httpx.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {s.tavily_api_key}"}, json={"query": "SOC 2 certification announced", "max_results": 1}, timeout=20)
            return {"ok": r.status_code == 200, "message": "Tavily answered with live results." if r.status_code == 200 else f"Tavily refused the key (HTTP {r.status_code})."}
        if provider == "hubspot":
            if not s.hubspot_live:
                return {"ok": False, "message": "No token saved."}
            return {"ok": True, "message": hubspot.test(s)}
        if provider == "slack":
            if not s.slack_webhook_url:
                return {"ok": False, "message": "No webhook saved."}
            r = httpx.post(s.slack_webhook_url, json={"text": f"{s.seller_company} sales agent: test message from Settings."}, timeout=10)
            return {"ok": r.status_code == 200, "message": "Test message posted." if r.status_code == 200 else f"Slack said HTTP {r.status_code}."}
    except hubspot.HubSpotError as e:
        return {"ok": False, "message": str(e)}
    except (httpx.HTTPError, OSError) as e:
        return {"ok": False, "message": f"Could not connect: {type(e).__name__}."}
    raise HTTPException(404, "Unknown provider.")
