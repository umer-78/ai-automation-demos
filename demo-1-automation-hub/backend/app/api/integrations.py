"""Airtable webhook bridge (free plan) and admin endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.api.deps import get_ctx, require_admin
from app.context import Context
from app.seed import seed_demo
from app.services.airtable import AirtableError, verify_webhook_mac
from app.workflows.airtable_bridge import STATE_KEY, kv_get, kv_set, process_payloads

router = APIRouter()


@router.post("/api/webhooks/airtable", tags=["airtable"])
async def airtable_ping(request: Request, background: BackgroundTasks, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    state = kv_get(ctx, STATE_KEY)
    if not state or not ctx.airtable.live:
        raise HTTPException(404, "Airtable webhook is not registered")
    body = await request.body()
    if not verify_webhook_mac(state.get("mac_secret", ""), body, request.headers.get("x-airtable-content-mac")):
        raise HTTPException(401, "invalid Airtable signature")
    background.add_task(process_payloads, ctx)
    return {"ok": True}


@router.post("/api/admin/airtable/webhook", dependencies=[Depends(require_admin)], tags=["admin"])
def register_airtable_webhook(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    if not ctx.airtable.live:
        raise HTTPException(400, "set AIRTABLE_TOKEN and AIRTABLE_BASE_ID first")
    url = f"{ctx.settings.public_base_url.rstrip('/')}/api/webhooks/airtable"
    try:
        created = ctx.airtable.create_webhook(url)
    except AirtableError as exc:
        raise HTTPException(502, str(exc))
    kv_set(ctx, STATE_KEY, {"id": created["id"], "mac_secret": created["macSecretBase64"], "cursor": 1, "expires": created.get("expirationTime")})
    return {"webhook_id": created["id"], "notification_url": url, "expires": created.get("expirationTime")}


@router.post("/api/admin/airtable/webhook/refresh", dependencies=[Depends(require_admin)], tags=["admin"])
def refresh_airtable_webhook(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    state = kv_get(ctx, STATE_KEY)
    if not state:
        raise HTTPException(404, "no webhook registered")
    try:
        result = ctx.airtable.refresh_webhook(state["id"])
    except AirtableError as exc:
        raise HTTPException(502, str(exc))
    kv_set(ctx, STATE_KEY, {**state, "expires": result.get("expirationTime")})
    return {"webhook_id": state["id"], "expires": result.get("expirationTime")}


@router.post("/api/admin/reset", dependencies=[Depends(require_admin)], tags=["admin"])
def reset_demo(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return seed_demo(ctx, reset=True)
