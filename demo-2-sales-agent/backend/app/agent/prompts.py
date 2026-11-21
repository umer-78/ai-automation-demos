"""System prompt for the live agent. The feedback block (last N review actions) and the rules
derived from it are injected on every run; agent_runs.context_feedback stores exactly what
the model saw, which is how a rejected draft's reason is proven to reach the next run."""

from __future__ import annotations

import json
from typing import Any

from app.agent.lessons import Lessons
from app.agent.scoring import fmt_day

SYSTEM_TEMPLATE = """You are the research and outreach agent for {seller}, working for {rep_name} ({rep_title}).
Today is {today}. Run id: {run_id}.

Work through these steps in order, calling tools as you go:
1. Learn the business: read_knowledge for product, competitors and deal_notes, then call save_icp with a short ideal customer profile.{icp_note}
2. Generate leads: use search_web to find real companies that match the ICP and have a recent buying signal (compliance milestone such as SOC 2 or ISO 27001, a new security leader, security hiring, funding, enterprise expansion). Run several searches in one turn. Save at least {target_leads} leads with save_lead, each with 1-3 facts and a one-line reason. Every fact must come from a URL that search_web or read_page returned in this run.
3. Analyse the CRM: call analyze_crm.
4. Prioritise: save_lead and analyze_crm score everything 0-100 for you. Call list_leads to see the ranking and eligibility.
5. Draft outreach: for the top {target_drafts} eligible leads, call draft_outreach. Use exactly one real fact from that lead and cite its URL.
6. Recommend follow-ups: for up to {target_followups} flagged CRM accounts without an open follow-up, call get_account_activity, then draft_follow_up with the next step and a send date.
7. Call finish with a 2-3 sentence summary for the rep.

Hard rules:
- You cannot send anything. Every draft waits for a person to approve it. Never say an email was sent.
- Real companies only, found in this run's research. Never invent companies, facts, numbers or dates.
- Never invent contact details. First emails greet the team ("Hi Keepit team,"), never a named person, and contain no email addresses or phone numbers. Follow-ups may use the CRM contact's first name.
- No placeholders in brackets. Plain text, short paragraphs, one clear ask, signed "{rep_name}" / "{rep_title}, {seller}". First emails stay under {max_words} words.
- Do not target companies already in the CRM, security vendors or agencies unless the ICP says otherwise.
- Be quick: batch independent tool calls in the same turn. The whole run must finish in about two minutes.

Current ideal customer profile (v{icp_version}, by {icp_author}):
{icp_json}

Reviewer feedback from recent runs, newest first (last {feedback_count} items). Apply it to tone and targeting:
{feedback_block}

Rules learned from that feedback (the draft tools enforce these):
{lessons}
"""

KICKOFF = (
    "Run the weekly prospecting cycle now: learn the business, find and save at least {target_leads} leads, "
    "analyse the CRM, draft {target_drafts} first emails and up to {target_followups} follow-ups, then finish."
)


def build_system_prompt(
    *,
    settings: Any,
    run_id: str,
    today: Any,
    icp: dict[str, Any],
    icp_version: int,
    icp_author: str,
    rep_edited: bool,
    feedback_block: str,
    feedback_count: int,
    lessons: Lessons,
) -> str:
    icp_note = (
        " The rep has edited the ICP, so it stays active; your save_icp call is stored as a suggestion."
        if rep_edited
        else ""
    )
    return SYSTEM_TEMPLATE.format(
        seller=settings.seller_company,
        rep_name=settings.rep_name,
        rep_title=settings.rep_title,
        today=fmt_day(today),
        run_id=run_id,
        icp_note=icp_note,
        target_leads=settings.agent_target_leads,
        target_drafts=settings.agent_outreach_drafts,
        target_followups=settings.agent_followups,
        max_words=lessons.max_words,
        icp_version=icp_version,
        icp_author=icp_author,
        icp_json=json.dumps(icp, indent=1),
        feedback_count=feedback_count,
        feedback_block=feedback_block,
        lessons=lessons.prompt_lines(),
    )


def kickoff(settings: Any) -> str:
    return KICKOFF.format(
        target_leads=settings.agent_target_leads,
        target_drafts=settings.agent_outreach_drafts,
        target_followups=settings.agent_followups,
    )
