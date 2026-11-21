"""Generate the mock CRM (50 fictional accounts + activity history) as two CSV files.

    python -m scripts.generate_crm        (run from backend/)

Dates are stored as "days ago" offsets so the seed always lands relative to today:
the 8 stalled deals stay stalled and the 6 untouched accounts stay 30+ days untouched,
whenever the demo is deployed. All companies, people and domains are invented
(.example is a reserved domain, so nothing here can reach a real inbox).
"""

from __future__ import annotations

import csv
import random
import re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
OWNERS = ["Jordan Reyes", "Priya Natarajan", "Sam Okafor", "Lena Fischer"]
STAGE_LIMIT = {"Prospect": 30, "Discovery": 30, "Proposal": 21}

FIRST = ["Maya", "Tomas", "Aisha", "Daniel", "Hana", "Lucas", "Ingrid", "Omar", "Chloe", "Ravi", "Sofia", "Marcus",
         "Elena", "Kofi", "Grace", "Mateo", "Noor", "Felix", "Yara", "Leo", "Amara", "Jonas", "Mei", "Isaac", "Zara",
         "Pedro", "Freya", "Arjun", "Nadia", "Hugo", "Lina", "Ezra", "Saoirse", "Kenji", "Ama", "Tobias", "Leila",
         "Rafael", "Ines", "Callum", "Priyanka", "Mikael", "Esme", "Dario", "Halima", "Owen", "Valentina", "Sami",
         "Juno", "Bastian"]
LAST = ["Lindqvist", "Okoro", "Brennan", "Castillo", "Yamada", "Petrov", "Haddad", "Moreau", "Kowalski", "Mensah",
        "Duarte", "Nakamura", "Fitzgerald", "Varga", "Ndiaye", "Sorensen", "Iqbal", "Albrecht", "Quinn", "Takahashi",
        "Romero", "Ekström", "Achebe", "Laurent", "Novak", "Bhatt", "Oduya", "Hartmann", "Silva", "Kerr", "Delacroix",
        "Mwangi", "Lindgren", "Aziz", "Costa", "Byrne", "Sato", "Kaur", "Vance", "Olsen", "Mbeki", "Ferreira",
        "Holm", "Rahman", "Gallo", "Tanaka", "Ward", "Ozturk", "Nilsen", "Reyes-Ortiz"]
TITLES = ["Head of Security", "VP Engineering", "CTO", "Security Lead", "Director of Platform", "Compliance Manager",
          "CISO", "Head of IT"]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


