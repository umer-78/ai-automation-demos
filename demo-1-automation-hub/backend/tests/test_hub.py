"""API tests for Demo 1. Run: cd demo-1-automation-hub/backend && python -m pytest -q"""
from __future__ import annotations

import dataclasses
import re
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import mockdata, reporting
from app.config import Settings
from app.db import make_engine, tx
from app.llm import LLM
from app.main import create_app
from app.seed import reset

TODAY = date(2026, 11, 20)


def make_settings(tmp_path, **over) -> Settings:
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><title>hub</title>")
    base = dataclasses.replace(Settings(), database_url=f"sqlite:///{tmp_path / 'hub.db'}", anthropic_api_key="",
                               slack_webhook_url="", airtable_token="", airtable_base_id="", supabase_url="",
                               supabase_service_key="", hub_api_token="", smtp_host="", smtp_from="",
                               frontend_dist=str(dist), rate_limit_per_minute=1000)
    return dataclasses.replace(base, **over)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(make_settings(tmp_path), today_fn=lambda: TODAY))


def test_status_is_honest_about_engine(client):
    s = client.get("/api/status").json()
    assert s["live_model"] is False and s["engine"].startswith("offline engine")
    assert s["database"] == "SQLite (local)" and s["clients"] == 5


def test_kpi_matches_trend_and_one_alert(client):
    d = client.get("/api/dashboard").json()
    assert len(d["trend"]) == 30
    assert d["kpis"]["spend"] == sum(x["spend"] for x in d["trend"])
    assert d["kpis"]["conversions"] == sum(x["conversions"] for x in d["trend"])
    assert [(a["client_id"], a["channel"]) for a in d["alerts"]] == [("c2", "Google Ads")]
    assert len(d["by_client"]) == 5 and d["kpis"]["cpa"] == round(d["kpis"]["spend"] / d["kpis"]["conversions"], 2)


def test_daily_job_is_idempotent_and_keeps_the_story(client):
    for _ in range(3):
        r = client.post("/api/reporting/job", json={"source": "mock-api"}).json()
        assert r["duplicate_rows"] == 0 and r["upserted"] == 5 * 3 * reporting.RESTATE_DAYS
    d = client.get("/api/dashboard").json()
    assert [(a["client_id"], a["channel"]) for a in d["alerts"]] == [("c2", "Google Ads")]


@pytest.mark.parametrize("offset", range(0, 120, 1))
def test_exactly_one_alert_on_any_day(tmp_path, offset):
    today = TODAY + timedelta(days=offset)
    engine = make_engine(f"sqlite:///{tmp_path / 'x.db'}")
    reset(engine, today)
    with tx(engine) as conn:
        a = reporting.alerts(conn, reporting.Windows(today))
    assert [(x["client_id"], x["channel"]) for x in a] == [("c2", "Google Ads")]


def test_forced_failure_is_logged(client):
    r = client.post("/api/test/forced-failure").json()
    assert r["logged"] and r["slack"]["sent"] is False
    log = client.get("/api/log").json()
    assert log[0]["status"] == "failure" and "timed out" in log[0]["error"]


def test_unknown_client_failure_is_committed(client):
    assert client.post("/api/onboarding", json={"client_id": "nope", "service": "SEO"}).status_code == 404
    log = client.get("/api/log").json()
    assert log[0]["status"] == "failure" and "nope" in log[0]["error"]
    # the database must not be left locked
    assert client.post("/api/test/forced-failure").status_code == 200


def test_onboarding_offline_creates_tasks_brief_and_email(client):
    r = client.post("/api/onboarding", json={"client_id": "c1", "service": "SEO"}).json()
    names = [s["name"] for s in r["steps"]]
    assert "Claude client brief" in names and len(r["brief"]["quick_wins"]) == 3
    assert r["engine"].startswith("offline engine")
    c = client.get("/api/clients/c1").json()
    assert sum(1 for t in c["tasks"] if t["status"] == "open") == 4 and c["emails"]
    # running it again doesn't duplicate tasks
    client.post("/api/onboarding", json={"client_id": "c1", "service": "SEO"})
    assert sum(1 for t in client.get("/api/clients/c1").json()["tasks"] if t["status"] == "open") == 4


def test_service_must_belong_to_client(client):
    assert client.post("/api/onboarding", json={"client_id": "c1", "service": "Web Design"}).status_code == 400


