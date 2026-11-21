"""The demo's first start also runs a week of real workflows, so no screen starts empty."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import make_settings


def test_first_start_has_real_run_history(tmp_path):
    app = create_app(make_settings(tmp_path, auto_seed=True, seed_history=True))
    with TestClient(app) as c:
        logs = c.get("/api/automation/logs?limit=50").json()
        workflows = {row["workflow"] for row in logs}
        assert {"client_onboarding", "site_draft_generate"} <= workflows and any(w.startswith("daily") for w in workflows), workflows
        assert all(row["status"] == "success" for row in logs)
        times = [row["created_at"] for row in logs]
        assert len(set(times)) == len(times), "history is spread over the past days"
        assert c.get("/api/notifications?limit=5").json(), "the onboarding sent its Slack and email messages"
        assert c.get("/api/sites").json(), "a website draft exists to show as slabs"