# (company, industry, category, size, region, cloud)
COMPANIES = [
    ("Brightloom Analytics", "Product analytics SaaS", "data_ai", 180, "North America", "AWS"),
    ("Cedarline Health", "Patient intake software", "healthtech", 240, "North America", "Azure"),
    ("Quillstack", "Document automation SaaS", "b2b_saas", 95, "UK & Ireland", "AWS"),
    ("Ferncrest Payroll", "Payroll software", "fintech", 410, "Europe", "Azure"),
    ("Tidemark Logistics", "Freight visibility platform", "vertical_software", 520, "North America", "AWS"),
    ("Orchardly", "Farm management SaaS", "vertical_software", 70, "ANZ", "GCP"),
    ("Ploverly HR", "HR and onboarding software", "b2b_saas", 150, "Europe", "AWS"),
    ("Saltmarsh Data", "Data pipeline platform", "data_ai", 310, "North America", "GCP"),
    ("Bramblewick", "E-signature and contract SaaS", "b2b_saas", 130, "UK & Ireland", "AWS"),
    ("Copperwren Billing", "Subscription billing platform", "fintech", 260, "North America", "AWS"),
    ("Duneglass", "Retail analytics SaaS", "data_ai", 85, "Europe", "GCP"),
    ("Emberlane Learning", "Corporate learning platform", "b2b_saas", 205, "North America", "AWS"),
    ("Foxglove Clinics", "Clinic scheduling software", "healthtech", 120, "UK & Ireland", "Azure"),
    ("Glimmerpath", "Customer success platform", "b2b_saas", 340, "North America", "AWS"),
    ("Harborline Insurance Cloud", "Insurance policy admin SaaS", "fintech", 680, "North America", "Hybrid"),
    ("Inkwell Legal", "Legal practice software", "vertical_software", 160, "UK & Ireland", "Azure"),
    ("Jasperforge", "CI/CD tooling", "devtools", 110, "Europe", "AWS"),
    ("Kitewing Travel", "Corporate travel platform", "b2b_saas", 450, "Europe", "AWS"),
    ("Larkspur Retail Cloud", "Point-of-sale SaaS", "vertical_software", 390, "ANZ", "AWS"),
    ("Meadowgate Property", "Property management software", "vertical_software", 220, "North America", "Azure"),
    ("Nettlefield", "Observability platform", "devtools", 270, "North America", "GCP"),
    ("Oakhaven Payments", "Payments API", "fintech", 190, "UK & Ireland", "AWS"),
    ("Pebblestream", "Video collaboration SaaS", "b2b_saas", 140, "North America", "AWS"),
    ("Quarrylight", "Construction project software", "vertical_software", 300, "North America", "Azure"),
    ("Riverbend Telehealth", "Telehealth platform", "healthtech", 560, "North America", "AWS"),
    ("Sablecrest", "Expense management SaaS", "fintech", 230, "Europe", "AWS"),
    ("Thistledown Media", "Digital publishing platform", "b2b_saas", 75, "UK & Ireland", "GCP"),
    ("Umberpoint", "Field service software", "vertical_software", 480, "North America", "Azure"),
    ("Vellumworks", "Knowledge base SaaS", "b2b_saas", 60, "Europe", "AWS"),
    ("Willowmere Finance", "Lending platform", "fintech", 820, "North America", "Hybrid"),
    ("Yarrowfield", "Clinical trials software", "healthtech", 350, "Europe", "AWS"),
    ("Zephyrine", "API gateway platform", "devtools", 165, "North America", "AWS"),
    ("Ashgrove Fleet", "Fleet telematics SaaS", "vertical_software", 610, "ANZ", "AWS"),
    ("Birchwell Labs", "Lab data platform", "healthtech", 105, "North America", "GCP"),
    ("Cobaltine", "Machine learning platform", "data_ai", 145, "North America", "GCP"),
    ("Driftwood CRM", "CRM for small businesses", "b2b_saas", 280, "Europe", "AWS"),
    ("Elmstead Benefits", "Employee benefits platform", "fintech", 370, "North America", "AWS"),
    ("Mapleforge Games", "Game backend services", "devtools", 90, "APAC", "AWS"),
    ("Gorsefield Energy", "Energy trading software", "enterprise_software", 1900, "Europe", "On-prem"),
    ("Heathermoor", "Procurement software", "b2b_saas", 420, "UK & Ireland", "Azure"),
    ("Islecraft", "Hospitality booking SaaS", "vertical_software", 135, "APAC", "AWS"),
    ("Juniperline", "IT services and consulting", "services", 900, "APAC", "Hybrid"),
    ("Kelpwater", "Water utility analytics", "data_ai", 115, "ANZ", "Azure"),
    ("Lanternfish AI", "Conversational AI platform", "data_ai", 210, "North America", "GCP"),
    ("Mossbridge", "Supply chain planning SaaS", "b2b_saas", 640, "Europe", "AWS"),
    ("Nimbuslane", "Managed hosting provider", "services", 55, "North America", "On-prem"),
    ("Oxbow Robotics", "Robotics fleet software", "vertical_software", 38, "North America", "AWS"),
    ("Primrose Ledger", "Accounting software", "fintech", 290, "UK & Ireland", "AWS"),
    ("Quietwater Security", "Email security vendor", "security_vendor", 160, "North America", "AWS"),
    ("Rookwood Commerce", "E-commerce platform", "b2b_saas", 2600, "North America", "AWS"),
]

