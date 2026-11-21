"""Human approval: Approve, Edit, Reject, then a manual send step.

Hard rule from the spec: nothing customer-facing leaves without a recorded approval. This app
has no email client at all; the only ways a draft leaves the queue are

* GET  /api/drafts/{id}/eml        a .eml file the rep opens in their own mail client, and
* POST /api/drafts/{id}/mark-sent  the rep confirming they sent it themselves.

Both call `require_recorded_approval`, which looks for an approve/edit row in the feedback
table for that exact draft. Status flags alone are not trusted.
"""

from __future__ import annotations

import re
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine

from app.agent.lessons import NOT_A_FIT_RE, word_count
from app.config import Settings
from app.db import accounts, activity, drafts, feedback, leads, row_to_dict, utcnow


class ReviewError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _get(conn: Connection, draft_id: int) -> dict[str, Any]:
    row = conn.execute(select(drafts).where(drafts.c.id == draft_id)).first()
    if not row:
        raise ReviewError(404, "Draft not found.")
    return dict(row._mapping)


def has_recorded_approval(conn: Connection, draft_id: int) -> bool:
    q = select(feedback.c.id).where(feedback.c.draft_id == draft_id, feedback.c.action.in_(("approve", "edit"))).limit(1)
    return conn.execute(q).first() is not None


def require_recorded_approval(conn: Connection, draft: dict[str, Any]) -> None:
    if draft["status"] not in ("approved", "edited", "sent") or not has_recorded_approval(conn, draft["id"]):
        raise ReviewError(409, "This draft has no recorded approval. Approve or edit it first.")


def _record(conn: Connection, draft_id: int, action: str, reviewer: str, **extra: Any) -> None:
    conn.execute(
        feedback.insert().values(
            draft_id=draft_id, action=action, reviewer=reviewer, created_at=utcnow(),
            reason=extra.get("reason"), edited_subject=extra.get("edited_subject"), edited_body=extra.get("edited_body"),
        )
    )


def _set_lead_status(conn: Connection, draft: dict[str, Any], status: str, excluded_reason: str | None = None) -> None:
    if draft.get("lead_id"):
        values: dict[str, Any] = {"status": status, "updated_at": utcnow()}
        if excluded_reason:
            values["excluded_reason"] = excluded_reason
        conn.execute(update(leads).where(leads.c.id == draft["lead_id"]).values(**values))


def _clean_reviewer(reviewer: str | None) -> str:
    reviewer = " ".join((reviewer or "").split())[:60]
    return reviewer or "Sales rep"


def approve(engine: Engine, draft_id: int, reviewer: str | None = None) -> dict[str, Any]:
    reviewer = _clean_reviewer(reviewer)
    with engine.begin() as conn:
        draft = _get(conn, draft_id)
        if draft["status"] != "pending":
            raise ReviewError(409, f"Only pending drafts can be approved (this one is {draft['status']}).")
        now = utcnow()
        conn.execute(update(drafts).where(drafts.c.id == draft_id).values(status="approved", reviewer=reviewer, reviewed_at=now, updated_at=now))
        _record(conn, draft_id, "approve", reviewer)
        _set_lead_status(conn, draft, "approved")
        return row_to_dict(conn.execute(select(drafts).where(drafts.c.id == draft_id)).first())


def edit(engine: Engine, draft_id: int, subject: str, body: str, reason: str | None, reviewer: str | None = None) -> dict[str, Any]:
    reviewer = _clean_reviewer(reviewer)
    subject = " ".join(subject.split())
    body = body.replace("\r\n", "\n").strip()
    if not 3 <= len(subject) <= 200:
        raise ReviewError(422, "Subject must be 3 to 200 characters.")
    if word_count(body) < 5:
        raise ReviewError(422, "The edited email is empty.")
    with engine.begin() as conn:
        draft = _get(conn, draft_id)
        if draft["status"] not in ("pending", "approved", "edited"):
            raise ReviewError(409, f"A {draft['status']} draft cannot be edited.")
        if subject == draft["subject"] and body == draft["body"]:
            raise ReviewError(422, "Nothing changed. Use Approve to accept the draft as it is.")
        now = utcnow()
        conn.execute(
            update(drafts)
            .where(drafts.c.id == draft_id)
            .values(subject=subject, body=body, status="edited", reviewer=reviewer, reviewed_at=now, updated_at=now)
        )
        _record(conn, draft_id, "edit", reviewer, reason=(reason or "").strip()[:300] or None, edited_subject=subject, edited_body=body)
        _set_lead_status(conn, draft, "approved")
        return row_to_dict(conn.execute(select(drafts).where(drafts.c.id == draft_id)).first())


