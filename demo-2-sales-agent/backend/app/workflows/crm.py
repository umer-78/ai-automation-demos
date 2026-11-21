"""Mock CRM: CSV seed, read helpers and the deterministic account analysis."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine

from app.agent.scoring import analyze_account
from app.db import accounts, activity, drafts, row_to_dict, rows_to_dicts, utcnow

FLAG_ORDER = {"stalled": 0, "no_contact": 1, "upsell": 2}


def _num(value: str, cast=float):
    value = (value or "").strip()
    return cast(value) if value else None


def load_csv(engine: Engine, accounts_csv: str | Path, activity_csv: str | Path, now: datetime | None = None) -> dict[str, int]:
    """Load the mock CRM. Dates in the CSV are 'days ago' offsets, resolved against `now`."""
    now = now or utcnow()
    with open(accounts_csv, newline="", encoding="utf-8") as fh:
        account_rows = list(csv.DictReader(fh))
    with open(activity_csv, newline="", encoding="utf-8") as fh:
        activity_rows = list(csv.DictReader(fh))
    ids: dict[str, int] = {}
    with engine.begin() as conn:
        for r in account_rows:
            renewal = _num(r.get("renewal_in_days"), int)
            row = {
                "company": r["company"],
                "domain": r["domain"],
                "industry": r["industry"],
                "category": r["category"],
                "size": _num(r["size"], int),
                "region": r["region"],
                "cloud_provider": r["cloud_provider"],
                "stage": r["stage"],
                "deal_value": _num(r.get("deal_value")),
                "arr": _num(r.get("arr")),
                "plan": r.get("plan") or None,
                "cloud_accounts_used": _num(r.get("cloud_accounts_used"), int),
                "cloud_accounts_limit": _num(r.get("cloud_accounts_limit"), int),
                "renewal_date": (now + timedelta(days=renewal)).date() if renewal is not None else None,
                "stage_entered_at": now - timedelta(days=int(r["days_in_stage"]), hours=2),
                "last_contact": now - timedelta(days=int(r["last_contact_days_ago"]), hours=1),
                "owner": r["owner"],
                "contact_name": r["contact_name"],
                "contact_title": r["contact_title"],
                "contact_email": r["contact_email"],
                "notes": r["notes"],
                "flags": [],
                "flag_reasons": {},
                "created_at": now,
                "updated_at": now,
            }
            result = conn.execute(accounts.insert().values(**row))
            ids[r["company"]] = result.inserted_primary_key[0]
        rows = []
        for a in activity_rows:
            if a["company"] not in ids:
                continue
            days = int(a["days_ago"])
            rows.append(
                {
                    "account_id": ids[a["company"]],
                    "kind": a["kind"],
                    "direction": a["direction"],
                    "summary": a["summary"],
                    "occurred_at": now - timedelta(days=days, hours=1),
                    "created_at": now,
                }
            )
        if rows:
            conn.execute(activity.insert(), rows)
    return {"accounts": len(ids), "activity": len(rows)}


def last_activity_map(engine: Engine) -> dict[int, dict[str, Any]]:
    latest = (
        select(activity.c.account_id, func.max(activity.c.occurred_at).label("ts"))
        .where(activity.c.direction != "internal")
        .group_by(activity.c.account_id)
        .subquery()
    )
    q = select(activity).join(
        latest, (activity.c.account_id == latest.c.account_id) & (activity.c.occurred_at == latest.c.ts)
    )
    with engine.connect() as conn:
        return {r.account_id: row_to_dict(r) for r in conn.execute(q)}


def analyze_all(engine: Engine, icp: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Flag stalled / no-contact / upsell accounts and score all of them. Writes results to the CRM."""
    now = now or utcnow()
    last = last_activity_map(engine)
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(accounts))]
    results = []
    with engine.begin() as conn:
        for acc in rows:
            analysis = analyze_account(acc, icp, now, (last.get(acc["id"]) or {}).get("summary", ""))
            conn.execute(
                update(accounts)
                .where(accounts.c.id == acc["id"])
                .values(
                    score=analysis["score"],
                    score_reason=analysis["reason"],
                    score_parts=analysis["parts"],
                    flags=analysis["flags"],
                    flag_reasons=analysis["flag_reasons"],
                    analyzed_at=now,
                )
            )
            results.append((acc, analysis))
    flagged = [
        {
            "account_id": acc["id"],
            "company": acc["company"],
            "stage": acc["stage"],
            "owner": acc["owner"],
            "score": a["score"],
            "flags": a["flags"],
            "why": " ".join(a["flag_reasons"].values()),
            "last_activity": (last.get(acc["id"]) or {}).get("summary"),
        }
        for acc, a in results
        if a["flags"]
    ]
    flagged.sort(key=lambda f: (-f["score"], f["company"]))
    counts = {k: sum(1 for f in flagged if k in f["flags"]) for k in FLAG_ORDER}
    return {"analyzed": len(results), "flagged": flagged, "counts": counts}


def list_accounts(engine: Engine, flag: str | None = None, stage: str | None = None) -> list[dict[str, Any]]:
    q = select(accounts).order_by(accounts.c.score.desc().nulls_last(), accounts.c.company)
    if stage:
        q = q.where(accounts.c.stage == stage)
    with engine.connect() as conn:
        rows = rows_to_dicts(conn.execute(q))
    if flag:
        rows = [r for r in rows if flag in (r.get("flags") or [])]
    return rows


def account_detail(engine: Engine, account_id: int) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(select(accounts).where(accounts.c.id == account_id)).first()
        if not row:
            return None
        acts = conn.execute(
            select(activity).where(activity.c.account_id == account_id).order_by(activity.c.occurred_at.desc())
        ).fetchall()
        drs = conn.execute(
            select(drafts).where(drafts.c.account_id == account_id).order_by(drafts.c.created_at.desc())
        ).fetchall()
    out = row_to_dict(row)
    out["activity"] = rows_to_dicts(acts)
    out["drafts"] = rows_to_dicts(drs)
    return out
