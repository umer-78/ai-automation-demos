"""One-page weekly report, built from live data every time it is opened."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.agent.scoring import analyze_account, fmt_day
from app.db import accounts, agent_runs, drafts, feedback, leads, rows_to_dicts, utcnow
from app.workflows import crm
from app.workflows.icp import active_icp


def build(engine: Engine, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    start = now - timedelta(days=7)
    icp = active_icp(engine)
    last = crm.last_activity_map(engine)

    with engine.connect() as conn:
        new_leads = conn.execute(select(func.count()).select_from(leads).where(leads.c.created_at >= start)).scalar() or 0
        total_leads = conn.execute(select(func.count()).select_from(leads)).scalar() or 0
        top_leads = rows_to_dicts(
            conn.execute(
                select(leads.c.id, leads.c.company, leads.c.score, leads.c.reason, leads.c.score_reason, leads.c.status, leads.c.source_url)
                .where(leads.c.status.in_(("new", "drafted", "approved")))
                .order_by(leads.c.score.desc())
                .limit(5)
            )
        )
        account_rows = [dict(r._mapping) for r in conn.execute(select(accounts))]
        pending = rows_to_dicts(
            conn.execute(
                select(
                    drafts.c.id, drafts.c.kind, drafts.c.subject, drafts.c.send_date, drafts.c.created_at,
                    func.coalesce(leads.c.company, accounts.c.company).label("company"),
                )
                .select_from(drafts.outerjoin(leads, leads.c.id == drafts.c.lead_id).outerjoin(accounts, accounts.c.id == drafts.c.account_id))
                .where(drafts.c.status == "pending")
                .order_by(drafts.c.created_at.desc())
            )
        )
        week_feedback = rows_to_dicts(conn.execute(select(feedback).where(feedback.c.created_at >= start)))
        runs = rows_to_dicts(conn.execute(select(agent_runs).where(agent_runs.c.started_at >= start).order_by(agent_runs.c.started_at.desc())))

    analysed = []
    for acc in account_rows:
        a = analyze_account(acc, icp["criteria"], now, (last.get(acc["id"]) or {}).get("summary", ""))
        analysed.append({"id": acc["id"], "company": acc["company"], "owner": acc["owner"], "stage": acc["stage"],
                         "score": a["score"], "flags": a["flags"], "why": a["flag_reasons"], "reason": a["reason"],
                         "value": acc.get("deal_value") or acc.get("arr")})
    by_flag = {k: sorted([a for a in analysed if k in a["flags"]], key=lambda a: -a["score"]) for k in ("stalled", "no_contact", "upsell")}
    top_accounts = sorted([a for a in analysed if a["stage"] != "Customer" or a["flags"]], key=lambda a: -a["score"])[:5]
    open_pipeline = sum(a["value"] or 0 for a in analysed if a["stage"] != "Customer")
    stalled_value = sum(a["value"] or 0 for a in by_flag["stalled"])

    counts = Counter(f["action"] for f in week_feedback)
    reviewed = counts["approve"] + counts["edit"] + counts["reject"]
    reasons = [f["reason"] for f in sorted(week_feedback, key=lambda f: f["created_at"], reverse=True) if f["action"] == "reject" and f.get("reason")]
    finished = [r for r in runs if r["status"] != "running"]
    stats = {
        "runs": len(runs),
        "avg_duration_s": round(sum((r["duration_ms"] or 0) for r in finished) / len(finished) / 1000, 1) if finished else None,
        "tokens": sum(r["tokens"] or 0 for r in runs),
        "cost_usd": round(sum(r["cost_usd"] or 0 for r in runs), 3),
        "tool_calls": sum(r["tool_call_count"] or 0 for r in runs),
    }

    headline = [
        f"The agent found {new_leads} new leads this week ({total_leads} in total); the best is "
        + (f"{top_leads[0]['company']} at {top_leads[0]['score']}/100." if top_leads else "not available yet. Run the agent to start.")
        if total_leads else "No leads yet. Click Run agent to research the market and fill the pipeline.",
        f"{len(by_flag['stalled'])} deals are stalled (${stalled_value / 1000:,.0f}k at stake), {len(by_flag['no_contact'])} accounts have had no contact for 30+ days and {len(by_flag['upsell'])} customers look ready to upgrade.",
        f"{len(pending)} drafts are waiting for approval; this week the team approved {counts['approve'] + counts['edit']} and rejected {counts['reject']}."
        + (f" Most recent rejection reason: \"{reasons[0]}\"." if reasons else ""),
    ]
    return {
        "generated_at": now.isoformat(),
        "period": {"start": start.date().isoformat(), "end": now.date().isoformat(), "label": f"{fmt_day(start)} to {fmt_day(now)}"},
        "headline": headline,
        "leads": {"new_this_week": new_leads, "total": total_leads, "top": top_leads},
        "pipeline": {"open_value": open_pipeline, "stalled_value": stalled_value, "top_accounts": top_accounts},
        "stalled": by_flag["stalled"],
        "no_contact": by_flag["no_contact"],
        "upsell": by_flag["upsell"],
        "pending_drafts": pending,
        "reviews": {
            "approved": counts["approve"], "edited": counts["edit"], "rejected": counts["reject"], "sent": counts["mark_sent"],
            "approval_rate": round((counts["approve"] + counts["edit"]) / reviewed, 2) if reviewed else None,
            "recent_rejection_reasons": reasons[:5],
        },
        "agent": stats,
        "icp_version": icp["version"],
    }


def to_markdown(report: dict[str, Any]) -> str:
    out = [f"# Weekly sales report: {report['period']['label']}", ""]
    out += [f"{line}" for line in report["headline"]]
    out += ["", "## Top priorities", ""]
    for lead in report["leads"]["top"]:
        out.append(f"- **{lead['company']}** ({lead['score']}/100): {lead['reason']} [source]({lead['source_url']})")
    for acc in report["pipeline"]["top_accounts"]:
        out.append(f"- **{acc['company']}** (CRM, {acc['stage']}, {acc['score']}/100), owner {acc['owner']}")
    for title, key in (("Stalled deals", "stalled"), ("No contact for 30+ days", "no_contact"), ("Likely upsells", "upsell")):
        out += ["", f"## {title}", ""]
        rows = report[key]
        out += [f"- **{a['company']}** ({a['stage']}, {a['owner']}): {' '.join(a['why'].values())}" for a in rows] or ["- None"]
    out += ["", "## Drafts waiting for approval", ""]
    out += [f"- {d['company']}: \"{d['subject']}\" ({'first email' if d['kind'] == 'outreach' else 'follow-up'})" for d in report["pending_drafts"]] or ["- None"]
    r = report["reviews"]
    out += ["", "## Reviews and agent activity", "",
            f"- Approved {r['approved']}, edited {r['edited']}, rejected {r['rejected']}, marked as sent {r['sent']}.",
            f"- Agent runs: {report['agent']['runs']}, tool calls: {report['agent']['tool_calls']}, tokens: {report['agent']['tokens']:,}, cost: ${report['agent']['cost_usd']:.2f}."]
    return "\n".join(out) + "\n"
