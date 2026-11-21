"""Approval queue: Approve, Edit, Reject (with reason), then export and mark as sent by a person."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import get_ctx, limit_reviews
from app.context import Context
from app.db import accounts, drafts, feedback, leads, row_to_dict, rows_to_dicts
from app.workflows import approvals
from app.workflows.approvals import ReviewError

router = APIRouter(prefix="/api")


class ReviewIn(BaseModel):
    reviewer: str | None = Field(default=None, max_length=60)


class EditIn(ReviewIn):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    reason: str | None = Field(default=None, max_length=300)


class RejectIn(ReviewIn):
    reason: str = Field(min_length=3, max_length=300)


def _query():
    return (
        select(
            drafts,
            func.coalesce(leads.c.company, accounts.c.company).label("company"),
            leads.c.score.label("lead_score"),
            leads.c.score_parts.label("lead_score_parts"),
            leads.c.score_reason.label("lead_score_reason"),
            accounts.c.score.label("account_score"),
            accounts.c.flags.label("account_flags"),
            accounts.c.stage.label("account_stage"),
            accounts.c.owner.label("account_owner"),
        )
        .select_from(drafts.outerjoin(leads, leads.c.id == drafts.c.lead_id).outerjoin(accounts, accounts.c.id == drafts.c.account_id))
    )


@router.get("/drafts")
def list_drafts(
    status: str | None = Query(default=None, pattern=r"^(pending|approved|edited|rejected|sent|ready)$"),
    kind: str | None = Query(default=None, pattern=r"^(outreach|follow_up)$"),
    ctx: Context = Depends(get_ctx),
) -> list[dict[str, Any]]:
    q = _query().order_by(drafts.c.created_at.desc(), drafts.c.id.desc())
    if status == "ready":
        q = q.where(drafts.c.status.in_(("approved", "edited")))
    elif status:
        q = q.where(drafts.c.status == status)
    if kind:
        q = q.where(drafts.c.kind == kind)
    with ctx.engine.connect() as conn:
        return rows_to_dicts(conn.execute(q.limit(200)))


@router.get("/drafts/{draft_id}")
def draft_detail(draft_id: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        row = conn.execute(_query().where(drafts.c.id == draft_id)).first()
        if not row:
            raise HTTPException(404, "Draft not found")
        out = row_to_dict(row)
        out["feedback"] = rows_to_dicts(conn.execute(select(feedback).where(feedback.c.draft_id == draft_id).order_by(feedback.c.created_at)))
        out["has_recorded_approval"] = approvals.has_recorded_approval(conn, draft_id)
        if out.get("previous_draft_id"):
            prev = conn.execute(select(drafts).where(drafts.c.id == out["previous_draft_id"])).first()
            out["previous_draft"] = row_to_dict(prev) if prev else None
    return out


def _handle(fn, *args) -> dict[str, Any]:
    try:
        return fn(*args)
    except ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from None


@router.post("/drafts/{draft_id}/approve", dependencies=[Depends(limit_reviews)])
def approve(draft_id: int, body: ReviewIn | None = None, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return _handle(approvals.approve, ctx.engine, draft_id, body.reviewer if body else None)


@router.post("/drafts/{draft_id}/edit", dependencies=[Depends(limit_reviews)])
def edit(draft_id: int, body: EditIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return _handle(approvals.edit, ctx.engine, draft_id, body.subject, body.body, body.reason, body.reviewer)


@router.post("/drafts/{draft_id}/reject", dependencies=[Depends(limit_reviews)])
def reject(draft_id: int, body: RejectIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return _handle(approvals.reject, ctx.engine, draft_id, body.reason, body.reviewer)


@router.post("/drafts/{draft_id}/mark-sent", dependencies=[Depends(limit_reviews)])
def mark_sent(draft_id: int, body: ReviewIn | None = None, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return _handle(approvals.mark_sent, ctx.engine, draft_id, body.reviewer if body else None)


@router.get("/drafts/{draft_id}/eml")
def export_eml(draft_id: int, ctx: Context = Depends(get_ctx)) -> Response:
    try:
        filename, data = approvals.export_eml(ctx.engine, ctx.settings, draft_id)
    except ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from None
    return Response(
        content=data,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
