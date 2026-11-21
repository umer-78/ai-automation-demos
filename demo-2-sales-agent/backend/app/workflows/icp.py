"""Versioned ideal customer profile (ICP).

The agent writes the first version from product.md, competitors.md and the deal notes. The rep
can edit it at any time; a rep-authored version always wins, and later agent proposals are
kept as suggestions instead of overwriting the rep's choices.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine

from app.agent.scoring import DEFAULT_ICP, normalize_icp
from app.db import icp_versions, row_to_dict, rows_to_dicts, utcnow


def _latest(conn: Connection) -> dict[str, Any] | None:
    row = conn.execute(select(icp_versions).order_by(icp_versions.c.version.desc()).limit(1)).first()
    return row_to_dict(row) if row else None


def active_icp(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        latest = _latest(conn)
    if not latest:
        criteria = normalize_icp(DEFAULT_ICP)
        return {"version": 0, "author": "default", "summary": criteria["summary"], "criteria": criteria, "created_at": None}
    latest["criteria"] = normalize_icp(latest["criteria"])
    return latest


def rep_has_edited(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(conn.execute(select(func.count()).where(icp_versions.c.author == "rep")).scalar())


def save_version(engine: Engine, raw: dict[str, Any], *, author: str, note: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    criteria = normalize_icp(raw)
    with engine.begin() as conn:
        latest = _latest(conn)
        if latest and normalize_icp(latest["criteria"]) == criteria and latest["author"] == author:
            return {**latest, "criteria": criteria, "unchanged": True}
        version = (latest["version"] if latest else 0) + 1
        row = {
            "version": version,
            "author": author,
            "summary": criteria["summary"],
            "criteria": criteria,
            "note": note,
            "run_id": run_id,
            "created_at": utcnow(),
        }
        result = conn.execute(icp_versions.insert().values(**row))
        row["id"] = result.inserted_primary_key[0]
    return {**row, "created_at": row["created_at"].isoformat(), "unchanged": False}


def history(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(select(icp_versions).order_by(icp_versions.c.version.desc()).limit(30)).fetchall()
    return rows_to_dicts(rows)


def rescore_leads(engine: Engine, criteria: dict[str, Any], *, write: bool) -> list[dict[str, Any]]:
    """Re-score every saved lead against an ICP. With write=False it is a what-if preview."""
    from datetime import date as _date

    from sqlalchemy import update

    from app.agent.scoring import score_lead
    from app.db import leads

    criteria = normalize_icp(criteria)
    today: _date = utcnow().date()
    changes = []
    with engine.begin() as conn:
        for row in conn.execute(select(leads)).fetchall():
            lead = dict(row._mapping)
            attrs = {k: lead.get(k) for k in ("category", "size_band", "region", "cloud_native")}
            scored = score_lead(attrs, lead["facts"] or [], criteria, today)
            status = lead["status"]
            excluded_reason = lead.get("excluded_reason")
            if scored["excluded"]:
                if status in ("new", "drafted", "excluded"):
                    status, excluded_reason = "excluded", scored["excluded_reason"]
            elif status == "excluded" and (excluded_reason or "").startswith("Excluded by the ICP"):
                status, excluded_reason = "new", None
            changes.append({
                "lead_id": lead["id"], "company": lead["company"], "old_score": lead["score"], "new_score": scored["score"],
                "delta": scored["score"] - lead["score"], "old_status": lead["status"], "new_status": status,
                "score_reason": scored["reason"],
            })
            if write:
                conn.execute(update(leads).where(leads.c.id == lead["id"]).values(
                    score=scored["score"], score_reason=scored["reason"], score_parts=scored["parts"],
                    status=status, excluded_reason=excluded_reason, updated_at=utcnow(),
                ))
    changes.sort(key=lambda c: -c["new_score"])
    return changes
