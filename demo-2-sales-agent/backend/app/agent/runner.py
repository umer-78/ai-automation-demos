"""Agent runner. One run: learn the business, research leads, analyse the CRM, score,
draft first emails and follow-ups (into the approval queue), then report.

* Live mode (ANTHROPIC_API_KEY set): the model drives the tools in a loop.
* Offline mode: a deterministic planner calls the very same tools, with template drafts.

A completion step then checks the run's targets (12 scored leads, 5 first emails, follow-ups)
and fills any gap with the offline planner, so "Run agent" always delivers inside 3 minutes,
even if the model runs long or the AI API fails. Every tool call, by the model or the planner,
is logged on the run (agent_runs.tools_called).
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, time as dtime, timezone
from typing import Any

from sqlalchemy import func, select, update

from app.agent import templates
from app.agent.prompts import build_system_prompt, kickoff
from app.agent.scoring import parse_fact_date
from app.agent.tools import RunState, ToolBox, as_tool_result
from app.db import accounts, agent_runs, drafts, utcnow
from app.services.automation_log import AutomationRun, log_and_alert, new_run_id
from app.services.llm import LLMError
from app.workflows import icp as icp_store
from app.workflows import learning

log = logging.getLogger(__name__)
_RUN_LOCK = threading.Lock()

def why_now(entry: dict[str, Any]) -> str:
    """One-line 'why this company, why now' for a cached research result (offline planner)."""
    d = parse_fact_date(entry.get("date"))
    when = d.strftime("%b %Y") if d else "recently"
    fact = entry["fact"]
    kind = entry.get("fact_type")
    if kind == "compliance":
        framework = templates.framework_of(entry.get("hook") or fact)
        if re.search(r"toward|pursu", fact, re.I):
            return f"{framework} done ({when}) and ISO 27001 next, so their evidence work is about to double."
        if framework == "ISO 27001":
            return f"New ISO 27001 certificate ({when}); surveillance audits mean evidence has to stay current all year."
        if framework == "SOC 2":
            return f"Fresh SOC 2 report ({when}); evidence now has to stay current until the next audit window."
        return f"Compliance milestone ({when}); keeping evidence current is the next job."
    if kind == "security_leader":
        return f"New CISO since {when}; the first months are when cloud risk gets mapped and tools get chosen."
    if kind == "funding":
        m = re.search(r"\$\d+(?:\.\d+)?[MB] Series [A-D]", fact)
        return f"Raised {m.group(0) if m else 'a new round'} ({when}); bigger customers bring longer security reviews."
    return f"Recent news ({when}) suggests more customer security reviews ahead."


class RunInProgress(Exception):
    def __init__(self, run_id: str | None):
        super().__init__("An agent run is already in progress.")
        self.run_id = run_id


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0

    def add(self, usage: Any) -> None:
        if usage is None:
            return
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_write + self.cache_read

    def cost(self, price_in: float, price_out: float) -> float:
        billed_in = self.input_tokens + 1.25 * self.cache_write + 0.1 * self.cache_read
        return round(billed_in * price_in / 1e6 + self.output_tokens * price_out / 1e6, 4)


def _block(b: Any) -> dict[str, Any]:
    if isinstance(b, dict):
        return b
    kind = getattr(b, "type", None)
    if kind == "text":
        return {"type": "text", "text": b.text}
    if kind == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input or {})}
    if hasattr(b, "model_dump"):
        return b.model_dump(exclude_none=True)
    return {"type": kind or "text", "text": str(b)}


class AgentRunner:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.current: str | None = None

    # ------------------------------------------------------------------ entry points
    def start(self, trigger: str = "manual") -> str:
        """Start a run in a background thread and return its id immediately."""
        if not _RUN_LOCK.acquire(blocking=False):
            raise RunInProgress(self.current)
        try:
            run_id = self._create(trigger)
        except Exception:
            _RUN_LOCK.release()
            raise
        self.current = run_id
        threading.Thread(target=self._thread_main, args=(run_id, trigger), daemon=True, name=f"agent-{run_id}").start()
        return run_id

    def run_sync(self, trigger: str = "manual") -> dict[str, Any]:
        if not _RUN_LOCK.acquire(blocking=False):
            raise RunInProgress(self.current)
        try:
            run_id = self._create(trigger)
            self.current = run_id
            self.execute(run_id, trigger)
            return self.get(run_id)
        finally:
            self.current = None
            _RUN_LOCK.release()

    def _thread_main(self, run_id: str, trigger: str) -> None:
        try:
            self.execute(run_id, trigger)
        except Exception:  # pragma: no cover - execute() records its own failures
            log.exception("agent run %s crashed", run_id)
        finally:
            self.current = None
            _RUN_LOCK.release()

    def get(self, run_id: str) -> dict[str, Any]:
        from app.db import row_to_dict

        with self.ctx.engine.connect() as conn:
            row = conn.execute(select(agent_runs).where(agent_runs.c.id == run_id)).first()
        return row_to_dict(row) if row else {}

    # ------------------------------------------------------------------ helpers
    def _mode(self) -> str:
        if not self.ctx.llm.live:
            return "offline"
        midnight = datetime.combine(utcnow().date(), dtime.min, tzinfo=timezone.utc)
        with self.ctx.engine.connect() as conn:
            today = conn.execute(
                select(func.count()).where(agent_runs.c.mode == "live", agent_runs.c.started_at >= midnight)
            ).scalar()
        return "live" if today < self.ctx.settings.live_runs_per_day else "offline"

    def _create(self, trigger: str) -> str:
        run_id = new_run_id()
        mode = self._mode()
        with self.ctx.engine.begin() as conn:
            conn.execute(
                agent_runs.insert().values(
                    id=run_id, trigger=trigger, mode=mode, model=self.ctx.llm.model if mode == "live" else None,
                    research_source=self.ctx.research.source, status="running", started_at=utcnow(),
                    tools_called=[], feedback_ids=[],
                )
            )
        return run_id

    # ------------------------------------------------------------------ the run
    def execute(self, run_id: str, trigger: str) -> None:
        ctx, settings = self.ctx, self.ctx.settings
        run = self.get(run_id)
        mode = run["mode"]
        fb = learning.build_context(ctx.engine, settings.feedback_context_size)
        icp_info = icp_store.active_icp(ctx.engine)
        state = RunState(
            run_id=run_id, mode=mode, now=utcnow(), icp=icp_info["criteria"], icp_version=icp_info["version"],
            lessons=fb["lessons"], target_leads=settings.agent_target_leads, target_drafts=settings.agent_outreach_drafts,
            target_followups=settings.agent_followups,
            rep={"name": settings.rep_name, "title": settings.rep_title, "company": settings.seller_company},
        )
        with ctx.engine.begin() as conn:
            conn.execute(
                update(agent_runs).where(agent_runs.c.id == run_id).values(
                    feedback_ids=fb["feedback_ids"], context_feedback=fb["block"], lessons=fb["lessons"].as_dict(),
                    icp_version=icp_info["version"],
                )
            )
        tb = ToolBox(ctx, state)
        usage = Usage()
        notes: list[str] = []
        status, error = "completed", None
        try:
            with AutomationRun(ctx.engine, ctx.notifier, "agent_run", run_id=run_id, source="cron" if trigger == "schedule" else "api") as auto:
                state.on_step = lambda name, **info: auto.step(name, **info)
                if mode == "live":
                    try:
                        self._live(tb, state, usage, fb, icp_info, notes)
                    except LLMError as exc:
                        notes.append(f"The AI call failed ({exc}); the run was finished by the offline planner.")
                        log_and_alert(ctx.engine, ctx.notifier, workflow="agent_ai_call", status="failure", run_id=run_id,
                                      error=str(exc), source="api")
                else:
                    self._offline(tb, state, via="planner")
                filled = self._complete(tb, state) if mode == "live" else []
                if filled and mode == "live":
                    notes.append("Completed by the fallback planner: " + ", ".join(filled) + ".")
                if mode == "live" and (filled or any("AI call failed" in n for n in notes)):
                    status = "completed_with_fallback"
                auto.set(leads_scored=len(state.scored_lead_ids), drafts=state.outreach_created, follow_ups=state.followups_created)
        except Exception as exc:  # AutomationRun already logged the failure and sent the alert
            status, error = "failed", f"{type(exc).__name__}: {exc}"
            log.exception("agent run %s failed", run_id)
        finally:
            self._finalize(run_id, state, usage, status, error, notes)

    def _finalize(self, run_id: str, state: RunState, usage: Usage, status: str, error: str | None, notes: list[str]) -> None:
        settings = self.ctx.settings
        leads_scored = len(state.scored_lead_ids)
        summary = state.summary or (
            f"Scored {leads_scored} leads ({state.leads_created} new), analysed the CRM "
            f"({len(state.crm_flagged)} accounts flagged) and queued {state.outreach_created} first emails and "
            f"{state.followups_created} follow-ups for approval. Nothing was sent."
        )
        outcome = " ".join([f"{state.outreach_created + state.followups_created} drafts waiting for approval."] + notes)
        if status == "failed":
            outcome = f"Run failed: {error}"
        values = dict(
            status=status, outcome=outcome, finished_at=utcnow(), duration_ms=state.elapsed_ms,
            tools_called=state.tools_called, tool_call_count=len(state.tools_called), tokens=usage.total,
            input_tokens=usage.input_tokens + usage.cache_write + usage.cache_read, output_tokens=usage.output_tokens,
            cost_usd=usage.cost(settings.price_input_per_mtok, settings.price_output_per_mtok),
            leads_scored=leads_scored, leads_created=state.leads_created, drafts_created=state.outreach_created,
            followups_created=state.followups_created, accounts_flagged=len(state.crm_flagged), summary=summary,
            error=error, research_source="+".join(sorted(state.research_sources)) or self.ctx.research.source,
        )
        if state.icp_suggestion:
            values["lessons"] = {**(state.lessons.as_dict()), "icp_suggestion": state.icp_suggestion}
        with self.ctx.engine.begin() as conn:
            conn.execute(update(agent_runs).where(agent_runs.c.id == run_id).values(**values))
        if status != "failed":
            queue = f"{settings.public_base_url.rstrip('/')}/approvals"
            self.ctx.notifier.slack(
                f":robot_face: Agent run `{run_id}` finished: {leads_scored} leads scored, "
                f"{state.outreach_created} first emails and {state.followups_created} follow-ups waiting for approval. "
                f"<{queue}|Review the queue>",
                kind="message", run_id=run_id,
            )

    # ------------------------------------------------------------------ live loop
    def _live(self, tb: ToolBox, state: RunState, usage: Usage, fb: dict[str, Any], icp_info: dict[str, Any], notes: list[str]) -> None:
        ctx, settings = self.ctx, self.ctx.settings
        system = build_system_prompt(
            settings=settings, run_id=state.run_id, today=state.today, icp=state.icp, icp_version=icp_info["version"],
            icp_author=icp_info["author"], rep_edited=icp_store.rep_has_edited(ctx.engine), feedback_block=fb["block"],
            feedback_count=len(fb["feedback_ids"]), lessons=state.lessons,
        )
        tools = [dict(t) for t in tb.schemas()]
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        messages: list[dict[str, Any]] = [{"role": "user", "content": kickoff(settings)}]
        turns = 0
        for _ in range(settings.agent_max_turns):
            if state.elapsed_ms / 1000 > settings.agent_time_budget_s:
                notes.append(f"Stopped the model at the {settings.agent_time_budget_s}s time budget.")
                break
            resp = ctx.llm.create(
                model=ctx.llm.model,
                max_tokens=4096,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tools,
                messages=messages,
            )
            turns += 1
            usage.add(getattr(resp, "usage", None))
            content = [_block(b) for b in (resp.content or [])]
            if not content:
                break
            messages.append({"role": "assistant", "content": content})
            uses = [c for c in content if c.get("type") == "tool_use"]
            if not uses:
                break
            results = tb.call_many(uses, via="agent")
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": uid, "content": as_tool_result(payload), **({} if ok else {"is_error": True})}
                        for uid, payload, ok in results
                    ],
                }
            )
            if state.finished:
                break
        with ctx.engine.begin() as conn:
            conn.execute(update(agent_runs).where(agent_runs.c.id == state.run_id).values(turns=turns))

    # ------------------------------------------------------------------ offline planner
    def _offline(self, tb: ToolBox, state: RunState, *, via: str) -> None:
        for doc in ("product", "competitors", "deal_notes"):
            if doc not in state.knowledge_read:
                tb.call("read_knowledge", {"doc": doc}, via=via)
        if not state.icp_saved:
            tb.call("save_icp", state.icp, via=via)
        self._offline_leads(tb, state, via=via)
        if not state.crm_analyzed:
            tb.call("analyze_crm", {}, via=via)
        tb.call("list_leads", {"limit": 15}, via=via)
        self._offline_outreach(tb, state, via=via)
        self._offline_followups(tb, state, via=via)
        if not state.finished:
            tb.call("finish", {"summary": ""}, via=via)

    @staticmethod
    def _queries(state: RunState) -> list[str]:
        weights = state.icp["signal_weights"]
        options = {
            "compliance": ["B2B SaaS company completes SOC 2 Type II audit 2026", "software company achieves ISO 27001 certification 2026"],
            "security_leader": ["software company appoints Chief Information Security Officer CISO 2026"],
            "funding": ["SaaS company raises Series B funding 2026"],
            "security_hiring": ["SaaS company hiring cloud security engineer"],
        }
        ordered = sorted(options, key=lambda k: weights.get(k, 0), reverse=True)
        return [q for key in ordered if weights.get(key, 0) > 0 for q in options[key]][:5]

    def _offline_leads(self, tb: ToolBox, state: RunState, *, via: str) -> None:
        cache = self.ctx.research.cache
        seen_companies: set[str] = set()
        for query in self._queries(state):
            if len(state.scored_lead_ids) >= state.target_leads + 6:
                break
            result, ok = tb.call("search_web", {"query": query}, via=via)
            if not ok:
                continue
            for item in result["results"]:
                entry = cache.entry_for_url(item["url"])
                if not entry or entry["company"] in seen_companies:
                    continue
                seen_companies.add(entry["company"])
                tb.call(
                    "save_lead",
                    {
                        "company": entry["company"],
                        "domain": entry.get("domain") or "",
                        "industry": entry["industry"],
                        "category": entry["category"],
                        "size_band": entry["size_band"],
                        "region": entry["region"],
                        "cloud_native": entry["cloud_native"],
                        "facts": [{"fact": entry["fact"], "url": entry["url"], "date": entry["date"], "type": entry["fact_type"]}],
                        "reason": why_now(entry),
                    },
                    via=via,
                )

    def _offline_outreach(self, tb: ToolBox, state: RunState, *, via: str) -> None:
        need = state.target_drafts - state.outreach_created
        if need <= 0:
            return
        weights = state.icp["signal_weights"]
        for lead in tb.ranked_leads(60):
            if need <= 0:
                break
            if not lead["eligible"] or not lead["facts"]:
                continue
            fact = max(lead["facts"], key=lambda f: (weights.get(f.get("type") or "news", 0), f.get("date") or ""))
            draft = templates.outreach(lead, fact, state.lessons, state.rep)
            _, ok = tb.call(
                "draft_outreach",
                {"lead_id": lead["id"], "subject": draft["subject"], "body": draft["body"], "cited_fact": fact["fact"],
                 "source_url": fact["url"], "_applied": draft["lessons_applied"]},
                via=via,
            )
            if ok:
                need -= 1

    def _offline_followups(self, tb: ToolBox, state: RunState, *, via: str) -> None:
        need = state.target_followups - state.followups_created
        if need <= 0:
            return
        if not state.crm_analyzed:
            tb.call("analyze_crm", {}, via=via)
        with self.ctx.engine.connect() as conn:
            busy = {
                r.account_id
                for r in conn.execute(
                    select(drafts.c.account_id).where(drafts.c.account_id.is_not(None), drafts.c.status.in_(("pending", "approved", "edited")))
                )
            }
        candidates = [f for f in state.crm_flagged if f["account_id"] not in busy]
        # round-robin across flag types so the rep sees one of each kind first
        buckets = {k: [f for f in candidates if f["flags"] and f["flags"][0] == k] for k in ("stalled", "upsell", "no_contact")}
        picks: list[dict[str, Any]] = []
        while any(buckets.values()) and len(picks) < need:
            for key in ("stalled", "upsell", "no_contact"):
                if buckets[key] and len(picks) < need:
                    picks.append(buckets[key].pop(0))
        for item in picks:
            detail, ok = tb.call("get_account_activity", {"account_id": item["account_id"]}, via=via)
            if not ok:
                continue
            with self.ctx.engine.connect() as conn:
                acc = dict(conn.execute(select(accounts).where(accounts.c.id == item["account_id"])).first()._mapping)
            last = next((a for a in detail["activity"] if a["direction"] != "internal"), None)
            draft = templates.follow_up(acc, {"flags": item["flags"]}, last, state.lessons, state.rep, state.today)
            tb.call(
                "draft_follow_up",
                {"account_id": item["account_id"], "next_step": draft["next_step"], "send_date": draft["send_date"].isoformat(),
                 "subject": draft["subject"], "body": draft["body"], "_applied": draft["lessons_applied"]},
                via=via,
            )

    # ------------------------------------------------------------------ completion check
    def _complete(self, tb: ToolBox, state: RunState) -> list[str]:
        filled: list[str] = []
        if not state.icp_saved:
            tb.call("save_icp", state.icp, via="fallback")
            filled.append("ICP")
        if len(state.scored_lead_ids) < state.target_leads:
            before = len(state.scored_lead_ids)
            self._offline_leads(tb, state, via="fallback")
            if len(state.scored_lead_ids) > before:
                filled.append(f"{len(state.scored_lead_ids) - before} leads from the research cache")
        if not state.crm_analyzed:
            tb.call("analyze_crm", {}, via="fallback")
            filled.append("CRM analysis")
        if state.outreach_created < state.target_drafts:
            before = state.outreach_created
            self._offline_outreach(tb, state, via="fallback")
            if state.outreach_created > before:
                filled.append(f"{state.outreach_created - before} template first emails")
        if state.followups_created < state.target_followups:
            before = state.followups_created
            self._offline_followups(tb, state, via="fallback")
            if state.followups_created > before:
                filled.append(f"{state.followups_created - before} template follow-ups")
        return filled
