"""Synthetic data: the 5 fake clients and a deterministic mock ad-platform API.

Nothing here is real. The ad numbers are a pure function of (client, channel, date, today), so the
seed, the daily job and the CSV export always agree. One planted event makes the demo's alert real:
Hale & Marsh Legal's Google Ads cost per conversion jumps in the most recent 7 days.
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

CHANNELS = ["Google Ads", "Meta Ads", "SEO"]
SERVICES = ["SEO", "Paid Ads", "Web Design"]

SEED_CLIENTS = [
    {"id": "c1", "name": "Lumen Coffee Co.", "website": "https://lumencoffee.example", "industry": "E-commerce / Food & Beverage",
     "services": ["SEO", "Paid Ads"], "manager": "Priya Nair", "manager_email": "priya.nair@northwind.example"},
    {"id": "c2", "name": "Hale & Marsh Legal", "website": "https://halemarsh.example", "industry": "Legal / B2B Services",
     "services": ["Paid Ads", "Web Design"], "manager": "Diego Fuentes", "manager_email": "diego.fuentes@northwind.example"},
    {"id": "c3", "name": "Bloom Beauty Bar", "website": "https://bloombar.example", "industry": "Beauty / Retail",
     "services": ["SEO", "Paid Ads"], "manager": "Sofia Klein", "manager_email": "sofia.klein@northwind.example"},
    {"id": "c4", "name": "Vantage SaaS", "website": "https://vantagesaas.example", "industry": "B2B Software / SaaS",
     "services": ["Paid Ads", "Web Design"], "manager": "Marcus Lee", "manager_email": "marcus.lee@northwind.example"},
    {"id": "c5", "name": "North & Cedar Realty", "website": "https://northcedar.example", "industry": "Real Estate / Local Services",
     "services": ["SEO", "Paid Ads", "Web Design"], "manager": "Aisha Rahman", "manager_email": "aisha.rahman@northwind.example"},
]

SEED_IDS = [c["id"] for c in SEED_CLIENTS]  # the only clients the simulated ad API knows

BENCHMARK_SOURCES = {
    "Google Ads": {"title": "LocaliQ: Search advertising benchmarks, 2026 data (published 26 May 2026)",
                   "url": "https://localiq.com/blog/search-advertising-benchmarks/"},
    "Meta Ads": {"title": "LocaliQ: Facebook ads benchmarks 2026, leads campaigns (1,892 US campaigns, Apr 2025 to Jun 2026)",
                 "url": "https://localiq.com/blog/facebook-advertising-benchmarks/"},
}
META_ALL_INDUSTRIES = (1.80, 27.39)  # leads campaigns, all-industry median CPC and CPL
# Per client: the benchmark category used, (CPC, cost per lead) in USD for each paid channel, and daily budgets.
PROFILES = {
    "c1": {"category": "Restaurants & Food", "Google Ads": (2.05, 30.57), "Meta Ads": META_ALL_INDUSTRIES,
           "budget": {"Google Ads": 160, "Meta Ads": 190, "SEO": 95}, "seo_clicks": 140, "seo_cvr": 0.035},
    "c2": {"category": "Attorneys & Legal Services", "Google Ads": (9.87, 131.63), "Meta Ads": META_ALL_INDUSTRIES,
           "budget": {"Google Ads": 900, "Meta Ads": 120, "SEO": 165}, "seo_clicks": 85, "seo_cvr": 0.05},
    "c3": {"category": "Beauty & Personal Care", "Google Ads": (4.62, 39.25), "Meta Ads": (2.97, 50.91),
           "budget": {"Google Ads": 210, "Meta Ads": 260, "SEO": 80}, "seo_clicks": 120, "seo_cvr": 0.04},
    "c4": {"category": "Business Services", "Google Ads": (5.87, 93.69), "Meta Ads": META_ALL_INDUSTRIES,
           "budget": {"Google Ads": 650, "Meta Ads": 210, "SEO": 150}, "seo_clicks": 110, "seo_cvr": 0.03},
    "c5": {"category": "Real Estate", "Google Ads": (3.22, 102.51), "Meta Ads": (1.27, 13.74),
           "budget": {"Google Ads": 420, "Meta Ads": 150, "SEO": 120}, "seo_clicks": 95, "seo_cvr": 0.03},
}
META_NOTE = "This industry has no row in the leads-campaign tables, so the all-industry median is used."
GOLDEN = 0.6180339887498949


def benchmark_basis() -> list[dict]:
    """What each sample client's numbers are built from, for the dashboard to show next to them."""
    out = []
    for c in SEED_CLIENTS:
        prof = PROFILES[c["id"]]
        out.append({"client_id": c["id"], "client": c["name"], "category": prof["category"],
                    "google": {"cpc": prof["Google Ads"][0], "cpl": prof["Google Ads"][1]},
                    "meta": {"cpc": prof["Meta Ads"][0], "cpl": prof["Meta Ads"][1],
                             "note": META_NOTE if prof["Meta Ads"] == META_ALL_INDUSTRIES else None},
                    "daily_budget": prof["budget"]})
    return out


