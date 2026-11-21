"""Lead and account scoring: 0-100 = fit (0-50) + buying signals (0-30) + recency (0-20).

Scores are computed in code from the ideal customer profile (ICP), never guessed by the
model, so they are consistent between runs and every point can be explained in plain
English. The model's job is research and judgement; arithmetic stays deterministic.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime, timedelta
from typing import Any


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def ago(days: int) -> str:
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


CATEGORIES = {
    "b2b_saas": "B2B SaaS",
    "fintech": "Fintech",
    "healthtech": "Healthtech",
    "devtools": "Developer tools",
    "data_ai": "Data and AI",
    "vertical_software": "Vertical software",
    "enterprise_software": "Enterprise software",
    "security_vendor": "Security vendor",
    "services": "Agency or IT services",
    "other": "Other",
}
SIZE_BANDS: dict[str, tuple[int, int] | None] = {
    "1-49": (1, 49),
    "50-199": (50, 199),
    "200-499": (200, 499),
    "500-999": (500, 999),
    "1000+": (1000, 1_000_000),
    "unknown": None,
}
REGIONS = ["North America", "UK & Ireland", "Europe", "ANZ", "APAC", "LATAM", "Middle East & Africa", "unknown"]
CLOUD_VALUES = ["yes", "no", "unknown"]
SIGNAL_TYPES = {
    "compliance": "compliance milestone",
    "security_leader": "new security leader",
    "security_hiring": "hiring security or cloud engineers",
    "funding": "recent funding",
    "expansion": "expansion into new markets",
    "cloud": "cloud migration or growth",
    "tech_stack": "relevant technology in use",
    "news": "other company news",
}
STAGES = ["Prospect", "Discovery", "Proposal", "Customer"]
STAGE_LIMIT_DAYS = {"Prospect": 30, "Discovery": 30, "Proposal": 21}
NO_CONTACT_DAYS = 30
UPSELL_KEYWORDS = (
    "expand", "expansion", "new region", "acquir", "iso 27001", "more accounts", "above 20 accounts",
    "new product line", "product line",
)

DEFAULT_ICP: dict[str, Any] = {
    "summary": (
        "B2B software companies with 50 to 1,000 employees that run mostly in AWS, Azure or Google Cloud "
        "and face SOC 2 or ISO 27001 pressure right now: a compliance milestone, a new security leader, "
        "security hiring or a recent funding round. Skip security vendors, agencies and large on-premise enterprises."
    ),
    "target_categories": ["b2b_saas", "fintech", "healthtech", "devtools", "data_ai", "vertical_software"],
    "adjacent_categories": ["enterprise_software", "other"],
    "excluded_categories": ["security_vendor", "services"],
    "employee_min": 50,
    "employee_max": 1000,
    "regions": ["North America", "UK & Ireland", "Europe", "ANZ"],
    "signal_weights": {
        "compliance": 30,
        "security_leader": 27,
        "security_hiring": 25,
        "funding": 22,
        "expansion": 16,
        "cloud": 14,
        "tech_stack": 10,
        "news": 8,
    },
    "exclusions": [
        "Security vendors (they build this in-house)",
        "Agencies and IT services firms",
        "Fewer than 50 employees",
        "Large enterprises that run mostly on-premise",
    ],
}


# ------------------------------------------------------------------------------- ICP handling
def normalize_icp(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate an ICP coming from the rep's form or the agent; fill gaps from the default."""
    icp = copy.deepcopy(DEFAULT_ICP)
    raw = raw or {}
    summary = " ".join(str(raw.get("summary") or "").split())
    if len(summary) >= 20:
        icp["summary"] = summary[:900]
    for key in ("target_categories", "adjacent_categories", "excluded_categories"):
        if key in raw and isinstance(raw[key], list):
            icp[key] = [c for c in dict.fromkeys(raw[key]) if c in CATEGORIES]
    # a category can only be in one bucket; exclusion wins, then target
    icp["target_categories"] = [c for c in icp["target_categories"] if c not in icp["excluded_categories"]]
    icp["adjacent_categories"] = [
        c for c in icp["adjacent_categories"] if c not in icp["excluded_categories"] and c not in icp["target_categories"]
    ]
    try:
        lo = int(raw.get("employee_min", icp["employee_min"]))
        hi = int(raw.get("employee_max", icp["employee_max"]))
    except (TypeError, ValueError):
        lo, hi = icp["employee_min"], icp["employee_max"]
    lo = max(1, min(lo, 100_000))
    hi = max(lo, min(hi, 1_000_000))
    icp["employee_min"], icp["employee_max"] = lo, hi
    if isinstance(raw.get("regions"), list):
        icp["regions"] = [r for r in dict.fromkeys(raw["regions"]) if r in REGIONS and r != "unknown"]
    weights = raw.get("signal_weights")
    if isinstance(weights, dict):
        for key in SIGNAL_TYPES:
            if key in weights:
                try:
                    icp["signal_weights"][key] = max(0, min(30, int(weights[key])))
                except (TypeError, ValueError):
                    pass
    if isinstance(raw.get("exclusions"), list):
        icp["exclusions"] = [" ".join(str(x).split())[:160] for x in raw["exclusions"] if str(x).strip()][:10]
    return icp


