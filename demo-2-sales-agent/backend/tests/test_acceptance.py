"""The spec's acceptance criteria, one test each (offline mode: no API keys needed)."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select

from app.db import agent_runs, automation_log, drafts, leads, notifications
from app.services.research import normalize_url
from tests.conftest import wait_for_run


def run_agent(client) -> dict:
    resp = client.post("/api/agent/run")
    assert resp.status_code == 202, resp.text
    return wait_for_run(client, resp.json()["run_id"])


def test_seed_matches_the_spec(client, ctx):
    accounts = client.get("/api/accounts").json()
    assert len(accounts) == 50
    assert Counter(a["stage"] for a in accounts) == {"Prospect": 14, "Discovery": 13, "Proposal": 11, "Customer": 12}
    run_agent(client)
    flagged = client.get("/api/accounts").json()
    stalled = {a["company"] for a in flagged if "stalled" in a["flags"]}
    untouched = {a["company"] for a in flagged if "no_contact" in a["flags"]}
    upsell = {a["company"] for a in flagged if "upsell" in a["flags"]}
    assert len(stalled) == 8 and len(untouched) == 6 and len(upsell) == 5
    assert not (stalled & untouched) and not (upsell & untouched)
    for a in flagged:
        if a["flags"]:
            assert all(a["flag_reasons"][f] for f in a["flags"])


def test_one_click_gives_10_scored_leads_and_5_drafts_fast(client, ctx):
    run = run_agent(client)
    assert run["status"] == "completed", run
    assert run["duration_ms"] < 180_000
    assert run["leads_scored"] >= 10
    assert run["drafts_created"] == 5
    with ctx.engine.connect() as conn:
        scored = conn.execute(select(leads).where(leads.c.last_run_id == run["id"])).fetchall()
        outreach = conn.execute(select(drafts).where(drafts.c.run_id == run["id"], drafts.c.kind == "outreach")).fetchall()
    assert len(scored) >= 10
    assert len(outreach) == 5
    assert all(d.status == "pending" for d in outreach)


def test_every_score_has_a_reason_and_every_draft_cites_a_sourced_fact(client, ctx):
    run_agent(client)
    for lead in client.get("/api/leads").json():
        assert 0 <= lead["score"] <= 100
        assert lead["score_reason"].startswith(("Fit ", "Excluded by the ICP"))
        assert lead["source_url"].startswith("https://")
        assert lead["reason"]
        parts = lead["score_parts"]
        assert parts["fit"] <= 50 and parts["signals"] <= 30 and parts["recency"] <= 20
    for account in client.get("/api/accounts").json():
        assert account["score"] is not None and account["score_reason"].startswith("Fit ")
    for draft in client.get("/api/drafts?kind=outreach").json():
        lead = client.get(f"/api/leads/{draft['lead_id']}").json()
        fact_urls = {normalize_url(f["url"]) for f in lead["facts"]}
        assert normalize_url(draft["source_url"]) in fact_urls
        assert draft["cited_fact"] in {f["fact"] for f in lead["facts"]}


def test_no_path_sends_without_a_recorded_approval(client, ctx):
    run_agent(client)
    pending = client.get("/api/drafts?status=pending").json()
    draft = pending[0]
    assert client.get(f"/api/drafts/{draft['id']}/eml").status_code == 409
    assert client.post(f"/api/drafts/{draft['id']}/mark-sent").status_code == 409
    # tampering with the status column is not enough: approval must exist in the feedback table
    with ctx.engine.begin() as conn:
        conn.execute(drafts.update().where(drafts.c.id == draft["id"]).values(status="approved"))
    assert client.get(f"/api/drafts/{draft['id']}/eml").status_code == 409
    with ctx.engine.begin() as conn:
        conn.execute(drafts.update().where(drafts.c.id == draft["id"]).values(status="pending"))
    assert client.post(f"/api/drafts/{draft['id']}/approve", json={"reviewer": "Jordan"}).status_code == 200
    eml = client.get(f"/api/drafts/{draft['id']}/eml")
    assert eml.status_code == 200 and b"X-Unsent: 1" in eml.content
    assert client.post(f"/api/drafts/{draft['id']}/mark-sent").json()["status"] == "sent"


def test_rejected_reason_reaches_the_next_run(client, ctx):
    first = run_agent(client)
    draft = client.get("/api/drafts?status=pending&kind=outreach").json()[0]
    reason = "Too long and generic for a first email. Mention pricing."
    assert client.post(f"/api/drafts/{draft['id']}/reject", json={"reason": reason}).status_code == 200
    preview = client.get("/api/agent/context").json()
    assert reason in preview["feedback_block"] and reason in preview["system_prompt"]
    second = run_agent(client)
    assert second["id"] != first["id"]
    assert reason in second["context_feedback"]
    fb_id = client.get(f"/api/drafts/{draft['id']}").json()["feedback"][0]["id"]
    assert fb_id in second["feedback_ids"]


def test_every_run_is_logged_with_its_tool_calls(client, ctx):
    run = run_agent(client)
    tools = [t["tool"] for t in run["tools_called"]]
    for name in ("read_knowledge", "save_icp", "search_web", "save_lead", "analyze_crm", "draft_outreach", "draft_follow_up", "finish"):
        assert name in tools
    assert run["tool_call_count"] == len(tools)
    with ctx.engine.connect() as conn:
        logged = conn.execute(select(automation_log).where(automation_log.c.run_id == run["id"])).first()
        stored = conn.execute(select(agent_runs).where(agent_runs.c.id == run["id"])).first()
    assert logged.status == "success" and logged.workflow == "agent_run"
    assert stored.tools_called and stored.outcome


def test_weekly_report_renders_from_live_data(client, ctx):
    empty = client.get("/api/report/weekly").json()
    assert empty["leads"]["total"] == 0 and "Run agent" in empty["headline"][0]
    run_agent(client)
    rep = client.get("/api/report/weekly").json()
    assert rep["leads"]["total"] == len(client.get("/api/leads").json())
    assert len(rep["stalled"]) == 8 and len(rep["no_contact"]) == 6 and len(rep["upsell"]) == 5
    assert len(rep["pending_drafts"]) == len(client.get("/api/drafts?status=pending").json())
    md = client.get("/api/report/weekly.md")
    assert md.status_code == 200 and md.text.startswith("# Weekly sales report")
    assert rep["leads"]["top"][0]["company"] in md.text


def test_failures_are_logged_and_alerted(client, ctx):
    resp = client.post("/api/automation/test-failure").json()
    assert resp["logged"] is True
    with ctx.engine.connect() as conn:
        row = conn.execute(select(automation_log).where(automation_log.c.run_id == resp["run_id"])).first()
        alert = conn.execute(select(notifications).where(notifications.c.kind == "alert")).first()
    assert row.status == "failure" and "Deliberate test failure" in row.error
    assert alert is not None and "forced_failure_check" in alert.body
