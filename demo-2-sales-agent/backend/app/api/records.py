"""Leads (from web research) and accounts (mock CRM)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.deps import get_ctx
from app.context import Context
from app.db import drafts, leads, row_to_dict, rows_to_dicts
from app.workflows import crm

router = APIRouter(prefix="/api")


@router.get("/leads")
def list_leads(
    status: str | None = Query(default=None, pattern=r"^(new|drafted|approved|contacted|excluded)$"),
    ctx: Context = Depends(get_ctx),
) -> list[dict[str, Any]]:
    q = select(leads).order_by(leads.c.score.desc(), leads.c.id)
    if status:
        q = q.where(leads.c.status == status)
    with ctx.engine.connect() as conn:
        return rows_to_dicts(conn.execute(q))


@router.get("/leads/{lead_id}")
def lead_detail(lead_id: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = conn.execute(select(leads).where(leads.c.id == lead_id)).first()
        if not row:
            raise HTTPException(404, "Lead not found")
        lead = row_to_dict(row)
        lead["drafts"] = rows_to_dicts(conn.execute(select(drafts).where(drafts.c.lead_id == lead_id).order_by(drafts.c.created_at.desc())))
    return lead


@router.get("/accounts")
def list_accounts(
    flag: str | None = Query(default=None, pattern=r"^(stalled|no_contact|upsell)$"),
    stage: str | None = Query(default=None, pattern=r"^(Prospect|Discovery|Proposal|Customer)$"),
    ctx: Context = Depends(get_ctx),
) -> list[dict[str, Any]]:
    return crm.list_accounts(ctx.engine, flag=flag, stage=stage)


@router.get("/accounts/{account_id}")
def account_detail(account_id: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    detail = crm.account_detail(ctx.engine, account_id)
    if not detail:
        raise HTTPException(404, "Account not found")
    return detail