JUMP_CLIENT, JUMP_CHANNEL = "c2", "Google Ads"

CHECKLISTS = {
    "SEO": ["Site and technical audit", "Keyword research", "Local and entity pages", "Baseline rankings report"],
    "Paid Ads": ["Account access and billing", "Campaign architecture", "Pixel and GA4 tracking", "Budget and bidding plan"],
    "Web Design": ["Discovery call", "Wireframes", "Design system", "Build and QA"],
}
WELCOME = {
    "SEO": ":rocket: New SEO client onboarded: *{name}*. Kickoff checklist posted ({n} tasks). AM: {manager}.",
    "Paid Ads": ":mega: New Paid Ads client onboarded: *{name}*. Campaign plan started ({n} tasks). AM: {manager}.",
    "Web Design": ":art: New Web Design client onboarded: *{name}*. Discovery scheduled ({n} tasks). AM: {manager}.",
}


def _count(expected: float, day: date, key: str) -> int:
    """Whole conversions for one day without drifting from the expected total: a low-discrepancy dither
    keeps any run of days within about one conversion of what the benchmark predicts."""
    phase = random.Random(f"dither|{key}").random()
    return int(expected + ((day.toordinal() * GOLDEN + phase) % 1.0))


def ad_rows_for(day: date, today: date, client_ids: list[str]) -> list[dict]:
    """The mock ad platform: one row per client and channel for `day`."""
    out = []
    weekend = 0.82 if day.weekday() >= 5 else 1.0
    for cid in client_ids:
        prof = PROFILES[cid]
        for channel in CHANNELS:
            r = random.Random(f"{cid}|{channel}|{day.isoformat()}")
            budget = prof["budget"][channel]
            if channel == "SEO":
                spend = budget  # the monthly SEO retainer, spread evenly over the days
                clicks = prof["seo_clicks"] * weekend * (0.9 + 0.2 * r.random())
                expected = clicks * prof["seo_cvr"]
            else:
                cpc, cpl = prof[channel]
                spend = budget * weekend * (0.92 + 0.16 * r.random())   # Google and Meta pace around the daily budget
                clicks = spend / cpc * (0.94 + 0.12 * r.random())
                expected = spend / cpl * (0.97 + 0.06 * r.random())
            if cid == JUMP_CLIENT and channel == JUMP_CHANNEL and 0 <= (today - day).days < 7:
                spend *= 1.9       # bid strategy change: spend up ~90% ...
                expected *= 1.9 * 0.29   # ... while conversions fall ~45%, so cost per conversion more than triples
            out.append({"client_id": cid, "date": day, "channel": channel, "spend": round(spend, 2),
                        "clicks": round(clicks), "conversions": _count(expected, day, f"{cid}|{channel}")})
    return out


def window_rows(today: date, days: int, client_ids: list[str]) -> list[dict]:
    rows = []
    for back in range(days - 1, -1, -1):
        rows.extend(ad_rows_for(today - timedelta(days=back), today, client_ids))
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "client_id", "channel", "spend", "clicks", "conversions"])
        w.writeheader()
        for r in rows:
            w.writerow({**{k: r[k] for k in ("client_id", "channel", "spend", "clicks", "conversions")},
                        "date": r["date"].isoformat()})


def read_csv(path: Path) -> list[dict]:
    with path.open() as fh:
        return [{"client_id": r["client_id"], "date": date.fromisoformat(r["date"]), "channel": r["channel"],
                 "spend": round(float(r["spend"]), 2), "clicks": int(r["clicks"]), "conversions": int(r["conversions"])}
                for r in csv.DictReader(fh)]

