"""Deterministic draft writer used in offline mode (no API key) and as the fallback when a
live run runs out of time. It follows the same learned rules as the model does."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agent.lessons import Lessons
from app.agent.scoring import add_business_days

ANGLES: dict[str, dict[str, str]] = {
    "compliance": {
        "why": "Most teams find the audit is the easy part. Keeping evidence current until the next audit window is where the hours go.",
        "value": "Acme Guard connects read-only to AWS, Azure or Google Cloud and keeps SOC 2 and ISO 27001 evidence up to date as things change, so the next audit starts with a full folder.",
        "short": "Acme Guard keeps that evidence current automatically, read-only, from your cloud accounts.",
        "subject": "After the audit: keeping {framework} evidence current",
        "question": "Is the next {framework} window already covered?",
        "offer": "a one-page checklist for the months between audits",
    },
    "security_leader": {
        "why": "The first 90 days in that seat usually start with one question: what is actually exposed in our cloud accounts?",
        "value": "Acme Guard answers that within a day, read-only, and turns it into a short, ranked list the security team can work through.",
        "short": "Acme Guard answers that within a day, read-only, with a short ranked list.",
        "subject": "A first-90-days cloud risk map for {company}",
        "question": "What is exposed in {company}'s cloud today?",
        "offer": "the 90-day cloud security plan other new security leaders have used",
    },
    "funding": {
        "why": "A raise like that is usually followed by bigger customers and much longer security questionnaires.",
        "value": "Acme Guard keeps your cloud setup audit-ready and answers most questionnaire items from live evidence, so deals do not stall in security review.",
        "short": "Acme Guard answers most questionnaire items from live cloud evidence, so deals keep moving.",
        "subject": "Security reviews after the raise",
        "question": "Ready for longer security reviews after the raise?",
        "offer": "a sample security questionnaire answered from live cloud evidence",
    },
    "default": {
        "why": "Moments like this tend to bring more customer security reviews and audit questions.",
        "value": "Acme Guard connects read-only to your cloud accounts, flags risky settings as they change and keeps SOC 2 and ISO 27001 evidence ready.",
        "short": "Acme Guard keeps cloud settings and compliance evidence in check, read-only.",
        "subject": "{company} and cloud compliance",
        "question": "Is cloud compliance on {company}'s list this quarter?",
        "offer": "a two-page summary of how similar teams handle this",
    },
}
JARGON = {"audit-ready": "ready for audits", "read-only": "with read-only access"}


def framework_of(fact: str) -> str:
    """The framework a fact is about; when both are named, the one mentioned first wins."""
    lower = fact.lower()
    hits = [(lower.find(key), name) for key, name in (("soc 2", "SOC 2"), ("soc2", "SOC 2"), ("27001", "ISO 27001")) if key in lower]
    return min(hits)[1] if hits else "compliance"


def make_hook(company: str, fact: dict[str, Any]) -> str:
    """'Congratulations on ...' phrase. Cached research carries a hand-checked hook; otherwise derive one."""
    if fact.get("hook"):
        return fact["hook"]
    text = fact["fact"].strip().rstrip(".")
    first, _, rest = text.partition(" ")
    verbs = {"completed": "completing", "achieved": "achieving", "raised": "raising", "closed": "closing",
             "appointed": "appointing", "announced": "announcing", "obtained": "obtaining", "launched": "launching"}
    if first.lower() in verbs and rest:
        return f"{verbs[first.lower()]} {rest}"
    return f"the recent news at {company}"


def outreach(lead: dict[str, Any], fact: dict[str, Any], lessons: Lessons, rep: dict[str, str]) -> dict[str, Any]:
    company = lead["company"]
    kind = fact.get("type") or "news"
    angle = ANGLES.get(kind, ANGLES["default"])
    framework = framework_of(fact.get("hook") or fact["fact"])
    applied: list[str] = []

    hook = make_hook(company, fact)
    opener = f"Congratulations on {hook}." if not hook.startswith("the recent news") else f"I read about {hook}: {fact['fact']}"
    lines = [f"Hi {company} team,", ""]
    short = lessons.max_words <= 100
    if short:
        applied.append("short")
        lines.append(f"{opener} {angle['short']}")
    else:
        lines.append(f"{opener} {angle['why']}")
        lines.append("")
        lines.append(angle["value"])
    if lessons.include_price:
        applied.append("include_price")
        lines += ["", "Plans start at $1,500 a month for up to three cloud accounts."]
    lines.append("")
    # The won-deal notes say a useful offer beats a meeting request, so first emails never ask for a call.
    if lessons.soft_cta:
        applied.append("soft_cta")
    lines.append(f"If it helps, I can send {angle['offer']}. Want me to?")
    lines += ["", rep["name"], f"{rep['title']}, {rep['company']}"]
    body = "\n".join(lines)
    if lessons.plain_language:
        applied.append("plain_language")
        for word, plain in JARGON.items():
            body = body.replace(word, plain)
    if lessons.question_subject:
        applied.append("question_subject")
        subject = angle["question"].format(company=company, framework=framework)
    else:
        subject = angle["subject"].format(company=company, framework=framework)
    return {"subject": subject[:90], "body": body, "lessons_applied": applied}


# ------------------------------------------------------------------------------- follow-ups
def follow_up(account: dict[str, Any], analysis: dict[str, Any], last_activity: dict[str, Any] | None,
              lessons: Lessons, rep: dict[str, str], today: date) -> dict[str, Any]:
    flags = analysis["flags"]
    stage = account["stage"]
    first = (account.get("contact_name") or "there").split()[0]
    plan = account.get("plan") or "Growth"
    applied: list[str] = []

    if "upsell" in flags:
        used, limit = account.get("cloud_accounts_used"), account.get("cloud_accounts_limit")
        said = f"{(last_activity or {}).get('summary', '')} ".lower()
        if used is not None and limit and used / limit >= 0.8:
            usage_line = f"You are now using {used} of the {limit} cloud accounts on your {plan} plan."
        elif "iso 27001" in said:
            usage_line = "On our last call you asked about ISO 27001. It is included in the Growth plan, so moving up would cover it without another tool."
        elif "acquisition" in said or "acquir" in said:
            usage_line = "You mentioned the acquisition is closing. If their cloud accounts are joining yours, it is worth checking how that fits your plan."
        else:
            usage_line = "From our last conversation it sounds like your cloud footprint is growing."
        next_step = "Propose the upgrade path before renewal and share a usage summary"
        subject = "Room to grow on Acme Guard"
        middle = (
            f"{usage_line} Before it becomes a blocker, I can put together a short summary of your usage "
            "and what the next plan would add, so you can decide on your own timeline."
        )
        ask = "Would that be useful?"
        send = add_business_days(today, 2)
    elif "no_contact" in flags and stage == "Customer":
        next_step = "Check in before renewal and share their latest posture report"
        subject = "Your Acme Guard check-in"
        middle = (
            "It has been a while since we last spoke, so I wanted to check that Acme Guard is still doing its job for you. "
            "I can send a short report of what it flagged in the last 30 days and anything worth fixing before renewal."
        )
        ask = "Shall I send it over?"
        send = add_business_days(today, 1)
    elif "no_contact" in flags:
        next_step = "Re-open the conversation with a short, low-pressure check-in"
        subject = "Picking this back up"
        topic = {
            "Prospect": "your cloud compliance plans",
            "Discovery": "your audit timeline",
            "Proposal": "the proposal",
        }.get(stage, "our last conversation")
        middle = (
            f"It has been a few weeks since we talked about {topic}. Priorities shift, so no pressure. "
            "If it is still on your list, I can send a short update on what has changed on our side since then."
        )
        ask = "Is it still worth a conversation this quarter?"
        send = add_business_days(today, 1)
    else:  # stalled
        context = _context_line((last_activity or {}).get("summary", ""))
        if stage == "Proposal":
            next_step = "Send a one-page close plan and ask who else needs to sign off"
            subject = "Making the last steps easy"
            middle = (
                f"{context or 'I know reviews take time on your side.'} To help, I put together a one-page plan "
                "with what is left before go-live and who usually signs off at this point."
            )
            ask = "Would it help if I sent it over, or is there someone else I should include?"
        elif stage == "Discovery":
            next_step = "Offer a 30-minute technical deep-dive with their cloud lead"
            subject = "A technical deep-dive for your team"
            middle = (
                f"{context or 'Last time it sounded like the next step was a closer technical look.'} I can run a "
                "read-only scan of one cloud account with your cloud lead and walk through the findings together."
            )
            ask = "Would a 30-minute slot next week work for them?"
        else:
            webinar = "webinar" in (last_activity or {}).get("summary", "").lower()
            next_step = "Share a relevant customer story and ask for a short intro call"
            subject = "How a team like yours handled SOC 2 Type II"
            middle = (
                ("You joined our session on SOC 2 Type II, so I thought this might be useful: " if webinar
                 else "I thought this might be useful: ")
                + "a fintech team of about 200 people used Acme Guard to pass their Type II audit in 11 weeks."
            )
            ask = "Happy to share the details if it is relevant. Worth a short chat?"
        send = add_business_days(today, 1)

    body = "\n".join([f"Hi {first},", "", middle, "", ask, "", rep["name"], f"{rep['title']}, {rep['company']}"])
    return {
        "subject": subject,
        "body": body,
        "next_step": next_step,
        "send_date": send,
        "lessons_applied": applied,
    }


def _context_line(summary: str) -> str:
    """Turn the last CRM activity into a neutral opening line (never quotes internal notes)."""
    s = summary.lower()
    if "legal" in s or "msa" in s:
        return "I know legal reviews take time on your side."
    if "budget" in s:
        return "I know budget reviews can move dates around."
    if "questionnaire" in s or "security review" in s:
        return "I know the security review is still with your team."
    if "discount" in s or "pricing" in s:
        return "Following up on your pricing question."
    if "migration" in s:
        return "I know the cloud migration comes first right now."
    if "deep-dive" in s or "technical" in s:
        return "Last time it sounded like the next step was a closer technical look."
    return ""
