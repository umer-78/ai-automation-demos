"""AI mode (with a fake model client), Make.com endpoints, Airtable bridge, security."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ratelimit import RateLimiter
from app.services.web_snapshot import validate_url
from app.workflows.airtable_bridge import STATE_KEY, kv_set
from app.workflows.site_generator import palette_for, sanitize_section
from tests.conftest import FakeAnthropic, make_settings

CLIENT = {
    "name": "Northside Physio",
    "website": "https://northside-physio.example",
    "industry": "Physiotherapy clinics",
    "services": "SEO, Paid Ads",
    "manager": "Priya Shah",
    "manager_email": "priya@northwind-digital.example",
}


# --------------------------------------------------------------------------- AI mode
def test_ai_brief_is_used_when_model_is_configured(ai_client):
    run_id = ai_client.post("/api/clients", json=CLIENT).json()["run_id"]
    run = ai_client.get(f"/api/automation/runs/{run_id}").json()
    assert run["status"] == "success"
    cid = run["log"][0]["client_id"]
    brief = ai_client.get(f"/api/clients/{cid}").json()["client"]["brief_data"]
    assert brief["generated_by"] == "ai"
    assert brief["quick_wins"] == ["AI win one", "AI win two", "AI win three"]
    call = ai_client.fake.messages.calls[-1]
    assert call["tool_choice"] == {"type": "tool", "name": "submit_brief"}
    assert "Northside Physio" in call["messages"][0]["content"]


def test_ai_weekly_summary(ai_client):
    data = ai_client.post("/api/summaries/weekly").json()
    assert data["generated_by"] == "ai"
    assert all(len(s["sentences"]) == 3 and s["sentences"][0].startswith("AI one") for s in data["summaries"])


def test_ai_site_is_sanitised_and_regenerates_only_one_block(ai_client):
    body = {"business_name": "Bloom", "industry": "Florist", "tone": "warm", "services": ["A1", "B2", "C3"], "colour": "#336699"}
    v1 = ai_client.post("/api/sites", json=body).json()
    html_all = " ".join(v1["sections"].values())
    assert "<script" not in html_all and "onclick" not in html_all and "javascript:" not in html_all
    assert "evil-class" not in html_all
    v2 = ai_client.post(f"/api/sites/{v1['group_id']}/regenerate", json={"section": "hero", "instruction": "shorter"}).json()
    assert "Regenerated hero" in v2["sections"]["hero"] and "onerror" not in v2["sections"]["hero"]
    assert {k: v2["sections"][k] for k in ("services", "proof", "cta")} == {k: v1["sections"][k] for k in ("services", "proof", "cta")}


def test_model_failure_is_logged_and_alerted(tmp_path):
    def broken(tool, kwargs):
        raise RuntimeError("upstream 529 overloaded")

    app = create_app(make_settings(tmp_path), llm_client=FakeAnthropic(broken))
    with TestClient(app) as c:
        resp = c.post("/api/summaries/weekly")
        assert resp.status_code == 502
        failures = c.get("/api/automation/logs?status=failure").json()
        assert failures[0]["workflow"] == "weekly_summary"
        assert any(n["kind"] == "alert" for n in c.get("/api/notifications").json())


# --------------------------------------------------------------------------- Make.com endpoints
@pytest.fixture
def make_client(tmp_path):
    app = create_app(make_settings(tmp_path, automation_api_key="test-key"))
    with TestClient(app) as c:
        yield c


def test_automation_endpoints_require_the_key(make_client):
    assert make_client.post("/api/automation/clients/sync", json=CLIENT).status_code == 401
    bad = make_client.post("/api/automation/clients/sync", json=CLIENT, headers={"X-Automation-Key": "nope"})
    assert bad.status_code == 401


def test_make_scenario_step_sequence(make_client):
    h = {"X-Automation-Key": "test-key"}
    run_id = "make123456"
    synced = make_client.post("/api/automation/clients/sync", json={**CLIENT, "run_id": run_id}, headers=h).json()
    assert synced["has_seo"] and synced["has_paid_ads"] and not synced["has_web_design"]
    for service in ("SEO", "Paid Ads"):
        branch = make_client.post(
            "/api/automation/onboarding/checklist", json={"client_id": synced["client_id"], "service": service, "run_id": run_id}, headers=h
        ).json()
        assert branch["tasks"] == 5 and service in branch["welcome_text"]
    brief = make_client.post("/api/automation/onboarding/brief", json={"client_id": synced["client_id"], "run_id": run_id}, headers=h).json()
    assert brief["brief_text"].startswith("CLIENT BRIEF")
    done = make_client.post(
        "/api/automation/log", json={"workflow": "client_onboarding", "status": "success", "run_id": run_id}, headers=h
    ).json()
    assert done["status"] == "success"
    run = make_client.get(f"/api/automation/runs/{run_id}").json()
    assert run["status"] == "success" and run["live"]["orchestrator"] == "make"
    assert [s["step"] for s in run["live"]["steps"]] == ["client_synced", "branch_done", "branch_done", "brief_saved"]


def test_make_deliberate_failure_and_error_route(make_client):
    h = {"X-Automation-Key": "test-key"}
    synced = make_client.post("/api/automation/clients/sync", json={**CLIENT, "simulate_failure": True}, headers=h).json()
    resp = make_client.post("/api/automation/onboarding/brief", json={"client_id": synced["client_id"], "simulate_failure": True}, headers=h)
    assert resp.status_code == 500
    # what the Make error route does next:
    logged = make_client.post(
        "/api/automation/log",
        json={"workflow": "client_onboarding", "status": "failure", "error": resp.json()["detail"], "module": "Generate brief"},
        headers=h,
    ).json()
    assert logged["alerted"] is True
    assert make_client.get("/api/automation/logs?status=failure").json()[0]["details"]["module"] == "Generate brief"


def test_make_offboarding_returns_text_for_slack(make_client):
    h = {"X-Automation-Key": "test-key"}
    cid = make_client.get("/api/clients").json()[0]["id"]
    result = make_client.post("/api/automation/offboarding", json={"client_id": cid}, headers=h).json()
    assert result["status"] == "archived" and "off-boarded" in result["slack_text"]
    again = make_client.post("/api/automation/offboarding", json={"client_id": cid}, headers=h).json()
    assert again["status"] == "already_archived"


def test_production_requires_automation_key(tmp_path):
    app = create_app(make_settings(tmp_path, environment="production"))
    with TestClient(app) as c:
        assert c.post("/api/automation/log", json={"workflow": "x1", "status": "success"}).status_code == 503


# --------------------------------------------------------------------------- live Slack + Make dispatch
@respx.mock
def test_slack_webhook_is_called_when_configured(tmp_path):
    route = respx.post("https://hooks.slack.test/services/T/B/X").mock(return_value=httpx.Response(200, text="ok"))
    app = create_app(make_settings(tmp_path, slack_webhook_url="https://hooks.slack.test/services/T/B/X"))
    with TestClient(app) as c:
        c.post("/api/demo/forced-failure")
        assert route.called
        sent = json.loads(route.calls.last.request.content)
        assert "Automation failure" in sent["text"]
        assert c.get("/api/notifications?channel=slack").json()[0]["status"] == "sent"


@respx.mock
def test_form_dispatches_to_make_when_configured(tmp_path):
    hook = respx.post("https://hook.make.test/abc").mock(return_value=httpx.Response(200, text="Accepted"))
    app = create_app(make_settings(tmp_path, make_onboarding_webhook_url="https://hook.make.test/abc"))
    with TestClient(app) as c:
        resp = c.post("/api/clients", json=CLIENT).json()
        assert resp["mode"] == "make" and hook.called
        payload = json.loads(hook.calls.last.request.content)
        assert payload["event"] == "client.created" and payload["services"] == ["SEO", "Paid Ads"]


# --------------------------------------------------------------------------- Airtable bridge
@respx.mock
def test_airtable_webhook_bridge_onboards_new_rows(tmp_path):
    secret = base64.b64encode(b"super-secret").decode()
    app = create_app(make_settings(tmp_path, airtable_token="pat_test", airtable_base_id="appTEST1234567890"))
    respx.get("https://api.airtable.com/v0/bases/appTEST1234567890/webhooks/achW1/payloads").mock(
        return_value=httpx.Response(
            200,
            json={"cursor": 2, "mightHaveMore": False, "payloads": [{"changedTablesById": {"tblX": {"createdRecordsById": {"recAAAAAAAAAAAAAA": {}}}}}]},
        )
    )
    respx.get("https://api.airtable.com/v0/appTEST1234567890/Clients/recAAAAAAAAAAAAAA").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "recAAAAAAAAAAAAAA",
                "fields": {"Name": "Lakeside Vets", "Industry": "Veterinary", "Services": ["SEO"], "Account Manager": "Marcus Lee", "Status": "New"},
            },
        )
    )
    patch = respx.patch("https://api.airtable.com/v0/appTEST1234567890/Clients/recAAAAAAAAAAAAAA").mock(
        return_value=httpx.Response(200, json={"id": "recAAAAAAAAAAAAAA", "fields": {}})
    )
    with TestClient(app) as c:
        kv_set(c.app.state.ctx, STATE_KEY, {"id": "achW1", "mac_secret": secret, "cursor": 1})
        body = json.dumps({"base": {"id": "appTEST1234567890"}, "webhook": {"id": "achW1"}, "timestamp": "2026-11-17T10:00:00.000Z"}).encode()
        assert c.post("/api/webhooks/airtable", content=body, headers={"X-Airtable-Content-MAC": "hmac-sha256=bad"}).status_code == 401
        mac = "hmac-sha256=" + hmac.new(b"super-secret", body, hashlib.sha256).hexdigest()
        assert c.post("/api/webhooks/airtable", content=body, headers={"X-Airtable-Content-MAC": mac}).status_code == 200
        names = {x["name"]: x for x in c.get("/api/clients").json()}
        assert names["Lakeside Vets"]["status"] == "active"
        assert names["Lakeside Vets"]["airtable_record_id"] == "recAAAAAAAAAAAAAA"
        assert patch.called  # brief written back to Airtable
        assert json.loads(patch.calls.last.request.content)["fields"]["Brief"].startswith("CLIENT BRIEF")


# --------------------------------------------------------------------------- security and units
def test_rate_limit_returns_429(tmp_path):
    app = create_app(make_settings(tmp_path, rate_limit_per_hour=2))
    with TestClient(app) as c:
        assert c.post("/api/jobs/daily-metrics").status_code == 200
        assert c.post("/api/jobs/daily-metrics").status_code == 200
        resp = c.post("/api/jobs/daily-metrics")
        assert resp.status_code == 429 and "Retry-After" in resp.headers


def test_validation_errors(client):
    assert client.post("/api/clients", json={**CLIENT, "services": ["Knitting"]}).status_code == 422
    assert client.post("/api/clients", json={**CLIENT, "manager_email": "not-an-email"}).status_code == 422
    assert client.post("/api/sites", json={"business_name": "X Y", "industry": "Z1", "tone": "ok", "services": ["a1"], "colour": "red"}).status_code == 422
    assert client.post("/api/sites/nope/regenerate", json={"section": "footer"}).status_code == 422
    assert client.post("/api/sites/nope/regenerate", json={"section": "hero"}).status_code == 404


def test_admin_endpoints_disabled_without_token(client):
    assert client.post("/api/admin/reset").status_code == 403


def test_admin_reset_reseeds(tmp_path):
    app = create_app(make_settings(tmp_path, admin_token="adm"))
    with TestClient(app) as c:
        c.post("/api/demo/forced-failure")
        assert c.post("/api/admin/reset", headers={"X-Admin-Token": "wrong"}).status_code == 401
        result = c.post("/api/admin/reset", headers={"X-Admin-Token": "adm"}).json()
        assert result["seeded"] and len(c.get("/api/clients").json()) == 5


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://example.org", True),
        ("example.org/about", True),
        ("http://localhost:8000", False),
        ("http://127.0.0.1/admin", False),
        ("http://169.254.169.254/latest/meta-data", False),
        ("file:///etc/passwd", False),
        ("https://brightsmile-dental.example", False),
        ("ftp://example.org", False),
    ],
)
def test_ssrf_guard(url, ok):
    assert (validate_url(url) is not None) is ok


def test_sanitizer_and_palette():
    out = sanitize_section('<div class="card x" style="color:red" onmouseover="a()"><a href="javascript:x">y</a><iframe src="//evil"></iframe>ok</div>')
    assert out == '<div class="card"><a rel="noopener noreferrer nofollow">y</a>ok</div>'
    assert palette_for("dark green please")["primary"].startswith("#")
    assert palette_for("#ff0000")["primary"] != palette_for("navy")["primary"]


def test_rate_limiter_window():
    rl = RateLimiter(limit=1, window_seconds=3600)
    assert rl.allow("a")[0] and not rl.allow("a")[0] and rl.allow("b")[0]


def test_mock_api_is_deterministic(client):
    a = client.get("/mock-api/ad-performance?start=2026-10-01&end=2026-10-03").json()
    b = client.get("/mock-api/ad-performance?start=2026-10-01&end=2026-10-03").json()
    assert a == b and len(a["rows"]) == 5 * 3 * 3


def test_csv_source(tmp_path):
    from app.seed import write_sample_csv
    from app.workflows.metrics_pipeline import run_daily_metrics

    app = create_app(make_settings(tmp_path, metrics_csv_path=str(tmp_path / "s.csv")))
    with TestClient(app) as c:
        ctx = c.app.state.ctx
        n = write_sample_csv(ctx, tmp_path / "s.csv")
        result = run_daily_metrics(ctx, source="csv")
        assert result["fetched"] == n == 900 and result["inserted"] == 0 and result["total_rows"] == 900


def test_export_csv(client):
    resp = client.get("/api/metrics/export.csv?days=7")
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.text.splitlines()[0] == "date,client,channel,impressions,clicks,spend,conversions"
    assert len(resp.text.splitlines()) == 1 + 7 * 15
