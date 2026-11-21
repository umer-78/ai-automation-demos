"""Module A: client onboarding and off-boarding.

`run_onboarding` is the local orchestrator. It follows the Make.com scenario step for step
(webhook -> router by service -> checklist + Slack welcome per branch -> AI brief -> save to
Airtable -> email the account manager), so the demo also runs without a Make account.
With MAKE_ONBOARDING_WEBHOOK_URL set, Make drives the same steps through the
/api/automation/* endpoints instead.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.context import Context
from app.db import as_utc, campaign_metrics, client_tasks, clients, insert_ignore, today_utc, utcnow
from app.services.automation_log import AutomationRun, StepRecorder
from app.services.llm import LLMError
from app.services.web_snapshot import fetch_snapshot
from app.workflows.clients import (
    NotFound,
    ROUTER_ORDER,
    client_tasks_for,
    find_client,
    set_status,
    upsert_client,
)

log = logging.getLogger(__name__)

CHECKLISTS: dict[str, list[str]] = {
    "General": [
        "Send welcome pack and onboarding questionnaire",
        "Book kickoff call with the client",
        "Add client to the reporting dashboard",
    ],
    "SEO": [
        "Get Google Search Console and GA4 access",
        "Run technical SEO audit (crawl, Core Web Vitals, indexation)",
        "Keyword research and content gap analysis",
        "On-page plan for the top 10 landing pages",
        "Set ranking and organic traffic baseline",
    ],
    "Paid Ads": [
        "Get admin access to Google Ads and Meta Business Manager",
        "Audit conversion tracking (GA4, Meta Pixel / Conversions API)",
        "Build campaign structure and audiences",
        "Draft first creative set (3 variants per channel)",
        "Agree monthly budget, pacing and CPA targets",
    ],
    "Web Design": [
        "Kickoff: goals, sitemap and brand assets",
        "Collect logo, brand guidelines and photography",
        "Wireframes for home page and 2 key pages",
        "Design system: colours, type, components",
        "Staging site and QA checklist",
    ],
}

TASK_DUE_DAYS = (2, 3, 5, 7, 10)


def human_join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


class DeliberateFailure(RuntimeError):
    """Raised on purpose to prove the error route (automation_log + Slack alert) works."""


def wants_failure(payload: dict[str, Any]) -> bool:
    if payload.get("simulate_failure"):
        return True
    name = str(payload.get("name") or "").lower()
    return "[fail]" in name or "forced failure" in name


# --------------------------------------------------------------------------- checklist
def create_checklist(ctx: Context, client_id: int, service: str) -> list[dict[str, Any]]:
    """Idempotent: re-running a branch (e.g. a Make retry) never duplicates tasks."""
    titles = CHECKLISTS.get(service)
    if titles is None:
        raise ValueError(f"unknown service '{service}'")
    today = today_utc()
    rows = [
        {
            "client_id": client_id,
            "service": service,
            "title": title,
            "position": i,
            "status": "open",
            "due_date": today + timedelta(days=TASK_DUE_DAYS[min(i, len(TASK_DUE_DAYS) - 1)]),
            "created_at": utcnow(),
        }
        for i, title in enumerate(titles)
    ]
    with ctx.engine.begin() as conn:
        insert_ignore(conn, client_tasks, rows, ["client_id", "service", "title"])
    return [t for t in client_tasks_for(ctx, client_id) if t["service"] == service]


def welcome_text(client: dict[str, Any], service: str, n_tasks: int) -> str:
    who = client.get("manager") or "the account team"
    industry = f" ({client['industry']})" if client.get("industry") else ""
    return (
        f":wave: Welcome aboard, *{client['name']}*{industry}! New *{service}* client.\n"
        f"{n_tasks} kickoff tasks created and assigned to {who}."
    )


# --------------------------------------------------------------------------- brief
BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2 sentences: who the client is and what we will focus on."},
        "audience": {"type": "string", "description": "Primary audience, concrete and specific (2-3 sentences)."},
        "tone": {"type": "string", "description": "Tone of voice guidance for copy and ads (1-2 sentences)."},
        "quick_wins": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
            "description": "Exactly 3 quick wins the team can ship in the first 30 days.",
        },
        "kickoff_questions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 3,
            "description": "Questions to confirm on the kickoff call.",
        },
    },
    "required": ["summary", "audience", "tone", "quick_wins", "kickoff_questions"],
}

BRIEF_SYSTEM = (
    "You are a senior strategist at Northwind Digital, a marketing agency. You write short, specific "
    "client briefs for account managers. Use only the facts given (client form + website snapshot). "
    "Never invent awards, numbers, locations or testimonials. If the website snapshot is missing, base "
    "the brief on the industry and services and list what to confirm at kickoff. Plain English, no hype."
)

_INDUSTRY_PRESETS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (
        ("dental", "dentist", "clinic", "health", "medical"),
        {
            "audience": "Local families and busy professionals within a short drive who are choosing a new dentist or need urgent care. They compare reviews, price transparency and appointment availability.",
            "tone": "Warm, reassuring and plain-spoken. Lead with comfort and convenience, avoid clinical jargon.",
            "wins": [
                "Add online booking and 'emergency appointment today' messaging to the top of the home page",
                "Claim and complete the Google Business Profile with services, photos and review replies",
                "Launch a call-only search campaign for 'emergency dentist near me' style searches",
            ],
        },
    ),
    (
        ("real estate", "realty", "property"),
        {
            "audience": "First-time buyers, upsizing families and local investors researching neighbourhoods, plus homeowners thinking about selling who want a valuation.",
            "tone": "Confident, local and trustworthy. Use neighbourhood knowledge and clear next steps.",
            "wins": [
                "Create a 'What is my home worth?' valuation landing page with a short form",
                "Run lead-form ads targeting recent movers and local homeowners",
                "Publish neighbourhood guide pages for the 3 most-searched areas",
            ],
        },
    ),
    (
        ("fitness", "gym", "yoga", "sport"),
        {
            "audience": "Adults 22-45 within a 15-minute commute who want to get fit, often January joiners or people returning after a break. Price and class times drive the decision.",
            "tone": "Energetic and encouraging, never shaming. Short sentences, strong verbs.",
            "wins": [
                "Promote a free 7-day trial pass with a simple sign-up page",
                "Retarget site visitors with class-schedule and member-story ads",
                "Add class timetable schema and local landing pages for SEO",
            ],
        },
    ),
    (
        ("e-commerce", "ecommerce", "shop", "store", "food", "organic", "retail"),
        {
            "audience": "Health-conscious shoppers aged 25-55 who buy online regularly, compare ingredients and delivery terms, and respond to bundles and subscriptions.",
            "tone": "Friendly, honest and specific about sourcing. Let product benefits do the talking.",
            "wins": [
                "Set up a subscribe-and-save offer on the top 5 repeat-purchase products",
                "Launch Performance Max / Advantage+ shopping campaigns with clean product feeds",
                "Add an abandoned-cart email flow with a delivery-threshold reminder",
            ],
        },
    ),
    (
        ("legal", "law", "solicitor", "attorney"),
        {
            "audience": "Individuals and small-business owners facing a specific legal issue who need a trustworthy firm quickly. They search by problem and location and want a fast first consultation.",
            "tone": "Calm, credible and precise. Explain process and next steps; avoid promises about outcomes.",
            "wins": [
                "Build one landing page per practice area with a free-consultation form",
                "Launch tightly themed search campaigns on high-intent practice-area keywords",
                "Add FAQ content and review schema to the main practice pages",
            ],
        },
    ),
]

_SERVICE_WINS = {
    "SEO": "Fix the top technical SEO issues found in the first crawl and resubmit the sitemap",
    "Paid Ads": "Verify conversion tracking end to end before scaling any ad spend",
    "Web Design": "Rewrite the home page hero around one clear offer with a single primary call to action",
}


def offline_brief(client: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    industry = (client.get("industry") or "").lower()
    preset = next((p for keys, p in _INDUSTRY_PRESETS if any(k in industry for k in keys)), None)
    services = client.get("services") or []
    wins: list[str] = []
    if preset:
        wins.extend(preset["wins"])
    for svc in services:
        if len(wins) >= 3:
            break
        wins.append(_SERVICE_WINS[svc])
    while len(wins) < 3:
        wins.append("Agree 3 measurable 90-day goals and a reporting cadence at kickoff")
    focus = human_join(services) if services else "marketing"
    industry_text = client.get("industry") or "new"
    return {
        "summary": f"{client['name']} ({industry_text}) starts {focus} with Northwind. "
        "The first 30 days focus on clean tracking, quick visibility gains and one clear offer.",
        "audience": preset["audience"] if preset else "Local and online buyers actively searching for this type of business; confirm the core customer segments at kickoff.",
        "tone": preset["tone"] if preset else "Clear, helpful and professional. Match the client's existing brand voice once confirmed.",
        "quick_wins": wins[:3],
        "kickoff_questions": [
            "Which products or services have the best margin, and which should we push first?",
            "What does a qualified lead or sale look like, and what is it worth?",
            "Who approves ad copy and creative, and how fast can they turn it around?",
        ],
        "generated_by": "offline-template",
        "model": None,
        "website_checked": bool(snapshot),
    }


def build_brief(ctx: Context, client: dict[str, Any], *, simulate_failure: bool = False) -> dict[str, Any]:
    if simulate_failure:
        raise DeliberateFailure(
            "Deliberate test failure at the 'generate brief' step (simulate_failure=true). "
            "This proves the error route writes to automation_log and alerts Slack."
        )
    snapshot = fetch_snapshot(client["website"]) if client.get("website") else None
    if not ctx.llm.live:
        return offline_brief(client, snapshot)

    facts = [
        f"Client: {client['name']}",
        f"Industry: {client.get('industry') or 'unknown'}",
        f"Services bought: {', '.join(client.get('services') or []) or 'not specified'}",
        f"Website: {client.get('website') or 'none given'}",
    ]
    if snapshot:
        facts.append(
            "Website snapshot:\n"
            f"- Title: {snapshot.get('title')}\n- Description: {snapshot.get('description')}\n"
            f"- Headings: {'; '.join(snapshot.get('headings') or [])}\n- Excerpt: {snapshot.get('excerpt')}"
        )
    else:
        facts.append("Website snapshot: not available (site unreachable or placeholder domain).")
    prompt = "\n".join(facts) + "\n\nWrite the client brief and return it with the submit_brief tool."
    try:
        result = ctx.llm.structured(
            system=BRIEF_SYSTEM,
            prompt=prompt,
            tool_name="submit_brief",
            tool_description="Submit the finished client brief.",
            schema=BRIEF_SCHEMA,
            max_tokens=1200,
        )
    except LLMError:
        raise
    data = result.data
    wins = [str(w).strip() for w in (data.get("quick_wins") or []) if str(w).strip()]
    if len(wins) < 3:
        wins += offline_brief(client, snapshot)["quick_wins"][len(wins) :]
    return {
        "summary": str(data.get("summary", "")).strip(),
        "audience": str(data.get("audience", "")).strip(),
        "tone": str(data.get("tone", "")).strip(),
        "quick_wins": wins[:3],
        "kickoff_questions": [str(q).strip() for q in (data.get("kickoff_questions") or [])][:3],
        "generated_by": "ai",
        "model": result.model,
        "tokens": result.input_tokens + result.output_tokens,
        "website_checked": bool(snapshot),
    }


def brief_to_text(client: dict[str, Any], brief: dict[str, Any]) -> str:
    wins = "\n".join(f"{i}. {w}" for i, w in enumerate(brief["quick_wins"], start=1))
    questions = "\n".join(f"- {q}" for q in brief.get("kickoff_questions") or [])
    return (
        f"CLIENT BRIEF: {client['name']}  [DRAFT]\n"
        f"Industry: {client.get('industry') or '-'} | Services: {', '.join(client.get('services') or [])} | "
        f"Account manager: {client.get('manager') or '-'}\n\n"
        f"Summary\n{brief['summary']}\n\n"
        f"Audience\n{brief['audience']}\n\n"
        f"Tone of voice\n{brief['tone']}\n\n"
        f"3 quick wins\n{wins}\n\n"
        f"Confirm at kickoff\n{questions}\n"
    )


def save_brief(ctx: Context, client: dict[str, Any], brief: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    """Save to the database, write back to Airtable and email the account manager a draft."""
    text = brief_to_text(client, brief)
    with ctx.engine.begin() as conn:
        conn.execute(
            clients.update()
            .where(clients.c.id == client["id"])
            .values(brief=text, brief_data=brief, updated_at=utcnow())
        )
    airtable_status = "skipped (Airtable not connected)"
    if client.get("airtable_record_id") and ctx.airtable.live:
        ctx.airtable.update_record(
            client["airtable_record_id"],
            {"Brief": text, "Status": "Active", "Hub Client ID": client["id"], "Onboarded At": today_utc().isoformat()},
        )
        airtable_status = "saved"
    email = ctx.notifier.email(
        client.get("manager_email") or "",
        f"[DRAFT] Client brief: {client['name']}",
        f"Hi {client.get('manager') or 'team'},\n\nHere is the first-draft brief for {client['name']}. "
        "Edit it in Airtable (Brief field) before sharing with the client.\n\n" + text,
        kind="draft",
        run_id=run_id,
    )
    return {"text": text, "airtable": airtable_status, "email_status": email["status"]}


# --------------------------------------------------------------------------- orchestrator
def run_onboarding(ctx: Context, payload: dict[str, Any], *, source: str = "api", run_id: str | None = None) -> dict[str, Any]:
    with AutomationRun(ctx.engine, ctx.notifier, "client_onboarding", source=source, run_id=run_id) as run:
        client = upsert_client(ctx, payload)
        run.client_id = client["id"]
        client = set_status(ctx, client["id"], "onboarding")
        run.step("client_synced", client_id=client["id"], name=client["name"])

        created: dict[str, int] = {}
        general = create_checklist(ctx, client["id"], "General")
        created["General"] = len(general)
        for service in ROUTER_ORDER:  # Make router: one branch per service bought
            if service not in (client.get("services") or []):
                continue
            tasks = create_checklist(ctx, client["id"], service)
            created[service] = len(tasks)
            ctx.notifier.slack(welcome_text(client, service, len(tasks)), run_id=run.run_id)
            run.step("branch_done", service=service, tasks=len(tasks))

        brief = build_brief(ctx, client, simulate_failure=wants_failure(payload))
        run.step("brief_generated", generated_by=brief["generated_by"], website_checked=brief["website_checked"])
        saved = save_brief(ctx, client, brief, run_id=run.run_id)
        run.step("brief_saved", airtable=saved["airtable"], email=saved["email_status"])

        client = set_status(ctx, client["id"], "active")
        total = sum(created.values())
        ctx.notifier.slack(
            f":white_check_mark: Onboarding complete for *{client['name']}*: {total} tasks across "
            f"{', '.join(k for k in created if k != 'General') or 'general setup'}; brief emailed to "
            f"{client.get('manager') or 'the account manager'} as a draft.",
            kind="summary",
            run_id=run.run_id,
        )
        run.step("done")
        run.set(client=client["name"], services=client.get("services"), tasks_created=created, brief_by=brief["generated_by"])

    return {
        "run_id": run.run_id,
        "status": "success",
        "duration_ms": run.log_row["duration_ms"] if run.log_row else None,
        "client": client,
        "tasks_created": created,
        "brief": brief,
    }


# --------------------------------------------------------------------------- off-boarding
def offboard_client(
    ctx: Context,
    *,
    client_id: int | None = None,
    airtable_record_id: str | None = None,
    source: str = "api",
    run_id: str | None = None,
    managed_by_make: bool = False,
) -> dict[str, Any]:
    """Close open tasks, archive the client and post a summary. When Make.com orchestrates the
    run (managed_by_make=True) this returns the Slack text for Make to post and leaves the run
    log to the scenario."""
    runner = (
        StepRecorder("client_offboarding", run_id)
        if managed_by_make
        else AutomationRun(ctx.engine, ctx.notifier, "client_offboarding", source=source, run_id=run_id)
    )
    with runner as run:
        client = find_client(ctx, client_id=client_id, airtable_record_id=airtable_record_id)
        if not client:
            raise NotFound(f"client not found (id={client_id}, airtable_record_id={airtable_record_id})")
        run.client_id = client["id"]
        if client["status"] == "archived":
            run.step("already_archived")
            run.set(client=client["name"], idempotent=True)
            return {"run_id": run.run_id, "status": "already_archived", "client": client, "slack_text": None}

        set_status(ctx, client["id"], "churned")
        now = utcnow()
        with ctx.engine.begin() as conn:
            closed = conn.execute(
                client_tasks.update()
                .where(client_tasks.c.client_id == client["id"], client_tasks.c.status != "closed")
                .values(status="closed", closed_at=now)
            ).rowcount
            since = today_utc() - timedelta(days=30)
            agg = conn.execute(
                select(
                    func.coalesce(func.sum(campaign_metrics.c.spend), 0.0),
                    func.coalesce(func.sum(campaign_metrics.c.conversions), 0),
                ).where(campaign_metrics.c.client_id == client["id"], campaign_metrics.c.date >= since)
            ).one()
        run.step("tasks_closed", count=closed)

        client = set_status(ctx, client["id"], "archived", archived_at=now)
        run.step("client_archived")
        if client.get("airtable_record_id") and ctx.airtable.live:
            ctx.airtable.update_record(client["airtable_record_id"], {"Status": "Archived"})
            run.step("airtable_updated")

        created_at = as_utc(datetime.fromisoformat(client["created_at"]))
        tenure_days = max(0, (now - created_at).days)
        spend, conversions = float(agg[0] or 0), int(agg[1] or 0)
        cpa = round(spend / conversions, 2) if conversions else None
        summary = {
            "client": client["name"],
            "tenure_days": tenure_days,
            "tasks_closed": closed,
            "spend_30d": round(spend, 2),
            "conversions_30d": conversions,
            "cpa_30d": cpa,
            "manager": client.get("manager"),
            "services": client.get("services"),
        }
        cpa_text = f"${cpa:,.2f}" if cpa is not None else "n/a"
        slack_text = (
            f":file_folder: *{client['name']}* off-boarded (status Churned). {tenure_days} days with Northwind, "
            f"{closed} open tasks closed, last 30 days: ${spend:,.0f} spend, {conversions} conversions, CPA {cpa_text}. "
            f"Client archived; AM: {client.get('manager') or '-'}."
        )
        if not managed_by_make:
            ctx.notifier.slack(slack_text, kind="summary", run_id=run.run_id)
        run.set(**summary)
    return {"run_id": run.run_id, "status": "archived", "summary": summary, "client": client, "slack_text": slack_text}
