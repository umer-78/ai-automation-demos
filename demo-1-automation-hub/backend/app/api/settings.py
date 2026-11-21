"""Settings page: add, replace, test and remove API keys without redeploying."""

from __future__ import annotations

import hmac
import smtplib
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_ctx, rate_limit
from app.context import Context, apply_settings
from app.services import connectors, secrets

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
        return (403, "This hub holds real client data. Set OWNER_TOKEN on the server to open it.") if base.is_production else None
    if given and any(hmac.compare_digest(given.encode(), c.encode()) for c in codes):
        return None
    return 401, "This hub holds real client data. Enter your access code."


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
        if provider == "google":
            if not s.google_live:
                return {"ok": False, "message": "Save the client ID and secret, then use Sign in with Google."}
            return {"ok": True, "message": connectors.test_google(s)}
        if provider == "google_ads":
            if not s.google_ads_live:
                return {"ok": False, "message": "Needs the developer token and a Google sign-in."}
            return {"ok": True, "message": connectors.test_google_ads(s)}
        if provider == "meta_ads":
            if not s.meta_live:
                return {"ok": False, "message": "No access token saved."}
            return {"ok": True, "message": connectors.test_meta(s)}
        if provider == "anthropic":
            if not s.anthropic_api_key:
                return {"ok": False, "message": "No key saved."}
            r = httpx.get("https://api.anthropic.com/v1/models", headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"}, timeout=10)
            return {"ok": r.status_code == 200, "message": "Claude answered." if r.status_code == 200 else f"Claude refused the key (HTTP {r.status_code})."}
        if provider == "airtable":
            if not s.airtable_live:
                return {"ok": False, "message": "Token and base ID are both needed."}
            r = httpx.get(f"https://api.airtable.com/v0/meta/bases/{s.airtable_base_id}/tables", headers={"Authorization": f"Bearer {s.airtable_token}"}, timeout=10)
            return {"ok": r.status_code == 200, "message": "Airtable base found." if r.status_code == 200 else f"Airtable said HTTP {r.status_code}."}
        if provider == "slack":
            if not s.slack_webhook_url:
                return {"ok": False, "message": "No webhook saved."}
            r = httpx.post(s.slack_webhook_url, json={"text": "Northwind hub: test message from Settings."}, timeout=10)
            return {"ok": r.status_code == 200, "message": "Test message posted." if r.status_code == 200 else f"Slack said HTTP {r.status_code}."}
        if provider == "make":
            if not s.make_onboarding_webhook_url:
                return {"ok": False, "message": "No webhook saved."}
            r = httpx.post(s.make_onboarding_webhook_url, json={"event": "settings.test"}, timeout=10)
            return {"ok": r.status_code < 300, "message": "Make accepted the test event." if r.status_code < 300 else f"Make said HTTP {r.status_code}."}
        if provider == "email":
            if not s.smtp_host:
                return {"ok": False, "message": "No SMTP host saved."}
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
            return {"ok": True, "message": "Signed in to the mail server."}
        if provider == "supabase":
            if not s.storage_live:
                return {"ok": False, "message": "Project URL and service role key are both needed."}
            r = httpx.get(f"{s.supabase_url.rstrip('/')}/storage/v1/bucket", headers={"Authorization": f"Bearer {s.supabase_service_role_key}", "apikey": s.supabase_service_role_key}, timeout=10)
            return {"ok": r.status_code == 200, "message": "Storage answered." if r.status_code == 200 else f"Supabase said HTTP {r.status_code}."}
    except connectors.ConnectorError as e:
        return {"ok": False, "message": str(e)}
    except (httpx.HTTPError, OSError, smtplib.SMTPException) as e:
        return {"ok": False, "message": f"Could not connect: {type(e).__name__}."}
    raise HTTPException(404, "Unknown provider.")
