"""The sales agent: a Claude tool-use loop, or a scripted offline run that uses exactly the same tools.

Hard rule from the spec: the agent has no tool that can send anything. Every email it writes lands in the
approval queue as a draft, and only a person can approve it (see approvals.py).
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any, Callable

from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection, Engine

from . import crm, report
from .config import DATA_DIR, Settings
from .db import (accounts, agent_runs, drafts, feedback, icp, jdump, jload, leads, log_activity, now_utc, run_events,
                 tx)
from .notify import slack_alert
from .research import SNAPSHOT, Research, ResearchError
from .scoring import SIGNALS, lead_score, parse_day

OFFLINE_ENGINE = "offline agent (no Claude key)"
MIN_LEADS, MIN_DRAFTS = 10, 5
FEEDBACK_ITEMS = 20
REP = "Sara Lind"
_run_lock = threading.Lock()

DEFAULT_ICP = {
    "summary": "B2B SaaS companies with 200 to 2,000 staff on AWS or Google Cloud that are making a first security "
               "hire, preparing for SOC 2 or ISO 27001, or growing after new funding.",
    "industries": ["B2B SaaS"], "size_min": 200, "size_max": 2000, "regions": ["North America", "UK", "EU"],
    "signals": ["hiring_security", "compliance", "funding", "incident", "cloud_stack"],
    "exclusions": ["Security vendors", "Companies under 50 people", "Public sector with on-premise mandates"],
}


class ToolError(Exception):
    """A tool refused its input. The message goes back to the model so it can correct itself."""


class AlreadyRunning(Exception):
    pass


class RunFailed(Exception):
    pass


def company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


# --------------------------------------------------------------------------------------------- ICP

def get_icp(conn: Connection) -> dict | None:
    r = conn.execute(select(icp).where(icp.c.id == 1)).mappings().first()
    if not r:
        return None
    out = {k: jload(r[k], []) for k in ("industries", "regions", "signals", "exclusions")}
    out.update(summary=r["summary"], size_min=r["size_min"], size_max=r["size_max"], edited_by=r["edited_by"],
               updated_at=r["updated_at"].isoformat())
    return out


def validate_icp(data: dict) -> dict:
    def strings(key: str, limit: int = 12) -> list[str]:
        items = data.get(key) or []
        if not isinstance(items, list) or len(items) > limit:
            raise ToolError(f"{key} must be a list of up to {limit} short items.")
        return [str(x).strip()[:80] for x in items if str(x).strip()]
    summary = str(data.get("summary") or "").strip()
    if not 10 <= len(summary) <= 600:
        raise ToolError("The profile summary should be 10 to 600 characters.")
    try:
        lo, hi = int(data.get("size_min")), int(data.get("size_max"))
    except (TypeError, ValueError):
        raise ToolError("size_min and size_max must be whole numbers.") from None
    if not 1 <= lo <= hi <= 1_000_000:
        raise ToolError("Company size range must be positive, with the minimum below the maximum.")
    signals = [s for s in strings("signals") if s in SIGNALS]
    return {"summary": summary, "industries": strings("industries") or ["B2B SaaS"], "size_min": lo, "size_max": hi,
            "regions": strings("regions"), "signals": signals or list(SIGNALS), "exclusions": strings("exclusions")}


def save_icp_row(conn: Connection, data: dict, edited_by: str) -> dict:
    clean = validate_icp(data)
    values = {**{k: jdump(clean[k]) for k in ("industries", "regions", "signals", "exclusions")},
              "summary": clean["summary"], "size_min": clean["size_min"], "size_max": clean["size_max"],
              "edited_by": edited_by, "updated_at": now_utc()}
    if conn.execute(select(icp.c.id).where(icp.c.id == 1)).first():
        conn.execute(update(icp).where(icp.c.id == 1).values(**values))
    else:
        conn.execute(icp.insert().values(id=1, **values))
    return get_icp(conn) or {}


# ------------------------------------------------------------------------------------ run context

@dataclass
class RunContext:
    engine: Engine
    settings: Settings
    research: Research
    run_id: int
    today: date
    deadline: float
    engine_label: str
    seq: int = 0
    tools_called: list[str] = field(default_factory=list)
    seen: dict[str, dict] = field(default_factory=dict)  # every URL web_search returned this run
    leads_saved: set[int] = field(default_factory=set)
    drafts_made: int = 0
    followups_made: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    finished: bool = False
    summary: str = ""

    def emit(self, kind: str, summary: str, tool: str | None = None, ms: int | None = None) -> None:
        self.seq += 1
        with tx(self.engine) as conn:
            conn.execute(run_events.insert().values(run_id=self.run_id, seq=self.seq, kind=kind, tool=tool,
                                                    summary=summary[:600], ms=ms, at=now_utc()))
        self.checkpoint()
        if kind == "tool" and not self.settings.live_model and self.settings.offline_step_s > 0:
            time.sleep(self.settings.offline_step_s)

    def checkpoint(self) -> None:
        with tx(self.engine) as conn:
            conn.execute(update(agent_runs).where(agent_runs.c.id == self.run_id).values(
                tools_called=jdump(self.tools_called), input_tokens=self.input_tokens, output_tokens=self.output_tokens))


# ------------------------------------------------------------------------------------------- tools

def _text(args: dict, key: str, lo: int, hi: int, label: str | None = None) -> str:
    value = str(args.get(key) or "").strip()
    if not lo <= len(value) <= hi:
        raise ToolError(f"{label or key} must be {lo} to {hi} characters.")
    return value


def business_notes() -> dict:
    deals = sorted((DATA_DIR / "deals").glob("*.md"))
    return {"product_md": (DATA_DIR / "product.md").read_text(encoding="utf-8"),
            "competitors_md": (DATA_DIR / "competitors.md").read_text(encoding="utf-8"),
            "deal_notes": [{"file": p.name, "text": p.read_text(encoding="utf-8")} for p in deals]}


def t_read_business_notes(ctx: RunContext, args: dict) -> dict:
    return business_notes()


def t_save_icp(ctx: RunContext, args: dict) -> dict:
    with tx(ctx.engine) as conn:
        current = get_icp(conn)
        if current and current["edited_by"] == "rep":
            return {"kept_rep_profile": True, "icp": current,
                    "note": "The rep edited this profile, so it was kept. Use it for targeting."}
        return {"saved": True, "icp": save_icp_row(conn, args, "agent")}


def t_web_search(ctx: RunContext, args: dict) -> dict:
    query = _text(args, "query", 3, 300)
    results = ctx.research.search(query)
    for r in results:
        if r.get("url"):
            ctx.seen[r["url"]] = r
    return {"query": query, "results": [{k: r.get(k) for k in ("title", "url", "snippet", "published")} for r in results]}


def _seen(ctx: RunContext, url: str, label: str) -> str:
    url = str(url or "").strip()
    if url not in ctx.seen:
        raise ToolError(f"{label} must be one of the URLs web_search returned in this run. Never invent URLs.")
    return url


def t_save_lead(ctx: RunContext, args: dict) -> dict:
    company = _text(args, "company", 2, 200)
    source_url = _seen(ctx, args.get("source_url"), "source_url")
    fact_url = _seen(ctx, args.get("fact_url") or source_url, "fact_url")
    reason = _text(args, "reason", 10, 300)
    fact = _text(args, "fact", 10, 400)
    industry = str(args.get("industry") or "").strip()[:200]
    if "security" in industry.lower() and any("security vendor" in e.lower() for e in _icp_or_default(ctx)["exclusions"]):
        raise ToolError(f"{company} looks like a security vendor, which the profile excludes. Skip it.")
    employees = args.get("employees")
    try:
        employees = int(employees) if employees not in (None, "") else None
    except (TypeError, ValueError):
        employees = None
    if employees is not None and not 1 <= employees <= 2_000_000:
        employees = None
    note = {"source": "from source", "estimate": "estimate"}.get(str(args.get("employees_source") or ""), None) \
        if employees else None
    signals = [s for s in args.get("signals") or [] if s in SIGNALS]
    fact_day, precision = parse_day(args.get("fact_date"))
    if fact_day and fact_day > ctx.today:
        fact_day, precision = None, "none"
    score, score_reason, parts = lead_score(_icp_or_default(ctx), industry=industry, employees=employees,
                                            employees_note=note, signals=signals, fact_date=fact_day,
                                            precision=precision, today=ctx.today)
    website = str(args.get("website") or "").strip()[:300] or None
    if website and not website.startswith(("http://", "https://")):
        website = "https://" + website
    values = dict(company=company, website=website, industry=industry or None, employees=employees,
                  employees_note=note, source_url=source_url, reason=reason, fact=fact, fact_url=fact_url,
                  fact_date=fact_day, fact_precision=precision, signals=jdump(signals), score=score, score_reason=score_reason,
                  score_parts=jdump(parts), run_id=ctx.run_id, updated_at=now_utc())
    key = company_key(company)
    with tx(ctx.engine) as conn:
        existing = conn.execute(select(leads.c.id).where(leads.c.company_key == key)).scalar()
        if existing:
            conn.execute(update(leads).where(leads.c.id == existing).values(**values))
            lead_id, state = existing, "updated"
        else:
            lead_id = conn.execute(leads.insert().values(company_key=key, status="new", created_at=now_utc(),
                                                         **values)).inserted_primary_key[0]
            state = "new"
    ctx.leads_saved.add(int(lead_id))
    return {"lead_id": int(lead_id), "company": company, "score": score, "score_reason": score_reason, "saved_as": state}


def _icp_or_default(ctx: RunContext) -> dict:
    with ctx.engine.connect() as conn:
        return get_icp(conn) or DEFAULT_ICP


def t_read_crm(ctx: RunContext, args: dict) -> dict:
    with tx(ctx.engine) as conn:
        accts = crm.all_accounts(conn, ctx.today)
        summ = crm.summary(conn, ctx.today)
    flagged = [{"account_id": a["id"], "company": a["company"], "stage": a["stage"], "deal_value": a["deal_value"],
                "owner": a["owner"], "flags": a["flags"], "days_since_contact": a["days_since_contact"],
                "days_in_stage": a["days_in_stage"], "notes": a["notes"], "expansion_signal": a["expansion_signal"]}
               for a in accts if a["flags"]]
    return {"summary": summ, "flagged_accounts": flagged,
            "note": f"{summ['total'] - len(flagged)} other accounts have no flags."}


def t_score_accounts(ctx: RunContext, args: dict) -> dict:
    with tx(ctx.engine) as conn:
        scored = crm.score_all(conn, ctx.today)
    return {"scored": len(scored), "top": [{"account_id": a["id"], "company": a["company"], "score": a["score"],
                                            "reason": a["score_reason"], "flags": a["flags"]} for a in scored[:10]]}


_PLACEHOLDER = re.compile(r"\[[^\]]{1,40}\]|\{[^}]{1,40}\}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def _check_email(subject: str, body: str) -> None:
    if _PLACEHOLDER.search(subject + body):
        raise ToolError("Remove placeholders like [Name]; address the team and sign as the rep.")
    if _EMAIL.search(body):
        raise ToolError("Don't put email addresses in the draft. The rep adds the contact when sending.")


def t_create_draft(ctx: RunContext, args: dict) -> dict:
    try:
        lead_id = int(args.get("lead_id"))
    except (TypeError, ValueError):
        raise ToolError("lead_id must be the number save_lead returned.") from None
    subject = _text(args, "subject", 3, 140)
    body = _text(args, "body", 40, 1600)
    fact = _text(args, "fact", 10, 400)
    _check_email(subject, body)
    with tx(ctx.engine) as conn:
        lead = conn.execute(select(leads).where(leads.c.id == lead_id)).mappings().first()
        if not lead:
            raise ToolError(f"No lead with id {lead_id}.")
        fact_url = str(args.get("fact_url") or "").strip()
        if fact_url not in (lead["fact_url"], lead["source_url"]) and fact_url not in ctx.seen:
            raise ToolError("fact_url must be the lead's source or fact URL from research.")
        conn.execute(update(drafts).where(drafts.c.lead_id == lead_id, drafts.c.kind == "first_touch",
                                          drafts.c.status.in_(["pending", "edited"])).values(status="superseded"))
        draft_id = conn.execute(drafts.insert().values(
            lead_id=lead_id, kind="first_touch", subject=subject, body=body, fact=fact, fact_url=fact_url,
            status="pending", original_subject=subject, original_body=body, engine=ctx.engine_label,
            run_id=ctx.run_id, created_at=now_utc())).inserted_primary_key[0]
        conn.execute(update(leads).where(leads.c.id == lead_id).values(status="drafted", updated_at=now_utc()))
    ctx.drafts_made += 1
    return {"draft_id": int(draft_id), "company": lead["company"], "status": "waiting for approval"}


def t_recommend_followup(ctx: RunContext, args: dict) -> dict:
    account_id = str(args.get("account_id") or "").strip()
    next_step = _text(args, "next_step", 5, 200, "next_step")
    subject = _text(args, "subject", 3, 140)
    body = _text(args, "body", 40, 1600)
    _check_email(subject, body)
    due, precision = parse_day(args.get("due_date"))
    if not due or precision != "day" or not ctx.today < due <= ctx.today + timedelta(days=21):
        raise ToolError("due_date must be a YYYY-MM-DD date within the next 21 days.")
    if due.weekday() >= 5:
        due += timedelta(days=7 - due.weekday())  # move weekends to Monday
    with tx(ctx.engine) as conn:
        acct = conn.execute(select(accounts).where(accounts.c.id == account_id)).mappings().first()
        if not acct:
            raise ToolError(f"No CRM account with id {account_id}.")
        fact = str(args.get("fact") or "").strip()[:400] or acct["expansion_signal"] or acct["notes"]
        conn.execute(update(drafts).where(drafts.c.account_id == account_id, drafts.c.kind == "follow_up",
                                          drafts.c.status.in_(["pending", "edited"])).values(status="superseded"))
        draft_id = conn.execute(drafts.insert().values(
            account_id=account_id, kind="follow_up", subject=subject, body=body, fact=fact, fact_url=f"crm:{account_id}",
            next_step=next_step, due_date=due, status="pending", original_subject=subject, original_body=body,
            engine=ctx.engine_label, run_id=ctx.run_id, created_at=now_utc())).inserted_primary_key[0]
    ctx.followups_made += 1
    return {"draft_id": int(draft_id), "company": acct["company"], "next_step": next_step, "due_date": due.isoformat()}


def t_write_report(ctx: RunContext, args: dict) -> dict:
    with ctx.engine.connect() as conn:
        rep = report.build(conn, ctx.today)
    return {"new_leads": rep["counts"]["new_leads"], "stalled": rep["counts"]["stalled"],
            "waiting_for_approval": rep["counts"]["waiting"], "top_lead": (rep["top_leads"] or [{}])[0].get("company")}


def t_finish(ctx: RunContext, args: dict) -> dict:
    n, m = len(ctx.leads_saved), ctx.drafts_made
    if n < MIN_LEADS or m < MIN_DRAFTS:
        raise ToolError(f"Not done yet: {n} leads and {m} first-touch drafts this run. "
                        f"The target is at least {MIN_LEADS} scored leads and {MIN_DRAFTS} drafts.")
    ctx.finished = True
    ctx.summary = str(args.get("summary") or "").strip()[:600]
    return {"ok": True}


HANDLERS: dict[str, Callable[[RunContext, dict], dict]] = {
    "read_business_notes": t_read_business_notes, "save_icp": t_save_icp, "web_search": t_web_search,
    "save_lead": t_save_lead, "read_crm": t_read_crm, "score_accounts": t_score_accounts,
    "create_draft": t_create_draft, "recommend_followup": t_recommend_followup, "write_report": t_write_report,
    "finish": t_finish,
}

_STR = {"type": "string"}
_LIST = {"type": "array", "items": {"type": "string"}}
TOOLS: list[dict] = [
    {"name": "read_business_notes", "description": "Read Acme's product notes, competitor notes and the won and lost deal notes. Call this first.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "save_icp", "description": "Save a short ideal customer profile the rep can edit. If the rep already edited it, theirs is kept and returned.",
     "input_schema": {"type": "object", "properties": {
         "summary": _STR, "industries": _LIST, "size_min": {"type": "integer"}, "size_max": {"type": "integer"},
         "regions": _LIST, "signals": {"type": "array", "items": {"type": "string", "enum": list(SIGNALS)}}, "exclusions": _LIST},
         "required": ["summary", "industries", "size_min", "size_max", "regions", "signals", "exclusions"]}},
    {"name": "web_search", "description": "Search the public web. Returns titles, URLs, snippets and dates. Only URLs returned here may be used as sources.",
     "input_schema": {"type": "object", "properties": {"query": _STR}, "required": ["query"]}},
    {"name": "save_lead", "description": "Save one real public company as a lead. The server scores it 0-100 from fit, buying signals and recency.",
     "input_schema": {"type": "object", "properties": {
         "company": _STR, "website": _STR, "industry": _STR,
         "employees": {"type": "integer", "description": "Staff count, if a source states it or you can estimate it."},
         "employees_source": {"type": "string", "enum": ["source", "estimate"]},
         "source_url": {"type": "string", "description": "URL from web_search where you found the company."},
         "reason": {"type": "string", "description": "One line on why they match the profile."},
         "fact": {"type": "string", "description": "One real, specific fact from the source: a news item, job post or technology they use."},
         "fact_url": _STR, "fact_date": {"type": "string", "description": "YYYY-MM-DD, YYYY-MM or YYYY, if known."},
         "signals": {"type": "array", "items": {"type": "string", "enum": list(SIGNALS)}}},
         "required": ["company", "industry", "source_url", "reason", "fact", "fact_url", "signals"]}},
    {"name": "read_crm", "description": "Read the CRM: counts by stage and every flagged account (stalled deals, no contact in 30+ days, likely upsells).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "score_accounts", "description": "Score all 50 CRM accounts 0-100 for priority and return the top ten with reasons.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "create_draft", "description": "Write a personalised first email for a lead, using one real fact from research. It goes to the approval queue and is never sent automatically.",
     "input_schema": {"type": "object", "properties": {
         "lead_id": {"type": "integer"}, "subject": _STR, "body": _STR, "fact": _STR,
         "fact_url": {"type": "string", "description": "The lead's source or fact URL."}},
         "required": ["lead_id", "subject", "body", "fact", "fact_url"]}},
    {"name": "recommend_followup", "description": "For a CRM account already in contact, suggest the next step and a date, with a draft email for approval.",
     "input_schema": {"type": "object", "properties": {
         "account_id": _STR, "next_step": _STR, "due_date": {"type": "string", "description": "YYYY-MM-DD within 21 days."},
         "subject": _STR, "body": _STR, "fact": {"type": "string", "description": "The CRM detail the follow-up is based on."}},
         "required": ["account_id", "next_step", "due_date", "subject", "body"]}},
    {"name": "write_report", "description": "Build the one-page weekly report from the database and return its headline numbers.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "finish", "description": "Finish with a two-sentence summary. Refused until this run has at least 10 scored leads and 5 first-touch drafts.",
     "input_schema": {"type": "object", "properties": {"summary": _STR}, "required": ["summary"]}},
]
assert not any(w in t["name"] for t in TOOLS for w in ("send", "mail", "post", "message")), "the agent must not be able to send"


def describe(name: str, args: dict, out: dict) -> str:
    if name == "read_business_notes":
        return f"Read product notes, competitor notes and {len(out['deal_notes'])} won and lost deal notes"
    if name == "save_icp":
        return "Kept the rep's edited customer profile" if out.get("kept_rep_profile") else "Saved the ideal customer profile"
    if name == "web_search":
        return f"Searched “{out['query']}” ({len(out['results'])} results)"
    if name == "save_lead":
        return f"Saved lead {out['company']}: {out['score']}/100"
    if name == "read_crm":
        s = out["summary"]
        return f"Read {s['total']} CRM accounts: {s['stalled']} stalled, {s['untouched']} untouched, {s['upsell']} likely upsells"
    if name == "score_accounts":
        top = out["top"][0] if out["top"] else None
        return f"Scored {out['scored']} accounts" + (f"; top is {top['company']} at {top['score']}" if top else "")
    if name == "create_draft":
        return f"Drafted a first email to {out['company']} (waiting for approval)"
    if name == "recommend_followup":
        due = date.fromisoformat(out["due_date"])
        return f"Follow-up for {out['company']}: {out['next_step']} by {due:%a} {due.day} {due:%b}"
    if name == "write_report":
        return f"Wrote the weekly report: {out['new_leads']} new leads, {out['waiting_for_approval']} drafts waiting"
    return "Finished"


def dispatch(ctx: RunContext, name: str, args: dict) -> tuple[dict, bool]:
    fn = HANDLERS.get(name)
    t0 = time.monotonic()
    ctx.tools_called.append(name)
    try:
        if not fn:
            raise ToolError(f"Unknown tool {name}.")
        out = fn(ctx, args or {})
        ctx.emit("tool", describe(name, args or {}, out), tool=name, ms=int((time.monotonic() - t0) * 1000))
        return out, False
    except (ToolError, ResearchError) as exc:
        ctx.emit("error", f"{name} refused: {exc}", tool=name, ms=int((time.monotonic() - t0) * 1000))
        return {"error": str(exc)}, True


# -------------------------------------------------------------------------------------- feedback

def feedback_context(conn: Connection, limit: int = FEEDBACK_ITEMS) -> list[dict]:
    q = (select(feedback.c.action, feedback.c.reason, feedback.c.edited_subject, feedback.c.edited_body,
                feedback.c.created_at, drafts.c.original_subject, drafts.c.original_body, drafts.c.kind,
                leads.c.company.label("lead_company"), accounts.c.company.label("account_company"))
         .select_from(feedback.join(drafts, drafts.c.id == feedback.c.draft_id)
                      .outerjoin(leads, leads.c.id == drafts.c.lead_id)
                      .outerjoin(accounts, accounts.c.id == drafts.c.account_id))
         .order_by(feedback.c.created_at.desc()).limit(limit))
    return [dict(r) for r in conn.execute(q).mappings()]


def feedback_lines(items: list[dict]) -> list[str]:
    lines = []
    for f in items:
        who = f["lead_company"] or f["account_company"] or "a prospect"
        if f["action"] == "reject":
            lines.append(f"Rejected the draft to {who} (“{f['original_subject']}”). Reason: {f['reason']}")
        elif f["action"] == "edit":
            lines.append(f"Edited the draft to {who}: subject “{f['original_subject']}” became "
                         f"“{f['edited_subject']}”; the rep's body starts: “{(f['edited_body'] or '')[:220]}”")
        else:
            lines.append(f"Approved the draft to {who} as written (“{f['original_subject']}”)")
    return lines


STYLE_RULES = [
    ("short", re.compile(r"\b(long|shorter|wordy|too much|brief|concise|tl;?dr|under \d+ words)\b", re.I), "keep emails short"),
    ("plain", re.compile(r"\b(jargon|buzzword|technical|acronym|fluff)\b", re.I), "use plain words"),
    ("pilot", re.compile(r"\b(pilot|trial|try it)\b", re.I), "mention the 14-day pilot"),
]
# The ask goes one way or the other, so it follows the newest piece of feedback that mentions it.
ASK_CALL = re.compile(r"\b(ask|asks|asking|suggest|offer|propose|book|request)\w*\b[^.]{0,30}?\b(call|meeting|chat|demo)\b", re.I)
ASK_SOFT = re.compile(r"\b(pushy|salesy|aggressive|hard sell|too strong|no (call|meeting|demo)|without a (call|meeting|demo)|"
                      r"skip\w* (the |a )?(call|meeting|demo)|(don't|do not|stop) (ask|push)\w*)\b", re.I)
MINUTES = re.compile(r"\b(\d{1,2})[- ]?min", re.I)


def learned_style(items: list[dict]) -> tuple[set[str], list[str]]:
    """What the offline agent takes from the rep's feedback (the live agent reads the feedback itself).
    `items` is newest first."""
    style, notes = set(), []
    for key, pattern, words in STYLE_RULES:
        hits = sum(1 for f in items if pattern.search(f.get("reason") or ""))
        if hits:
            style.add(key)
            notes.append(f"{words} ({hits} piece{'s' if hits > 1 else ''} of feedback)")
    for f in items:
        reason = f.get("reason") or ""
        if ASK_CALL.search(reason) and not ASK_SOFT.search(reason):
            m = MINUTES.search(reason)
            style.add(f"call:{m.group(1) if m else 15}")
            notes.append(f"end by asking for a {m.group(1) if m else 15}-minute call")
            break
        if ASK_SOFT.search(reason):
            style.add("soft")
            notes.append("use a softer ask, with no call")
            break
    edited = [f for f in items if f["action"] == "edit" and f.get("edited_subject")]
    if edited and sum(1 for f in edited if f["edited_subject"].strip().endswith("?")) * 2 >= len(edited):
        style.add("question")
        notes.append("write subjects as questions, like the rep's edits")
    if edited and sum(len((f["edited_body"] or "").split()) for f in edited) / len(edited) < 75:
        style.add("short")
        if not any(n.startswith("keep emails short") for n in notes):
            notes.append("keep emails short, like the rep's edits")
    return style, notes


# --------------------------------------------------------------------------------- system prompt

def system_prompt(current_icp: dict | None, fb: list[str], today: date) -> str:
    profile = json.dumps({k: v for k, v in current_icp.items() if k not in ("updated_at",)}, ensure_ascii=False) \
        if current_icp else "Not written yet: write it with save_icp after reading the notes."
    feedback_block = "\n".join(f"- {line}" for line in fb) if fb else "- No feedback yet."
    return f"""You are the research and outreach agent for Acme Cloud Security, a fictional company in a demo. Today is {today.isoformat()}.
