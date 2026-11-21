"""Demo clients and their ad numbers.

The five clients are invented, but their numbers are not guesses: each client's cost per click,
cost per lead, click-through and conversion rates follow the published 2026 median for its
industry (sources in BENCHMARK_SOURCES), with a fixed per-client offset of up to 12% and normal
day-to-day noise, so no two clients look identical. Values are deterministic for a given
(client, channel, date), so the demo "ad platform API" returns the same numbers all day.

One scripted event: GreenLeaf Organics' Meta Ads cost per lead roughly doubles over the most
recent 7 days, so the week-on-week alert has something real to catch.
"""

from __future__ import annotations

import calendar
import hashlib
import random
from datetime import date, timedelta
from typing import Any

CHANNELS = ("Google Ads", "Meta Ads", "SEO")
SERVICES = ("SEO", "Paid Ads", "Web Design")

SEED_CLIENTS: list[dict[str, Any]] = [
    {
        "name": "Bright Smile Dental",
        "website": "https://brightsmile-dental.example",
        "industry": "Dental clinics",
        "services": ["SEO", "Paid Ads"],
        "manager": "Priya Shah",
        "manager_email": "priya@northwind-digital.example",
        "monthly_budget": 9000,
    },
    {
        "name": "Harbor & Pine Realty",
        "website": "https://harborpine-realty.example",
        "industry": "Real estate",
        "services": ["Paid Ads", "SEO", "Web Design"],
        "manager": "Marcus Lee",
        "manager_email": "marcus@northwind-digital.example",
        "monthly_budget": 14000,
    },
    {
        "name": "Peak Performance Gym",
        "website": "https://peakperformance-gym.example",
        "industry": "Gyms and fitness studios",
        "services": ["Paid Ads", "SEO"],
        "manager": "Elena Rossi",
        "manager_email": "elena@northwind-digital.example",
        "monthly_budget": 6000,
    },
    {
        "name": "GreenLeaf Organics",
        "website": "https://greenleaf-organics.example",
        "industry": "Organic food e-commerce",
        "services": ["Paid Ads", "SEO", "Web Design"],
        "manager": "Priya Shah",
        "manager_email": "priya@northwind-digital.example",
        "monthly_budget": 18000,
    },
    {
        "name": "Summit Legal Partners",
        "website": "https://summitlegal-partners.example",
        "industry": "Legal services",
        "services": ["SEO", "Paid Ads"],
        "manager": "Marcus Lee",
        "manager_email": "marcus@northwind-digital.example",
        "monthly_budget": 11000,
    },
]

SPIKE_CLIENT = "GreenLeaf Organics"
SPIKE_CHANNEL = "Meta Ads"
SPIKE_DAYS = 7

# --------------------------------------------------------------------------------------
# Published 2026 benchmarks the demo numbers follow
# --------------------------------------------------------------------------------------
BENCHMARK_SOURCES: list[dict[str, str]] = [
    {
        "id": "google",
        "publisher": "WordStream by LocaliQ",
        "title": "Google Ads Benchmarks 2026",
        "url": "https://www.wordstream.com/blog/2026-google-ads-benchmarks",
        "used_for": "Google Ads click-through rate, cost per click and cost per lead (medians of 13,474 US search campaigns, April 2025 to March 2026)",
    },
    {
        "id": "meta",
        "publisher": "LocaliQ",
        "title": "Facebook Advertising Benchmarks for 2026",
        "url": "https://localiq.com/blog/facebook-advertising-benchmarks/",
        "used_for": "Meta Ads click-through rate (traffic campaigns), conversion rate and cost per lead (lead campaigns)",
    },
    {
        "id": "organic_ctr",
        "publisher": "Ahrefs",
        "title": "What is a Good Organic CTR? Real Website Benchmarks (July 2026)",
        "url": "https://ahrefs.com/blog/what-is-a-good-ctr/",
        "used_for": "SEO click-through rate: 1.5%, the middle of the 1 to 2% whole-site range across 400,000 Search Console sites",
    },
    {
        "id": "organic_cvr",
        "publisher": "Ruler Analytics",
        "title": "Average Conversion Rate by Industry (November 2026)",
        "url": "https://ruleranalytics.com/blog/insight/conversion-rate-by-industry/",
        "used_for": "SEO conversion rate from organic search by industry (110M+ sessions, 5M+ conversions)",
    },
]

