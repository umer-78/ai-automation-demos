"""The acceptance criteria from the build spec, one test each (plus close variants)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, update

from app.db import automation_log, campaign_metrics, notifications
from app.workflows.metrics_pipeline import run_daily_metrics

NEW_CLIENT = {
    "name": "Coastal Coffee Roasters",
    "website": "https://coastalcoffee.example",
    "industry": "Food & beverage",
    "services": ["SEO", "Paid Ads", "Web Design"],
    "manager": "Elena Rossi",
    "manager_email": "elena@northwind-digital.example",
}


def _count(ctx, table, *where):
    with ctx.engine.connect() as conn:
        stmt = select(func.count()).select_from(table)
        for w in where:
            stmt = stmt.where(w)
        return conn.execute(stmt).scalar_one()


def test_seed_matches_spec(client, ctx):
    status = client.get("/api/status").json()
    assert status["counts"]["clients"] == 5
    assert status["counts"]["metric_rows"] == 5 * 3 * 60  # 5 clients, 3 channels, 60 days
    channels = {c["channel"] for c in client.get("/api/metrics/channels?days=60").json()["channels"]}
    assert channels == {"Google Ads", "Meta Ads", "SEO"}


def test_adding_a_client_runs_full_onboarding_without_manual_steps(client, ctx):
    resp = client.post("/api/clients", json=NEW_CLIENT)
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    run = client.get(f"/api/automation/runs/{run_id}").json()
    assert run["status"] == "success"
    log_row = run["log"][0]
    assert log_row["duration_ms"] < 120_000  # spec: under 2 minutes
    steps = [s["step"] for s in log_row["details"]["steps"]]
    assert steps.count("branch_done") == 3  # router: one branch per service
    assert {"client_synced", "brief_generated", "brief_saved", "done"} <= set(steps)

    detail = client.get(f"/api/clients/{log_row['client_id']}").json()
    assert detail["client"]["status"] == "active"
    assert "3 quick wins" in detail["client"]["brief"]
    assert len(detail["client"]["brief_data"]["quick_wins"]) == 3
    services = {t["service"] for t in detail["tasks"]}
    assert services == {"General", "SEO", "Paid Ads", "Web Design"}

    feed = client.get("/api/notifications").json()
    welcome = [n for n in feed if n["channel"] == "slack" and n["kind"] == "message" and "Coastal Coffee" in n["body"]]
    assert len(welcome) == 3  # one welcome per branch
    emails = [n for n in feed if n["channel"] == "email" and n["recipient"] == NEW_CLIENT["manager_email"]]
    assert emails and emails[0]["subject"].startswith("[DRAFT]")


def test_onboarding_is_idempotent_for_tasks(client, ctx):
    client.post("/api/clients", json=NEW_CLIENT)
    client.post("/api/clients", json=NEW_CLIENT)  # e.g. a retry
    cid = [c for c in client.get("/api/clients").json() if c["name"] == NEW_CLIENT["name"]][0]["id"]
    tasks = client.get(f"/api/clients/{cid}").json()["tasks"]
    titles = [(t["service"], t["title"]) for t in tasks]
    assert len(titles) == len(set(titles))


def test_rerunning_the_daily_job_twice_creates_no_duplicates(ctx):
    before = _count(ctx, campaign_metrics)
    first = run_daily_metrics(ctx, days=14)
    second = run_daily_metrics(ctx, days=14)
    after = _count(ctx, campaign_metrics)
    assert before == after == 900
    assert first["inserted"] == 0 and second["inserted"] == 0
    assert second["updated"] == 14 * 15
    # a full 60-day backfill, twice, still leaves exactly one row per client/date/channel
    run_daily_metrics(ctx, days=60)
    run_daily_metrics(ctx, days=60)
    with ctx.engine.connect() as conn:
        dupes = conn.execute(
            select(campaign_metrics.c.client_id, campaign_metrics.c.date, campaign_metrics.c.channel, func.count())
            .group_by(campaign_metrics.c.client_id, campaign_metrics.c.date, campaign_metrics.c.channel)
            .having(func.count() > 1)
        ).all()
    assert dupes == []
    assert _count(ctx, campaign_metrics) == 900


def test_pipeline_button_twice_via_api(client):
    a = client.post("/api/jobs/daily-metrics").json()
    b = client.post("/api/jobs/daily-metrics").json()
    assert a["total_rows"] == b["total_rows"] == 900
    assert b["inserted"] == 0


def test_forced_failure_shows_in_automation_log_and_slack(client, ctx):
    result = client.post("/api/demo/forced-failure").json()
    assert result["status"] == "failure"
    rows = client.get("/api/automation/logs?status=failure").json()
    assert rows and rows[0]["run_id"] == result["run_id"]
    assert "Deliberate test failure" in rows[0]["error"]
    alerts = [n for n in client.get("/api/notifications?channel=slack").json() if n["kind"] == "alert"]
    assert any(result["run_id"] in a["body"] for a in alerts)


def test_pipeline_failure_is_logged_and_alerted(ctx):
    try:
        run_daily_metrics(ctx, simulate_failure=True)
    except Exception:
        pass
    assert _count(ctx, automation_log, automation_log.c.workflow == "daily_metrics_pipeline", automation_log.c.status == "failure") == 1
    assert _count(ctx, notifications, notifications.c.kind == "alert") >= 1


def test_dashboard_reads_live_data_not_hardcoded_numbers(client, ctx):
    before = client.get("/api/metrics/overview?days=30").json()
    with ctx.engine.connect() as conn:
        db_spend = conn.execute(
            select(func.sum(campaign_metrics.c.spend)).where(campaign_metrics.c.date >= date.fromisoformat(before["period"]["start"]))
        ).scalar_one()
    assert abs(before["totals"]["spend"] - round(db_spend, 2)) < 0.05
    with ctx.engine.begin() as conn:  # change the database, the dashboard must follow
        conn.execute(update(campaign_metrics).where(campaign_metrics.c.date == date.fromisoformat(before["period"]["end"])).values(spend=campaign_metrics.c.spend + 100))
    after = client.get("/api/metrics/overview?days=30").json()
    assert after["totals"]["spend"] > before["totals"]["spend"] + 1000


def test_cpa_alert_badge_flags_only_the_spiking_campaign(client):
    alerts = client.get("/api/metrics/alerts").json()["alerts"]
    assert [(a["client"], a["channel"]) for a in alerts] == [("GreenLeaf Organics", "Meta Ads")]
    assert alerts[0]["change"] > 0.25
    overview = client.get("/api/metrics/overview").json()
    badges = {c["client"]: c["alerts"] for c in overview["clients"]}
    assert badges["GreenLeaf Organics"] == 1
    assert sum(badges.values()) == 1


def test_trend_and_channel_breakdown(client):
    trend = client.get("/api/metrics/trend?days=30").json()["series"]
    assert len(trend) == 30 and all(p["spend"] > 0 for p in trend)
    chans = client.get("/api/metrics/channels").json()["channels"]
    assert abs(sum(c["share_of_spend"] for c in chans) - 1) < 0.01


def test_weekly_summary_three_sentences_per_client(client):
    data = client.post("/api/summaries/weekly").json()
    assert len(data["summaries"]) == 5
    for s in data["summaries"]:
        assert len(s["sentences"]) == 3
    latest = client.get("/api/summaries/latest").json()
    assert latest["run_id"] == data["run_id"]


def test_offboarding_closes_tasks_archives_and_posts_summary(client):
    client.post("/api/clients", json=NEW_CLIENT)
    cid = [c for c in client.get("/api/clients").json() if c["name"] == NEW_CLIENT["name"]][0]["id"]
    run_id = client.post(f"/api/clients/{cid}/churn").json()["run_id"]
    assert client.get(f"/api/automation/runs/{run_id}").json()["status"] == "success"
    detail = client.get(f"/api/clients/{cid}").json()
    assert detail["client"]["status"] == "archived"
    assert all(t["status"] == "closed" for t in detail["tasks"])
    summaries = [n for n in client.get("/api/notifications").json() if n["kind"] == "summary" and "off-boarded" in n["body"]]
    assert summaries
    assert client.post(f"/api/clients/{cid}/churn").status_code == 409


def test_site_generator_and_regenerate_one_section(client):
    body = {
        "business_name": "Bloom & Co",
        "industry": "Florist",
        "tone": "friendly",
        "services": ["Wedding flowers", "Same-day delivery", "Workshops"],
        "colour": "rose",
    }
    v1 = client.post("/api/sites", json=body).json()
    assert v1["version"] == 1 and v1["html_url"]
    v2 = client.post(f"/api/sites/{v1['group_id']}/regenerate", json={"section": "hero"}).json()
    assert v2["version"] == 2 and v2["changed_section"] == "hero"
    assert v1["sections"]["hero"] != v2["sections"]["hero"]
    for key in ("services", "proof", "cta"):
        assert v1["sections"][key] == v2["sections"][key]
    preview = client.get(f"/sites/{v1['group_id']}/preview?v=2")
    assert preview.status_code == 200
    assert "default-src 'none'" in preview.headers["content-security-policy"]
    assert "<script" not in preview.text.lower()
    assert all(f'data-section="{k}"' in preview.text for k in ("hero", "services", "proof", "cta"))
