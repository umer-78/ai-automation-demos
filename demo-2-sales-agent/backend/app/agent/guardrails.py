"""Checks every draft must pass before it reaches the approval queue.

A failed check is returned to the model as a tool error with the reason, so it can fix the
draft. The same checks run on template drafts, so offline mode follows the same rules.
"""

from __future__ import annotations

import re
from datetime import date

from app.agent.lessons import MEETING_RE, Lessons, word_count
from app.agent.scoring import is_business_day

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<![\w$])\+?\(?\d{2,4}\)?[\s.-]\d{3,4}[\s.-]\d{3,4}(?!\d)")
PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{1,40}\]|\{\{[^}]*\}\}|<[A-Z][A-Z _]{2,}>|\bXXX\b|\bTBD\b")
BANNED = ("guarantee", "100% secure", "breach-proof", "unhackable", "risk-free", "never be breached")
SIGNIFICANT_RE = re.compile(r"[A-Za-z][A-Za-z0-9/.-]{3,}|\$?\d[\d.,]*[MBK]?")
COMMON = {
    "with", "from", "that", "this", "their", "have", "after", "into", "about", "your", "they", "which",
    "achieved", "completed", "announced", "company", "platform", "software", "earlier", "independent",
    "information", "security", "management", "system", "certification", "provider", "covering",
}
ANCHOR_TERMS = (
    "soc 2", "type ii", "type 2", "iso 27001", "iso/iec 27001", "series a", "series b", "series c", "ciso",
    "chief information security officer", "head of security", "trust center",
)


SYNONYMS = (
    {"ciso", "chief information security officer", "chief security officer", "security leader"},
    {"type ii", "type 2"},
    {"iso 27001", "iso/iec 27001"},
)


def anchor_terms(fact: str) -> set[str]:
    lower = fact.lower()
    terms = {t for t in ANCHOR_TERMS if t in lower}
    for group in SYNONYMS:
        if terms & group:
            terms |= group
    terms |= {m.lower() for m in re.findall(r"\$\d[\d.,]*[MBK]?", fact)}
    return terms


def mentions_fact(body: str, fact: str) -> bool:
    lower = body.lower()
    anchors = anchor_terms(fact)
    if any(a in lower for a in anchors):
        return True
    words = {w.lower() for w in SIGNIFICANT_RE.findall(fact)} - COMMON
    shared = {w for w in words if w in lower}
    return len(shared) >= 3


def _common_checks(subject: str, body: str, errors: list[str]) -> None:
    if not 3 <= len(subject.strip()) <= 90:
        errors.append("Subject must be 3 to 90 characters.")
    if EMAIL_RE.search(body) or EMAIL_RE.search(subject):
        errors.append("Remove email addresses from the draft. Never invent contact details.")
    if PHONE_RE.search(body):
        errors.append("Remove phone numbers from the draft. Never invent contact details.")
    if PLACEHOLDER_RE.search(body) or PLACEHOLDER_RE.search(subject):
        errors.append("No placeholders like [Name]. Write a draft that is ready to send after approval.")
    lower = body.lower()
    for phrase in BANNED:
        if phrase in lower:
            errors.append(f"Do not promise outcomes (found '{phrase}').")


def check_outreach(subject: str, body: str, fact: str, lessons: Lessons) -> list[str]:
    errors: list[str] = []
    _common_checks(subject, body, errors)
    words = word_count(body)
    limit = int(lessons.max_words * 1.1)
    if words < 25:
        errors.append("The email is too short to be useful (under 25 words).")
    if words > limit:
        errors.append(f"The email has {words} words; reviewer feedback sets the limit at {lessons.max_words}. Shorten it.")
    if not mentions_fact(body, fact):
        errors.append("The email must mention the fact you cite, in your own words.")
    if lessons.soft_cta and MEETING_RE.search(body):
        errors.append("Reviewer feedback: do not ask for a meeting, call or demo in a first email. Offer something useful instead.")
    return errors


def check_follow_up(subject: str, body: str, next_step: str, send_date: date | None, today: date, lessons: Lessons) -> list[str]:
    errors: list[str] = []
    _common_checks(subject, body, errors)
    words = word_count(body)
    if words < 20:
        errors.append("The follow-up is too short to be useful (under 20 words).")
    if words > max(lessons.max_words, 120) * 1.1:
        errors.append(f"The follow-up has {words} words; keep it under {max(lessons.max_words, 120)}.")
    if not 5 <= len(next_step.strip()) <= 240:
        errors.append("Describe the next step in 5 to 240 characters.")
    if send_date is None:
        errors.append("send_date must be a date in YYYY-MM-DD format.")
    else:
        delta = (send_date - today).days
        if delta < 1 or delta > 14:
            errors.append("send_date must be between tomorrow and 14 days from today.")
        elif not is_business_day(send_date):
            errors.append("send_date must be a weekday.")
    return errors


def is_meeting_ask(text: str) -> bool:
    return bool(MEETING_RE.search(text or ""))
