"""Mock CRM analysis: stalled deals, accounts untouched for 30+ days, likely upsells, and account scores."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.engine import Connection

from .db import accounts, as_dict, meta

STALLED_DAYS = 30
UNTOUCHED_DAYS = 30
OPEN_STAGES = ("Proposal", "Negotiation")
STAGES = ["Prospecting", "Proposal", "Negotiation", "Customer"]
STAGE_POINTS = {"Negotiation": 30, "Proposal": 24, "Customer": 18, "Prospecting": 14}


def flags(acct: dict, today: date) -> list[str]:
    out = []
    if acct["stage"] in OPEN_STAGES and (today - _d(acct["stage_changed"])).days >= STALLED_DAYS:
        out.append("stalled")
    if (today - _d(acct["last_contact"])).days > UNTOUCHED_DAYS:
        out.append("untouched")
    if acct["stage"] == "Customer" and acct.get("expansion_signal"):
        out.append("upsell")
    return out


def _d(v: date | str) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def account_score(acct: dict, today: date) -> tuple[int, str]:
    """Priority to act on an account now: fit (stage and value), signals (stalled, untouched, upsell), recency."""
    stage_pts = STAGE_POINTS.get(acct["stage"], 10)
    value_pts = min(20, round(acct["deal_value"] / 4000))
    fit = stage_pts + value_pts
    words = [f"{acct['stage']}, ${acct['deal_value'] / 1000:,.0f}k"]
    f = flags(acct, today)
    sig = 0
    if "upsell" in f:
        sig += 25
        words.append(f"expansion signal: {acct['expansion_signal'].rstrip('.').lower()}")
    if "stalled" in f:
        sig += 18
        words.append(f"stalled {(today - _d(acct['stage_changed'])).days} days in {acct['stage']}")
    days = (today - _d(acct["last_contact"])).days
    if "untouched" in f:
        sig += 15
        words.append(f"no contact for {days} days")
    rec = 12 if days <= 7 else 9 if days <= 14 else 6 if days <= 30 else 2
    if "untouched" not in f:
        words.append("last contact today" if days == 0 else f"last contact {days} days ago")
    return min(100, fit + sig + rec), "; ".join(words)


def all_accounts(conn: Connection, today: date) -> list[dict]:
    out = []
    for r in conn.execute(select(accounts).order_by(accounts.c.id)).mappings():
        a = dict(r)
        a["flags"] = flags(a, today)
        a["days_since_contact"] = (today - _d(a["last_contact"])).days
        a["days_in_stage"] = (today - _d(a["stage_changed"])).days
        out.append(a)
    return out


def summary(conn: Connection, today: date) -> dict:
    accts = all_accounts(conn, today)
    return {
        "total": len(accts),
        "by_stage": {s: sum(1 for a in accts if a["stage"] == s) for s in STAGES},
        "stalled": sum("stalled" in a["flags"] for a in accts),
        "untouched": sum("untouched" in a["flags"] for a in accts),
        "upsell": sum("upsell" in a["flags"] for a in accts),
    }


def score_all(conn: Connection, today: date) -> list[dict]:
    """Score every account, store the score, and return them best first."""
    scored = []
    for a in all_accounts(conn, today):
        score, reason = account_score(a, today)
        conn.execute(update(accounts).where(accounts.c.id == a["id"]).values(score=score, score_reason=reason))
        a.update(score=score, score_reason=reason)
        scored.append(a)
    return sorted(scored, key=lambda a: (-a["score"], a["id"]))


def roll_forward(conn: Connection, today: date) -> int:
    """Keep the demo CRM's ages stable: shift every date forward by the days since it was seeded."""
    anchor = conn.execute(select(meta.c.value).where(meta.c.key == "crm_anchor")).scalar()
    if not anchor:
        return 0
    delta = (today - date.fromisoformat(anchor)).days
    if delta <= 0:
        return 0
    for a in conn.execute(select(accounts.c.id, accounts.c.last_contact, accounts.c.stage_changed)).mappings().all():
        conn.execute(update(accounts).where(accounts.c.id == a["id"]).values(
            last_contact=_d(a["last_contact"]) + timedelta(days=delta),
            stage_changed=_d(a["stage_changed"]) + timedelta(days=delta)))
    conn.execute(update(meta).where(meta.c.key == "crm_anchor").values(value=today.isoformat()))
    return delta


def public(a: dict) -> dict:
    return as_dict(a)
