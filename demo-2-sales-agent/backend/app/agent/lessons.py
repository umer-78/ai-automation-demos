"""Turn reviewer feedback into rules the next run follows.

The last N feedback items go into the next run's prompt verbatim (that is the spec). On top
of that, this module derives explicit rules from them ("keep first emails under 90 words",
"no meeting asks in a first email", "skip 1,000+ employee companies"), which are:

* listed in the prompt, so the model sees the pattern and not just the anecdotes;
* enforced by the draft guardrails (a draft that breaks a learned rule is sent back to the
  model with the reason), so the improvement is visible and not left to chance;
* applied by the offline template writer, so the loop also works without an API key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MAX_WORDS = 140
SHORT_MAX_WORDS = 90
MEETING_RE = re.compile(
    r"(\b\d{2}[- ]?(minute|min)\b|\bmeeting\b|\bcall next week\b|\bbook (a|some) time\b|\bcalendar\b|\bwalkthrough\b|\bdemo\b|\bjump on a call\b|\bquick call\b)",
    re.I,
)

RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("short", re.compile(r"\b(too long|shorter|wordy|lengthy|long|concise|brief|too much text)\b", re.I),
     f"Keep first emails under {SHORT_MAX_WORDS} words."),
    ("soft_cta", re.compile(r"(pushy|aggressive|salesy|hard sell|too strong|meeting|demo|\bcall\b|calendar|book)", re.I),
     "Do not ask for a meeting in a first email; offer something useful instead."),
    ("question_subject", re.compile(r"\bsubject\b", re.I), "Write short, question-style subject lines."),
    ("include_price", re.compile(r"\b(price|prices|pricing|cost|costs|how much)\b", re.I), "Mention the starting price in one sentence."),
    ("plain_language", re.compile(r"(jargon|buzzword|corporate speak|plain english|plain language)", re.I),
     "Use plain words, no security jargon."),
    ("lead_with_fact", re.compile(r"(generic|template|personal|specific|vague)", re.I),
     "Open with the specific fact and say why it matters to that company."),
    ("skip_large", re.compile(r"(too big|too large|large enterprise|enterprise-size|large compan|big compan|1,?000\+)", re.I),
     "Skip companies with 1,000+ employees."),
    ("skip_small", re.compile(r"(too small|tiny|too early)", re.I), "Skip companies with fewer than 50 employees."),
    ("skip_security_vendors", re.compile(r"(security vendor|competitor|build (it|this) in-house|sells security)", re.I),
     "Skip security vendors."),
    ("skip_services", re.compile(r"(agency|consultanc|services firm|outsourc)", re.I), "Skip agencies and IT services firms."),
]
NOT_A_FIT_RE = re.compile(r"(not a fit|bad fit|wrong target|not our icp|wrong company|not relevant)", re.I)


@dataclass
class Lessons:
    max_words: int = DEFAULT_MAX_WORDS
    soft_cta: bool = False
    question_subject: bool = False
    include_price: bool = False
    plain_language: bool = False
    lead_with_fact: bool = False
    skip_size_bands: set[str] = field(default_factory=set)
    skip_categories: set[str] = field(default_factory=set)
    rules: list[dict[str, Any]] = field(default_factory=list)

    def add(self, key: str, text: str, feedback_id: int) -> None:
        for rule in self.rules:
            if rule["key"] == key:
                if feedback_id not in rule["feedback_ids"]:
                    rule["feedback_ids"].append(feedback_id)
                if key == "rep_length":
                    rule["text"] = text
                return
        self.rules.append({"key": key, "text": text, "feedback_ids": [feedback_id]})

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_words": self.max_words,
            "soft_cta": self.soft_cta,
            "question_subject": self.question_subject,
            "include_price": self.include_price,
            "plain_language": self.plain_language,
            "lead_with_fact": self.lead_with_fact,
            "skip_size_bands": sorted(self.skip_size_bands),
            "skip_categories": sorted(self.skip_categories),
            "rules": self.rules,
        }

    def prompt_lines(self) -> str:
        if not self.rules:
            return "None yet."
        return "\n".join(f"- {r['text']} (from feedback #{', #'.join(str(i) for i in r['feedback_ids'])})" for r in self.rules)


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'$%.-]+\b", text or ""))


def derive_lessons(items: list[dict[str, Any]]) -> Lessons:
    """items: newest-first feedback rows joined with their draft (see learning.recent_feedback)."""
    lessons = Lessons()
    for item in reversed(items):  # oldest first, so newer feedback can tighten earlier rules
        fid = item["id"]
        action = item["action"]
        reason = item.get("reason") or ""
        is_outreach = item.get("draft_kind") == "outreach"
        if action in ("reject", "edit") and reason:
            for key, pattern, text in RULES:
                if not pattern.search(reason):
                    continue
                if key in ("skip_large", "skip_small", "skip_security_vendors", "skip_services") and not is_outreach:
                    continue  # targeting rules only make sense for new-lead outreach
                _apply(lessons, key)
                lessons.add(key, text, fid)
        if action == "edit" and item.get("edited_body") and item.get("original_body"):
            before, after = word_count(item["original_body"]), word_count(item["edited_body"])
            if before and after < before * 0.75:
                target = max(60, min(lessons.max_words, after + 10))
                lessons.max_words = target
                lessons.add("rep_length", f"The rep cut a draft from {before} to {after} words; stay under {target} words.", fid)
            if MEETING_RE.search(item["original_body"]) and not MEETING_RE.search(item["edited_body"]):
                lessons.soft_cta = True
                lessons.add("soft_cta", "Do not ask for a meeting in a first email; offer something useful instead.", fid)
    return lessons


def _apply(lessons: Lessons, key: str) -> None:
    if key == "short":
        lessons.max_words = min(lessons.max_words, SHORT_MAX_WORDS)
    elif key == "soft_cta":
        lessons.soft_cta = True
    elif key == "question_subject":
        lessons.question_subject = True
    elif key == "include_price":
        lessons.include_price = True
    elif key == "plain_language":
        lessons.plain_language = True
    elif key == "lead_with_fact":
        lessons.lead_with_fact = True
    elif key == "skip_large":
        lessons.skip_size_bands.add("1000+")
    elif key == "skip_small":
        lessons.skip_size_bands.add("1-49")
    elif key == "skip_security_vendors":
        lessons.skip_categories.add("security_vendor")
    elif key == "skip_services":
        lessons.skip_categories.add("services")
