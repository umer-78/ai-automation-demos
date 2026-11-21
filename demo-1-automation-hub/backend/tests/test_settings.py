"""API keys saved from the Settings page: encrypted at rest, masked on the way out, applied live."""

from __future__ import annotations

from sqlalchemy import select

from app.api import settings as settings_api
from app.db import app_secrets
from app.main import create_app
from fastapi.testclient import TestClient

from .conftest import make_settings


def _provider(body, pid):
    return next(p for p in body["providers"] if p["id"] == pid)


def test_save_mask_apply_and_remove(client, ctx):
    body = client.get("/api/settings").json()
    assert _provider(body, "anthropic")["live"] is False

    key = "sk-ant-test-1234567890abcd"
    r = client.put("/api/settings/anthropic", json={"values": {"anthropic_api_key": key}})
    assert r.status_code == 200, r.text
    field = _provider(r.json(), "anthropic")["fields"][0]
    assert field["set"] and field["source"] == "saved"
    assert key not in r.text and field["preview"].endswith("abcd")
    assert ctx.settings.llm_live, "the saved key is applied without a restart"

    with ctx.engine.connect() as conn:
        stored = conn.execute(select(app_secrets.c.ciphertext)).scalar_one()
    assert key not in stored, "keys are encrypted at rest"

    assert client.get("/api/status").json()["integrations"]["ai"] != "offline templates"
    r = client.delete("/api/settings/anthropic")
    assert _provider(r.json(), "anthropic")["live"] is False
    assert not ctx.settings.llm_live


def test_unknown_fields_and_providers_are_refused(client):
    assert client.put("/api/settings/anthropic", json={"values": {"database_url": "sqlite://"}}).status_code == 422
    assert client.put("/api/settings/nope", json={"values": {"x": "y"}}).status_code == 404


def test_owner_token_guards_writes(tmp_path):
    app = create_app(make_settings(tmp_path, owner_token="owner-secret"))
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["owner_token_required"] is True
        bad = c.put("/api/settings/slack", json={"values": {"slack_webhook_url": "https://hooks.slack.com/services/T/B/x"}})
        assert bad.status_code == 401
        ok = c.put(
            "/api/settings/slack",
            json={"values": {"slack_webhook_url": "https://hooks.slack.com/services/T/B/x"}},
            headers={"X-Owner-Token": "owner-secret"},
        )
        assert ok.status_code == 200 and _provider(ok.json(), "slack")["live"] is True


def test_production_needs_owner_token_and_app_secret(tmp_path):
    app = create_app(make_settings(tmp_path, environment="production", admin_token="a", automation_api_key="b"))
    with TestClient(app) as c:
        r = c.put("/api/settings/slack", json={"values": {"slack_webhook_url": "https://hooks.slack.com/services/T/B/x"}})
        assert r.status_code == 403
    assert settings_api.router is not None
