"""Real numbers: benchmark-true demo data, CSV imports, live ad accounts and the access lock."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import campaign_metrics, clients, today_utc
from app.main import create_app
from app.seed import seed_demo
from app.services import connectors
from app.workflows.analytics import poisson_cdf
from app.workflows.synthetic import BENCHMARKS, SEED_CLIENTS, SPIKE_CHANNEL, SPIKE_CLIENT, benchmark_category

from .conftest import make_settings

OWNER = {"X-Owner-Token": "owner-code-123"}


@pytest.fixture
def locked(tmp_path):
    app = create_app(make_settings(tmp_path, owner_token="owner-code-123", viewer_token="viewer-code-456"))
    with TestClient(app) as c:
        yield c


def _sums(ctx):
    with ctx.engine.connect() as conn:
        rows = conn.execute(select(campaign_metrics)).fetchall()
    return {
        "spend": round(sum(r.spend for r in rows), 2),
        "clicks": sum(r.clicks for r in rows),
        "impressions": sum(r.impressions for r in rows),
        "conversions": round(sum(r.conversions for r in rows), 2),
        "rows": len(rows),
    }


# ------------------------------------------------------------------------------ demo data
def test_demo_numbers_follow_published_2026_medians(client, ctx):
    names = {}
    with ctx.engine.connect() as conn:
        for r in conn.execute(select(clients.c.id, clients.c.name, clients.c.industry)):
            names[r.id] = (r.name, r.industry)
        rows = conn.execute(select(campaign_metrics)).fetchall()
    spike_from = today_utc() - timedelta(days=7)
    agg = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for r in rows:
        name, _ = names[r.client_id]
        if name == SPIKE_CLIENT and r.channel == SPIKE_CHANNEL and r.date >= spike_from:
            continue  # the scripted spike is meant to break the pattern
        a = agg[(name, r.channel)]
        a[0] += r.impressions
        a[1] += r.clicks
        a[2] += r.spend
        a[3] += r.conversions
    for spec in SEED_CLIENTS:
        bench = BENCHMARKS[benchmark_category(spec["industry"])]
        g = agg[(spec["name"], "Google Ads")]
        ctr, cpc, cpl = bench["google"]
        assert g[2] / g[1] == pytest.approx(cpc, rel=0.2), spec["name"]
        assert g[2] / g[3] == pytest.approx(cpl, rel=0.25), spec["name"]
        assert g[1] / g[0] == pytest.approx(ctr, rel=0.25), spec["name"]
        m = agg[(spec["name"], "Meta Ads")]
        mctr, mcvr, mcpl = bench["meta"]
        assert m[2] / m[3] == pytest.approx(mcpl, rel=0.25), spec["name"]
        assert m[3] / m[1] == pytest.approx(mcvr, rel=0.25), spec["name"]
        s = agg[(spec["name"], "SEO")]
        assert s[1] / s[0] == pytest.approx(0.015, rel=0.25)


def test_poisson_guard_ignores_noise_and_catches_real_drops():
    assert poisson_cdf(3, 5) == pytest.approx(0.2650, abs=1e-3)  # 3 instead of 5: ordinary noise
    assert poisson_cdf(0, 3) == pytest.approx(0.0498, abs=1e-3)
    assert 0 < poisson_cdf(400, 500) < 1e-5  # large counts do not underflow
    assert poisson_cdf(10, 0) == 1.0


def test_alerts_carry_their_evidence(client):
    alerts = client.get("/api/metrics/alerts").json()["alerts"]
    assert [(a["client"], a["channel"]) for a in alerts] == [(SPIKE_CLIENT, SPIKE_CHANNEL)]
    a = alerts[0]
    assert a["p_value"] < 0.05 and a["expected_conversions"] > a["conversions_this_week"]


# ------------------------------------------------------------------------------ CSV import
META_EXPORT = (
    "Reporting starts,Account name,Platform,Impressions,Link clicks,Amount spent (USD),Results\n"
    "{d1},Northside Physio,facebook,\"12,400\",210,$310.55,12\n"
    "{d1},Northside Physio,Google,8800,340,\"$1,020.10\",19\n"
    "{d2},Northside Physio,facebook,11950,198,298.10,9\n"
    "{d2},Northside Physio,TikTok,5000,50,90,1\n"
)


def _us(d):
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def test_csv_import_replaces_demo_and_totals_match_the_file(client, ctx):
    d1, d2 = today_utc() - timedelta(days=3), today_utc() - timedelta(days=2)
    r = client.post("/api/data/import", json={"csv": META_EXPORT.format(d1=_us(d1), d2=_us(d2))})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["demo_removed"] and body["new_clients"] == ["Northside Physio"]
    assert body["rows"] == 3 and body["skipped_count"] == 1 and "TikTok" in body["skipped"][0]

    with ctx.engine.connect() as conn:
        names = [r.name for r in conn.execute(select(clients.c.name))]
    assert names == ["Northside Physio"], "no demo client survives next to real data"
    assert _sums(ctx) == {"spend": 1628.75, "clicks": 748, "impressions": 33150, "conversions": 40.0, "rows": 3}

    totals = client.get("/api/metrics/overview?days=7").json()["totals"]
    assert totals["spend"] == pytest.approx(1628.75) and totals["conversions"] == pytest.approx(40)
    assert totals["cpa"] == pytest.approx(1628.75 / 40, rel=1e-3)

    st = client.get("/api/data/status").json()
    assert st["mode"] == "real" and st["label"] == "Your data"
    assert st["last_import"]["at"].endswith("+00:00"), "times carry their zone so browsers show the right age"
    assert seed_demo(ctx)["seeded"] is False, "a restart never brings sample clients back"
    assert client.post("/api/jobs/daily-metrics").json()["fetched"] == 0, "nothing synthetic is generated in real mode"
    assert _sums(ctx)["rows"] == 3


def test_import_reads_day_first_dates_and_rejects_the_future(client, ctx):
    d = today_utc() - timedelta(days=40)
    d = d.replace(day=20)  # a day above 12 tells the importer the column is day-first
    day_first = f"date,client,channel,clicks,spend,conversions\n{d.day:02d}/{d.month:02d}/{d.year},A,SEO,10,5,1\n05/{d.month:02d}/{d.year},A,SEO,11,5,1\n"
    r = client.post("/api/data/import", json={"csv": day_first})
    assert r.status_code == 200, r.text
    with ctx.engine.connect() as conn:
        dates = sorted(r.date for r in conn.execute(select(campaign_metrics.c.date)))
    assert dates == [d.replace(day=5), d]
    future = (today_utc() + timedelta(days=2)).isoformat()
    r = client.post("/api/data/import", json={"csv": f"date,client,channel,clicks,spend,conversions\n{future},A,SEO,1,1,1\n"})
    assert r.status_code == 422 and "future" in r.json()["detail"]
    r = client.post("/api/data/import", json={"csv": "day,client,clicks\n2026-01-01,A,3\n"})
    assert r.status_code == 422 and "channel" in r.json()["detail"]


def test_back_to_demo_restores_the_sample(client, ctx):
    client.post("/api/data/real")
    assert _sums(ctx)["rows"] == 0
    assert client.post("/api/data/demo").json()["mode"] == "demo"
    assert _sums(ctx)["rows"] > 500


# ------------------------------------------------------------------------------ access lock
def test_real_data_needs_an_access_code(locked):
    assert locked.get("/api/metrics/overview").status_code == 200, "demo data stays public"
    assert locked.post("/api/data/real").status_code == 401
    assert locked.post("/api/data/real", headers=OWNER).status_code == 200

    r = locked.get("/api/metrics/overview")
    assert r.status_code == 401 and r.json()["locked"] is True
    st = locked.get("/api/status").json()
    assert st["locked"] is True and "counts" not in st
    assert locked.get("/api/metrics/overview", headers=OWNER).status_code == 200
    viewer = {"X-Owner-Token": "viewer-code-456"}
    assert locked.get("/api/clients", headers=viewer).status_code == 200, "teammates can read"
    assert locked.get("/api/data/accounts", headers=viewer).status_code == 401, "but not manage accounts"
    assert locked.get("/api/health").status_code == 200


# ------------------------------------------------------------------------------ live accounts
class FakePlatforms:
    """Google OAuth, Google Ads, Meta Marketing API, Search Console and GA4 in one transport."""

    def __init__(self, day1: str, day2: str):
        self.day1, self.day2 = day1, day2
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = request.url
        if url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
        if url.host == "googleads.googleapis.com":
            assert request.headers["developer-token"] == "dev-token"
            assert request.headers["login-customer-id"] == "1112223333"
            assert request.headers["authorization"] == "Bearer ya29.test"
            assert "/customers/1234567890/googleAds:searchStream" in url.path
            results = [
                {"segments": {"date": self.day1}, "customer": {"currencyCode": "USD"}, "metrics": {"impressions": "1500", "clicks": "75", "costMicros": "412350000", "conversions": 4.5}},
                {"segments": {"date": self.day2}, "customer": {"currencyCode": "USD"}, "metrics": {"impressions": "1320", "clicks": "61", "costMicros": "380000000", "conversions": 3.0}},
            ]
            return httpx.Response(200, json=[{"results": results}])
        if url.host == "graph.facebook.com":
            assert request.headers["authorization"] == "Bearer meta-token"
            assert "access_token" not in str(url)
            if "act_777" in url.path:  # an account in another currency
                return httpx.Response(200, json={"data": [{"date_start": self.day1, "impressions": "10", "clicks": "1", "spend": "5", "actions": [], "account_currency": "EUR"}]})
            if "after=cursor2" in str(url):
                return httpx.Response(200, json={"data": [{"date_start": self.day2, "impressions": "9000", "clicks": "300", "inline_link_clicks": "120", "spend": "150.25", "account_currency": "USD", "actions": [{"action_type": "lead", "value": "6"}, {"action_type": "link_click", "value": "120"}]}]})
            params = parse_qs(url.query.decode())
            assert set(json.loads(params["time_range"][0])) == {"since", "until"}
            assert params["time_increment"] == ["1"] and params["level"] == ["account"]
            return httpx.Response(
                200,
                json={
                    "data": [{"date_start": self.day1, "impressions": "8000", "clicks": "280", "inline_link_clicks": "110", "spend": "140.00", "account_currency": "USD", "actions": [{"action_type": "lead", "value": "5"}, {"action_type": "purchase", "value": "1"}, {"action_type": "post_engagement", "value": "300"}]}],
                    "paging": {"next": "https://graph.facebook.com/v26.0/act_42/insights?after=cursor2"},
                },
            )
        if url.host == "www.googleapis.com":
            assert "sc-domain%3Aacme.example" in str(url)
            return httpx.Response(200, json={"rows": [{"keys": [self.day1], "clicks": 40, "impressions": 2600}, {"keys": [self.day2], "clicks": 38, "impressions": 2500}]})
        if url.host == "analyticsdata.googleapis.com":
            body = json.loads(request.content)
            assert body["dimensionFilter"]["filter"]["stringFilter"]["value"] == "Organic Search"
            return httpx.Response(200, json={"rows": [{"dimensionValues": [{"value": self.day1.replace("-", "")}], "metricValues": [{"value": "2"}]}]})
        raise AssertionError(f"unexpected call {request.method} {url}")


@pytest.fixture
def live(tmp_path, monkeypatch):
    s = make_settings(
        tmp_path,
        google_oauth_client_id="cid.apps.googleusercontent.com",
        google_oauth_client_secret="secret",
        google_oauth_refresh_token="1//refresh",
        google_ads_developer_token="dev-token",
        google_ads_login_customer_id="111-222-3333",
        meta_access_token="meta-token",
    )
    d1, d2 = (today_utc() - timedelta(days=3)).isoformat(), (today_utc() - timedelta(days=2)).isoformat()
    fake = FakePlatforms(d1, d2)
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(fake))
    connectors._tokens.clear()
    with TestClient(create_app(s)) as c:
        c.fake = fake  # type: ignore[attr-defined]
        yield c


def test_accounts_need_real_mode(live):
    r = live.put("/api/data/accounts", json={"name": "Acme", "accounts": {"google_ads": "1234567890"}})
    assert r.status_code == 409


def test_live_sync_stores_exactly_what_the_platforms_report(live):
    ctx = live.app.state.ctx
    live.post("/api/data/real")
    r = live.put(
        "/api/data/accounts",
        json={"name": "Acme Dental", "accounts": {"google_ads": "123-456-7890", "meta_ads": "42", "search_console": "sc-domain:acme.example", "ga4": "properties/987", "seo_fee": "$1,500"}},
    )
    assert r.status_code == 200, r.text
    acme = next(c for c in r.json()["clients"] if c["name"] == "Acme Dental")
    assert acme["accounts"] == {"google_ads": "123-456-7890", "meta_ads": "act_42", "search_console": "sc-domain:acme.example", "ga4": "987", "seo_fee": "1500.00"}
    live.put("/api/data/accounts", json={"name": "Euro Client", "accounts": {"meta_ads": "777"}})

    assert live.get("/api/data/status").json()["live_sources"] == ["Google Ads", "Meta Ads", "Search Console", "Google Analytics"]
    result = live.post("/api/data/sync?days=7").json()
    assert result["status"] == "success" and any("EUR" in w for w in result["warnings"])

    with ctx.engine.connect() as conn:
        rows = {(r.channel, r.date.isoformat()): r for r in conn.execute(select(campaign_metrics))}
    d1, d2 = live.fake.day1, live.fake.day2
    g = rows[("Google Ads", d1)]
    assert (g.impressions, g.clicks, g.spend, g.conversions) == (1500, 75, 412.35, 4.5)
    m1, m2 = rows[("Meta Ads", d1)], rows[("Meta Ads", d2)]
    assert (m1.clicks, m1.spend, m1.conversions) == (110, 140.0, 6.0), "link clicks; leads + purchases only"
    assert (m2.clicks, m2.spend, m2.conversions) == (120, 150.25, 6.0), "the second page of results is read"
    s1, s2 = rows[("SEO", d1)], rows[("SEO", d2)]
    import calendar
    from datetime import date as _date

    days_in_month = calendar.monthrange(_date.fromisoformat(d1).year, _date.fromisoformat(d1).month)[1]
    assert (s1.clicks, s1.impressions, s1.conversions) == (40, 2600, 2.0)
    assert s1.spend == round(1500 / days_in_month, 2) and s2.conversions == 0
    assert len(rows) == 6, "the EUR account was left out instead of being added to USD totals"

    st = live.get("/api/status").json()
    assert st["data"]["label"] == "Live data" and st["data"]["last_sync"]["source"] == "dashboard"


def test_first_sync_backfills_so_30_day_totals_are_complete(live):
    live.post("/api/data/real")
    live.put("/api/data/accounts", json={"name": "Acme Dental", "accounts": {"meta_ads": "42"}})

    def meta_range() -> int:
        req = [r for r in live.fake.calls if r.url.host == "graph.facebook.com" and "after=" not in str(r.url)][-1]
        rng = json.loads(parse_qs(req.url.query.decode())["time_range"][0])
        return (date.fromisoformat(rng["until"]) - date.fromisoformat(rng["since"])).days + 1

    assert live.post("/api/data/sync").json()["status"] == "success"
    assert meta_range() == 60, "a new client gets 60 days: 30-day totals plus the period they are compared with"
    live.post("/api/data/sync")
    assert meta_range() == 14, "after that only the window platforms still restate is re-read"
    live.put("/api/data/accounts", json={"name": "Bright Smile", "accounts": {"meta_ads": "43"}})
    live.post("/api/data/sync")
    assert meta_range() == 60, "a client linked later is backfilled too"


def test_discover_lists_accounts_with_names(live, monkeypatch):
    live.post("/api/data/real")
    monkeypatch.setattr(connectors, "google_ads_accounts", lambda s: [{"id": "1234567890", "name": "Acme Dental", "currency": "USD"}])
    monkeypatch.setattr(connectors, "meta_accounts", lambda s: [{"id": "42", "name": "Acme Dental FB", "currency": "USD"}])
    monkeypatch.setattr(connectors, "search_console_sites", lambda s: [{"id": "sc-domain:acme.example", "name": "sc-domain:acme.example"}])

    def broken(s):
        raise connectors.ConnectorError("Google Analytics: permission denied (HTTP 403)")

    monkeypatch.setattr(connectors, "ga4_properties", broken)
    body = live.get("/api/data/discover").json()
    assert body["google_ads"]["items"][0]["name"] == "Acme Dental"
    assert body["ga4"]["error"].startswith("Google Analytics")


def test_google_sign_in_round_trip(live, monkeypatch):
    start = live.post("/api/data/google/start").json()
    q = parse_qs(urlparse(start["url"]).query)
    assert q["access_type"] == ["offline"] and "adwords" in q["scope"][0] and q["redirect_uri"] == [start["redirect_uri"]]
    monkeypatch.setattr(connectors, "google_exchange_code", lambda s, code, redirect: "1//new-refresh")
    r = live.get("/api/data/google/callback", params={"code": "abc", "state": q["state"][0]}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("google=connected")
    assert live.app.state.ctx.settings.google_oauth_refresh_token == "1//new-refresh"
    bad = live.get("/api/data/google/callback", params={"code": "abc", "state": "1.forged"}, follow_redirects=False)
    assert bad.headers["location"].endswith("google=expired")