# Hand-written accounts that carry the story: 8 stalled, 6 untouched for 30+ days, 5 upsells.
# company -> overrides (days_in_stage, last_contact_days_ago, notes, last activity summary)
STALLED = {
    "Tidemark Logistics": dict(stage="Proposal", days_in_stage=49, last=6, deal=72000,
        notes="Proposal for Growth (16 AWS accounts). Champion keeps saying legal review is 'next week'.",
        last_activity="Follow-up call: legal still reviewing the MSA, no date given."),
    "Glimmerpath": dict(stage="Proposal", days_in_stage=33, last=9, deal=48000,
        notes="Pricing pushback. Wants Growth features at Starter price.",
        last_activity="Email: asked whether we can discount Growth by 30%."),
    "Harborline Insurance Cloud": dict(stage="Proposal", days_in_stage=72, last=14, deal=96000,
        notes="Enterprise proposal. New CFO froze new spend pending budget review.",
        last_activity="Call: budget review moved to next quarter."),
    "Kitewing Travel": dict(stage="Proposal", days_in_stage=27, last=4, deal=52000,
        notes="Security review questionnaire returned by us 3 weeks ago, no feedback since.",
        last_activity="Email: sent completed security questionnaire again on request."),
    "Saltmarsh Data": dict(stage="Discovery", days_in_stage=44, last=11, deal=38000,
        notes="Two discovery calls, but no technical owner assigned on their side.",
        last_activity="Call: VP Engineering wants a technical deep-dive but has not picked a date."),
    "Emberlane Learning": dict(stage="Discovery", days_in_stage=36, last=18, deal=30000,
        notes="SOC 2 Type I done with a consultant. Unsure whether to automate Type II.",
        last_activity="Email: asked for a customer reference in education."),
    "Meadowgate Property": dict(stage="Discovery", days_in_stage=58, last=7, deal=26000,
        notes="Interested, but their Azure migration is half done.",
        last_activity="Meeting: they want to wait until the Azure migration finishes."),
    "Pebblestream": dict(stage="Prospect", days_in_stage=41, last=12, deal=24000,
        notes="Replied once to cold email, attended webinar, no meeting booked.",
        last_activity="Webinar attended: 'SOC 2 Type II without the spreadsheet'."),
}
UNTOUCHED = {
    "Bramblewick": dict(stage="Prospect", days_in_stage=64, last=64, deal=22000,
        notes="Inbound demo request in the summer. Never followed up after first call.",
        last_activity="Intro call: wants ISO 27001 for a UK public-sector tender."),
    "Thistledown Media": dict(stage="Prospect", days_in_stage=38, last=38, deal=18000,
        notes="Met at a conference. Asked for pricing.",
        last_activity="Email: sent pricing sheet."),
    "Yarrowfield": dict(stage="Discovery", days_in_stage=45, last=45, deal=64000,
        notes="Clinical data, strict auditors. Champion is the Compliance Manager.",
        last_activity="Discovery call: auditors flagged evidence gaps in their last ISO surveillance audit."),
    "Primrose Ledger": dict(stage="Proposal", days_in_stage=52, last=52, deal=46000,
        notes="Proposal sent, then the champion went on parental leave.",
        last_activity="Email: proposal v1 sent (Growth, 10 accounts)."),
    "Sablecrest": dict(stage="Customer", days_in_stage=410, last=41, arr=48000, plan="Growth", used=9, limit=20, renewal=45,
        notes="Customer since last year. Renewal coming up. Quiet account.",
        last_activity="Support ticket closed: SSO login issue."),
    "Driftwood CRM": dict(stage="Customer", days_in_stage=260, last=70, arr=18000, plan="Starter", used=1, limit=3, renewal=150,
        notes="Low usage. Only one AWS account connected.",
        last_activity="Onboarding call: connected first AWS account."),
}
UPSELL = {
    "Oakhaven Payments": dict(days_in_stage=380, last=8, arr=48000, plan="Growth", used=18, limit=20, renewal=74,
        notes="Heavy user. Adding a second payments product line.",
        last_activity="QBR: 18 of 20 cloud accounts connected; asked about Enterprise SSO."),
    "Riverbend Telehealth": dict(days_in_stage=520, last=5, arr=48000, plan="Growth", used=17, limit=20, renewal=190,
        notes="Opening a new region in Canada next quarter; needs more accounts.",
        last_activity="Email: asked how pricing works above 20 accounts."),
    "Islecraft": dict(days_in_stage=200, last=15, arr=18000, plan="Starter", used=3, limit=3, renewal=120,
        notes="Starter plan is full. Expanding to Singapore.",
        last_activity="Usage alert: all 3 Starter accounts in use."),
    "Ferncrest Payroll": dict(days_in_stage=610, last=12, arr=18000, plan="Starter", used=2, limit=3, renewal=95,
        notes="Needs ISO 27001 evidence for an EU bank customer; Starter covers SOC 2 only.",
        last_activity="Call: asked whether ISO 27001 mapping is included."),
    "Copperwren Billing": dict(days_in_stage=330, last=19, arr=48000, plan="Growth", used=13, limit=20, renewal=60,
        notes="Acquired a smaller billing startup; integrating their AWS org.",
        last_activity="Email: CTO mentioned the acquisition closes this month."),
}