# Benchmark category -> Google Ads (CTR, CPC, CPL), Meta Ads (CTR, CVR, CPL), organic search CVR.
# Meta lead-campaign figures are missing for three categories; those use the all-industry median.
BENCHMARKS: dict[str, dict[str, Any]] = {
    "Attorneys & Legal Services": {"google": (0.0587, 9.87, 131.63), "meta": (0.0177, 0.0854, 27.39), "organic_cvr": 0.073},
    "Dentists & Dental Services": {"google": (0.0566, 8.00, 72.97), "meta": (0.0155, 0.0607, 61.56), "organic_cvr": 0.018},
    "Real Estate": {"google": (0.0761, 3.22, 102.51), "meta": (0.0237, 0.0995, 13.74), "organic_cvr": 0.024},
    "Health & Fitness": {"google": (0.0581, 6.17, 67.36), "meta": (0.0186, 0.0798, 27.11), "organic_cvr": 0.018},
    "Restaurants & Food": {"google": (0.0683, 2.05, 30.57), "meta": (0.0268, 0.0854, 27.39), "organic_cvr": 0.020},
    "Shopping, Collectibles & Gifts": {"google": (0.0828, 4.14, 49.40), "meta": (0.0188, 0.0854, 27.39), "organic_cvr": 0.020},
    "All industries": {"google": (0.0664, 5.42, 66.69), "meta": (0.0193, 0.0854, 27.39), "organic_cvr": 0.049},
}
ORGANIC_CTR = 0.015

# Organic clicks per day before growth, by client (a modelling input, not a benchmark)
_ORGANIC_CLICKS: dict[str, float] = {
    "Bright Smile Dental": 42,
    "Harbor & Pine Realty": 64,
    "Peak Performance Gym": 38,
    "GreenLeaf Organics": 150,
    "Summit Legal Partners": 36,
}
_SHARES = {"Google Ads": 0.50, "Meta Ads": 0.35, "SEO": 0.15}


def benchmark_category(industry: str | None) -> str:
    text = (industry or "").lower()
    rules = (
        (("e-commerce", "ecommerce", "online store", "shop", "retail"), "Shopping, Collectibles & Gifts"),
        (("legal", "law", "attorney", "solicitor"), "Attorneys & Legal Services"),
        (("dental", "dentist", "orthodont"), "Dentists & Dental Services"),
        (("real estate", "realty", "property", "estate agent"), "Real Estate"),
        (("gym", "fitness", "yoga", "pilates", "health club"), "Health & Fitness"),
        (("food", "bakery", "restaurant", "cafe", "catering"), "Restaurants & Food"),
    )
    for words, category in rules:
        if any(w in text for w in words):
            return category
    return "All industries"


def _industry_of(client_name: str) -> str | None:
    return next((c["industry"] for c in SEED_CLIENTS if c["name"] == client_name), None)
# per-client budget split across Google Ads / Meta Ads / SEO (defaults to the channel shares)
_CLIENT_SHARES: dict[str, dict[str, float]] = {
    "Peak Performance Gym": {"Google Ads": 0.40, "Meta Ads": 0.45, "SEO": 0.15},
    "Summit Legal Partners": {"Google Ads": 0.52, "Meta Ads": 0.30, "SEO": 0.18},
    "Bright Smile Dental": {"Google Ads": 0.52, "Meta Ads": 0.28, "SEO": 0.20},
}
_WEEKDAY = (1.05, 1.08, 1.04, 1.00, 0.95, 0.85, 0.88)  # Mon..Sun


def stable_seed(*parts: Any) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:16], 16)


def channels_for_services(services: list[str]) -> list[str]:
    chans: list[str] = []
    if "Paid Ads" in services:
        chans += ["Google Ads", "Meta Ads"]
    if "SEO" in services:
        chans.append("SEO")
    return chans


def budget_for(client_name: str, monthly_budget: float | None) -> float:
    if monthly_budget:
        return float(monthly_budget)
    return 5000 + stable_seed("budget", client_name) % 10000