# ------------------------------------------------------------------------------- helpers
def parse_fact_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt, length in (("%Y-%m-%d", 10), ("%Y-%m", 7)):
        try:
            return datetime.strptime(text[:length], fmt).date()
        except ValueError:
            continue
    return None


def fmt_day(d: date | datetime | None) -> str:
    if d is None:
        return "an unknown date"
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {d.strftime('%b %Y')}"


def age_phrase(days: int) -> str:
    if days < 14:
        return f"{days} day{'s' if days != 1 else ''} old"
    if days < 60:
        return f"{days // 7} weeks old"
    return f"{round(days / 30.4)} months old"


def band_for_size(size: int | None) -> str:
    if not size:
        return "unknown"
    for band, rng in SIZE_BANDS.items():
        if rng and rng[0] <= size <= rng[1]:
            return band
    return "unknown"


def size_points(band: str, icp: dict[str, Any]) -> tuple[int, str]:
    rng = SIZE_BANDS.get(band)
    if rng is None:
        return 7, "size not confirmed"
    lo, hi = icp["employee_min"], icp["employee_max"]
    label = f"{band} employees"
    if rng[0] >= lo and rng[1] <= hi:
        return 15, label
    if rng[0] < hi and rng[1] > lo and min(rng[1], hi) - max(rng[0], lo) >= 20:
        return 8, f"{label} (partly in range)"
    return 0, f"{label} (outside the {lo:,}-{hi:,} range)"


def category_points(category: str, icp: dict[str, Any]) -> int:
    if category in icp["target_categories"]:
        return 20
    if category in icp["adjacent_categories"]:
        return 10
    if category in icp["excluded_categories"]:
        return 0
    return 5


def region_points(region: str, icp: dict[str, Any]) -> int:
    if region in icp["regions"]:
        return 5
    return 2 if region in ("", "unknown", None) else 0


def recency_points(age_days: int | None) -> int:
    if age_days is None:
        return 3
    for limit, pts in ((30, 20), (60, 17), (90, 14), (180, 10), (270, 7), (365, 5)):
        if age_days <= limit:
            return pts
    return 2


# ------------------------------------------------------------------------------- leads
def score_lead(attrs: dict[str, Any], facts: list[dict[str, Any]], icp: dict[str, Any], today: date) -> dict[str, Any]:
    category = attrs.get("category") or "other"
    band = attrs.get("size_band") or "unknown"
    region = attrs.get("region") or "unknown"
    cloud = attrs.get("cloud_native") or "unknown"

    cat_pts = category_points(category, icp)
    size_pts, size_label = size_points(band, icp)
    reg_pts = region_points(region, icp)
    cloud_pts = {"yes": 10, "no": 0}.get(cloud, 4)
    fit = cat_pts + size_pts + reg_pts + cloud_pts

    weights = icp["signal_weights"]
    types = sorted({f.get("type") or "news" for f in facts}, key=lambda t: weights.get(t, 0), reverse=True)
    signals = min(30, weights.get(types[0], 0) + 4 * (len(types) - 1)) if types else 0

    dated = [(parse_fact_date(f.get("date")), f) for f in facts]
    dated = [(d, f) for d, f in dated if d]
    newest = max(dated, key=lambda x: x[0]) if dated else None
    age = (today - newest[0]).days if newest else None
    if age is not None and age < 0:
        age = 0
    recency = recency_points(age)

    excluded = category in icp["excluded_categories"]
    total = fit + signals + recency
    if excluded:
        total = min(total, 20)

    where = region if region not in ("", "unknown") else "region not confirmed"
    cloud_label = {"yes": "cloud-native", "no": "mostly on-premise"}.get(cloud, "cloud use not confirmed")
    fit_txt = f"Fit {fit}/50: {CATEGORIES.get(category, category)}, {size_label}, {where}, {cloud_label}."
    if types:
        lead_type = types[0]
        signal_date = next((d for d, f in dated if (f.get("type") or "news") == lead_type), None)
        sig_txt = f"Signals {signals}/30: {SIGNAL_TYPES.get(lead_type, lead_type)}"
        sig_txt += f" ({fmt_day(signal_date)})" if signal_date else ""
        if len(types) > 1:
            sig_txt += f" plus {len(types) - 1} more"
        sig_txt += "."
    else:
        sig_txt = "Signals 0/30: no buying signal found."
    rec_txt = (
        f"Recency {recency}/20: newest signal is {age_phrase(age)}." if age is not None else f"Recency {recency}/20: date not stated."
    )
    reason = f"{fit_txt} {sig_txt} {rec_txt}"
    excluded_reason = None
    if excluded:
        excluded_reason = f"Excluded by the ICP: {CATEGORIES.get(category, category).lower()}."
        reason = f"{excluded_reason} {reason}"
    return {
        "score": int(total),
        "parts": {"fit": fit, "signals": signals, "recency": recency},
        "reason": reason,
        "excluded": excluded,
        "excluded_reason": excluded_reason,
        "newest_signal_age_days": age,
    }