HEALTHY_CUSTOMER_NOTES = [
    "Happy with alerts. Uses weekly report in their security standup.",
    "Uses questionnaire answers for most enterprise deals.",
    "Small security team, relies on daily digest.",
    "Passed SOC 2 Type II with our evidence last quarter.",
    "Steady usage. Champion is the Head of Security.",
]
OPEN_NOTES = {
    "Prospect": [
        "Replied to cold email. Intro call booked.",
        "Downloaded SOC 2 checklist. Opened two emails.",
        "Referral from an existing customer.",
        "Inbound: pricing page visit and demo request.",
    ],
    "Discovery": [
        "Discovery call done. Multi-account AWS, audit due next quarter.",
        "Evaluating us against ComplyFlow.",
        "Security lead joined 2 months ago and is reviewing tools.",
        "Wants evidence for SOC 2 and HIPAA.",
    ],
    "Proposal": [
        "Proposal sent for Growth. Waiting on security review sign-off.",
        "Verbal yes from champion; procurement started.",
        "Comparing our Growth plan with Bastion Cloud's quote.",
    ],
}
FIRST_TOUCH = {
    "Prospect": "Cold email sent with SOC 2 Type II checklist.",
    "Discovery": "Intro call: mapped their cloud accounts and audit dates.",
    "Proposal": "Proposal sent (Growth plan).",
}