def test_add_client_runs_flow_then_offboarding(client):
    r = client.post("/api/clients", json={"name": "Test Bakery", "website": "https://bakery.example",
                                           "industry": "Food", "services": ["SEO", "Web Design"],
                                           "manager": "Sam", "manager_email": "sam@example.com"}).json()
    assert r["mode"] == "direct" and len(r["onboarding"]) == 2
    cid = r["client"]["id"]
    off = client.post(f"/api/clients/{cid}/churn").json()
    assert off["tasks_closed"] == 8
    assert client.get(f"/api/clients/{cid}").json()["status"] == "Archived"
    assert client.post(f"/api/clients/{cid}/churn").status_code == 400


def test_bad_client_input_rejected(client):
    assert client.post("/api/clients", json={"name": "X", "services": []}).status_code == 422
    assert client.post("/api/clients", json={"name": "Okay Name", "website": "notaurl", "services": ["SEO"]}).status_code == 400


def test_integrity_passes_and_writes_nothing(client):
    before = client.get("/api/dashboard").json()["kpis"]
    r = client.get("/api/integrity").json()
    assert r["all_ok"], r
    assert client.get("/api/dashboard").json()["kpis"] == before


def test_lineage_sql_reproduces_dashboard(client):
    d = client.get("/api/dashboard").json()
    lin = client.get("/api/lineage").json()["metrics"]
    k = lin[0]["sample"][0]
    assert round(float(k["spend"]), 2) == d["kpis"]["spend"]


def test_static_files_cannot_escape(client):
    for path in ["/..%2f..%2f..%2fetc%2fpasswd", "/%2e%2e/%2e%2e/etc/passwd", "/../app/config.py"]:
        r = client.get(path)
        assert "root:" not in r.text and "anthropic_api_key" not in r.text


def test_site_generate_regenerate_one_section(client):
    spec = {"business_name": "Fern & Field", "industry": "Florist", "tone": "warm",
            "services": ["Weddings", "Subscriptions", "Events"], "colour": "#2f855a"}
    s = client.post("/api/sites", json=spec).json()
    assert s["version"] == 1 and all(f'data-section="{x}"' in s["html"] for x in ["hero", "services", "proof", "cta"])
    r = client.post(f"/api/sites/{s['site_id']}/regenerate", json={"section": "services"}).json()
    assert r["version"] == 2

    def section(html, name):
        return re.search(rf'<section[^>]*data-section="{name}".*?</section>', html, re.S).group(0)
    assert section(r["html"], "services") != section(s["html"], "services")
    for other in ["hero", "proof", "cta"]:
        assert section(r["html"], other) == section(s["html"], other)
    p = client.get(f"/api/sites/{s['site_id']}/preview")
    assert p.status_code == 200 and "sandbox" in p.headers["content-security-policy"]
    assert client.post("/api/sites", json={**spec, "colour": "red"}).status_code == 400


def test_weekly_summary_three_sentences(client):
    r = client.post("/api/reporting/weekly-summary", json={}).json()
    assert len(r["clients"]) == 5 and all(len(c["sentences"]) == 3 for c in r["clients"])
    c2 = next(c for c in r["clients"] if c["client_id"] == "c2")
    assert "alert" in c2["sentences"][2]


def test_hooks_need_token(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path), today_fn=lambda: TODAY))
    assert c.post("/api/hooks/cron/daily-report").status_code == 503
    c2 = TestClient(create_app(make_settings(tmp_path, hub_api_token="s3cret"), today_fn=lambda: TODAY))
    assert c2.post("/api/hooks/cron/daily-report", headers={"X-Hub-Token": "nope"}).status_code == 401
    body = {"record_id": "recABC", "name": "Airtable Co", "services": "SEO, Paid Ads", "service": "Paid Ads"}
    r = c2.post("/api/hooks/make/onboarding", json=body, headers={"X-Hub-Token": "s3cret"}).json()
    assert r["steps"][0]["status"] == "ok" and r["service"] == "Paid Ads"
    off = c2.post("/api/hooks/make/offboarding", json={"record_id": "recABC"}, headers={"X-Hub-Token": "s3cret"}).json()
    assert off["tasks_closed"] == 4


