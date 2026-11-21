"""Live CRM from HubSpot (CRM v3 API, private app token).

One account per company that has a deal. The account takes its stage from the company's most
advanced open deal (or "Customer" when it only has won deals), and every date comes straight from
HubSpot:

  stage entered  the time the deal's dealstage property was set to its current value
                 (propertiesWithHistory=dealstage, newest version first)
  last contact   the later of the deal's and the company's "Last contacted" (notes_last_contacted)

Deal stages map by the probability on the pipeline stage: under 25% Prospect, under 50% Discovery,
otherwise Proposal; closed won is Customer; closed lost is left out.

Scopes the private app needs: crm.objects.companies.read, crm.objects.deals.read,
crm.objects.contacts.read, crm.objects.owners.read.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings
from app.workflows.crm_import import category_of, region_of

BASE = "https://api.hubapi.com"
TRANSPORT: httpx.BaseTransport | None = None  # tests swap in httpx.MockTransport
DEAL_PROPS = ["dealname", "amount", "dealstage", "pipeline", "createdate", "closedate", "notes_last_contacted", "hubspot_owner_id", "hs_arr"]
COMPANY_PROPS = ["name", "domain", "industry", "numberofemployees", "country", "notes_last_contacted", "description"]
CONTACT_PROPS = ["firstname", "lastname", "jobtitle", "email"]


class HubSpotError(RuntimeError):
    """HubSpot refused or failed a request; the message says why."""


def _client(s: Settings) -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=30, transport=TRANSPORT, headers={"Authorization": f"Bearer {s.hubspot_token}"})


def _check(r: httpx.Response, what: str) -> dict[str, Any]:
    if r.status_code == 401:
        raise HubSpotError("HubSpot refused the token (401). Create a private app token and save it again.")
    if r.status_code == 403:
        raise HubSpotError(f"HubSpot token is missing a scope for {what} (403). Add the read scopes listed in Settings.")
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", "")
        except ValueError:
            msg = ""
        raise HubSpotError(f"HubSpot {what}: {msg or f'HTTP {r.status_code}'}")
    return r.json()


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.isdigit():  # epoch milliseconds
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _num(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def test(s: Settings) -> str:
    with _client(s) as http:
        _check(http.get("/crm/v3/objects/companies", params={"limit": 1}), "companies")
        _check(http.get("/crm/v3/objects/deals", params={"limit": 1}), "deals")
    return "HubSpot answered: companies and deals can be read."


def stage_map(http: httpx.Client) -> dict[str, str | None]:
    """{stage id: Prospect | Discovery | Proposal | Customer | None (closed lost)}"""
    out: dict[str, str | None] = {}
    for pipeline in _check(http.get("/crm/v3/pipelines/deals"), "pipelines").get("results", []):
        for st in pipeline.get("stages", []):
            meta = st.get("metadata") or {}
            closed = str(meta.get("isClosed", "false")).lower() == "true"
            p = _num(meta.get("probability")) or 0.0
            out[st["id"]] = ("Customer" if p >= 1 else None) if closed else ("Prospect" if p < 0.25 else "Discovery" if p < 0.5 else "Proposal")
    return out


def _owners(http: httpx.Client) -> dict[str, str]:
    out, after = {}, None
    while True:
        body = _check(http.get("/crm/v3/owners", params={"limit": 100, **({"after": after} if after else {})}), "owners")
        for o in body.get("results", []):
            out[str(o["id"])] = " ".join(x for x in (o.get("firstName"), o.get("lastName")) if x) or o.get("email") or "Unassigned"
        after = (body.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return out


def _deals(http: httpx.Client) -> list[dict[str, Any]]:
    out, after = [], None
    while True:
        params = {"limit": 50, "properties": ",".join(DEAL_PROPS), "propertiesWithHistory": "dealstage", "associations": "companies,contacts", "archived": "false"}
        if after:
            params["after"] = after
        body = _check(http.get("/crm/v3/objects/deals", params=params), "deals")
        out += body.get("results", [])
        after = (body.get("paging") or {}).get("next", {}).get("after")
        if not after:
            return out


def _batch(http: httpx.Client, kind: str, ids: list[str], props: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), 100):
        body = _check(http.post(f"/crm/v3/objects/{kind}/batch/read", json={"properties": props, "inputs": [{"id": x} for x in ids[i : i + 100]]}), kind)
        out.update({r["id"]: r.get("properties") or {} for r in body.get("results", [])})
    return out


def _assoc(deal: dict[str, Any], kind: str) -> list[str]:
    return [str(a["id"]) for a in ((deal.get("associations") or {}).get(kind) or {}).get("results", [])]


def _stage_entered(deal: dict[str, Any]) -> datetime | None:
    current = (deal.get("properties") or {}).get("dealstage")
    history = ((deal.get("propertiesWithHistory") or {}).get("dealstage")) or []
    entered = None
    for version in history:  # newest first: walk back while the stage stays the same
        if version.get("value") != current:
            break
        entered = _ts(version.get("timestamp"))
    return entered


RANK = {"Prospect": 0, "Discovery": 1, "Proposal": 2, "Customer": -1}


def fetch_accounts(s: Settings, now: datetime) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Account rows ready for the accounts table, plus counts of what was skipped and why."""
    with _client(s) as http:
        stages = stage_map(http)
        owners = _owners(http)
        deals = _deals(http)
        company_ids = sorted({c for d in deals for c in _assoc(d, "companies")})
        contact_ids = sorted({c for d in deals for c in _assoc(d, "contacts")[:1]})
        companies = _batch(http, "companies", company_ids, COMPANY_PROPS)
        contacts = _batch(http, "contacts", contact_ids, CONTACT_PROPS)

    skipped = {"no_company": 0, "closed_lost": 0}
    by_company: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for d in deals:
        stage = stages.get((d.get("properties") or {}).get("dealstage", ""))
        cids = _assoc(d, "companies")
        if not cids:
            skipped["no_company"] += 1
            continue
        if stage is None:
            skipped["closed_lost"] += 1
            continue
        by_company.setdefault(cids[0], []).append((stage, d))

    rows = []
    for cid, items in by_company.items():
        open_deals = [x for x in items if x[0] != "Customer"]
        pick = max(open_deals, key=lambda x: (RANK[x[0]], (x[1].get("properties") or {}).get("createdate") or "")) if open_deals else items[0]
        stage, deal = pick
        p = deal.get("properties") or {}
        comp = companies.get(cid, {})
        name = (comp.get("name") or "").strip()
        if not name:
            skipped["no_company"] += 1
            continue
        contact = contacts.get(next(iter(_assoc(deal, "contacts")), ""), {})
        won = [x[1] for x in items if x[0] == "Customer"]
        arr = sum(_num((w.get("properties") or {}).get("hs_arr")) or 0 for w in won) or None
        last = [t for t in (_ts(p.get("notes_last_contacted")), _ts(comp.get("notes_last_contacted"))) if t]
        industry = (comp.get("industry") or "").replace("_", " ").title() or None
        employees = _num(comp.get("numberofemployees"))
        rows.append(
            {
                "company": name[:200],
                "domain": comp.get("domain") or None,
                "industry": industry,
                "category": category_of(f"{industry or ''} {comp.get('description') or ''}"),
                "size": int(employees) if employees else None,
                "region": region_of(comp.get("country")),
                "cloud_provider": None,
                "stage": stage,
                "deal_value": _num(p.get("amount")) if stage != "Customer" else None,
                "arr": arr,
                "stage_entered_at": _stage_entered(deal) or _ts(p.get("createdate")) or now,
                "last_contact": max(last) if last else None,
                "owner": owners.get(str(p.get("hubspot_owner_id") or ""), "Unassigned"),
                "contact_name": " ".join(x for x in (contact.get("firstname"), contact.get("lastname")) if x) or None,
                "contact_title": contact.get("jobtitle") or None,
                "contact_email": contact.get("email") or None,
                "notes": f"HubSpot deal: {p.get('dealname') or 'untitled'}" + (f" ({len(items)} deals)" if len(items) > 1 else ""),
            }
        )
    return rows, skipped
