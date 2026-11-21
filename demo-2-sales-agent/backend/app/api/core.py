"""Overview, knowledge notes, Slack feed and the automation log."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app import __version__
from app.api.deps import get_ctx
from app.context import Context
from app.db import accounts, agent_runs, automation_log, drafts, leads, notifications, row_to_dict, rows_to_dicts
from app.services.knowledge import list_docs
from app.workflows.icp import active_icp

router = APIRouter(prefix="/api")


@router.get("/health")
def health(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        conn.execute(select(1))
    return {"ok": True, "version": __version__, "integrations": ctx.integrations()}


@router.get("/overview")
def overview(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        lead_rows = rows_to_dicts(conn.execute(select(leads).order_by(leads.c.score.desc(), leads.c.id)))
        acc_rows = rows_to_dicts(conn.execute(select(accounts).order_by(accounts.c.score.desc().nulls_last(), accounts.c.company)))
        draft_counts = dict(conn.execute(select(drafts.c.status, func.count()).group_by(drafts.c.status)).fetchall())
        latest = conn.execute(select(agent_runs).order_by(agent_runs.c.started_at.desc()).limit(1)).first()
    analysed = any(a.get("analyzed_at") for a in acc_rows)
    flagged = [a for a in acc_rows if a.get("flags")]
    open_value = sum(a.get("deal_value") or 0 for a in acc_rows if a["stage"] != "Customer")
    active = [l for l in lead_rows if l["status"] != "excluded"]
    icp = active_icp(ctx.engine)
    return {
        "integrations": ctx.integrations(),
        "running": ctx.runner.current,
        "latest_run": row_to_dict(latest) if latest else None,
        "icp": {"version": icp["version"], "author": icp["author"], "summary": icp["summary"]},
        "counts": {
            "leads": len(lead_rows),
            "active_leads": len(active),
            "avg_lead_score": round(sum(l["score"] for l in active) / len(active)) if active else None,
            "hot_leads": sum(1 for l in active if l["score"] >= 75),
            "accounts": len(acc_rows),
            "crm_analysed": analysed,
            "stalled": sum(1 for a in flagged if "stalled" in a["flags"]),
            "no_contact": sum(1 for a in flagged if "no_contact" in a["flags"]),
            "upsell": sum(1 for a in flagged if "upsell" in a["flags"]),
            "pending_drafts": draft_counts.get("pending", 0),
            "approved_drafts": draft_counts.get("approved", 0) + draft_counts.get("edited", 0),
            "rejected_drafts": draft_counts.get("rejected", 0),
            "sent_drafts": draft_counts.get("sent", 0),
            "open_pipeline": open_value,
        },
        "top_leads": [_lead_card(l) for l in active[:6]],
        "top_accounts": [_account_card(a) for a in sorted(flagged, key=lambda a: -(a.get("score") or 0))[:6]],
        "radar": [_lead_card(l) for l in lead_rows],
    }


def _lead_card(l: dict[str, Any]) -> dict[str, Any]:
    facts = l.get("facts") or []
    top = facts[0] if facts else {}
    return {
        "id": l["id"], "company": l["company"], "score": l["score"], "parts": l.get("score_parts") or {},
        "status": l["status"], "category": l.get("category"), "region": l.get("region"), "reason": l["reason"],
        "signal": top.get("type"), "fact": top.get("fact"), "source_url": l["source_url"], "fact_date": top.get("date"),
    }


def _account_card(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a["id"], "company": a["company"], "stage": a["stage"], "owner": a["owner"], "score": a.get("score"),
        "flags": a.get("flags") or [], "why": " ".join((a.get("flag_reasons") or {}).values()),
        "value": a.get("deal_value") or a.get("arr"),
    }


@router.get("/knowledge")
def knowledge(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    return list_docs(ctx.engine)


@router.get("/notifications")
def slack_feed(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        return rows_to_dicts(conn.execute(select(notifications).order_by(notifications.c.created_at.desc()).limit(40)))


@router.get("/automation-log")
def automation_rows(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        rows = rows_to_dicts(conn.execute(select(automation_log).order_by(automation_log.c.created_at.desc()).limit(60)))
    for row in rows:  # step lists can be long; the UI only needs a count
        details = row.get("details") or {}
        row["step_count"] = len(details.get("steps", []))
        row["details"] = {k: v for k, v in details.items() if k != "steps"}
    return rows
