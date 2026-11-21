"""Your own CRM: a CSV export (HubSpot, Salesforce, Pipedrive or any sheet) or a HubSpot sync.

Rows are matched to accounts by company name, so importing the same export twice updates the
accounts instead of doubling them. Nothing is invented: a column the file does not have stays
empty, and the agent's analysis says "unknown" for it.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import accounts, utcnow

HEADERS = {
    "company": ("company", "company name", "account name", "account", "organization", "organisation", "name"),
    "domain": ("domain", "company domain name", "website", "website url", "company website"),
    "industry": ("industry", "company industry"),
    "size": ("size", "employees", "number of employees", "employee count", "headcount"),
    "region": ("region",),
    "country": ("country", "country/region", "billing country", "company country"),
    "stage": ("stage", "deal stage", "opportunity stage", "lifecycle stage", "status"),
    "deal_value": ("deal value", "amount", "deal amount", "opportunity amount", "value"),
    "arr": ("arr", "annual recurring revenue", "annual contract value", "acv"),
    "owner": ("owner", "deal owner", "account owner", "opportunity owner", "company owner", "sales rep"),
    "contact_name": ("contact", "contact name", "primary contact", "associated contact"),
    "contact_title": ("contact title", "job title", "title"),
    "contact_email": ("contact email", "email", "email address"),
    "last_contact": ("last contact", "last contacted", "last activity", "last activity date", "last touch"),
    "stage_entered": ("stage entered", "date entered current stage", "stage date", "last stage change date", "stage change date"),
    "renewal_date": ("renewal date", "renewal", "contract end date"),
    "notes": ("notes", "description", "next step", "next steps"),
}

CATEGORY_WORDS = (
    ("security_vendor", ("security vendor", "cybersecurity", "cyber security", "computer & network security", "network security")),
    ("services", ("agency", "consult", "it services", "services", "outsourc", "staffing")),
    ("fintech", ("fintech", "payment", "bank", "lending", "insur", "financial", "accounting software")),
    ("healthtech", ("health", "medical", "clinic", "patient", "pharma", "hospital", "care")),
    ("devtools", ("developer", "devops", "api", "dev tool", "infrastructure software", "observability")),
    ("data_ai", ("data", "analytics", "machine learning", " ai ", "artificial intelligence")),
    ("vertical_software", ("vertical", "construction software", "legal software", "real estate software", "education software", "logistics software")),
    ("enterprise_software", ("enterprise", "erp", "crm software")),
    ("b2b_saas", ("saas", "software", "platform", "cloud")),
)
REGION_WORDS = (
    ("North America", ("united states", "usa", "us", "u.s.", "canada", "america")),
    ("UK & Ireland", ("united kingdom", "uk", "england", "scotland", "wales", "ireland", "great britain")),
    ("ANZ", ("australia", "new zealand")),
    ("LATAM", ("brazil", "mexico", "argentina", "chile", "colombia", "peru", "uruguay")),
    ("Middle East & Africa", ("united arab emirates", "uae", "saudi", "israel", "south africa", "nigeria", "egypt", "kenya", "qatar", "turkey")),
    ("APAC", ("india", "singapore", "japan", "china", "korea", "hong kong", "indonesia", "philippines", "vietnam", "malaysia", "thailand", "pakistan", "taiwan")),
    ("Europe", ("germany", "france", "netherlands", "spain", "italy", "sweden", "denmark", "norway", "finland", "poland", "belgium", "austria", "switzerland", "portugal", "czech", "estonia", "romania", "europe")),
)


def category_of(text: str | None) -> str:
    t = f" {(text or '').lower()} "
    for cat, words in CATEGORY_WORDS:
        if any(w in t for w in words):
            return cat
    return "other"


def region_of(country: str | None) -> str | None:
    c = (country or "").strip().lower()
    if not c:
        return None
    for region, words in REGION_WORDS:
        if c in words or any(len(w) > 3 and w in c for w in words):
            return region
    return None


def stage_of(text: str) -> str | None:
    """Prospect | Discovery | Proposal | Customer, None for lost or unknown stages."""
    t = text.strip().lower()
    if not t:
        return None
    if "lost" in t or "churn" in t or "disqualif" in t:
        return None
    if "won" in t or "customer" in t or "closed" in t:
        return "Customer"
    if any(w in t for w in ("proposal", "negotiat", "contract", "quote", "decision", "commit", "pricing")):
        return "Proposal"
    if any(w in t for w in ("discovery", "qualif", "demo", "meeting", "evaluation", "presentation", "solution")):
        return "Discovery"
    if any(w in t for w in ("prospect", "lead", "new", "appointment", "outreach", "contacted", "opportunity", "subscriber")):
        return "Prospect"
    return None


def _number(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if text in ("", "-", "--"):
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    return float(cleaned) if cleaned not in ("", "-", ".") else None


SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")
TEXT_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y", "%d-%m-%Y")


def slash_order(values: list[str]) -> str:
    first = second = 0
    for v in values:
        m = SLASH.match(v.strip())
        if m:
            first, second = max(first, int(m.group(1))), max(second, int(m.group(2)))
    if first > 12 and second > 12:
        raise ValueError("a date column mixes day-first and month-first dates")
    return "dmy" if first > 12 else "mdy"


def parse_date(value: str, order: str) -> datetime | None:
    v = (value or "").strip()
    if not v:
        return None
    m = SLASH.match(v)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        day, month = (a, b) if order == "dmy" else (b, a)
        return datetime(y, month, day, 12, tzinfo=timezone.utc)
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", v):
        dt = datetime.fromisoformat(v.replace("Z", "+00:00").replace(" ", "T", 1))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    for fmt in TEXT_FORMATS:
        try:
            return datetime.strptime(v, fmt).replace(hour=12, tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"'{v}' is not a date")


def parse_csv(text: str, now: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ValueError("The file has no header row.")
    lookup = {h.strip().lower(): h for h in reader.fieldnames if h}
    cols = {key: next((lookup[n] for n in names if n in lookup), None) for key, names in HEADERS.items()}
    missing = [k for k in ("company", "stage") if not cols[k]]
    if missing:
        raise ValueError(f"Missing column(s): {', '.join(missing)}. Download the template to see the layout.")
    raw = list(reader)
    orders = {k: slash_order([str(r.get(cols[k]) or "") for r in raw]) for k in ("last_contact", "stage_entered", "renewal_date") if cols[k]}
    out: dict[str, dict[str, Any]] = {}
    problems: list[str] = []

    def get(r: dict[str, Any], key: str) -> str:
        return str(r.get(cols[key]) or "").strip() if cols[key] else ""

    for i, r in enumerate(raw, start=2):
        if not any((v or "").strip() for v in r.values() if isinstance(v, str)):
            continue
        try:
            company = get(r, "company")
            if not company:
                raise ValueError("no company name")
            stage = stage_of(get(r, "stage"))
            if stage is None:
                raise ValueError(f"stage '{get(r, 'stage')}' is closed lost or not recognised")
            size = _number(get(r, "size"))
            industry = get(r, "industry") or None
            renewal = parse_date(get(r, "renewal_date"), orders.get("renewal_date", "mdy"))
            row = {
                "company": company[:200],
                "domain": re.sub(r"^https?://(www\.)?", "", get(r, "domain")).strip("/") or None,
                "industry": industry,
                "category": category_of(f"{industry or ''} {get(r, 'notes')}"),
                "size": int(size) if size else None,
                "region": get(r, "region") or region_of(get(r, "country")),
                "cloud_provider": None,
                "stage": stage,
                "deal_value": _number(get(r, "deal_value")) if stage != "Customer" else None,
                "arr": _number(get(r, "arr")) or (_number(get(r, "deal_value")) if stage == "Customer" and not cols["arr"] else None),
                "renewal_date": renewal.date() if renewal else None,
                "stage_entered_at": parse_date(get(r, "stage_entered"), orders.get("stage_entered", "mdy")) or now,
                "last_contact": parse_date(get(r, "last_contact"), orders.get("last_contact", "mdy")),
                "owner": get(r, "owner") or "Unassigned",
                "contact_name": get(r, "contact_name") or None,
                "contact_title": get(r, "contact_title") or None,
                "contact_email": get(r, "contact_email") or None,
                "notes": get(r, "notes") or None,
            }
            if row["last_contact"] and row["last_contact"] > now:
                raise ValueError("last contact date is in the future")
            if row["company"].lower() in out:
                problems.append(f"line {i}: {company} appears twice; the later row wins")
            out[row["company"].lower()] = row
        except ValueError as exc:
            problems.append(f"line {i}: {exc}")
    return list(out.values()), problems


def upsert_accounts(engine: Engine, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Insert new companies, update known ones (matched by name, case-insensitive)."""
    now = utcnow()
    inserted = updated = 0
    with engine.begin() as conn:
        known = {r.company.lower(): r.id for r in conn.execute(select(accounts.c.id, accounts.c.company))}
        for row in rows:
            values = {**row, "updated_at": now}
            acc_id = known.get(row["company"].lower())
            if acc_id:
                conn.execute(accounts.update().where(accounts.c.id == acc_id).values(**values))
                updated += 1
            else:
                conn.execute(accounts.insert().values(**values, flags=[], flag_reasons={}, created_at=now))
                inserted += 1
    return {"inserted": inserted, "updated": updated}


TEMPLATE = (
    "company,domain,industry,employees,country,stage,amount,owner,contact name,contact title,contact email,last contacted,date entered current stage,notes\n"
    "Example Co,example.com,B2B SaaS,180,United States,Proposal,24000,Your Name,Sam Lee,Head of Security,sam@example.com,2026-11-10,2026-10-28,Proposal sent; waiting on security review.\n"
)


def today() -> date:
    return utcnow().date()