# ------------------------------------------------------------------------------- accounts
def _days_since(ts: datetime | None, now: datetime) -> int | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        from datetime import timezone

        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, (now - ts).days)


def analyze_account(acc: dict[str, Any], icp: dict[str, Any], now: datetime, last_activity: str = "") -> dict[str, Any]:
    """Flags (stalled / no_contact / upsell) and a 0-100 priority score for one CRM account."""
    stage = acc["stage"]
    in_stage = _days_since(acc.get("stage_entered_at"), now) or 0
    since_contact = _days_since(acc.get("last_contact"), now)
    flags: list[str] = []
    reasons: dict[str, str] = {}

    if since_contact is None or since_contact >= NO_CONTACT_DAYS:
        flags.append("no_contact")
        reasons["no_contact"] = (
            f"No contact for {since_contact} days (last touch {fmt_day(acc.get('last_contact'))})."
            if since_contact is not None
            else "No contact has ever been logged."
        )
    elif stage in STAGE_LIMIT_DAYS and in_stage >= STAGE_LIMIT_DAYS[stage]:
        flags.append("stalled")
        reasons["stalled"] = (
            f"Stuck in {stage} for {in_stage} days (limit {STAGE_LIMIT_DAYS[stage]}), "
            f"although the last touch was only {ago(since_contact)}."
        )

    used, limit = acc.get("cloud_accounts_used"), acc.get("cloud_accounts_limit")
    usage = (used / limit) if used is not None and limit else 0.0
    renewal = acc.get("renewal_date")
    renewal_days = (renewal - now.date()).days if isinstance(renewal, date) else None
    if stage == "Customer" and "no_contact" not in flags:
        text = f"{acc.get('notes') or ''} {last_activity}".lower()
        keyword = next((k for k in UPSELL_KEYWORDS if k in text), None)
        bits = []
        if usage >= 0.8:
            bits.append(f"using {used} of {limit} cloud accounts on {acc.get('plan') or 'their plan'}")
        if keyword:
            bits.append(f"notes mention '{keyword}'")
        if renewal_days is not None and renewal_days <= 90 and usage >= 0.6:
            bits.append(f"renewal in {plural(renewal_days, 'day')}")
        if bits:
            flags.append("upsell")
            reasons["upsell"] = "Likely upsell: " + "; ".join(bits) + "."

    # ---- score
    cat_pts = category_points(acc.get("category") or "other", icp)
    size_pts, size_label = size_points(band_for_size(acc.get("size")), icp)
    if acc.get("size"):
        size_label = f"{acc['size']:,} employees" + (" (outside range)" if size_pts == 0 else "")
    reg_pts = region_points(acc.get("region") or "unknown", icp)
    provider = (acc.get("cloud_provider") or "").lower()
    cloud_pts = 10 if provider in ("aws", "azure", "gcp") else 6 if provider == "hybrid" else 0 if provider == "on-prem" else 4
    fit = cat_pts + size_pts + reg_pts + cloud_pts

    value = acc.get("deal_value") or acc.get("arr") or 0
    base = {"Prospect": 6, "Discovery": 12, "Proposal": 18, "Customer": 10}.get(stage, 6)
    value_pts = 8 if value >= 60000 else 6 if value >= 40000 else 4 if value >= 20000 else 2
    signals = min(30, base + value_pts + (8 if "upsell" in flags else 0))

    if since_contact is None:
        recency = 0
    else:
        recency = 20 if since_contact <= 7 else 16 if since_contact <= 14 else 11 if since_contact < 30 else 5 if since_contact <= 60 else 2

    money = f"${value / 1000:.0f}k {'ARR' if stage == 'Customer' else 'deal'}" if value else "no value logged"
    stage_txt = f"{stage}" + (f" on {acc['plan']}" if stage == "Customer" and acc.get("plan") else "")
    reason = (
        f"Fit {fit}/50: {CATEGORIES.get(acc.get('category') or 'other', 'Other')}, {size_label}, "
        f"{acc.get('region') or 'region unknown'}, {acc.get('cloud_provider') or 'cloud unknown'}. "
        f"Signals {signals}/30: {stage_txt}, {money}" + (", likely upsell" if "upsell" in flags else "") + ". "
        + (
            f"Recency {recency}/20: last touch {ago(since_contact)}."
            if since_contact is not None
            else "Recency 0/20: never contacted."
        )
    )
    return {
        "score": int(fit + signals + recency),
        "parts": {"fit": fit, "signals": signals, "recency": recency},
        "reason": reason,
        "flags": flags,
        "flag_reasons": reasons,
        "days_in_stage": in_stage,
        "days_since_contact": since_contact,
        "renewal_in_days": renewal_days,
        "usage": round(usage, 2),
    }


# ------------------------------------------------------------------------------- dates
def add_business_days(start: date, days: int) -> date:
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def is_business_day(d: date) -> bool:
    return d.weekday() < 5


def company_key(name: str) -> str:
    key = re.sub(r"\b(inc|llc|ltd|gmbh|ag|plc|corp|corporation|co|group|software|technologies)\b\.?", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "", key) or re.sub(r"[^a-z0-9]+", "", name.lower())
