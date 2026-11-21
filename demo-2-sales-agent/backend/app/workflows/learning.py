"""Feedback loop: the last N review actions become context for the next agent run."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.agent.lessons import MEETING_RE, Lessons, derive_lessons, word_count
from app.db import accounts, agent_runs, drafts, feedback, leads, row_to_dict, rows_to_dicts

ACTION_LABEL = {"approve": "approved", "edit": "edited", "reject": "rejected", "mark_sent": "marked as sent"}


def recent_feedback(engine: Engine, limit: int = 20) -> list[dict[str, Any]]:
    """Newest first. mark_sent rows are bookkeeping, not review feedback, so they are left out."""
    q = (
        select(
            feedback,
            drafts.c.kind.label("draft_kind"),
            drafts.c.subject.label("draft_subject"),
            drafts.c.original_body,
            drafts.c.original_subject,
            drafts.c.run_id.label("draft_run_id"),
            func.coalesce(leads.c.company, accounts.c.company).label("company"),
        )
        .select_from(
            feedback.join(drafts, drafts.c.id == feedback.c.draft_id)
            .outerjoin(leads, leads.c.id == drafts.c.lead_id)
            .outerjoin(accounts, accounts.c.id == drafts.c.account_id)
        )
        .where(feedback.c.action != "mark_sent")
        .order_by(feedback.c.created_at.desc(), feedback.c.id.desc())
        .limit(limit)
    )
    with engine.connect() as conn:
        return rows_to_dicts(conn.execute(q))


def describe(item: dict[str, Any]) -> str:
    kind = "first email" if item["draft_kind"] == "outreach" else "follow-up"
    head = f'- #{item["id"]} {ACTION_LABEL.get(item["action"], item["action"])} {kind} to {item["company"]}, subject "{item["original_subject"]}"'
    if item["action"] == "reject":
        return f'{head}. Reason: "{item.get("reason") or "none given"}"'
    if item["action"] == "edit":
        before, after = word_count(item.get("original_body") or ""), word_count(item.get("edited_body") or "")
        changes = [f"{before} to {after} words"]
        if MEETING_RE.search(item.get("original_body") or "") and not MEETING_RE.search(item.get("edited_body") or ""):
            changes.append("removed the meeting request")
        if (item.get("edited_subject") or "") and item.get("edited_subject") != item.get("original_subject"):
            changes.append(f'new subject "{item["edited_subject"]}"')
        text = f"{head}. Rep changed it ({', '.join(changes)})"
        if item.get("reason"):
            text += f'. Reason: "{item["reason"]}"'
        snippet = " ".join((item.get("edited_body") or "").split())[:420]
        return f'{text}. Rep\'s version: "{snippet}"'
    return f"{head} without changes."


def build_context(engine: Engine, limit: int) -> dict[str, Any]:
    items = recent_feedback(engine, limit)
    lessons: Lessons = derive_lessons(items)
    block = "\n".join(describe(i) for i in items) if items else "No feedback yet."
    return {"items": items, "feedback_ids": [i["id"] for i in items], "block": block, "lessons": lessons}


def overview(engine: Engine, limit: int) -> dict[str, Any]:
    ctx = build_context(engine, limit)
    with engine.connect() as conn:
        pairs_q = select(drafts).where(drafts.c.previous_draft_id.is_not(None)).order_by(drafts.c.created_at.desc()).limit(10)
        afters = rows_to_dicts(conn.execute(pairs_q))
        pairs = []
        for after in afters:
            before = conn.execute(select(drafts).where(drafts.c.id == after["previous_draft_id"])).first()
            if not before:
                continue
            before = row_to_dict(before)
            fb = conn.execute(
                select(feedback).where(feedback.c.draft_id == before["id"]).order_by(feedback.c.created_at.desc())
            ).first()
            company = None
            if after.get("lead_id"):
                company = conn.execute(select(leads.c.company).where(leads.c.id == after["lead_id"])).scalar()
            elif after.get("account_id"):
                company = conn.execute(select(accounts.c.company).where(accounts.c.id == after["account_id"])).scalar()
            pairs.append(
                {
                    "company": company,
                    "before": _draft_stats(before),
                    "after": _draft_stats(after),
                    "feedback": row_to_dict(fb) if fb else None,
                }
            )
        runs = rows_to_dicts(
            conn.execute(
                select(
                    agent_runs.c.id,
                    agent_runs.c.started_at,
                    agent_runs.c.mode,
                    agent_runs.c.feedback_ids,
                    agent_runs.c.lessons,
                    agent_runs.c.drafts_created,
                )
                .order_by(agent_runs.c.started_at.desc())
                .limit(10)
            )
        )
        per_run = []
        for run in runs:
            run_drafts = rows_to_dicts(conn.execute(select(drafts).where(drafts.c.run_id == run["id"], drafts.c.kind == "outreach")))
            if not run_drafts:
                continue
            words = [d["word_count"] or word_count(d["original_body"]) for d in run_drafts]
            reviewed = [d for d in run_drafts if d["status"] in ("approved", "edited", "rejected", "sent")]
            approved = [d for d in reviewed if d["status"] in ("approved", "edited", "sent")]
            per_run.append(
                {
                    "run_id": run["id"],
                    "started_at": run["started_at"],
                    "mode": run["mode"],
                    "feedback_in_context": len(run.get("feedback_ids") or []),
                    "rules_in_context": len((run.get("lessons") or {}).get("rules", [])),
                    "drafts": len(run_drafts),
                    "avg_words": round(sum(words) / len(words)),
                    "meeting_asks": sum(1 for d in run_drafts if MEETING_RE.search(d["original_body"])),
                    "reviewed": len(reviewed),
                    "approval_rate": round(len(approved) / len(reviewed), 2) if reviewed else None,
                }
            )
    return {
        "context_block": ctx["block"],
        "feedback": ctx["items"],
        "lessons": ctx["lessons"].as_dict(),
        "pairs": pairs,
        "runs": list(reversed(per_run)),
    }


def _draft_stats(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d["id"],
        "run_id": d["run_id"],
        "status": d["status"],
        "subject": d["original_subject"],
        "body": d["original_body"],
        "words": d.get("word_count") or word_count(d["original_body"]),
        "meeting_ask": bool(MEETING_RE.search(d["original_body"])),
        "lessons_applied": d.get("lessons_applied") or [],
        "created_at": d["created_at"],
    }
