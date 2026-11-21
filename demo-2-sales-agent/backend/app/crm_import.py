"""Replace the sample CRM with a real export (HubSpot, Salesforce, Pipedrive or any CSV with the usual columns).

Real dates are kept exactly as exported: the daily roll-forward used for the sample data is switched off.
Every skipped line is reported with its reason.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from sqlalchemy import delete
from sqlalchemy.engine import Engine

from .db import accounts, drafts, log_activity, meta, tx

MAX_BYTES = 2_000_000
MAX_ROWS = 2_000

HEADERS = {
    "company": ["company", "company name", "account", "account name", "name", "organization", "organisation"],
    "stage": ["stage", "deal stage", "lifecycle stage", "pipeline stage", "status"],
    "last_contact": ["last contact", "last_contact", "last contacted", "last activity date", "last activity", "last engagement date"],
    "stage_changed": ["stage changed", "stage_changed", "date entered stage", "stage date", "last stage change date"],
    "deal_value": ["deal value", "deal_value", "amount", "deal amount", "arr", "annual revenue", "opportunity amount"],
    "owner": ["owner", "account owner", "deal owner", "contact owner", "company owner"],
    "industry": ["industry"],
    "size": ["size", "employees", "number of employees", "company size", "headcount"],
    "notes": ["notes", "description", "next step", "note"],
    "expansion_signal": ["expansion signal", "expansion_signal", "upsell signal", "expansion"],
}
STAGES = {
    "Prospecting": ["prospect", "prospecting", "lead", "qualified", "qualification", "discovery", "appointment scheduled",
                    "new", "contacted", "mql", "sql", "opportunity"],
    "Proposal": ["proposal", "proposal sent", "presentation scheduled", "decision maker bought in", "proposal price quote",
                 "value proposition", "id decision makers", "perception analysis"],
    "Negotiation": ["negotiation", "negotiation review", "contract sent", "legal", "commit", "closing"],
    "Customer": ["customer", "closed won", "won", "active", "active customer", "evangelist"],
}
DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%b %d, %Y", "%d %b %Y")


class CrmImportError(ValueError):
    pass


def _norm(s: str) -> str:
    s = s.replace("﻿", "").strip().lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", re.sub(r"[()\[\].$:]", " ", s)).strip()


def _day(raw: str) -> date:
    s = (raw or "").strip()
    if "T" in s:
        s = s.split("T")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise CrmImportError(f"date isn't recognised: {raw!r} (use YYYY-MM-DD)")


def _stage(raw: str) -> str:
    n = _norm(raw)
    if n in ("closed lost", "lost", "disqualified", "churned"):
        raise CrmImportError(f"stage {raw!r} is closed, so it isn't part of the pipeline")
    for stage, options in STAGES.items():
        if n in options:
            return stage
    raise CrmImportError(f"stage {raw!r} doesn't map to Prospecting, Proposal, Negotiation or Customer")


def _int(raw: str, field: str, default: int) -> int:
    s = re.sub(r"[,$€£\s]", "", raw or "")
    if not s:
        return default
    try:
        return max(0, int(round(float(s))))
    except ValueError:
        raise CrmImportError(f"{field} isn't a number: {raw!r}") from None


def parse(text: str, today: date) -> tuple[list[dict], dict]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise CrmImportError("The file is over 2 MB.")
    reader = csv.reader(io.StringIO(text))
    try:
        header = [_norm(h) for h in next(reader)]
    except StopIteration:
        raise CrmImportError("The file is empty.") from None
    col = {key: next((i for i, h in enumerate(header) if h in opts), None) for key, opts in HEADERS.items()}
    missing = [k for k in ("company", "stage", "last_contact") if col[k] is None]
    if missing:
        raise CrmImportError(f"Missing columns: {', '.join(missing)}. The minimum is company, stage and last contact date.")

    out, skipped, seen, read = [], [], set(), 0
    for line_no, rec in enumerate(reader, start=2):
        if not any(c.strip() for c in rec):
            continue
        read += 1
        if read > MAX_ROWS:
            raise CrmImportError(f"More than {MAX_ROWS:,} accounts. Export one pipeline or region at a time.")
        get = lambda k: rec[col[k]].strip() if col[k] is not None and col[k] < len(rec) else ""  # noqa: E731
        try:
            company = get("company")[:200]
            if not company:
                raise CrmImportError("company name is empty")
            if company.lower() in seen:
                raise CrmImportError(f"{company!r} appears twice; the first line was kept")
            stage = _stage(get("stage"))
            last = _day(get("last_contact"))
            changed = _day(get("stage_changed")) if get("stage_changed") else last
            if last > today or changed > today:
                raise CrmImportError("a date is in the future")
        except CrmImportError as exc:
            skipped.append({"line": line_no, "reason": str(exc)})
            continue
        seen.add(company.lower())
        out.append({"id": f"A{len(out) + 1:03d}", "company": company, "industry": get("industry")[:120] or "Not stated",
                    "size": _int(get("size"), "size", 0), "stage": stage, "deal_value": _int(get("deal_value"), "deal value", 0),
                    "owner": get("owner")[:80] or "Unassigned", "last_contact": last, "stage_changed": changed,
                    "notes": get("notes")[:1000], "expansion_signal": get("expansion_signal")[:400] or None})
    if not out:
        raise CrmImportError("No usable accounts. " + (f"Line {skipped[0]['line']}: {skipped[0]['reason']}." if skipped else ""))
    return out, {"rows_read": read, "accounts": len(out), "skipped_count": len(skipped), "skipped": skipped[:50]}


def replace_crm(engine: Engine, rows: list[dict], report: dict) -> dict:
    """Swap the sample accounts for the imported ones. Leads (web research) are kept; CRM follow-ups are cleared."""
    with tx(engine) as conn:
        conn.execute(delete(drafts).where(drafts.c.account_id.is_not(None)))
        conn.execute(delete(accounts))
        conn.execute(accounts.insert(), rows)
        conn.execute(delete(meta).where(meta.c.key == "crm_anchor"))  # real dates never roll forward
        conn.execute(delete(meta).where(meta.c.key == "crm_source"))
        conn.execute(meta.insert().values(key="crm_source", value="import"))
        log_activity(conn, "crm_import", "success", f"Imported {len(rows)} CRM accounts; {report['skipped_count']} lines skipped")
    return report

