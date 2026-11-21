"""Runs the committed Make.com blueprints against the API with a small interpreter that follows
Make's semantics (variables, router filters, error routes, Skip/Ignore). This proves every URL,
parameter and {{module.field}} reference in the blueprints matches the real API."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

MAKE_DIR = Path(__file__).resolve().parents[2] / "make"
API_BASE = "http://testserver"
SLACK = "https://hooks.slack.test/services/T/B/X"
KEY = "make-test-key"


class MakeRunner:
    def __init__(self, client: TestClient, blueprint: dict[str, Any]):
        self.client = client
        self.bp = blueprint
        self.out: dict[int, Any] = {}
        self.slack_posts: list[dict[str, Any]] = []
        self.executed: list[str] = []

    def value(self, path: str) -> Any:
        mid, *keys = path.split(".")
        cur: Any = self.out.get(int(mid), {})
        for k in keys:
            cur = cur.get(k) if isinstance(cur, dict) else None
        return cur

    def resolve(self, text: str, error: dict[str, Any] | None) -> str:
        def join(m: re.Match) -> str:
            val = self.value(m.group(1)) or []
            return m.group(2).join(val) if isinstance(val, list) else str(val)

        text = re.sub(r'\{\{join\(([\d.\w]+); "(.*?)"\)\}\}', join, text)
        text = text.replace("{{error.message}}", (error or {}).get("message", ""))

        def ref(m: re.Match) -> str:
            val = self.value(m.group(1))
            if isinstance(val, bool):
                return "true" if val else "false"
            return "" if val is None else str(val)

        return re.sub(r"\{\{(\d+(?:\.\w+)+)\}\}", ref, text)

    def passes(self, flt: dict[str, Any] | None) -> bool:
        if not flt:
            return True
        for group in flt["conditions"]:  # OR of AND-groups
            if all(self.resolve(c["a"], None) == c["b"] for c in group if c["o"] == "boolean:equal"):
                return True
        return False

    def run(self, payload: dict[str, Any]) -> None:
        self.out[1] = payload
        self.exec(self.bp["flow"], None)

    def exec(self, modules: list[dict[str, Any]], error: dict[str, Any] | None) -> bool:
        for m in modules:
            kind = m["module"]
            if kind == "gateway:CustomWebHook":
                continue
            if kind == "util:SetVariables":
                values = {v["name"]: v["value"] for v in m["mapper"]["variables"]}
                values.update(api_base=API_BASE, automation_key=KEY, slack_webhook=SLACK)
                self.out[m["id"]] = values
                continue
            if kind == "builtin:BasicRouter":
                for route in m["routes"]:
                    self.exec(route["flow"], error)
                continue
            if kind == "builtin:Ignore":
                return False
            assert kind == "http:ActionSendData", kind
            if not self.passes(m.get("filter")):
                return False
            self.executed.append(m["metadata"]["designer"]["name"])
            mp = m["mapper"]
            url = self.resolve(mp["url"], error)
            body = self.resolve(mp["data"], error)
            json.loads(body)  # every body Make sends must be valid JSON
            if url == SLACK:
                self.slack_posts.append(json.loads(body))
                self.out[m["id"]] = {"data": "ok", "statusCode": 200}
                continue
            assert url.startswith(API_BASE), url
            params = {q["name"]: self.resolve(q["value"], error) for q in mp["qs"]}
            headers = {h["name"]: self.resolve(h["value"], error) for h in mp["headers"]}
            resp = self.client.post(url[len(API_BASE):], params=params, content=body, headers=headers)
            if resp.status_code >= 400:
                if "onerror" not in m:
                    raise AssertionError(f"{m['metadata']['designer']['name']} failed: {resp.status_code} {resp.text}")
                self.exec(m["onerror"], {"message": f"[{resp.status_code}] {resp.json().get('detail')}"})
                return False
            self.out[m["id"]] = {"data": resp.json(), "statusCode": resp.status_code}
        return True


@pytest.fixture
def hub(tmp_path):
    app = create_app(make_settings(tmp_path, automation_api_key=KEY))
    with TestClient(app) as c:
        yield c


def load(name: str) -> dict[str, Any]:
    return json.loads((MAKE_DIR / name).read_text())


PAYLOAD = {
    "event": "client.created",
    "name": 'Rosa\'s "Best" Bakery',
    "website": "https://rosas-bakery.example",
    "industry": "Bakery",
    "services": ["SEO", "Web Design"],
    "manager": "Elena Rossi",
    "manager_email": "elena@northwind-digital.example",
    "airtable_record_id": "recBAKERY00000000",
    "run_id": "mk0000000001",
}


def test_onboarding_blueprint_runs_end_to_end(hub):
    runner = MakeRunner(hub, load("northwind-client-onboarding.blueprint.json"))
    runner.run(PAYLOAD)
    assert runner.executed == [
        "Sync client to hub",
        "SEO checklist",
        "Slack welcome (SEO)",
        "Web Design checklist",
        "Slack welcome (Web Design)",
        "Generate brief (AI) + save to Airtable + email AM",
        "Slack: onboarding complete",
        "Log success",
    ]
    assert len(runner.slack_posts) == 3 and 'Rosa\'s "Best" Bakery' in runner.slack_posts[0]["text"]
    logs = hub.get("/api/automation/logs?workflow=client_onboarding").json()
    assert logs[0]["status"] == "success" and logs[0]["source"] == "make" and logs[0]["run_id"] == PAYLOAD["run_id"]
    client = next(c for c in hub.get("/api/clients").json() if c["airtable_record_id"] == "recBAKERY00000000")
    assert client["status"] == "active" and client["services"] == ["SEO", "Web Design"]


def test_onboarding_blueprint_error_route_logs_and_alerts(hub):
    runner = MakeRunner(hub, load("northwind-client-onboarding.blueprint.json"))
    runner.run({**PAYLOAD, "simulate_failure": True, "run_id": "mk0000000002"})
    assert "Log failure: Generate brief" in runner.executed
    assert "Slack: onboarding complete" not in runner.executed and "Log success" not in runner.executed
    failure = hub.get("/api/automation/logs?status=failure").json()[0]
    assert failure["details"]["module"] == "Generate brief" and "Deliberate test failure" in failure["error"]
    assert any(n["kind"] == "alert" and "mk0000000002" in n["body"] for n in hub.get("/api/notifications").json())


def test_offboarding_blueprint(hub):
    MakeRunner(hub, load("northwind-client-onboarding.blueprint.json")).run(PAYLOAD)
    runner = MakeRunner(hub, load("northwind-client-offboarding.blueprint.json"))
    runner.run({"event": "client.churned", "airtable_record_id": "recBAKERY00000000", "run_id": "mk0000000003"})
    assert runner.executed == ["Off-board client (close tasks, archive)", "Slack: off-boarding summary", "Log success"]
    assert "off-boarded" in runner.slack_posts[0]["text"]
    client = next(c for c in hub.get("/api/clients").json() if c["airtable_record_id"] == "recBAKERY00000000")
    assert client["status"] == "archived" and client["tasks_open"] == 0


def test_blueprints_are_up_to_date():
    import subprocess
    import sys

    result = subprocess.run([sys.executable, str(MAKE_DIR / "build_blueprints.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
