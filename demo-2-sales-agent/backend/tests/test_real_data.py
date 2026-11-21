"""Your own CRM: CSV imports, a live HubSpot sync, your company notes and the access lock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import accounts
from app.main import create_app
from app.services import hubspot, knowledge

from .conftest import make_settings

OWNER = {"X-Owner-Token": "owner-code-123"}
NOW = datetime.now(timezone.utc)


def _day(days_ago: int) -> str:
    d = NOW - timedelta(days=days_ago)
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


HUBSPOT_EXPORT = (
    "Company name,Company Domain Name,Industry,Number of Employees,Country/Region,Deal Stage,Amount,Deal owner,"
    "Contact name,Job Title,Email,Last Contacted,Date entered current stage,Notes\n"
    f"Northwind Freight,https://www.northwindfreight.example,Logistics software,320,United States,Contract Sent,\"$48,000\",Ana Ruiz,Lee Park,CISO,lee@nf.example,{_day(5)},{_day(40)},Security review open\n"
    f"Kestrel Pay,kestrelpay.example,Payments,90,United Kingdom,qualifiedtobuy,12000,Ana Ruiz,,,,{_day(45)},{_day(50)},\n"
    f"Old Deal Ltd,old.example,Retail,40,France,Closed Lost,5000,Ana Ruiz,,,,{_day(90)},{_day(90)},\n"
)


def _accounts(ctx):
    with ctx.engine.connect() as conn:
        return {r.company: r for r in conn.execute(select(accounts))}


def test_csv_import_replaces_the_sample_crm(client):
    ctx = client.app.state.ctx
    assert len(_accounts(ctx)) == 50
    r = client.post("/api/data/import", json={"csv": HUBSPOT_EXPORT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sample_removed"] and body["inserted"] == 2 and body["skipped_count"] == 1 and "Closed Lost" in body["skipped"][0]

    rows = _accounts(ctx)
    assert sorted(rows) == ["Kestrel Pay", "Northwind Freight"], "no sample account survives next to real data"
    nf, kp = rows["Northwind Freight"], rows["Kestrel Pay"]
    assert (nf.stage, nf.deal_value, nf.region, nf.domain, nf.category) == ("Proposal", 48000, "North America", "northwindfreight.example", "vertical_software")
    assert (kp.stage, kp.region, kp.category) == ("Discovery", "UK & Ireland", "fintech")
    assert "stalled" in nf.flags, "40 days in Proposal is past the 21-day limit"
    assert "no_contact" in kp.flags, "45 days since the last contact"

    again = client.post("/api/data/import", json={"csv": HUBSPOT_EXPORT}).json()
    assert (again["inserted"], again["updated"]) == (0, 2), "a second import updates instead of doubling"
    st = client.get("/api/data/status").json()
    assert st["mode"] == "real" and st["label"] == "Your CRM" and st["accounts"] == 2 and st["needs"] == ["product", "anthropic", "tavily"]


def test_agent_needs_your_product_notes_in_real_mode(client):
    ctx = client.app.state.ctx
    client.post("/api/data/real")
    r = client.post("/api/agent/run")
    assert r.status_code == 409 and "product notes" in r.json()["detail"]
    assert knowledge.read_doc("product", ctx.engine) == "", "Acme's notes are never used for a real seller"

    client.put("/api/data/notes/product", json={"text": "We sell payroll software to restaurants with 20 to 200 staff."})
    assert knowledge.read_doc("product", ctx.engine).startswith("We sell payroll software")
    docs = {d["name"]: d for d in client.get("/api/knowledge").json()}
    assert docs["product"]["files"] == ["saved in Settings"]
    assert client.get("/api/data/status").json()["needs"] == ["anthropic", "tavily"], "real runs need live AI and live research"

    client.post("/api/data/demo")
    assert knowledge.read_doc("product", ctx.engine).startswith("#") or "Acme" in knowledge.read_doc("product", ctx.engine)
    assert len(_accounts(ctx)) == 50
    assert knowledge.saved_notes(ctx.engine)["product"]["text"].startswith("We sell payroll"), "your notes are kept for next time"


def test_company_settings_sign_the_emails(client):
    r = client.put("/api/settings/company", json={"values": {"seller_company": "Tablewise", "rep_name": "Sara Khan"}})
    assert r.status_code == 200, r.text
    s = client.app.state.ctx.settings
    assert (s.seller_company, s.rep_name, s.company_set) == ("Tablewise", "Sara Khan", True)


@pytest.fixture
def locked(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, owner_token="owner-code-123", viewer_token="viewer-456"))) as c:
        yield c


def test_real_crm_needs_an_access_code(locked):
    assert locked.get("/api/overview").status_code == 200, "the sample CRM stays public"
    assert locked.post("/api/data/import", json={"csv": HUBSPOT_EXPORT}).status_code == 401
    assert locked.post("/api/data/import", json={"csv": HUBSPOT_EXPORT}, headers=OWNER).status_code == 200
    r = locked.get("/api/overview")
    assert r.status_code == 401 and r.json()["locked"] is True
    assert locked.get("/api/overview", headers=OWNER).status_code == 200
    assert locked.get("/api/accounts", headers={"X-Owner-Token": "viewer-456"}).status_code == 200
    assert locked.get("/api/data/notes", headers={"X-Owner-Token": "viewer-456"}).status_code == 401
    assert locked.get("/api/health").status_code == 200


# ------------------------------------------------------------------------------ HubSpot
def _ms(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


class FakeHubSpot:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer pat-test"
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if path == "/crm/v3/pipelines/deals":
            stages = [("appt", "0.2", "false"), ("qualified", "0.4", "false"), ("contract", "0.9", "false"), ("won", "1.0", "true"), ("lost", "0.0", "true")]
            return httpx.Response(200, json={"results": [{"id": "default", "stages": [{"id": i, "label": i, "metadata": {"probability": p, "isClosed": c}} for i, p, c in stages]}]})
        if path == "/crm/v3/owners":
            return httpx.Response(200, json={"results": [{"id": "7", "firstName": "Ana", "lastName": "Ruiz"}]})
        if path == "/crm/v3/objects/deals":
            assert request.url.params["propertiesWithHistory"] == "dealstage"
            if request.url.params.get("after") == "p2":
                return httpx.Response(200, json={"results": [
                    {"id": "d3", "properties": {"dealname": "Old", "dealstage": "lost", "amount": "900"}, "associations": {"companies": {"results": [{"id": "c3"}]}}},
                    {"id": "d4", "properties": {"dealname": "Orphan", "dealstage": "appt"}, "associations": {}},
                    {"id": "d5", "properties": {"dealname": "Renewal", "dealstage": "won", "hs_arr": "36000"}, "associations": {"companies": {"results": [{"id": "c2"}]}}},
                ]})
            return httpx.Response(200, json={
                "results": [
                    {
                        "id": "d1",
                        "properties": {"dealname": "Platform", "dealstage": "contract", "amount": "52000", "hubspot_owner_id": "7", "createdate": _ms(80), "notes_last_contacted": _ms(3)},
                        "propertiesWithHistory": {"dealstage": [{"value": "contract", "timestamp": _ms(25)}, {"value": "contract", "timestamp": _ms(30)}, {"value": "qualified", "timestamp": _ms(60)}]},
                        "associations": {"companies": {"results": [{"id": "c1"}]}, "contacts": {"results": [{"id": "p1"}]}},
                    },
                    {
                        "id": "d2",
                        "properties": {"dealname": "Pilot", "dealstage": "appt", "amount": "8000", "hubspot_owner_id": "7", "createdate": _ms(10)},
                        "propertiesWithHistory": {"dealstage": [{"value": "appt", "timestamp": _ms(10)}]},
                        "associations": {"companies": {"results": [{"id": "c1"}]}},
                    },
                ],
                "paging": {"next": {"after": "p2"}},
            })
        if path == "/crm/v3/objects/companies/batch/read":
            return httpx.Response(200, json={"results": [
                {"id": "c1", "properties": {"name": "Harbor Health", "domain": "harborhealth.example", "industry": "HOSPITAL_HEALTH_CARE", "numberofemployees": "410", "country": "Canada", "notes_last_contacted": _ms(9)}},
                {"id": "c2", "properties": {"name": "Quill Data", "domain": "quill.example", "industry": "COMPUTER_SOFTWARE", "numberofemployees": "75", "country": "Germany"}},
                {"id": "c3", "properties": {"name": "Gone Corp"}},
            ]})
        if path == "/crm/v3/objects/contacts/batch/read":
            return httpx.Response(200, json={"results": [{"id": "p1", "properties": {"firstname": "Lee", "lastname": "Park", "jobtitle": "CISO", "email": "lee@harbor.example"}}]})
        raise AssertionError(f"unexpected {request.method} {request.url}")


def test_hubspot_sync_reads_stages_dates_and_owners(tmp_path, monkeypatch):
    fake = FakeHubSpot()
    monkeypatch.setattr(hubspot, "TRANSPORT", httpx.MockTransport(fake))
    with TestClient(create_app(make_settings(tmp_path, hubspot_token="pat-test"))) as c:
        r = c.post("/api/data/hubspot/sync")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["accounts"] == 2 and body["skipped"] == {"no_company": 1, "closed_lost": 1}
        rows = _accounts(c.app.state.ctx)
        assert sorted(rows) == ["Harbor Health", "Quill Data"]
        h, q = rows["Harbor Health"], rows["Quill Data"]
        assert (h.stage, h.deal_value, h.owner, h.region, h.size, h.contact_name, h.contact_title) == ("Proposal", 52000, "Ana Ruiz", "North America", 410, "Lee Park", "CISO")
        entered = h.stage_entered_at if h.stage_entered_at.tzinfo else h.stage_entered_at.replace(tzinfo=timezone.utc)
        assert abs((NOW - entered).days - 30) <= 1, "stage entered = when the deal first reached its current stage"
        last = h.last_contact if h.last_contact.tzinfo else h.last_contact.replace(tzinfo=timezone.utc)
        assert abs((NOW - last).days - 3) <= 1, "the later of the deal's and the company's last contact"
        assert (q.stage, q.arr, q.region) == ("Customer", 36000, "Europe")
        assert "stalled" in h.flags
        st = c.get("/api/data/status").json()
        assert st["label"] == "Live from HubSpot" and st["last_sync"]["kind"] == "hubspot_sync"
        assert all(not call.startswith(("PATCH", "DELETE", "PUT")) for call in fake.calls), "HubSpot is only read"


def test_hubspot_bad_token_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(hubspot, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "Authentication credentials not found."})))
    with TestClient(create_app(make_settings(tmp_path, hubspot_token="pat-test"))) as c:
        r = c.post("/api/data/hubspot/sync")
        assert r.status_code == 502 and "refused the token" in r.json()["detail"]
        assert c.post("/api/settings/hubspot/test").json()["ok"] is False