You work for a sales rep who approves everything you write.

Hard rules:
- You cannot send email or messages. You only create drafts. A person approves them later.
- Use only real public companies you found with web_search. Never invent people, contact details, facts or URLs.
- Every lead needs its source URL and a one-line reason. Every first email uses exactly one real fact from research and cites its URL.
- Skip security vendors and anyone the profile excludes.

Work in this order:
1. read_business_notes, then save_icp (if the rep edited the profile, keep theirs).
2. Run 3 to 5 web_search queries for companies that match the profile, and save_lead at least 12 of them.
3. read_crm, then score_accounts.
4. create_draft for the 5 highest-scoring leads.
5. recommend_followup for 3 accounts that need a next step (a stalled deal, a likely upsell, and one with no recent contact), with a date.
6. write_report, then finish.
Call several tools in one turn when they don't depend on each other.

How to write: under 120 words, specific, plain words, no buzzwords, one clear question. Address the team ("Hi <Company> team,") and sign as {REP}, Acme Cloud Security.

Current ideal customer profile:
{profile}

Feedback from the rep on earlier drafts, newest first. Follow it:
{feedback_block}"""


# ----------------------------------------------------------------------------------- the two loops

def make_client(settings: Settings):  # separated so tests can swap in a fake
    import anthropic
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=60.0, max_retries=2)


def run_live(ctx: RunContext, fb_items: list[dict]) -> None:
    client = make_client(ctx.settings)
    with ctx.engine.connect() as conn:
        current = get_icp(conn)
    system = system_prompt(current, feedback_lines(fb_items), ctx.today)
    messages: list[dict] = [{"role": "user", "content": "Run this week's workflow now, from reading the notes to finishing."}]
    nudges = 0
    for _ in range(ctx.settings.max_turns):
        if time.monotonic() > ctx.deadline:
            raise RunFailed("The run hit its time limit before finishing.")
        resp = client.messages.create(model=ctx.settings.claude_model, max_tokens=3000, system=system,
                                      tools=TOOLS, messages=messages)
        ctx.input_tokens += getattr(resp.usage, "input_tokens", 0) or 0
        ctx.output_tokens += getattr(resp.usage, "output_tokens", 0) or 0
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        if not uses:
            if ctx.finished:
                return
            nudges += 1
            if nudges > 2:
                raise RunFailed("The model stopped calling tools before finishing.")
            messages.append({"role": "user", "content": "Keep going with the tools, and call finish when the work is done."})
            continue
        results = []
        for u in uses:
            out, is_error = dispatch(ctx, u.name, dict(u.input or {}))
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out, default=str)[:9000],
                            "is_error": is_error})
        messages.append({"role": "user", "content": results})
        if ctx.finished:
            return
    raise RunFailed(f"The run used all {ctx.settings.max_turns} turns without finishing.")


SUBJECTS = {
    "hiring_security": ("Your first security hire at {c}", "Who owns cloud security at {c} until the new hire starts?"),
    "compliance": ("Keeping {p} SOC 2 evidence current", "Ready for {p} next audit?"),
    "funding": ("Security reviews after {p} new funding", "Are security reviews slowing {p} bigger deals?"),
}
BRIDGES = {
    "hiring_security": ["A first security hire usually inherits two jobs at once: finding risky cloud settings and keeping the evidence auditors ask for.",
                        "Acme Shield does both from one place and is set up in a day with read-only access."],
    "compliance": ["Keeping that report clean for the next audit means the evidence has to stay current between audits.",
                   "Acme Shield checks your cloud settings all year and files the evidence your auditor will ask for."],
    "funding": ["New funding usually brings bigger customers, and with them, longer security reviews.",
                "Acme Shield puts live cloud checks and SOC 2 evidence in one place, so those questionnaires take hours rather than weeks."],
}
ASKS = {
    "hiring_security": "Would it help to see what it finds in one of your cloud accounts before the new hire starts?",
    "compliance": "Is the next audit cycle something you're planning for yet?",
    "funding": "Are security reviews slowing any deals right now?",
}
SOFT_ASK = "If it's useful, I can send a one-page note on how teams your size set this up. No call needed."
CALL_ASK = "Would a {m}-minute call next week be worth it to see if this fits?"
PLAIN = {"read-only access": "read-only permissions", "questionnaires": "security forms"}


def offline_email(lead: dict, hook: str, style: set[str]) -> tuple[str, str]:
    signals = jload(lead["signals"], [])
    # The first signal is the one the cited fact is about, so the email stays on that point.
    angle = next((s for s in signals if s in SUBJECTS), "compliance")
    name = lead["company"]
    subject = SUBJECTS[angle][1 if "question" in style else 0].format(c=name, p=name + ("'" if name.endswith("s") else "'s"))
    bridge = BRIDGES[angle][:1] if "short" in style else list(BRIDGES[angle])
    if "pilot" in style:
        bridge.append("There's a 14-day pilot, so you can judge it on your own setup.")
    text = " ".join(bridge)
    if "plain" in style:
        for a, b in PLAIN.items():
            text = text.replace(a, b)
    call = next((k.split(":")[1] for k in style if k.startswith("call:")), None)
    ask = CALL_ASK.format(m=call) if call else SOFT_ASK if "soft" in style else ASKS[angle]
    body = f"Hi {lead['company']} team,\n\nI saw that {hook}. {text}\n\n{ask}\n\nBest,\n{REP}\nAcme Cloud Security"
    return subject, body


def offline_followup(acct: dict, today: date) -> dict:
    def workday(days: int) -> date:
        d = today
        while days:
            d += timedelta(days=1)
            if d.weekday() < 5:
                days -= 1
        return d
    owner, c = acct["owner"], acct["company"]
    if "stalled" in acct["flags"]:
        opener = (f"It's been {acct['days_in_stage']} days since we sent the proposal, and I want to make sure it still fits."
                  if acct["stage"] == "Proposal" else
                  f"We've been working through terms for {acct['days_in_stage']} days, and I want to make sure nothing is stuck on our side.")
        return {"next_step": "Call the champion and ask what's blocking the decision", "due_date": workday(2).isoformat(),
                "subject": f"Next step on the {acct['stage'].lower()} for {c}",
                "body": f"Hi {c} team,\n\n{opener} Is there a question on scope or price I can answer, or would it be better to pause until next quarter?\n\nBest,\n{owner}\nAcme Cloud Security",
                "fact": acct["notes"]}
    if "upsell" in acct["flags"]:
        signal = acct["expansion_signal"].rstrip(".")
        return {"next_step": "Share pricing for the expansion and offer a 30-minute review", "due_date": workday(3).isoformat(),
                "subject": f"Covering {c}'s next step",
                "body": f"Hi {c} team,\n\nYou mentioned this: {signal[0].lower() + signal[1:]}. I can send pricing that covers it and walk your team through the setup in 30 minutes. Would early next week work?\n\nBest,\n{owner}\nAcme Cloud Security",
                "fact": acct["expansion_signal"]}
    return {"next_step": "Send a short check-in with something useful", "due_date": workday(1).isoformat(),
            "subject": f"Checking in, {c}",
            "body": f"Hi {c} team,\n\nIt's been {acct['days_since_contact']} days since we last spoke, so a quick check-in. We keep a short checklist of the cloud settings auditors ask about most; would it help if I sent it over?\n\nBest,\n{owner}\nAcme Cloud Security",
            "fact": acct["notes"]}


def run_offline(ctx: RunContext, fb_items: list[dict]) -> None:
    style, notes = learned_style(fb_items)
    if notes:
        ctx.emit("note", "Applying the rep's feedback: " + "; ".join(notes))
    dispatch(ctx, "read_business_notes", {})
    dispatch(ctx, "save_icp", DEFAULT_ICP)
    hooks: dict[str, str] = {}
    for q in SNAPSHOT["queries"]:
        out, failed = dispatch(ctx, "web_search", {"query": q["query"]})
        if failed:
            continue
        for r in q["results"]:
            if r.get("category") == "security_vendor":
                ctx.emit("note", f"Skipped {r['company']}: a security vendor, which the profile excludes")
                continue
            res, failed = dispatch(ctx, "save_lead", {
                "company": r["company"], "website": r.get("website"), "industry": r["industry"],
                "employees": r.get("employees"), "employees_source": "source" if r.get("employees") else None,
                "source_url": r["url"], "fact_url": r["url"], "reason": _reason(r), "fact": r["snippet"],
                "fact_date": r.get("published"), "signals": r.get("signals", [])})
            if not failed:
                hooks[company_key(r["company"])] = r.get("hook") or r["snippet"]
    dispatch(ctx, "read_crm", {})
    dispatch(ctx, "score_accounts", {})
    with ctx.engine.connect() as conn:
        top = conn.execute(select(leads).where(leads.c.id.in_(ctx.leads_saved))
                           .order_by(leads.c.score.desc(), leads.c.id).limit(MIN_DRAFTS)).mappings().all()
        accts = crm.all_accounts(conn, ctx.today)
    for lead in top:
        subject, body = offline_email(dict(lead), hooks.get(lead["company_key"], lead["fact"]), style)
        dispatch(ctx, "create_draft", {"lead_id": lead["id"], "subject": subject, "body": body,
                                       "fact": lead["fact"], "fact_url": lead["fact_url"]})
    scored = sorted(accts, key=lambda a: (-(a["score"] or 0), a["id"]))
    for flag in ("stalled", "upsell", "untouched"):
        pick = next((a for a in scored if flag in a["flags"]), None)
        if pick:
            dispatch(ctx, "recommend_followup", {"account_id": pick["id"], **offline_followup(pick, ctx.today)})
    dispatch(ctx, "write_report", {})
    dispatch(ctx, "finish", {"summary": f"Found {len(ctx.leads_saved)} leads and drafted {ctx.drafts_made} first emails "
                                        f"and {ctx.followups_made} follow-ups. Everything is waiting for approval."})


def _reason(r: dict) -> str:
    sig = r.get("signals", [])
    if "hiring_security" in sig:
        return "B2B software company hiring for security, so cloud security ownership is changing hands now."
    if "funding" in sig:
        return "B2B SaaS with new funding, which usually brings enterprise security reviews."
    return "B2B SaaS that has just been through a SOC 2 or ISO audit and must keep evidence current."


# ------------------------------------------------------------------------------- run orchestration

def seed_first_run(engine: Engine, settings: Settings, today: date) -> int | None:
    """On a brand-new database, run the offline agent once so the first visitor finds real work on the desk.
    It is logged like any other run, under the offline engine's name."""
    with engine.connect() as conn:
        if conn.execute(select(func.count()).select_from(agent_runs)).scalar():
            return None
    offline = replace(settings, anthropic_api_key="", tavily_api_key="", offline_step_s=0)
    return start_run(engine, offline, today, background=False)