def build() -> tuple[list[dict], list[dict]]:
    rng = random.Random(42)
    accounts: list[dict] = []
    activity: list[dict] = []
    special = {**STALLED, **UNTOUCHED, **UPSELL}
    stage_quota = {"Prospect": 14, "Discovery": 13, "Proposal": 11, "Customer": 12}
    for stage in ("Prospect", "Discovery", "Proposal", "Customer"):
        stage_quota[stage] -= sum(1 for v in {**STALLED, **UNTOUCHED}.values() if v["stage"] == stage)
    stage_quota["Customer"] -= len(UPSELL)

    free_stages: list[str] = []
    for stage, n in stage_quota.items():
        free_stages += [stage] * n
    rng.shuffle(free_stages)

    for i, (company, industry, category, size, region, cloud) in enumerate(COMPANIES):
        domain = f"{slug(company)}.example"
        first, last = FIRST[i % len(FIRST)], LAST[(i * 7) % len(LAST)]  # 50 distinct first names
        row = dict(
            company=company, domain=domain, industry=industry, category=category, size=size, region=region,
            cloud_provider=cloud, owner=OWNERS[i % len(OWNERS)], contact_name=f"{first} {last}",
            contact_title=TITLES[i % len(TITLES)],
            contact_email=f"{first.lower()}.{slug(last)}@{domain}",
            deal_value="", plan="", arr="", cloud_accounts_used="", cloud_accounts_limit="", renewal_in_days="",
        )
        if company in special:
            spec = special[company]
            stage = spec.get("stage", "Customer")
            row.update(stage=stage, days_in_stage=spec["days_in_stage"], last_contact_days_ago=spec["last"],
                       notes=spec["notes"])
            if stage == "Customer":
                row.update(plan=spec["plan"], arr=spec["arr"], cloud_accounts_used=spec["used"],
                           cloud_accounts_limit=spec["limit"], renewal_in_days=spec["renewal"])
            else:
                row.update(deal_value=spec["deal"])
            last_summary = spec["last_activity"]
        else:
            stage = free_stages.pop()
            row["stage"] = stage
            if stage == "Customer":
                plan = rng.choice(["Starter", "Growth", "Growth", "Enterprise"])
                limit = {"Starter": 3, "Growth": 20, "Enterprise": 100}[plan]
                used = max(1, int(limit * rng.uniform(0.2, 0.55)))
                arr = {"Starter": 18000, "Growth": 48000, "Enterprise": rng.choice([60000, 72000, 90000])}[plan]
                row.update(days_in_stage=rng.randint(90, 700), last_contact_days_ago=rng.randint(2, 24),
                           plan=plan, arr=arr, cloud_accounts_used=used, cloud_accounts_limit=limit,
                           renewal_in_days=rng.randint(130, 330), notes=rng.choice(HEALTHY_CUSTOMER_NOTES))
                last_summary = rng.choice([
                    "Monthly check-in: no open issues.",
                    "Shared Q3 posture report with their security lead.",
                    "Support ticket closed: added a new GCP project.",
                ])
            else:
                limit_days = STAGE_LIMIT[stage]
                days = rng.randint(3, limit_days - 4)
                row.update(days_in_stage=days, last_contact_days_ago=rng.randint(1, min(days, 20)),
                           deal_value=rng.choice([18000, 24000, 30000, 36000, 48000, 52000, 60000, 72000]),
                           notes=rng.choice(OPEN_NOTES[stage]))
                last_summary = {
                    "Prospect": "Email: shared a two-minute product video.",
                    "Discovery": "Call: reviewed their audit timeline and cloud accounts.",
                    "Proposal": "Email: answered pricing questions on the proposal.",
                }[stage]
        accounts.append(row)

        # Activity history: first touch, stage change, a middle touch, and the latest touch.
        last_days = int(row["last_contact_days_ago"])
        stage_days = int(row["days_in_stage"])
        history = []
        start = stage_days + rng.randint(10, 40)
        history.append((start, "email", "outbound", FIRST_TOUCH.get(stage, "Proposal signed after a two-week pilot.")))
        history.append((stage_days, "note", "internal", f"Stage moved to {stage}."))
        if stage_days - last_days > 6:
            mid = rng.randint(last_days + 3, stage_days - 2)
            history.append((mid, rng.choice(["call", "email", "meeting"]), rng.choice(["outbound", "inbound"]),
                            rng.choice(["Shared a customer story from the same industry.",
                                        "Answered questions about read-only access.",
                                        "Sent a sample SOC 2 evidence report."])))
        kind = "call" if last_summary.lower().startswith(("call", "follow-up call", "discovery", "intro")) else (
            "meeting" if last_summary.lower().startswith(("meeting", "qbr", "webinar", "onboarding")) else "email")
        direction = "inbound" if ("asked" in last_summary.lower() or last_summary.startswith("Usage alert")) else "outbound"
        history.append((last_days, kind, direction, last_summary))
        for days_ago, kind, direction, summary in history:
            activity.append(dict(company=company, days_ago=days_ago, kind=kind, direction=direction, summary=summary))
    return accounts, activity


def main() -> None:
    accounts, activity = build()
    DATA.mkdir(exist_ok=True)
    with open(DATA / "crm_accounts.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(accounts[0].keys()))
        writer.writeheader()
        writer.writerows(accounts)
    with open(DATA / "crm_activity.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(activity[0].keys()))
        writer.writeheader()
        writer.writerows(activity)
    print(f"wrote {len(accounts)} accounts and {len(activity)} activity rows to {DATA}")


if __name__ == "__main__":
    main()
