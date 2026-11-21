"""Module C: AI website drafts, stored per version, with one-section regeneration."""
from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.engine import Engine

from .db import jdump, jload, log_event, now_utc, site_drafts, tx
from .llm import OFFLINE, SECTIONS, extract_section, offline_site, replace_section
from .onboarding import BadRequest, Deps, NotFound, alert_failure

TONES = ["confident", "warm", "playful", "premium", "minimal", "bold"]


def validate_spec(data: dict) -> dict:
    name = (data.get("business_name") or "").strip()
    industry = (data.get("industry") or "").strip()
    tone = (data.get("tone") or "confident").strip().lower()
    services = [s.strip() for s in (data.get("services") or []) if s and s.strip()]
    colour = (data.get("colour") or "#4f46e5").strip()
    if not 2 <= len(name) <= 80:
        raise BadRequest("Business name must be 2-80 characters.")
    if not 2 <= len(industry) <= 80:
        raise BadRequest("Industry must be 2-80 characters.")
    if tone not in TONES:
        raise BadRequest(f"Tone must be one of: {', '.join(TONES)}.")
    if len(services) != 3 or any(len(s) > 60 for s in services):
        raise BadRequest("Give exactly 3 services (up to 60 characters each).")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
        raise BadRequest("Colour must be a hex value like #4f46e5.")
    return {"business_name": name, "industry": industry, "tone": tone, "services": services, "colour": colour,
            "client_id": data.get("client_id") or None}


def _row_to_dict(row) -> dict:  # noqa: ANN001
    d = dict(row._mapping)
    d["services"] = jload(d["services"], [])
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    d["preview_url"] = f"/api/sites/{d['site_id']}/preview?v={d['version']}"
    return d


def _store(engine: Engine, deps: Deps, site_id: str, spec: dict, page: str, version: int, section: str | None,
           engine_label: str) -> dict:
    up = deps.storage.upload_html(f"{site_id}/v{version}.html", page)
    with tx(engine) as conn:
        conn.execute(site_drafts.insert().values(
            site_id=site_id, client_id=spec.get("client_id"), business_name=spec["business_name"],
            industry=spec["industry"], tone=spec["tone"], services=jdump(spec["services"]), colour=spec["colour"],
            html=page, html_url=up["url"] or f"/api/sites/{site_id}/preview?v={version}", version=version,
            section=section or "full", engine=engine_label, created_at=now_utc()))
        log_event(conn, "website_draft", "success",
                  f"{spec['business_name']} version {version} ({section or 'full page'}), {engine_label}, storage: {up['detail']}")
        row = conn.execute(select(site_drafts).where((site_drafts.c.site_id == site_id) &
                                                     (site_drafts.c.version == version))).first()
    return {**_row_to_dict(row), "storage": up}


def generate(engine: Engine, deps: Deps, data: dict) -> dict:
    spec = validate_spec(data)
    try:
        page, label = deps.llm.generate_site(spec)
    except Exception as exc:  # noqa: BLE001
        alert_failure(engine, deps, "website_draft", str(exc)[:300], spec["business_name"])
        page, label = offline_site(spec, 1), f"{OFFLINE.split(' (')[0]} (Claude error, fell back)"
    return _store(engine, deps, uuid.uuid4().hex[:12], spec, page, 1, None, label)


def latest(engine: Engine, site_id: str, version: int | None = None) -> dict:
    with tx(engine) as conn:
        q = select(site_drafts).where(site_drafts.c.site_id == site_id)
        q = q.where(site_drafts.c.version == version) if version else q.order_by(site_drafts.c.version.desc())
        row = conn.execute(q.limit(1)).first()
    if not row:
        raise NotFound("site draft not found")
    return _row_to_dict(row)


def regenerate(engine: Engine, deps: Deps, site_id: str, section: str, instructions: str = "") -> dict:
    if section not in SECTIONS:
        raise BadRequest(f"Section must be one of: {', '.join(SECTIONS)}.")
    cur = latest(engine, site_id)
    spec = {k: cur[k] for k in ("business_name", "industry", "tone", "services", "colour", "client_id")}
    new_version = cur["version"] + 1
    try:
        new_section, label = deps.llm.regenerate_section({**spec, "version": new_version}, section,
                                                         extract_section(cur["html"], section), instructions[:500])
    except Exception as exc:  # noqa: BLE001
        alert_failure(engine, deps, "website_draft", str(exc)[:300], f"{spec['business_name']}, rewrite of {section}")
        new_section = extract_section(offline_site(spec, new_version), section)
        label = f"{OFFLINE.split(' (')[0]} (Claude error, fell back)"
    page = replace_section(cur["html"], section, new_section)
    return _store(engine, deps, site_id, spec, page, new_version, section, label)


def versions(engine: Engine, site_id: str) -> list[dict]:
    with tx(engine) as conn:
        rs = conn.execute(select(site_drafts.c.version, site_drafts.c.section, site_drafts.c.engine,
                                 site_drafts.c.created_at, site_drafts.c.html_url)
                          .where(site_drafts.c.site_id == site_id).order_by(site_drafts.c.version)).all()
    return [{"version": r.version, "section": r.section, "engine": r.engine, "url": r.html_url,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rs]
