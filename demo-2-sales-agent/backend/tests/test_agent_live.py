"""The live tool-use loop, driven by a scripted fake model (no network)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import automation_log, drafts, notifications
from app.main import create_app
from tests.conftest import FakeAnthropic, ScriptedAgent, make_settings, wait_for_run


def live_client(tmp_path, agent: ScriptedAgent):
    fake = FakeAnthropic(agent)
    app = create_app(make_settings(tmp_path), llm_client=fake)
    return TestClient(app), fake


def test_live_loop_uses_tools_and_guards_provenance(tmp_path):
    agent = ScriptedAgent()
    client, fake = live_client(tmp_path, agent)
    with client:
        run = wait_for_run(client, client.post("/api/agent/run").json()["run_id"])
        assert run["mode"] == "live" and run["status"] == "completed_with_fallback", run  # 3 follow-ups filled in
        assert run["turns"] == 7
        assert run["tokens"] == 7 * 1200 and run["cost_usd"] > 0
        # the made-up company with an unseen URL was refused
        assert any("was not returned by search_web" in e for e in agent.lead_errors)
        names = {l["company"] for l in client.get("/api/leads").json()}
        assert "Imaginary Corp" not in names and len(names) >= 10
        # drafts written by the model are marked as AI drafts
        ai = client.get("/api/drafts?kind=outreach").json()
        assert len(ai) == 5 and all(d["generated_by"] == "ai" for d in ai)
        assert len(client.get("/api/drafts?kind=follow_up").json()) == 5  # 2 by the model + 3 by the fallback
        assert "Completed by the fallback planner" in run["outcome"]
        # the system prompt carries the hard rules and the feedback slot
        system = fake.messages.calls[0]["system"][0]["text"]
        assert "You cannot send anything" in system and "Reviewer feedback from recent runs" in system
        tools = {t["name"] for t in fake.messages.calls[0]["tools"]}
        assert not any(word in name for name in tools for word in ("send", "email", "post", "slack"))


def test_live_run_survives_an_api_outage(tmp_path):
    agent = ScriptedAgent(fail_on_turn=3)
    client, _ = live_client(tmp_path, agent)
    with client:
        run = wait_for_run(client, client.post("/api/agent/run").json()["run_id"])
        assert run["status"] == "completed_with_fallback"
        assert run["leads_scored"] >= 10 and run["drafts_created"] == 5
        ctx = client.app.state.ctx
        with ctx.engine.connect() as conn:
            failure = conn.execute(select(automation_log).where(automation_log.c.workflow == "agent_ai_call")).first()
            alert = conn.execute(select(notifications).where(notifications.c.kind == "alert")).first()
            template = conn.execute(select(drafts).where(drafts.c.generated_by == "template")).first()
        assert failure.status == "failure" and "simulated API outage" in failure.error
        assert alert is not None
        assert template is not None


def test_model_drafts_must_follow_learned_rules(tmp_path):
    """After a 'too long' rejection, a long model draft is bounced back by the guardrail."""
    agent = ScriptedAgent(bad_url=False)
    client, _ = live_client(tmp_path, agent)
    with client:
        wait_for_run(client, client.post("/api/agent/run").json()["run_id"])
        draft = client.get("/api/drafts?status=pending&kind=outreach").json()[0]
        client.post(f"/api/drafts/{draft['id']}/reject", json={"reason": "Way too long, keep it short."})
        ctx = client.app.state.ctx
        from app.agent.tools import RunState, ToolBox
        from app.db import utcnow
        from app.workflows import learning
        from app.workflows.icp import active_icp

        fb = learning.build_context(ctx.engine, 20)
        assert fb["lessons"].max_words == 90
        state = RunState(run_id="t", mode="live", now=utcnow(), icp=active_icp(ctx.engine)["criteria"],
                         icp_version=1, lessons=fb["lessons"], target_leads=12, target_drafts=5, target_followups=5,
                         rep={"name": "Jordan Reyes", "title": "AE", "company": "Acme"})
        tb = ToolBox(ctx, state)
        lead = client.get(f"/api/leads/{draft['lead_id']}").json()
        long_body = f"Hi {lead['company']} team,\n\n" + ("We help with SOC 2 and ISO 27001 evidence. " * 20) + "\n\nJordan"
        result, ok = tb.call("draft_outreach", {"lead_id": lead["id"], "subject": "Hello", "body": long_body,
                                                "cited_fact": lead["facts"][0]["fact"], "source_url": lead["facts"][0]["url"]})
        assert not ok and "limit at 90" in result["error"]
        named = f"Hi Sarah,\n\n{lead['facts'][0]['fact']} We keep evidence current.\n\nJordan"
        result, ok = tb.call("draft_outreach", {"lead_id": lead["id"], "subject": "Hello", "body": named,
                                                "cited_fact": lead["facts"][0]["fact"], "source_url": lead["facts"][0]["url"]})
        assert not ok and "Never use a person's name" in result["error"]
