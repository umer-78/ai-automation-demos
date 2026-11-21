"""Generate the mock CRM: 50 fictional accounts across 4 stages, 8 stalled deals, 6 untouched for 30+ days.

Dates are stored as "days ago" so the seed can place them relative to the day it runs, which keeps
the stalled and untouched counts exact. Run: python scripts/build_crm.py
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "crm_accounts.csv"
FIELDS = ["id", "company", "industry", "size", "stage", "deal_value", "owner", "last_contact_days_ago",
          "stage_changed_days_ago", "notes", "expansion_signal"]

NAMES = [
    "Larkspur Payroll", "Tidewater Scheduling", "Copperline Analytics", "Brightwater Billing", "Northpine Field Service",
    "Quillstone Legal", "Harborview Logistics", "Ironleaf HR", "Maplecrest Learning", "Silverbirch Docs",
    "Redfern Procurement", "Bluegate Insights", "Stonebridge Claims", "Wildrose Events", "Ashgrove Clinics",
    "Clearwell Payments", "Driftwood Ticketing", "Elmstead Property", "Foxglove Recruiting", "Granite Bay Fleet",
    "Hollowell Surveys", "Juniper Ledger", "Kestrel Dispatch", "Lindenfield Grants", "Moorland Energy",
    "Nettlefield Retail", "Oakhurst Benefits", "Pinecrest Tutoring", "Quarrystone Audit", "Rowan Contracts",
    "Saltmarsh Travel", "Thornbury Studio", "Valewood Telehealth", "Willowbrook CRM", "Yarrow Marketplace",
    "Alderbank Insurance", "Birchmoor Forms", "Cedarline Inventory", "Dunmore Expenses", "Evergate Identity",
    "Fernhill Booking", "Glenrock Signals", "Heathfield Compliance", "Inglewood Media", "Jasperton Freight",
    "Kingsmere Wealth", "Loxley Construction", "Marlow Pharmacy", "Northgate Leasing", "Oxbow Nonprofit",
]
INDUSTRY = {
    "Payroll": "Payroll SaaS", "Scheduling": "Scheduling SaaS", "Analytics": "Analytics SaaS", "Billing": "Billing SaaS",
    "Field Service": "Field service SaaS", "Legal": "Legal tech", "Logistics": "Logistics SaaS", "HR": "HR SaaS",
    "Learning": "Edtech", "Docs": "Document SaaS", "Procurement": "Procurement SaaS", "Insights": "Analytics SaaS",
    "Claims": "Insurtech", "Events": "Events SaaS", "Clinics": "Healthtech", "Payments": "Fintech", "Ticketing": "Events SaaS",
    "Property": "Proptech", "Recruiting": "HR SaaS", "Fleet": "Logistics SaaS", "Surveys": "Research SaaS",
    "Ledger": "Fintech", "Dispatch": "Logistics SaaS", "Grants": "Nonprofit SaaS", "Energy": "Energy SaaS",
    "Retail": "Retail SaaS", "Benefits": "HR SaaS", "Tutoring": "Edtech", "Audit": "Compliance SaaS", "Contracts": "Legal tech",
    "Travel": "Travel SaaS", "Studio": "Creative SaaS", "Telehealth": "Healthtech", "CRM": "Sales SaaS",
    "Marketplace": "Marketplace", "Insurance": "Insurtech", "Forms": "Productivity SaaS", "Inventory": "Retail SaaS",
    "Expenses": "Fintech", "Identity": "Identity verification SaaS", "Booking": "Booking SaaS", "Signals": "Analytics SaaS",
    "Compliance": "Compliance SaaS", "Media": "Media SaaS", "Freight": "Logistics SaaS", "Wealth": "Fintech",
    "Construction": "Construction SaaS", "Pharmacy": "Healthtech", "Leasing": "Fintech", "Nonprofit": "Nonprofit SaaS",
}
KNOWN_SIZES = {"Larkspur Payroll": 520, "Tidewater Scheduling": 410, "Copperline Analytics": 260}  # match the deal notes


def industry_of(name: str) -> str:
    return next(v for k, v in sorted(INDUSTRY.items(), key=lambda kv: -len(kv[0])) if name.endswith(k))
OWNERS = ["Sara Lind", "Omar Haddad", "Priya Nair", "Tom Becker"]
UPSELL = [
    "Opening an EU region in Q1 and asked whether Azure is covered.",
    "Headcount up about 40% since renewal; a new head of security starts next month.",
    "Asked about ISO 27001 after passing SOC 2 with us.",
    "A second product team is moving to Google Cloud.",
    "Requested pricing for six more cloud accounts.",
]
# One note per account, never repeated, so the CRM reads like a real one.
NOTES = {
    "Prospecting": [
        "Downloaded the SOC 2 checklist.", "Met at a CTO dinner; asked for a short demo.", "Replied to the posture benchmark email.",
        "Inbound from the pricing page.", "Referred by a customer's VP Engineering.", "Watched the cloud misconfiguration webinar to the end.",
        "Asked whether we cover AWS and Google Cloud in one view.", "Booked an intro call, then moved it twice.",
        "Head of platform connected after our AWS Summit talk.", "Trial sign-up from a staff engineer; no admin invited yet.",
        "Asked for a sample SOC 2 evidence report.", "Security lead left; new owner not named yet.",
        "Visited the Comply page three times this month.", "Has a large customer security questionnaire due soon.",
        "Uses an open-source scanner today; wants better alert triage.", "Introduced by their cloud consultancy.",
    ],
    "Proposal": [
        "Proposal sent for the Bundle with a 14-day pilot.", "Waiting on their security team to review the proposal.",
        "Proposal sent; champion is the VP Engineering.", "Asked for a revised quote on annual billing.",
        "Proposal covers Posture only; Comply deferred to next year.", "Pilot fixed 40 findings; proposal is with finance.",
        "Champion asked for a one-page ROI summary for the CFO.", "Comparing our proposal with Bastion Cloud.",
        "Proposal for 12 cloud accounts; may start with 6.", "Asked for a reference from another fintech customer.",
        "Proposal sent after the architecture review.", "Legal wants the DPA before they read the proposal.",
    ],
    "Negotiation": [
        "Legal reviewing the MSA.", "Discussing a two-year term for a discount.",
        "Procurement asked for our SOC 2 report and insurance certificate.", "Sent back redlines on the liability cap.",
        "Asked to pay in quarterly invoices.", "CTO approved final pricing; procurement next.",
        "Comparing our terms with Ledgerline's offer.", "Security questionnaire returned; legal is next.",
    ],
    "Customer": [
        "Healthy usage; weekly digest opened by the CTO.", "Renewal in five months.", "Uses Posture daily; Comply set up last quarter.",
        "Fixed 120 findings in the first month.", "Passed SOC 2 Type II with our evidence exports.",
        "Good quarterly review; asked about the API.", "New admin onboarded last month after a job change.",
        "Renewed in spring; usage steady.", "Two support tickets this quarter, both closed the same day.",
        "Uses Slack alerts for critical findings only.", "Champion spoke at our customer webinar.",
        "Asked for Okta SSO; it shipped for them in October.", "Usage dipped after a reorg; worth a check-in.",
        "Grew from 4 to 9 cloud accounts last year.",
    ],
}
# Why each stalled deal stalled: five proposals, then three negotiations.
STALLED = [
    "Proposal sent; no reply to the last two follow-ups.", "Champion on leave until next month; nobody else has replied.",
    "Budget review pushed the decision to next quarter.", "Went quiet after the pricing call.",
    "Waiting for their new head of security to start before deciding.",
    "Legal has had the MSA for five weeks with no redlines.", "Agreed a two-year term, then procurement stopped replying.",
    "Asked us to check back after their board meeting.",
]


def main() -> None:
    rnd = random.Random(20261121)
    stages = ["Customer"] * 14 + ["Negotiation"] * 8 + ["Proposal"] * 12 + ["Prospecting"] * 16
    rows = []
    notes = {stage: rnd.sample(pool, len(pool)) for stage, pool in NOTES.items()}
    for i, (name, stage) in enumerate(zip(NAMES, stages), start=1):
        value_ranges = {"Prospecting": (15, 45), "Proposal": (20, 60), "Negotiation": (25, 80), "Customer": (18, 70)}
        lo, hi = value_ranges[stage]
        rows.append({
            "id": f"A{i:03d}", "company": name, "industry": industry_of(name), "size": KNOWN_SIZES.get(name) or rnd.randrange(120, 1800, 10),
            "stage": stage, "deal_value": rnd.randrange(lo, hi) * 1000, "owner": OWNERS[i % 4],
            "last_contact_days_ago": rnd.randint(1, 25), "stage_changed_days_ago": 0,
            "notes": notes[stage].pop(), "expansion_signal": "",
        })
    for r in rows:
        r["stage_changed_days_ago"] = r["last_contact_days_ago"] + rnd.randint(2, 6) if r["stage"] != "Customer" \
            else rnd.randint(60, 400)
        if r["stage"] in ("Proposal", "Negotiation"):
            r["stage_changed_days_ago"] = min(r["stage_changed_days_ago"], 28)

    by_stage = {s: [r for r in rows if r["stage"] == s] for s in ("Prospecting", "Proposal", "Negotiation", "Customer")}
    # The three won deals in the notes are customers.
    for name in ("Larkspur Payroll", "Tidewater Scheduling", "Copperline Analytics"):
        assert next(r for r in rows if r["company"] == name)["stage"] == "Customer"

    # 8 stalled: open deals with no stage change for 32 to 58 days, but recent enough contact.
    for r, why in zip(by_stage["Proposal"][:5] + by_stage["Negotiation"][:3], STALLED):
        r["stage_changed_days_ago"] = rnd.randint(32, 58)
        r["last_contact_days_ago"] = rnd.randint(6, 24)
        r["notes"] = why
    # 5 likely upsells among customers.
    customers = by_stage["Customer"]
    for r, signal in zip(customers[3:8], UPSELL):
        r["expansion_signal"] = signal
    # 6 untouched for over 30 days: 4 prospects and 2 customers without an expansion signal.
    for r in by_stage["Prospecting"][-4:] + customers[-2:]:
        r["last_contact_days_ago"] = rnd.randint(34, 72)
        if r["stage"] == "Prospecting":
            r["stage_changed_days_ago"] = r["last_contact_days_ago"] + rnd.randint(3, 20)

    stalled = [r for r in rows if r["stage"] in ("Proposal", "Negotiation") and r["stage_changed_days_ago"] >= 30]
    untouched = [r for r in rows if r["last_contact_days_ago"] > 30]
    assert len(rows) == 50 and len(stalled) == 8 and len(untouched) == 6, (len(stalled), len(untouched))
    assert not {r["id"] for r in stalled} & {r["id"] for r in untouched}
    assert len({r["notes"] for r in rows}) == len(rows), "every account has its own note"

    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} accounts, {len(stalled)} stalled, {len(untouched)} untouched)")


if __name__ == "__main__":
    main()
