"""ICP (view, edit, what-if), the learning loop and the weekly report."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.agent.scoring import CATEGORIES, REGIONS, SIGNAL_TYPES, SIZE_BANDS
from app.api.deps import get_ctx, limit_reviews
from app.context import Context
from app.workflows import crm, learning, report
from app.workflows import icp as icp_store

router = APIRouter(prefix="/api")


class ICPIn(BaseModel):
    summary: str = Field(min_length=20, max_length=900)
    target_categories: list[str] = Field(default_factory=list, max_length=10)
    adjacent_categories: list[str] = Field(default_factory=list, max_length=10)
    excluded_categories: list[str] = Field(default_factory=list, max_length=10)
    employee_min: int = Field(ge=1, le=100_000)
    employee_max: int = Field(ge=1, le=1_000_000)
    regions: list[str] = Field(default_factory=list, max_length=8)
    signal_weights: dict[str, int] = Field(default_factory=dict)
    exclusions: list[str] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=300)


@router.get("/icp")
def get_icp(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return {
        "active": icp_store.active_icp(ctx.engine),
        "history": icp_store.history(ctx.engine),
        "rep_edited": icp_store.rep_has_edited(ctx.engine),
        "options": {
            "categories": CATEGORIES,
            "regions": [r for r in REGIONS if r != "unknown"],
            "signals": SIGNAL_TYPES,
            "size_bands": [b for b in SIZE_BANDS if b != "unknown"],
        },
    }


@router.post("/icp/preview")
def preview_icp(body: ICPIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    changes = icp_store.rescore_leads(ctx.engine, body.model_dump(exclude={"note"}), write=False)
    return {"changes": changes, "moved": sum(1 for c in changes if c["delta"])}


@router.put("/icp", dependencies=[Depends(limit_reviews)])
def save_icp(body: ICPIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    saved = icp_store.save_version(ctx.engine, body.model_dump(exclude={"note"}), author="rep", note=body.note or "Edited by the rep.")
    changes = icp_store.rescore_leads(ctx.engine, saved["criteria"], write=True)
    crm_result = crm.analyze_all(ctx.engine, saved["criteria"])
    return {"saved": saved, "lead_changes": changes, "accounts_rescored": crm_result["analyzed"]}


@router.get("/learning")
def learning_overview(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return learning.overview(ctx.engine, ctx.settings.feedback_context_size)


@router.get("/report/weekly")
def weekly_report(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return report.build(ctx.engine)


@router.get("/report/weekly.md", response_class=PlainTextResponse)
def weekly_report_markdown(ctx: Context = Depends(get_ctx)) -> PlainTextResponse:
    data = report.build(ctx.engine)
    return PlainTextResponse(
        report.to_markdown(data),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="weekly-report-{data["period"]["end"]}.md"'},
    )
