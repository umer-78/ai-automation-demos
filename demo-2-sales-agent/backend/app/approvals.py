"""Human approval: Approve, Edit, Reject. Every decision is stored as feedback for the next run.

Nothing in this codebase sends email. The only way a draft leaves the system is the .eml download,
and that is refused unless the draft is approved and the approval is recorded in the feedback table.
"""
from __future__ import annotations

import uuid
from email.message import EmailMessage

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine

from .db import accounts, as_dict, drafts, feedback, leads, log_activity, now_utc, tx

OPEN = ("pending", "edited")


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class BadRequest(Exception):
    pass


def _query():
    return (select(drafts, leads.c.company.label("lead_company"), leads.c.score.label("lead_score"),
                   accounts.c.company.label("account_company"), accounts.c.owner.label("account_owner"))
            .select_from(drafts.outerjoin(leads, leads.c.id == drafts.c.lead_id)
                         .outerjoin(accounts, accounts.c.id == drafts.c.account_id)))


def _shape(row: dict) -> dict:
    d = as_dict(row)
    d["company"] = d.pop("lead_company") or d.pop("account_company", None) or ""
    d.pop("account_company", None)
    d["edited"] = d["subject"] != d["original_subject"] or d["body"] != d["original_body"]
    return d


def get_draft(conn: Connection, draft_id: int) -> dict:
    r = conn.execute(_query().where(drafts.c.id == draft_id)).mappings().first()
    if not r:
        raise NotFound(f"No draft {draft_id}.")
    return _shape(dict(r))


def list_drafts(conn: Connection, which: str = "queue", lead_id: int | None = None, account_id: str | None = None) -> list[dict]:
    q = _query()
    if which == "queue":
        q = q.where(drafts.c.status.in_(OPEN))
    elif which != "all":
        q = q.where(drafts.c.status == which)
    if lead_id is not None:
        q = q.where(drafts.c.lead_id == lead_id)
    if account_id is not None:
        q = q.where(drafts.c.account_id == account_id)
    order = [drafts.c.kind, leads.c.score.desc(), drafts.c.id.desc()] if which == "queue" else [drafts.c.id.desc()]
    return [_shape(dict(r)) for r in conn.execute(q.order_by(*order)).mappings()]


def _record(conn: Connection, draft_id: int, action: str, **fields) -> str:
    fid = str(uuid.uuid4())
    conn.execute(feedback.insert().values(id=fid, draft_id=draft_id, action=action, created_at=now_utc(), **fields))
    return fid


def _open_draft(conn: Connection, draft_id: int) -> dict:
    d = get_draft(conn, draft_id)
    if d["status"] not in OPEN:
        raise Conflict(f"This draft is already {d['status']}.")
    return d


def approve(engine: Engine, draft_id: int) -> dict:
    with tx(engine) as conn:
        d = _open_draft(conn, draft_id)
        conn.execute(update(drafts).where(drafts.c.id == draft_id).values(status="approved", decided_at=now_utc()))
        _record(conn, draft_id, "approve")
        log_activity(conn, "approval", "success", f"Approved draft {draft_id} to {d['company']}; ready to send by hand")
        return get_draft(conn, draft_id)


def edit(engine: Engine, draft_id: int, subject: str, body: str) -> dict:
    subject, body = (subject or "").strip(), (body or "").strip()
    if not 3 <= len(subject) <= 140:
        raise BadRequest("The subject should be 3 to 140 characters.")
    if not 20 <= len(body) <= 3000:
        raise BadRequest("The email should be 20 to 3,000 characters.")
    with tx(engine) as conn:
        d = _open_draft(conn, draft_id)
        if subject == d["subject"] and body == d["body"]:
            raise BadRequest("Nothing changed. Edit the subject or the email, or approve it as it is.")
        conn.execute(update(drafts).where(drafts.c.id == draft_id).values(subject=subject, body=body, status="edited"))
        _record(conn, draft_id, "edit", edited_subject=subject, edited_body=body)
        log_activity(conn, "approval", "success", f"Edited draft {draft_id} to {d['company']}; still waiting for approval")
        return get_draft(conn, draft_id)


def reject(engine: Engine, draft_id: int, reason: str) -> dict:
    reason = " ".join((reason or "").split())
    if not 3 <= len(reason) <= 300:
        raise BadRequest("Give a one-line reason (3 to 300 characters). The agent reads it on the next run.")
    with tx(engine) as conn:
        d = _open_draft(conn, draft_id)
        conn.execute(update(drafts).where(drafts.c.id == draft_id).values(status="rejected", decided_at=now_utc()))
        _record(conn, draft_id, "reject", reason=reason)
        log_activity(conn, "approval", "success", f"Rejected draft {draft_id} to {d['company']}: {reason}")
        return get_draft(conn, draft_id)


def eml(engine: Engine, draft_id: int) -> tuple[str, str]:
    """The manual sending step: an .eml file for the rep's own mail app, only after a recorded approval."""
    with engine.connect() as conn:
        d = get_draft(conn, draft_id)
        approval = conn.execute(select(feedback.c.created_at).where(
            feedback.c.draft_id == draft_id, feedback.c.action == "approve")).scalar()
    if d["status"] != "approved" or approval is None:
        raise Conflict("Only approved drafts can be exported. Approve it first.")
    msg = EmailMessage()
    msg["Subject"] = d["subject"]
    msg["X-Approved-At"] = approval.isoformat()
    msg["X-Source-Fact"] = d["fact_url"]
    msg.set_content(d["body"])
    safe = "".join(ch if ch.isalnum() else "-" for ch in d["company"]).strip("-").lower() or "draft"
    return f"{safe}-draft-{draft_id}.eml", msg.as_string()


def proof(conn: Connection, limit: int = 5) -> list[dict]:
    """Before-and-after pairs: a draft the rep rejected or edited, and the next draft to the same lead."""
    fb = conn.execute(select(feedback.c.draft_id, feedback.c.action, feedback.c.reason, feedback.c.edited_body,
                             feedback.c.created_at).where(feedback.c.action.in_(["reject", "edit"]))
                      .order_by(feedback.c.created_at.desc())).mappings().all()
    pairs, used = [], set()
    for f in fb:
        before = get_draft(conn, f["draft_id"])
        key = before["lead_id"] or before["account_id"]
        if key in used:
            continue
        after_row = conn.execute(_query().where(
            (drafts.c.lead_id == before["lead_id"]) if before["lead_id"] else (drafts.c.account_id == before["account_id"]),
            drafts.c.kind == before["kind"], drafts.c.created_at > f["created_at"]).order_by(drafts.c.id.desc())).mappings().first()
        if not after_row:
            continue
        used.add(key)
        pairs.append({"company": before["company"], "feedback": {"action": f["action"], "reason": f["reason"]},
                      "before": before, "after": _shape(dict(after_row))})
        if len(pairs) >= limit:
            break
    return pairs