def start_run(engine: Engine, settings: Settings, today: date, background: bool = True) -> int:
    if not _run_lock.acquire(blocking=False):
        raise AlreadyRunning()
    try:
        research = Research(settings)
        label = f"live Claude ({settings.claude_model})" if settings.live_model else OFFLINE_ENGINE
        with tx(engine) as conn:
            run_id = int(conn.execute(agent_runs.insert().values(
                started_at=now_utc(), status="running", engine=label, research=research.label, tools_called="[]",
                input_tokens=0, output_tokens=0, feedback_used=0)).inserted_primary_key[0])
    except Exception:
        _run_lock.release()
        raise
    if background:
        threading.Thread(target=_execute, args=(engine, settings, run_id, today, research, label), daemon=True).start()
    else:
        _execute(engine, settings, run_id, today, research, label)
    return run_id


def _execute(engine: Engine, settings: Settings, run_id: int, today: date, research: Research, label: str) -> None:
    started = time.monotonic()
    ctx = RunContext(engine=engine, settings=settings, research=research, run_id=run_id, today=today,
                     deadline=started + settings.run_timeout_s, engine_label=label)
    try:
        with engine.connect() as conn:
            fb = feedback_context(conn)
        with tx(engine) as conn:
            conn.execute(update(agent_runs).where(agent_runs.c.id == run_id).values(feedback_used=len(fb)))
        ctx.emit("note", f"Started with {label} and {research.label}. {len(fb)} feedback items are in context.")
        (run_live if settings.live_model else run_offline)(ctx, fb)
        if not ctx.finished:
            raise RunFailed("The agent stopped before finishing.")
        secs = time.monotonic() - started
        paced = "" if settings.live_model or not settings.offline_step_s else ", paced so each step can be watched"
        outcome = (f"{len(ctx.leads_saved)} leads scored, {ctx.drafts_made} first emails and {ctx.followups_made} "
                   f"follow-ups drafted in {secs:.1f} s{paced}. Nothing was sent.")
        with tx(engine) as conn:
            conn.execute(update(agent_runs).where(agent_runs.c.id == run_id).values(
                status="succeeded", finished_at=now_utc(), outcome=outcome, tools_called=jdump(ctx.tools_called),
                input_tokens=ctx.input_tokens, output_tokens=ctx.output_tokens))
            log_activity(conn, "agent_run", "success", f"Run {run_id}: {outcome}")
        ctx.emit("done", outcome)
    except Exception as exc:  # noqa: BLE001 - every failure is logged and alerted
        message = f"{exc.__class__.__name__}: {exc}"[:500]
        alert = slack_alert(settings, f":warning: Sales agent run {run_id} failed: {message}")
        with tx(engine) as conn:
            conn.execute(update(agent_runs).where(agent_runs.c.id == run_id).values(
                status="failed", finished_at=now_utc(), error=message, tools_called=jdump(ctx.tools_called),
                input_tokens=ctx.input_tokens, output_tokens=ctx.output_tokens))
            log_activity(conn, "agent_run", "failure", f"Run {run_id}; alert: {alert['detail']}", message)
        try:
            ctx.emit("error", f"The run failed: {message}")
            ctx.emit("done", "Failed")
        except Exception:  # noqa: BLE001
            pass
    finally:
        _run_lock.release()


def mark_stale_runs(engine: Engine) -> None:
    """A restart mid-run leaves a run marked as running; close it honestly."""
    with tx(engine) as conn:
        conn.execute(update(agent_runs).where(agent_runs.c.status == "running").values(
            status="failed", finished_at=now_utc(), error="The server restarted during this run."))
