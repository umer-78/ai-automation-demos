from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Keep the module-level app (imported by app.main) away from any real .env / database.
_TMP = tempfile.mkdtemp(prefix="northwind-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/import.db"
os.environ["AUTO_SEED"] = "false"
os.environ["SEED_HISTORY"] = "false"  # tests check the seed against the spec; the history is a demo extra
os.environ["LIVE_SYNC_MINUTES"] = "0"
for key in (
    "ANTHROPIC_API_KEY",
    "SLACK_WEBHOOK_URL",
    "SMTP_HOST",
    "AIRTABLE_TOKEN",
    "AIRTABLE_BASE_ID",
    "MAKE_ONBOARDING_WEBHOOK_URL",
    "MAKE_OFFBOARDING_WEBHOOK_URL",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "AUTOMATION_API_KEY",
    "ADMIN_TOKEN",
    "OWNER_TOKEN",
    "VIEWER_TOKEN",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REFRESH_TOKEN",
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    "META_ACCESS_TOKEN",
):
    os.environ.pop(key, None)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


# Set TEST_DATABASE_URL (e.g. a local Postgres with supabase/schema.sql applied) to run the
# whole suite against Postgres instead of SQLite.
PG_URL = os.environ.get("TEST_DATABASE_URL", "")
TABLES = "clients, client_tasks, campaign_metrics, client_accounts, automation_log, site_drafts, notifications, weekly_summaries, kv_store, app_secrets"


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        _env_file=None,
        database_url=PG_URL or f"sqlite:///{tmp_path}/test.db",
        local_storage_dir=str(tmp_path / "storage"),
        anthropic_api_key="",
        slack_webhook_url="",
        smtp_host="",
        airtable_token="",
        airtable_base_id="",
        make_onboarding_webhook_url="",
        make_offboarding_webhook_url="",
        supabase_url="",
        supabase_service_role_key="",
        automation_api_key="",
        admin_token="",
        rate_limit_per_hour=1000,
        public_base_url="http://testserver",
        auto_seed=True,
        environment="development",
        live_sync_minutes=0,
    )
    base.update(overrides)
    return Settings(**base)


class FakeMessages:
    def __init__(self, handler: Callable[[str, dict[str, Any]], dict[str, Any]]):
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        tool = kwargs["tool_choice"]["name"]
        data = self.handler(tool, kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name=tool, input=data, id="toolu_test")],
            usage=SimpleNamespace(input_tokens=120, output_tokens=80),
            stop_reason="tool_use",
        )


class FakeAnthropic:
    """Mimics anthropic.Anthropic().messages.create for forced tool-use calls."""

    def __init__(self, handler: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None):
        self.messages = FakeMessages(handler or default_handler)


def default_handler(tool: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    prompt = kwargs["messages"][0]["content"]
    if tool == "submit_brief":
        return {
            "summary": "AI summary of the client.",
            "audience": "AI audience description.",
            "tone": "AI tone guidance.",
            "quick_wins": ["AI win one", "AI win two", "AI win three"],
            "kickoff_questions": ["Question A?", "Question B?"],
        }
    if tool == "submit_summaries":
        data = json.loads(prompt.split("Client data (JSON):\n", 1)[1].split("\n\nReturn", 1)[0])
        return {
            "summaries": [
                {"client_id": c["client_id"], "sentences": [f"AI one for {c['client']}.", "AI two.", "AI three."]}
                for c in data
            ]
        }
    if tool == "submit_site":
        return {
            "page_title": "AI Title",
            "meta_description": "AI description",
            "hero": '<span class="eyebrow">AI</span><h1 class="display" onclick="steal()">AI hero headline for the test</h1><script>alert(1)</script>',
            "services": '<div class="grid-3"><div class="card evil-class"><h3>Service one</h3><p>Details about service one.</p></div></div>',
            "proof": '<div class="stats"><div class="stat"><span class="stat-value"><span class="placeholder">[Add rating]</span></span></div></div><a href="javascript:alert(1)">x</a>',
            "cta": '<h2>Contact the AI team today</h2><a class="btn btn-primary" href="#cta">Book now please</a>',
        }
    if tool == "submit_section":
        return {"html": '<h1 class="display">Regenerated hero headline here</h1><img src=x onerror="bad()">'}
    raise AssertionError(f"unexpected tool {tool}")


@pytest.fixture(autouse=True)
def _clean_postgres():
    if PG_URL:
        from sqlalchemy import text

        from app.db import make_engine

        engine = make_engine(PG_URL)
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        engine.dispose()
    yield


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ctx(client):
    return client.app.state.ctx


@pytest.fixture
def ai_client(tmp_path: Path):
    fake = FakeAnthropic()
    app = create_app(make_settings(tmp_path), llm_client=fake)
    with TestClient(app) as c:
        c.fake = fake  # type: ignore[attr-defined]
        yield c


def sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])