def reject(engine: Engine, draft_id: int, reason: str, reviewer: str | None = None) -> dict[str, Any]:
    reviewer = _clean_reviewer(reviewer)
    reason = " ".join((reason or "").split())
    if not 3 <= len(reason) <= 300:
        raise ReviewError(422, "Give a one-line reason (3 to 300 characters) so the agent can learn from it.")
    with engine.begin() as conn:
        draft = _get(conn, draft_id)
        if draft["status"] != "pending":
            raise ReviewError(409, f"Only pending drafts can be rejected (this one is {draft['status']}).")
        now = utcnow()
        conn.execute(update(drafts).where(drafts.c.id == draft_id).values(status="rejected", reviewer=reviewer, reviewed_at=now, updated_at=now))
        _record(conn, draft_id, "reject", reviewer, reason=reason)
        if NOT_A_FIT_RE.search(reason):
            _set_lead_status(conn, draft, "excluded", f"Rejected by the rep: {reason}")
        else:
            _set_lead_status(conn, draft, "new")  # eligible again; the next draft must follow the feedback
        return row_to_dict(conn.execute(select(drafts).where(drafts.c.id == draft_id)).first())


def export_eml(engine: Engine, settings: Settings, draft_id: int) -> tuple[str, bytes]:
    """The approved email as a .eml file for the rep's own mail client. Requires recorded approval."""
    with engine.connect() as conn:
        draft = _get(conn, draft_id)
        require_recorded_approval(conn, draft)
    msg = EmailMessage()
    msg["From"] = f"{settings.rep_name} <{_rep_mailbox(settings)}>"
    msg["To"] = draft.get("recipient") or ""
    msg["Subject"] = draft["subject"]
    msg["Date"] = format_datetime(utcnow())
    msg["X-Unsent"] = "1"  # mail clients open it as a draft to review and send manually
    msg.set_content(draft["body"])
    name = re.sub(r"[^a-z0-9]+", "-", draft["subject"].lower()).strip("-")[:50] or "draft"
    return f"draft-{draft_id}-{name}.eml", msg.as_bytes()


def _rep_mailbox(settings: Settings) -> str:
    local = re.sub(r"[^a-z]+", ".", settings.rep_name.lower()).strip(".")
    return f"{local}@acme-cloud-security.example"


def mark_sent(engine: Engine, draft_id: int, reviewer: str | None = None) -> dict[str, Any]:
    """The rep confirms they sent the approved email from their own inbox."""
    reviewer = _clean_reviewer(reviewer)
    with engine.begin() as conn:
        draft = _get(conn, draft_id)
        require_recorded_approval(conn, draft)
        if draft["status"] == "sent":
            raise ReviewError(409, "Already marked as sent.")
        now = utcnow()
        conn.execute(update(drafts).where(drafts.c.id == draft_id).values(status="sent", sent_at=now, updated_at=now))
        _record(conn, draft_id, "mark_sent", reviewer)
        _set_lead_status(conn, draft, "contacted")
        if draft.get("account_id"):
            conn.execute(update(accounts).where(accounts.c.id == draft["account_id"]).values(last_contact=now, updated_at=now))
            conn.execute(
                activity.insert().values(
                    account_id=draft["account_id"], kind="email", direction="outbound",
                    summary=f"Email sent by {reviewer}: {draft['subject']}", occurred_at=now, created_at=now,
                )
            )
        return row_to_dict(conn.execute(select(drafts).where(drafts.c.id == draft_id)).first())
