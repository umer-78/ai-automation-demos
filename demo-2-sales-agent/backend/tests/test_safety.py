"""'Anything an agent sends to a customer waits for human approval' is enforced by design."""

from __future__ import annotations

import re
from pathlib import Path

from app.agent.tools import TOOL_SCHEMAS

APP = Path(__file__).resolve().parents[1] / "app"


def test_the_agent_has_no_tool_that_can_send():
    names = [t["name"] for t in TOOL_SCHEMAS]
    assert names == [
        "read_knowledge", "save_icp", "search_web", "read_page", "save_lead", "analyze_crm",
        "get_account_activity", "list_leads", "draft_outreach", "draft_follow_up", "finish",
    ]
    for tool in TOOL_SCHEMAS:
        assert not re.search(r"send|mail|post|slack|message", tool["name"])


def test_the_codebase_has_no_email_client():
    banned = re.compile(r"^\s*(import smtplib|from smtplib|import aiosmtplib|import sendgrid|import boto3|from email\.mime)", re.M)
    for path in APP.rglob("*.py"):
        assert not banned.search(path.read_text(encoding="utf-8")), f"{path} imports an email client"


def test_only_the_internal_slack_webhook_is_called():
    """Outbound POSTs go to the internal Slack webhook, the search API, HubSpot batch *reads* and the
    Settings test buttons (a Slack test message, one Tavily search). None of them can reach a customer."""
    posts: dict[str, list[str]] = {}
    for path in APP.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"\.post\(", line) and "@router.post" not in line:
                posts.setdefault(path.relative_to(APP).as_posix(), []).append(line.strip())
    assert sorted(posts) == ["api/settings.py", "services/hubspot.py", "services/notify.py", "services/research.py"]
    assert all("/batch/read" in line for line in posts["services/hubspot.py"]), "HubSpot is only read, never written"
    assert all("slack_webhook_url" in line or "api.tavily.com/search" in line for line in posts["api/settings.py"])


def test_review_actions_validate_input(client):
    assert client.post("/api/drafts/999/approve").status_code == 404
    assert client.post("/api/drafts/999/reject", json={"reason": "no"}).status_code == 422
    assert client.get("/api/drafts/999/eml").status_code == 404


def test_admin_reset_needs_a_token(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings

    with TestClient(create_app(make_settings(tmp_path))) as c:
        assert c.post("/api/admin/reset").status_code == 403
    with TestClient(create_app(make_settings(tmp_path, admin_token="s3cret"))) as c:
        assert c.post("/api/admin/reset").status_code == 401
        resp = c.post("/api/admin/reset", headers={"X-Admin-Token": "s3cret"})
        assert resp.status_code == 200 and resp.json()["accounts"] == 50


def test_scheduled_endpoints_need_the_automation_key(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings, wait_for_run

    with TestClient(create_app(make_settings(tmp_path, automation_api_key="k3y"))) as c:
        assert c.post("/api/automation/run-agent").status_code == 401
        assert c.post("/api/automation/weekly-report").status_code == 401
        run = c.post("/api/automation/run-agent", headers={"X-Automation-Key": "k3y"})
        assert run.status_code == 202
        done = wait_for_run(c, run.json()["run_id"])
        assert done["trigger"] == "schedule"
        rep = c.post("/api/automation/weekly-report", headers={"X-Automation-Key": "k3y"}).json()
        assert rep["slack"] == "simulated" and len(rep["headline"]) == 3


def test_public_run_button_is_rate_limited(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings, wait_for_run

    with TestClient(create_app(make_settings(tmp_path, agent_runs_per_hour=1))) as c:
        first = c.post("/api/agent/run")
        assert first.status_code == 202
        wait_for_run(c, first.json()["run_id"])
        assert c.post("/api/agent/run").status_code == 429
