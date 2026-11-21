"""The agent's tools.

There is deliberately no tool that can send an email or message. The most a run can do is put
a draft in the approval queue; sending is a separate, manual step for a person (see
app/workflows/approvals.py). tests/test_safety.py checks this list.

Guardrails enforced here (each failure goes back to the model as a tool error it can fix):
* provenance: a lead's facts may only cite URLs that search_web or read_page returned in this run;
* real companies only: reserved demo domains and existing CRM accounts are refused;
* no invented contact details: first emails greet the team, never a named person, and contain
  no email addresses or phone numbers;
* learned rules from reviewer feedback (length, call to action, targeting) are enforced.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy import select, update

from app.agent import guardrails
from app.agent.lessons import Lessons, word_count
from app.agent.scoring import (
    CATEGORIES,
    CLOUD_VALUES,
    REGIONS,
    SIGNAL_TYPES,
    SIZE_BANDS,
    company_key,
    parse_fact_date,
    score_lead,
)
from app.db import accounts, activity, drafts, leads, utcnow
from app.services.knowledge import DOCS, read_doc
from app.services.research import ResearchError, normalize_url
from app.workflows import crm, icp as icp_store

log = logging.getLogger(__name__)
RESERVED_TLDS = (".example", ".test", ".invalid", ".localhost", ".local", ".internal")
OPEN_DRAFT = ("pending", "approved", "edited", "sent")
GREETING_RE = re.compile(r"^(hi|hello|hey)( there| team| all| [\w .&'’-]{1,60} team)?\s*[,!]?\s*$", re.I)
MAX_PAGE_READS = 8
NETWORK_TOOLS = {"search_web", "read_page"}


class ToolError(Exception):
    pass


@dataclass
class RunState:
    run_id: str
    mode: str  # live | offline
    now: datetime
    icp: dict[str, Any]
    icp_version: int
    lessons: Lessons
    target_leads: int
    target_drafts: int
    target_followups: int
    rep: dict[str, str]
    on_step: Callable[..., None] = lambda *a, **k: None
    started: float = field(default_factory=time.perf_counter)
    seen: dict[str, dict[str, Any]] = field(default_factory=dict)
    tools_called: list[dict[str, Any]] = field(default_factory=list)
    knowledge_read: set[str] = field(default_factory=set)
    icp_saved: bool = False
    icp_suggestion: dict[str, Any] | None = None
    crm_analyzed: bool = False
    crm_flagged: list[dict[str, Any]] = field(default_factory=list)
    leads_created: int = 0
    leads_updated: int = 0
    scored_lead_ids: set[int] = field(default_factory=set)
    outreach_created: int = 0
    followups_created: int = 0
    page_reads: int = 0
    research_sources: set[str] = field(default_factory=set)
    finished: bool = False
    summary: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def today(self) -> date:
        return self.now.date()

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)


def _enum(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": values}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "read_knowledge",
        "description": "Read one of Acme's internal notes: 'product' (what we sell, pricing, ideal customer), "
        "'competitors', or 'deal_notes' (3 won and 3 lost deals).",
        "input_schema": {"type": "object", "properties": {"doc": _enum(list(DOCS))}, "required": ["doc"]},
    },
    {
        "name": "save_icp",
        "description": "Save the ideal customer profile (ICP) you derived from the notes. Leads and accounts are scored "
        "against it. If the rep has edited the ICP, theirs stays active and yours is kept as a suggestion.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "2-4 plain sentences the rep can read and edit."},
                "target_categories": {"type": "array", "items": _enum(list(CATEGORIES))},
                "adjacent_categories": {"type": "array", "items": _enum(list(CATEGORIES))},
                "excluded_categories": {"type": "array", "items": _enum(list(CATEGORIES))},
                "employee_min": {"type": "integer"},
                "employee_max": {"type": "integer"},
                "regions": {"type": "array", "items": _enum([r for r in REGIONS if r != "unknown"])},
                "signal_weights": {
                    "type": "object",
                    "description": "Points (0-30) for each buying signal type.",
                    "properties": {k: {"type": "integer"} for k in SIGNAL_TYPES},
                },
                "exclusions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "target_categories", "excluded_categories", "employee_min", "employee_max", "regions"],
        },
    },
    {
        "name": "search_web",
        "description": "Search the public web for real companies and recent facts (news, job posts, technology they use). "
        "Returns titles, URLs, snippets and dates. Only URLs returned by search_web or read_page may be cited.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A focused search query, 3-12 words."}},
            "required": ["query"],
        },
    },
    {
        "name": "read_page",
        "description": "Read the text of one public web page to confirm a fact before citing it. Use sparingly.",
        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    },
    {
        "name": "save_lead",
        "description": "Save a real company as a lead with 1-3 facts from this run's research and a one-line reason. "
        "The score (0-100: fit, signals, recency) is calculated for you from the ICP and returned.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "domain": {"type": "string", "description": "Company website domain if you saw it, else empty."},
                "industry": {"type": "string", "description": "What the company does, in a few words."},
                "category": _enum(list(CATEGORIES)),
                "size_band": _enum(list(SIZE_BANDS)),
                "region": _enum(REGIONS),
                "cloud_native": _enum(CLOUD_VALUES),
                "facts": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string", "description": "One sentence, in your own words."},
                            "url": {"type": "string", "description": "A URL returned by search_web or read_page."},
                            "date": {"type": "string", "description": "YYYY-MM-DD or YYYY-MM of the event."},
                            "type": _enum(list(SIGNAL_TYPES)),
                        },
                        "required": ["fact", "url", "type"],
                    },
                },
                "reason": {"type": "string", "description": "One line: why this company, why now."},
            },
            "required": ["company", "category", "size_band", "region", "cloud_native", "facts", "reason"],
        },
    },
    {
        "name": "analyze_crm",
        "description": "Analyse all CRM accounts: flags stalled deals, accounts with no contact in 30+ days and likely "
        "upsells, and scores every account 0-100. Returns the flagged accounts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_account_activity",
        "description": "Get one CRM account's details and recent activity, to write a relevant follow-up.",
        "input_schema": {"type": "object", "properties": {"account_id": {"type": "integer"}}, "required": ["account_id"]},
    },
    {
        "name": "list_leads",
        "description": "List saved leads ranked by score, with whether each is eligible for a first email "
        "(not excluded, no open or sent draft, not ruled out by reviewer feedback).",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
    },
    {
        "name": "draft_outreach",
        "description": "Put a personalised first email for an eligible lead in the approval queue. It is NOT sent. "
        "Use exactly one fact from that lead and cite its URL. Greet the team (no person names).",
        "input_schema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "integer"},
                "subject": {"type": "string"},
                "body": {"type": "string", "description": "Plain text. Greeting, short body, one ask, signature."},
                "cited_fact": {"type": "string", "description": "The fact the email uses."},
                "source_url": {"type": "string", "description": "The lead's fact URL you used."},
            },
            "required": ["lead_id", "subject", "body", "cited_fact", "source_url"],
        },
    },
    {
        "name": "draft_follow_up",
        "description": "Put a follow-up email for a CRM account that was already contacted in the approval queue, with "
        "the recommended next step and send date. It is NOT sent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "integer"},
                "next_step": {"type": "string", "description": "What the rep should do next, in one line."},
                "send_date": {"type": "string", "description": "YYYY-MM-DD, a weekday 1-14 days from today."},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["account_id", "next_step", "send_date", "subject", "body"],
        },
    },
    {
        "name": "finish",
        "description": "End the run with a 2-3 sentence summary for the rep.",
        "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
    },
]


def _clip(value: Any, n: int = 120) -> Any:
    if isinstance(value, str):
        return value if len(value) <= n else value[: n - 1] + "…"
    return value


class ToolBox:
    def __init__(self, ctx: Any, state: RunState):
        self.ctx = ctx
        self.engine = ctx.engine
        self.state = state

    # ------------------------------------------------------------------ dispatch
    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        return TOOL_SCHEMAS

    def call(self, name: str, args: dict[str, Any] | None, *, via: str = "agent") -> tuple[Any, bool]:
        handler = getattr(self, f"_t_{name}", None)
        args = args if isinstance(args, dict) else {}
        t0 = time.perf_counter()
        if handler is None:
            result, ok = {"error": f"Unknown tool '{name}'."}, False
        else:
            try:
                result, ok = handler(args, via=via), True
            except ToolError as exc:
                result, ok = {"error": str(exc)}, False
            except ResearchError as exc:
                result, ok = {"error": str(exc)}, False
            except Exception as exc:  # a tool bug must not kill the run; the model sees the error
                log.exception("tool %s failed", name)
                result, ok = {"error": f"Tool failed: {type(exc).__name__}: {exc}"}, False
        record = {
            "tool": name,
            "via": via,
            "ok": ok,
            "ms": int((time.perf_counter() - t0) * 1000),
            "at_ms": self.state.elapsed_ms,
            "input": self._input_summary(name, args),
            "result": self._result_summary(name, result, ok),
        }
        with self.state.lock:
            self.state.tools_called.append(record)
        self.state.on_step(name, ok=ok, via=via, result=record["result"])
        return result, ok

    def call_many(self, uses: list[dict[str, Any]], *, via: str = "agent") -> list[tuple[str, Any, bool]]:
        """Run a turn's tool calls. Network tools run in parallel; database writes stay sequential."""
        results: dict[str, tuple[Any, bool]] = {}
        network = [u for u in uses if u["name"] in NETWORK_TOOLS]
        if network:
            with ThreadPoolExecutor(max_workers=min(4, len(network))) as pool:
                futures = {u["id"]: pool.submit(self.call, u["name"], u.get("input"), via=via) for u in network}
                for uid, fut in futures.items():
                    results[uid] = fut.result()
        for u in uses:
            if u["id"] not in results:
                results[u["id"]] = self.call(u["name"], u.get("input"), via=via)
        return [(u["id"], *results[u["id"]]) for u in uses]

    @staticmethod
    def _input_summary(name: str, args: dict[str, Any]) -> dict[str, Any]:
        keep = {
            "read_knowledge": ("doc",),
            "search_web": ("query",),
            "read_page": ("url",),
            "save_lead": ("company", "category", "size_band"),
            "get_account_activity": ("account_id",),
            "draft_outreach": ("lead_id", "subject", "source_url"),
            "draft_follow_up": ("account_id", "next_step", "send_date", "subject"),
            "save_icp": ("employee_min", "employee_max"),
            "list_leads": ("limit",),
        }.get(name, ())
        return {k: _clip(args.get(k)) for k in keep if k in args}

    @staticmethod
    def _result_summary(name: str, result: Any, ok: bool) -> str:
        if not ok:
            return _clip(result.get("error", "error") if isinstance(result, dict) else str(result), 300)
        if name == "search_web":
            return f"{len(result.get('results', []))} results ({result.get('source')})"
        if name == "save_lead":
            verb = "saved" if result.get("created") else "updated"
            return f"{verb} {result['company']}: score {result['score']}" + (" (excluded)" if result.get("status") == "excluded" else "")
        if name == "analyze_crm":
            c = result["counts"]
            return f"{result['analyzed']} accounts: {c['stalled']} stalled, {c['no_contact']} no contact 30+ days, {c['upsell']} upsell"
        if name in ("draft_outreach", "draft_follow_up"):
            return f"draft #{result['draft_id']} waiting for approval"
        if name == "read_knowledge":
            return f"{result['doc']}: {len(result['content'])} characters"
        if name == "save_icp":
            return f"ICP v{result.get('version')}" + ("" if result.get("saved") else " kept (rep edited); suggestion stored")
        if name == "list_leads":
            return f"{len(result.get('leads', []))} leads, {sum(1 for l in result.get('leads', []) if l['eligible'])} eligible"
        if name == "get_account_activity":
            return f"{result['company']}: {len(result['activity'])} activities"
        if name == "read_page":
            return _clip(result.get("title") or result.get("url"), 100)
        return "done"

    # ------------------------------------------------------------------ helpers
    def _remember(self, item: dict[str, Any], source: str) -> None:
        key = normalize_url(item.get("url", ""))
        if key:
            with self.state.lock:
                self.state.seen[key] = {**item, "source": source}
                self.state.research_sources.add(source)

    def eligible(self, lead: dict[str, Any], open_draft_ids: set[int]) -> tuple[bool, str | None]:
        lessons = self.state.lessons
        if lead["status"] == "excluded":
            return False, lead.get("excluded_reason") or "Excluded by the ICP."
        if lead["status"] == "contacted":
            return False, "Already contacted."
        if lead["id"] in open_draft_ids:
            return False, "Already has a draft in the queue or approved."
        if lead.get("size_band") in lessons.skip_size_bands:
            return False, f"Skipped by a learned rule: no {lead['size_band']} employee companies."
        if lead.get("category") in lessons.skip_categories:
            return False, f"Skipped by a learned rule: no {CATEGORIES.get(lead['category'], lead['category']).lower()}s."
        return True, None

    def ranked_leads(self, limit: int = 25) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(select(leads).order_by(leads.c.score.desc(), leads.c.id).limit(200))]
            open_ids = {
                r.lead_id
                for r in conn.execute(select(drafts.c.lead_id).where(drafts.c.lead_id.is_not(None), drafts.c.status.in_(OPEN_DRAFT)))
            }
        out = []
        for lead in rows:
            ok, why = self.eligible(lead, open_ids)
            out.append({**lead, "eligible": ok, "why_not": why})
        return out[:limit]

    # ------------------------------------------------------------------ tools
    def _t_read_knowledge(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        doc = args.get("doc")
        if doc not in DOCS:
            raise ToolError(f"doc must be one of: {', '.join(DOCS)}")
        self.state.knowledge_read.add(doc)
        return {"doc": doc, "content": read_doc(doc, self.engine)}

    def _t_save_icp(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        self.state.icp_saved = True
        if icp_store.rep_has_edited(self.engine):
            from app.agent.scoring import normalize_icp

            self.state.icp_suggestion = normalize_icp(args)
            active = icp_store.active_icp(self.engine)
            return {
                "saved": False,
                "version": active["version"],
                "note": "The rep has edited the ICP, so their version stays active. Your suggestion is stored on this run for review.",
                "active_icp": active["criteria"],
            }
        saved = icp_store.save_version(self.engine, args, author="agent", run_id=self.state.run_id, note="Written by the agent from the product, competitor and deal notes.")
        self.state.icp = saved["criteria"]
        self.state.icp_version = saved["version"]
        return {"saved": True, "version": saved["version"], "icp": saved["criteria"]}

    def _t_search_web(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        query = " ".join(str(args.get("query") or "").split())
        if not 3 <= len(query) <= 200:
            raise ToolError("query must be 3 to 200 characters.")
        research = self.ctx.research
        use_cache = via == "fallback" and research.source == "web"
        note = None
        try:
            results = research.search(query, use_cache=use_cache)
            source = "cache" if use_cache or research.source == "cache" else "web"
        except ResearchError as exc:
            log.warning("web search failed, using the research cache: %s", exc)
            results = research.search(query, use_cache=True)
            source, note = "cache", f"Web search failed ({exc}); results come from the research cache."
        for item in results:
            self._remember(item, source)
        payload: dict[str, Any] = {
            "query": query,
            "source": source,
            "results": [{k: item.get(k) for k in ("title", "url", "content", "published_date")} for item in results],
        }
        if note:
            payload["note"] = note
        return payload

    def _t_read_page(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        url = str(args.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ToolError("url must start with http:// or https://")
        with self.state.lock:
            if self.state.page_reads >= MAX_PAGE_READS:
                raise ToolError(f"Page read limit ({MAX_PAGE_READS}) reached for this run. Use the search snippets.")
            self.state.page_reads += 1
        page = self.ctx.research.read_page(url)
        if not page:
            raise ToolError("Could not read that page (blocked, not HTML or not public).")
        self._remember({"url": page.get("url") or url, "title": page.get("title"), "content": page.get("excerpt")}, page.get("source", "web"))
        if normalize_url(url) != normalize_url(page.get("url") or url):
            self._remember({"url": url, "title": page.get("title"), "content": page.get("excerpt")}, page.get("source", "web"))
        return {"url": page.get("url") or url, "title": page.get("title"), "excerpt": (page.get("excerpt") or "")[:1500]}

    def _t_save_lead(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        company = " ".join(str(args.get("company") or "").split())
        if not 2 <= len(company) <= 120:
            raise ToolError("company must be 2 to 120 characters.")
        domain = re.sub(r"^https?://", "", str(args.get("domain") or "").strip().lower()).split("/")[0].removeprefix("www.")
        if domain and ("." not in domain or domain.endswith(RESERVED_TLDS)):
            raise ToolError("Use the company's real public domain, or leave domain empty.")
        attrs = {
            "category": args.get("category") if args.get("category") in CATEGORIES else "other",
            "size_band": args.get("size_band") if args.get("size_band") in SIZE_BANDS else "unknown",
            "region": args.get("region") if args.get("region") in REGIONS else "unknown",
            "cloud_native": args.get("cloud_native") if args.get("cloud_native") in CLOUD_VALUES else "unknown",
        }
        reason = " ".join(str(args.get("reason") or "").split())
        if not 10 <= len(reason) <= 240:
            raise ToolError("reason must be one line of 10 to 240 characters.")
        raw_facts = args.get("facts") or []
        if not isinstance(raw_facts, list) or not 1 <= len(raw_facts) <= 3:
            raise ToolError("Give 1 to 3 facts.")
        facts = []
        for f in raw_facts:
            if not isinstance(f, dict):
                raise ToolError("Each fact must be an object with fact, url, date and type.")
            text = " ".join(str(f.get("fact") or "").split())
            url = str(f.get("url") or "").strip()
            if not 10 <= len(text) <= 300:
                raise ToolError("Each fact must be one sentence of 10 to 300 characters.")
            seen = self.state.seen.get(normalize_url(url))
            if not seen:
                raise ToolError(
                    f"{url or 'This URL'} was not returned by search_web or read_page in this run. "
                    "Only cite pages you have actually seen."
                )
            d = parse_fact_date(f.get("date")) or parse_fact_date(seen.get("published_date"))
            ftype = f.get("type") if f.get("type") in SIGNAL_TYPES else "news"
            fact = {"fact": text, "url": seen["url"], "date": d.isoformat() if d else None, "type": ftype,
                    "title": _clip(seen.get("title") or "", 160), "source": seen.get("source")}
            if seen.get("source") == "cache":
                entry = self.ctx.research.cache.entry_for_url(seen["url"])
                if entry and entry.get("hook"):
                    fact["hook"] = entry["hook"]
            facts.append(fact)

        key = company_key(company)
        with self.engine.begin() as conn:
            crm_rows = conn.execute(select(accounts.c.company, accounts.c.domain)).fetchall()
            if any(company_key(c) == key or (domain and d == domain) for c, d in crm_rows):
                raise ToolError(f"{company} is already in the CRM. Leads must be new companies.")
            existing = conn.execute(select(leads).where(leads.c.company_key == key)).first()
            now = utcnow()
            if existing:
                ex = dict(existing._mapping)
                merged = {f["url"]: f for f in (ex["facts"] or [])}
                for f in facts:
                    merged[f["url"]] = f
                facts_all = sorted(merged.values(), key=lambda f: f.get("date") or "", reverse=True)[:5]
                for k, v in attrs.items():
                    if v in ("unknown", "other") and ex.get(k) not in (None, "unknown", "other"):
                        attrs[k] = ex[k]
                scored = score_lead(attrs, facts_all, self.state.icp, self.state.today)
                if scored["excluded"]:
                    status, excluded_reason = "excluded", scored["excluded_reason"]
                elif ex["status"] == "excluded" and (ex.get("excluded_reason") or "").startswith("Excluded by the ICP"):
                    status, excluded_reason = "new", None  # the ICP no longer excludes it
                else:
                    status = ex["status"]
                    excluded_reason = ex.get("excluded_reason") if status == "excluded" else None
                conn.execute(
                    update(leads).where(leads.c.id == ex["id"]).values(
                        domain=domain or ex["domain"], industry=_clip(args.get("industry") or ex["industry"] or "", 200),
                        **attrs, facts=facts_all, source_url=facts[0]["url"], reason=reason, score=scored["score"],
                        score_reason=scored["reason"], score_parts=scored["parts"], status=status,
                        excluded_reason=excluded_reason,
                        last_run_id=self.state.run_id, research_source=facts[0]["source"], updated_at=now,
                    )
                )
                lead_id, created = ex["id"], False
                self.state.leads_updated += 1
            else:
                scored = score_lead(attrs, facts, self.state.icp, self.state.today)
                status = "excluded" if scored["excluded"] else "new"
                result = conn.execute(
                    leads.insert().values(
                        company=company, company_key=key, domain=domain or None,
                        industry=_clip(args.get("industry") or "", 200), **attrs, source_url=facts[0]["url"],
                        reason=reason, facts=facts, score=scored["score"], score_reason=scored["reason"],
                        score_parts=scored["parts"], status=status, excluded_reason=scored["excluded_reason"],
                        research_source=facts[0]["source"], first_run_id=self.state.run_id,
                        last_run_id=self.state.run_id, created_at=now, updated_at=now,
                    )
                )
                lead_id, created = result.inserted_primary_key[0], True
                self.state.leads_created += 1
        self.state.scored_lead_ids.add(lead_id)
        return {"lead_id": lead_id, "company": company, "score": scored["score"], "score_reason": scored["reason"],
                "status": status, "created": created}

    def _t_analyze_crm(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        result = crm.analyze_all(self.engine, self.state.icp, self.state.now)
        self.state.crm_analyzed = True
        self.state.crm_flagged = result["flagged"]
        with self.engine.connect() as conn:
            open_follow = {
                r.account_id
                for r in conn.execute(
                    select(drafts.c.account_id).where(drafts.c.account_id.is_not(None), drafts.c.status.in_(("pending", "approved", "edited")))
                )
            }
        flagged = [{**f, "has_open_follow_up": f["account_id"] in open_follow} for f in result["flagged"]]
        return {"analyzed": result["analyzed"], "counts": result["counts"], "flagged": flagged[:25]}

    def _t_get_account_activity(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        try:
            account_id = int(args.get("account_id"))
        except (TypeError, ValueError):
            raise ToolError("account_id must be an integer.") from None
        with self.engine.connect() as conn:
            acc = conn.execute(select(accounts).where(accounts.c.id == account_id)).first()
            if not acc:
                raise ToolError(f"No CRM account with id {account_id}.")
            acc = dict(acc._mapping)
            acts = conn.execute(
                select(activity).where(activity.c.account_id == account_id).order_by(activity.c.occurred_at.desc()).limit(8)
            ).fetchall()
        return {
            "account_id": account_id,
            "company": acc["company"],
            "stage": acc["stage"],
            "owner": acc["owner"],
            "contact": {"name": acc["contact_name"], "title": acc["contact_title"]},
            "deal_value": acc["deal_value"],
            "plan": acc["plan"],
            "arr": acc["arr"],
            "cloud_accounts": f"{acc['cloud_accounts_used']} of {acc['cloud_accounts_limit']}" if acc["cloud_accounts_limit"] else None,
            "renewal_date": acc["renewal_date"].isoformat() if acc.get("renewal_date") else None,
            "internal_notes": acc["notes"],
            "flags": acc.get("flags") or [],
            "flag_reasons": acc.get("flag_reasons") or {},
            "activity": [
                {"date": a.occurred_at.date().isoformat(), "kind": a.kind, "direction": a.direction, "summary": a.summary}
                for a in acts
            ],
        }

    def _t_list_leads(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        try:
            limit = max(1, min(int(args.get("limit") or 12), 25))
        except (TypeError, ValueError):
            limit = 12
        rows = self.ranked_leads(limit)
        return {
            "leads": [
                {
                    "lead_id": r["id"],
                    "company": r["company"],
                    "score": r["score"],
                    "status": r["status"],
                    "eligible": r["eligible"],
                    "why_not": r["why_not"],
                    "industry": r["industry"],
                    "facts": [{k: f.get(k) for k in ("fact", "url", "date", "type")} for f in (r["facts"] or [])],
                }
                for r in rows
            ]
        }

    def _t_draft_outreach(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        try:
            lead_id = int(args.get("lead_id"))
        except (TypeError, ValueError):
            raise ToolError("lead_id must be an integer.") from None
        subject = " ".join(str(args.get("subject") or "").split())
        body = str(args.get("body") or "").replace("\r\n", "\n").strip()
        source_url = str(args.get("source_url") or "").strip()
        with self.engine.connect() as conn:
            row = conn.execute(select(leads).where(leads.c.id == lead_id)).first()
            if not row:
                raise ToolError(f"No lead with id {lead_id}.")
            lead = dict(row._mapping)
            open_ids = {
                r.lead_id for r in conn.execute(select(drafts.c.lead_id).where(drafts.c.lead_id == lead_id, drafts.c.status.in_(OPEN_DRAFT)))
            }
            prev = conn.execute(
                select(drafts.c.id).where(drafts.c.lead_id == lead_id, drafts.c.status == "rejected").order_by(drafts.c.id.desc()).limit(1)
            ).scalar()
        ok, why = self.eligible(lead, open_ids)
        if not ok:
            raise ToolError(f"{lead['company']} is not eligible for a first email: {why}")
        fact = next((f for f in (lead["facts"] or []) if normalize_url(f["url"]) == normalize_url(source_url)), None)
        if not fact:
            raise ToolError("source_url must be one of this lead's fact URLs (see list_leads).")
        greeting = body.split("\n", 1)[0].strip()
        if not GREETING_RE.match(greeting):
            raise ToolError(f'Start with a greeting to the team, such as "Hi {lead["company"]} team,". Never use a person\'s name.')
        errors = guardrails.check_outreach(subject, body, f"{fact['fact']} {args.get('cited_fact') or ''}", self.state.lessons)
        if errors:
            raise ToolError(" ".join(errors))
        now = utcnow()
        generated_by = "ai" if via == "agent" else "template"
        applied = [r["key"] for r in self.state.lessons.rules] if generated_by == "ai" else args.get("_applied", [])
        with self.engine.begin() as conn:
            result = conn.execute(
                drafts.insert().values(
                    kind="outreach", lead_id=lead_id, run_id=self.state.run_id, recipient=None, subject=subject[:300],
                    body=body, original_subject=subject[:300], original_body=body, cited_fact=fact["fact"],
                    source_url=fact["url"], status="pending", lessons_applied=applied, previous_draft_id=prev,
                    generated_by=generated_by, word_count=word_count(body), created_at=now, updated_at=now,
                )
            )
            conn.execute(update(leads).where(leads.c.id == lead_id).values(status="drafted", updated_at=now))
        self.state.outreach_created += 1
        return {"draft_id": result.inserted_primary_key[0], "status": "pending approval", "words": word_count(body)}

    def _t_draft_follow_up(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        try:
            account_id = int(args.get("account_id"))
        except (TypeError, ValueError):
            raise ToolError("account_id must be an integer.") from None
        subject = " ".join(str(args.get("subject") or "").split())
        body = str(args.get("body") or "").replace("\r\n", "\n").strip()
        next_step = " ".join(str(args.get("next_step") or "").split())
        send_date = parse_fact_date(args.get("send_date")) if len(str(args.get("send_date") or "")) == 10 else None
        with self.engine.connect() as conn:
            acc = conn.execute(select(accounts).where(accounts.c.id == account_id)).first()
            if not acc:
                raise ToolError(f"No CRM account with id {account_id}.")
            acc = dict(acc._mapping)
            open_draft = conn.execute(
                select(drafts.c.id).where(drafts.c.account_id == account_id, drafts.c.status.in_(("pending", "approved", "edited")))
            ).first()
            prev = conn.execute(
                select(drafts.c.id).where(drafts.c.account_id == account_id, drafts.c.status == "rejected").order_by(drafts.c.id.desc()).limit(1)
            ).scalar()
        if acc.get("last_contact") is None:
            raise ToolError("Follow-ups are only for accounts that were already contacted.")
        if open_draft:
            raise ToolError(f"{acc['company']} already has a follow-up waiting in the queue.")
        errors = guardrails.check_follow_up(subject, body, next_step, send_date, self.state.today, self.state.lessons)
        if errors:
            raise ToolError(" ".join(errors))
        now = utcnow()
        generated_by = "ai" if via == "agent" else "template"
        with self.engine.begin() as conn:
            result = conn.execute(
                drafts.insert().values(
                    kind="follow_up", account_id=account_id, run_id=self.state.run_id, recipient=acc["contact_email"],
                    recipient_name=acc["contact_name"], subject=subject[:300], body=body, original_subject=subject[:300],
                    original_body=body, next_step=next_step, send_date=send_date, status="pending",
                    lessons_applied=args.get("_applied", []), previous_draft_id=prev, generated_by=generated_by,
                    word_count=word_count(body), created_at=now, updated_at=now,
                )
            )
        self.state.followups_created += 1
        return {"draft_id": result.inserted_primary_key[0], "status": "pending approval", "send_date": send_date.isoformat()}

    def _t_finish(self, args: dict[str, Any], via: str) -> dict[str, Any]:
        self.state.finished = True
        self.state.summary = " ".join(str(args.get("summary") or "").split())[:1500]
        return {"ok": True}


def as_tool_result(payload: Any) -> str:
    text = json.dumps(payload, default=str, ensure_ascii=False)
    return text if len(text) <= 14000 else text[:14000] + "…(truncated)"