def test_rate_limit(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path, rate_limit_per_minute=2), today_fn=lambda: TODAY))
    codes = [c.post("/api/test/forced-failure").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_mock_api_rejects_future(client):
    assert client.get("/api/mock/ad-platform/performance", params={"date": "2099-01-01"}).status_code == 400
    rows = client.get("/api/mock/ad-platform/performance", params={"date": TODAY.isoformat()}).json()["rows"]
    assert len(rows) == 15


def test_live_claude_output_is_used(tmp_path):
    """Regression for the old trailing-comma bug: a live answer must be used, not discarded."""
    s = make_settings(tmp_path, anthropic_api_key="test-key")
    llm = LLM(s)
    block = SimpleNamespace(type="tool_use", name="client_brief",
                            input={"audience": "Busy founders", "tone": "warm", "quick_wins": ["a", "b", "c"]})
    llm._client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(content=[block])))
    brief, label = llm.write_brief(mockdata.SEED_CLIENTS[0], "SEO", None)
    assert brief["audience"] == "Busy founders" and label.startswith("live Claude")


# ------------------------------------------------------------------------- real ad exports

GOOGLE = """Day,Account,Campaign,Cost,Clicks,Conversions
2026-11-18,Lumen Coffee Co.,Brand,"1,204.37",812,31
2026-11-18,Lumen Coffee Co.,Generic,95.13,77,2
2026-11-19,Lumen Coffee Co.,Brand,1310.02,850,29
2026-11-19,Nobody Ltd,Brand,10.00,1,0
2026-11-25,Lumen Coffee Co.,Brand,10.00,1,0
Total,,,2609.52,1739,62
"""


def test_import_google_ads_export_keeps_cents_and_sums_campaigns(client):
    r = client.post("/api/reporting/import?channel=Google%20Ads", content=GOOGLE.encode(), headers={"content-type": "text/csv"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["days_written"] == 2 and rep["skipped_count"] == 2 and rep["unknown_clients"] == ["Nobody Ltd"]
    assert any("in the future" in s["reason"] for s in rep["skipped"])
    engine = client.app.state.engine
    with engine.connect() as conn:
        got = conn.exec_driver_sql("SELECT date, spend, clicks, conversions FROM campaign_metrics "
                                   "WHERE client_id='c1' AND channel='Google Ads' AND date IN ('2026-11-18','2026-11-19') ORDER BY date").all()
    assert [(str(d), round(float(s), 2), c, v) for d, s, c, v in got] == [("2026-11-18", 1299.50, 889, 33), ("2026-11-19", 1310.02, 850, 29)]
    again = client.post("/api/reporting/import?channel=Google%20Ads", content=GOOGLE.encode()).json()
    assert again["duplicate_rows"] == 0  # re-importing replaces, never double counts


def test_import_meta_export_headers_and_bad_files(client):
    meta = "Reporting starts,Account name,Amount spent (USD),Link clicks,Results\n2026-11-19,c3,250.5,300,12\n"
    ok = client.post("/api/reporting/import?channel=Meta%20Ads", content=meta.encode()).json()
    assert ok["days_written"] == 1 and ok["clients"] == ["c3"]
    bad = client.post("/api/reporting/import", content=b"Day,Cost\n2026-11-19,5\n")
    assert bad.status_code == 422 and "Missing columns" in bad.json()["detail"]
    assert client.post("/api/reporting/import?channel=TikTok", content=meta.encode()).status_code == 422


def test_real_clients_never_get_simulated_numbers(client):
    created = client.post("/api/clients", json={"name": "Harbour Physio", "services": ["Paid Ads"]}).json()
    cid = created["client"]["id"]
    client.post("/api/reporting/job", json={"source": "mock-api"})
    with client.app.state.engine.connect() as conn:
        assert conn.exec_driver_sql(f"SELECT COUNT(*) FROM campaign_metrics WHERE client_id='{cid}'").scalar() == 0
    csv_text = f"Date,Client,Channel,Spend,Clicks,Conversions\n2026-11-19,Harbour Physio,google,120.40,60,4\n"
    assert client.post("/api/reporting/import", content=csv_text.encode()).status_code == 200
    rows = {r["client_id"]: r for r in client.get("/api/dashboard").json()["by_client"]}
    assert rows[cid]["simulated"] is False and rows[cid]["spend"] == 120.4 and rows["c1"]["simulated"] is True
