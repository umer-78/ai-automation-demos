from __future__ import annotations

import itertools
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Keep the module-level app (imported by app.main) away from any real .env / database.
_TMP = tempfile.mkdtemp(prefix="acme-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/import.db"
os.environ["AUTO_SEED"] = "false"
os.environ["HUBSPOT_SYNC_MINUTES"] = "0"
for key in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY", "SLACK_WEBHOOK_URL", "AUTOMATION_API_KEY", "ADMIN_TOKEN", "OWNER_TOKEN", "VIEWER_TOKEN", "HUBSPOT_TOKEN", "APP_SECRET"):
    os.environ.pop(key, None)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import ALL_TABLES  # noqa: E402
from app.main import create_app  # noqa: E402

PG_URL = os.environ.get("TEST_DATABASE_URL", "")  # run the suite on Postgres (schema.sql applied) when set
SNAPSHOT = json.loads((BACKEND / "data" / "research_snapshot.json").read_text())["results"]
BY_URL = {e["url"]: e for e in SNAPSHOT}


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = dict(
        _env_file=None,
        database_url=PG_URL or f"sqlite:///{tmp_path}/test.db",
        anthropic_api_key="",
        tavily_api_key="",
        slack_webhook_url="",
        automation_api_key="",
        admin_token="",
        agent_runs_per_hour=1000,
        review_actions_per_hour=1000,
        public_base_url="http://testserver",
        auto_seed=True,
        environment="development",
        hubspot_token="",
        hubspot_sync_minutes=0,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _clean_postgres():
    if PG_URL:
        from sqlalchemy import text

        from app.db import make_engine

        engine = make_engine(PG_URL)
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE"))
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


def wait_for_run(client: TestClient, run_id: str, timeout: float = 180) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


# ------------------------------------------------------------------------------ fake model
def tool_use(name: str, payload: dict[str, Any], ids=itertools.count(1)) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=f"toolu_{next(ids)}", name=name, input=payload)


def last_results(messages: list[dict[str, Any]]) -> list[Any]:
    """Tool results (parsed JSON) from the newest user message."""
    content = messages[-1]["content"]
    if isinstance(content, str):
        return []
    out = []
    for block in content:
        if block.get("type") == "tool_result":
            try:
                out.append(json.loads(block["content"]))
            except (ValueError, TypeError):
                out.append(block["content"])
    return out


class ScriptedAgent:
    """Plays the model's side of the tool-use loop, turn by turn, like a well-behaved agent."""

    def __init__(self, *, bad_url: bool = True, fail_on_turn: int | None = None):
        self.turn = 0
        self.bad_url = bad_url
        self.fail_on_turn = fail_on_turn
        self.calls: list[dict[str, Any]] = []
        self.seen_urls: list[str] = []
        self.lead_errors: list[str] = []

    def __call__(self, kwargs: dict[str, Any]) -> list[SimpleNamespace]:
        self.turn += 1
        if self.fail_on_turn and self.turn >= self.fail_on_turn:
            raise RuntimeError("simulated API outage")
        msgs = kwargs["messages"]
        results = last_results(msgs)
        if self.turn == 1:
            return [SimpleNamespace(type="text", text="Reading the notes first.")] + [
                tool_use("read_knowledge", {"doc": d}) for d in ("product", "competitors", "deal_notes")
            ]
        if self.turn == 2:
            return [
                tool_use("save_icp", {
                    "summary": "B2B SaaS and fintech companies with 50 to 1,000 staff, cloud-first, under SOC 2 or ISO 27001 pressure.",
                    "target_categories": ["b2b_saas", "fintech", "devtools", "vertical_software", "healthtech", "data_ai"],
                    "excluded_categories": ["security_vendor", "services"],
                    "employee_min": 50, "employee_max": 1000,
                    "regions": ["North America", "Europe", "UK & Ireland", "ANZ"],
                    "signal_weights": {"compliance": 30, "security_leader": 26, "funding": 22},
                }),
                tool_use("search_web", {"query": "SaaS company completes SOC 2 Type II audit 2026"}),
                tool_use("search_web", {"query": "software company achieves ISO 27001 certification 2026"}),
                tool_use("search_web", {"query": "SaaS raises Series B funding 2026"}),
            ]
        if self.turn == 3:
            blocks = []
            for r in results:
                if isinstance(r, dict) and "results" in r:
                    for item in r["results"]:
                        if item["url"] in BY_URL and item["url"] not in self.seen_urls:
                            self.seen_urls.append(item["url"])
            for url in self.seen_urls[:14]:
                e = BY_URL[url]
                blocks.append(tool_use("save_lead", {
                    "company": e["company"], "domain": e.get("domain") or "", "industry": e["industry"],
                    "category": e["category"], "size_band": e["size_band"], "region": e["region"],
                    "cloud_native": e["cloud_native"],
                    "facts": [{"fact": e["fact"], "url": e["url"], "date": e["date"], "type": e["fact_type"]}],
                    "reason": "Recent compliance or funding milestone; evidence work is next.",
                }))
            if self.bad_url:
                blocks.append(tool_use("save_lead", {
                    "company": "Imaginary Corp", "category": "b2b_saas", "size_band": "50-199", "region": "Europe",
                    "cloud_native": "yes", "reason": "Made up to test the provenance guard.",
                    "facts": [{"fact": "Raised a large round last week, apparently.", "url": "https://imaginary.example.com/news", "date": "2026-11-01", "type": "funding"}],
                }))
            return blocks
        if self.turn == 4:
            self.lead_errors = [r["error"] for r in results if isinstance(r, dict) and "error" in r]
            return [tool_use("analyze_crm", {}), tool_use("list_leads", {"limit": 15})]
        if self.turn == 5:
            crm_result = next(r for r in results if isinstance(r, dict) and "flagged" in r)
            leads_result = next(r for r in results if isinstance(r, dict) and "leads" in r)
            self.flagged = [f for f in crm_result["flagged"] if not f["has_open_follow_up"]][:2]
            blocks = []
            for lead in [l for l in leads_result["leads"] if l["eligible"]][:5]:
                fact = lead["facts"][0]
                blocks.append(tool_use("draft_outreach", {
                    "lead_id": lead["lead_id"],
                    "subject": f"{lead['company']}: after the milestone",
                    "body": f"Hi {lead['company']} team,\n\nI read that your team recently shared this news: {fact['fact']} "
                            "Teams at that point usually need evidence to stay current between audits, which is what Acme Guard does, read-only.\n\n"
                            "If useful, I can send a one-page checklist.\n\nJordan Reyes\nAccount Executive, Acme Cloud Security",
                    "cited_fact": fact["fact"], "source_url": fact["url"],
                }))
            blocks += [tool_use("get_account_activity", {"account_id": f["account_id"]}) for f in self.flagged]
            return blocks
        if self.turn == 6:
            from app.agent.scoring import add_business_days
            from app.db import utcnow

            send = add_business_days(utcnow().date(), 1).isoformat()
            return [tool_use("draft_follow_up", {
                "account_id": f["account_id"], "next_step": "Send a short check-in tied to their last request",
                "send_date": send, "subject": "Quick follow-up",
                "body": "Hi there,\n\nFollowing up on our last conversation. I can send a short summary of the next steps and who usually signs off. Would that help?\n\nJordan Reyes\nAccount Executive, Acme Cloud Security",
            }) for f in self.flagged]
        return [tool_use("finish", {"summary": "Saved leads, analysed the CRM and queued drafts for approval."})]


class FakeMessages:
    def __init__(self, script: Callable[[dict[str, Any]], list[SimpleNamespace]]):
        self.script = script
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        content = self.script(kwargs)
        stop = "tool_use" if any(getattr(b, "type", "") == "tool_use" for b in content) else "end_turn"
        return SimpleNamespace(
            content=content,
            stop_reason=stop,
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        )


class FakeAnthropic:
    def __init__(self, script: Callable[[dict[str, Any]], list[SimpleNamespace]]):
        self.messages = FakeMessages(script)