def _offset(client_name: str, channel: str, metric: str) -> float:
    """A fixed per-client deviation from the median, between -12% and +12%."""
    return 0.88 + (stable_seed("offset", client_name, channel, metric) % 2401) / 10000


def _whole(value: float, rng: random.Random) -> int:
    """Round to a whole count without bias (2.3 becomes 3 three times in ten)."""
    base = int(value)
    return base + (1 if rng.random() < value - base else 0)


def synth_row(
    client_name: str,
    channel: str,
    day: date,
    *,
    anchor: date,
    monthly_budget: float | None = None,
    industry: str | None = None,
) -> dict[str, Any]:
    """One day of performance for one client+channel. `anchor` = "today" for the spike window."""
    rng = random.Random(stable_seed(client_name, channel, day.isoformat()))
    bench = BENCHMARKS[benchmark_category(industry or _industry_of(client_name))]
    share = _CLIENT_SHARES.get(client_name, {}).get(channel, _SHARES[channel])
    budget = budget_for(client_name, monthly_budget)
    days_before_anchor = (anchor - day).days
    week = _WEEKDAY[day.weekday()]
    off = lambda metric: _offset(client_name, channel, metric)  # noqa: E731

    if channel == "SEO":
        growth = 1.0 - 0.0015 * max(0, days_before_anchor)  # organic traffic compounds slowly
        base = _ORGANIC_CLICKS.get(client_name, 20 + stable_seed("organic", client_name) % 41)
        clicks = max(0, _whole(base * growth * week * rng.uniform(0.85, 1.15), rng))
        impressions = max(clicks, round(clicks / (ORGANIC_CTR * off("ctr") * rng.uniform(0.9, 1.1))))
        conversions = _whole(clicks * bench["organic_cvr"] * off("cvr") * rng.uniform(0.8, 1.2), rng)
        spend = budget * share / calendar.monthrange(day.year, day.month)[1]  # the SEO retainer, spread per day
        return {"date": day, "channel": channel, "impressions": impressions, "clicks": clicks, "spend": round(spend, 2), "conversions": conversions}

    trend = 1.0 - 0.003 * max(0, days_before_anchor - 7)  # gentle growth that levels off at budget pace
    spend = budget * share / 30.4 * week * trend * rng.uniform(0.90, 1.10)
    if channel == "Google Ads":
        ctr, cpc, cpl = bench["google"]
        clicks = max(1, round(spend / (cpc * off("cpc") * rng.uniform(0.95, 1.05))))
        expected = spend / (cpl * off("cpl") * rng.uniform(0.92, 1.08))
    else:  # Meta Ads lead campaigns: cost per click follows from cost per lead and conversion rate
        ctr, cvr, cpl = bench["meta"]
        expected = spend / (cpl * off("cpl") * rng.uniform(0.92, 1.08))
        clicks = max(1, round(expected / (cvr * off("cvr") * rng.uniform(0.94, 1.06))))
    if client_name == SPIKE_CLIENT and channel == SPIKE_CHANNEL and 1 <= days_before_anchor <= SPIKE_DAYS:
        spend *= 1.15  # the algorithm pushed budget into a fatigued audience...
        expected *= 0.55  # ...and leads fell: cost per lead roughly doubles
    impressions = max(clicks, round(clicks / (ctr * off("ctr") * rng.uniform(0.92, 1.08))))
    conversions = _whole(expected, rng)
    return {
        "date": day,
        "channel": channel,
        "impressions": impressions,
        "clicks": clicks,
        "spend": round(spend, 2),
        "conversions": conversions,
    }


def synth_rows(
    clients: list[dict[str, Any]],
    start: date,
    end: date,
    *,
    anchor: date,
    all_channels: bool = False,
) -> list[dict[str, Any]]:
    """Rows for every client/channel/day in [start, end]. Each row carries `client` (name)."""
    rows: list[dict[str, Any]] = []
    day = start
    while day <= end:
        for c in clients:
            chans = list(CHANNELS) if all_channels else channels_for_services(list(c.get("services") or []))
            for ch in chans:
                row = synth_row(c["name"], ch, day, anchor=anchor, monthly_budget=c.get("monthly_budget"), industry=c.get("industry"))
                row["client"] = c["name"]
                rows.append(row)
        day += timedelta(days=1)
    return rows
