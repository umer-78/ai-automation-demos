"""Deterministic 0-100 scores with plain-English reasons.

The agent supplies facts (industry, size, buying signals, the date of the fact); the server turns them
into a number, so every score is explainable and the model can't simply assert one.
Score = fit (up to 45) + buying signals (up to 35) + recency (up to 20).
"""
from __future__ import annotations

from datetime import date

SIGNALS: dict[str, tuple[int, str]] = {
    "hiring_security": (15, "hiring for security"),
    "compliance": (12, "working on SOC 2 or ISO 27001"),
    "incident": (12, "a recent security incident"),
    "funding": (10, "new funding"),
    "cloud_stack": (5, "runs in the cloud at scale"),
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def parse_day(value: str | None) -> tuple[date | None, str]:
    """'2026-07-04' -> day precision; '2026-11' -> month (dated mid-month); '2026' -> year (dated mid-year)."""
    if not value:
        return None, "none"
    v = str(value).strip()[:10]
    try:
        if len(v) == 10:
            return date.fromisoformat(v), "day"
        if len(v) == 7:
            y, m = (int(x) for x in v.split("-"))
            return date(y, m, 15), "month"
        if len(v) == 4:
            return date(int(v), 7, 1), "year"
    except ValueError:
        pass
    return None, "none"


def _recency(fact_date: date | None, precision: str, today: date) -> tuple[int, str]:
    if fact_date is None:
        return 6, "date not stated"
    days = max(0, (today - fact_date).days)
    if precision == "year":
        return (5, f"sometime in {fact_date.year}") if days <= 365 else (2, f"in {fact_date.year}")
    when = f"in {MONTHS[fact_date.month - 1]} {fact_date.year}" if precision == "month" else (
        "today" if days == 0 else f"{days} days ago")
    if days <= 30:
        return 20, when
    if days <= 90:
        return 14, when
    if days <= 180:
        return 9, when
    if days <= 365:
        return 5, when
    return 2, when


def lead_score(icp: dict, *, industry: str | None, employees: int | None, employees_note: str | None,
               signals: list[str], fact_date: date | None, precision: str, today: date) -> tuple[int, str, dict]:
    ind = (industry or "").lower()
    if "saas" in ind or any(k.lower() in ind for k in icp.get("industries", [])):
        fit, words = 25, ["B2B SaaS"]
    elif "software" in ind:
        fit, words = 15, ["software company"]
    else:
        fit, words = 6, ["outside our core industries"]
    lo, hi = icp.get("size_min", 200), icp.get("size_max", 2000)
    note = f" ({employees_note})" if employees_note else ""
    if employees is None:
        fit += 8
        words.append("size not stated")
    elif lo <= employees <= hi:
        fit += 20
        words.append(f"{employees:,} staff{note}, in range")
    elif employees < 50:
        fit += 0
        words.append(f"only {employees} staff{note}, below our floor")
    elif employees < lo:
        fit += 10
        words.append(f"{employees:,} staff{note}, smaller than our sweet spot")
    else:
        fit += 12
        words.append(f"{employees:,} staff{note}, larger than our sweet spot")
    fit = min(fit, 45)

    clean = [s for s in dict.fromkeys(signals) if s in SIGNALS]
    sig = min(35, sum(SIGNALS[s][0] for s in clean))
    sig_words = [SIGNALS[s][1] for s in clean] or ["no buying signal yet"]

    rec, rec_words = _recency(fact_date, precision, today)
    total = fit + sig + rec
    reason = f"{', '.join(words)}; {', '.join(sig_words)}; fact dated {rec_words}" if fact_date else \
        f"{', '.join(words)}; {', '.join(sig_words)}; fact {rec_words}"
    return total, reason, {"fit": fit, "signals": sig, "recency": rec}
