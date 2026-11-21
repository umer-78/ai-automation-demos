"""The one-page weekly report, built from live data every time it's opened."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from . import crm
from .db import accounts, agent_runs, as_dict, drafts, feedback, leads, now_utc

LEAD_COLS = [leads.c.id, leads.c.company, leads.c.website, leads.c.score, leads.c.score_reason, leads.c.reason,
             leads.c.fact, leads.c.fact_url, leads.c.status, leads.c.created_at]


def build(conn: Connection, today: date) -> dict:
    start = today - timedelta(days=6)
    since = datetime.combine(start, time.min, tzinfo=timezone.utc)

    new_leads = [as_dict(r) for r in conn.execute(select(*LEAD_COLS).where(leads.c.created_at >= since)
                                                  .order_by(leads.c.score.desc())).mappings()]
    top_leads = [as_dict(r) for r in conn.execute(select(*LEAD_COLS).order_by(leads.c.score.desc(), leads.c.id)
                                                  .limit(5)).mappings()]
    accts = crm.all_accounts(conn, today)
    for a in accts:
        a["score"], a["score_reason"] = crm.account_score(a, today)
    pick = ("id", "company", "stage", "deal_value", "owner", "score", "score_reason", "flags", "days_since_contact",
            "days_in_stage", "notes", "expansion_signal")

    def slim(a: dict) -> dict:
        return {k: a[k] for k in pick}

    top_accounts = [slim(a) for a in sorted(accts, key=lambda a: (-a["score"], a["id"]))[:5]]
    stalled = [slim(a) for a in sorted((a for a in accts if "stalled" in a["flags"]), key=lambda a: -a["days_in_stage"])]
    untouched = [slim(a) for a in sorted((a for a in accts if "untouched" in a["flags"]), key=lambda a: -a["days_since_contact"])]
    upsell = [slim(a) for a in accts if "upsell" in a["flags"]]

    waiting_q = (select(drafts.c.id, drafts.c.kind, drafts.c.subject, drafts.c.status, drafts.c.due_date,
                        drafts.c.created_at, leads.c.company.label("lead_company"),
                        accounts.c.company.label("account_company"))
                 .select_from(drafts.outerjoin(leads, leads.c.id == drafts.c.lead_id)
                              .outerjoin(accounts, accounts.c.id == drafts.c.account_id))
                 .where(drafts.c.status.in_(["pending", "edited"])).order_by(drafts.c.kind, drafts.c.id))
    waiting = []
    for r in conn.execute(waiting_q).mappings():
        d = as_dict(r)
        d["company"] = d.pop("lead_company") or d.pop("account_company", "")
        d.pop("account_company", None)
        waiting.append(d)

    runs = conn.execute(select(agent_runs).where(agent_runs.c.started_at >= since)
                        .order_by(agent_runs.c.id.desc())).mappings().all()
    decisions = dict(conn.execute(select(feedback.c.action, func.count()).where(feedback.c.created_at >= since)
                                  .group_by(feedback.c.action)).all())
    approved = conn.execute(select(func.count()).select_from(drafts).where(drafts.c.status == "approved",
                                                                            drafts.c.decided_at >= since)).scalar() or 0
    return {
        "week": {"start": start.isoformat(), "end": today.isoformat()},
        "generated_at": now_utc().isoformat(),
        "counts": {"new_leads": len(new_leads), "total_leads": conn.execute(select(func.count()).select_from(leads)).scalar() or 0,
                   "stalled": len(stalled), "untouched": len(untouched), "upsell": len(upsell), "waiting": len(waiting),
                   "approved": approved, "runs": len(runs)},
        "new_leads": new_leads[:10], "top_leads": top_leads, "top_accounts": top_accounts,
        "stalled": stalled, "untouched": untouched, "upsell": upsell, "waiting": waiting,
        "decisions": {"approve": decisions.get("approve", 0), "edit": decisions.get("edit", 0), "reject": decisions.get("reject", 0)},
        "last_run": as_dict(runs[0]) if runs else None,
    }
