"""Builds the two Make.com scenario blueprints in this folder.

    python make/build_blueprints.py              # writes *.blueprint.json
    python make/build_blueprints.py --check      # validates the committed files are up to date

Every outbound call is a plain HTTP module, so the blueprints import cleanly with no app
connections to remap. After import, open module 2 ("Settings") and paste your API URL,
automation key and Slack webhook.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
API = "{{2.api_base}}"
KEY_HEADER = {"name": "X-Automation-Key", "value": "{{2.automation_key}}"}
JSON_HEADER = {"name": "Content-Type", "value": "application/json"}


def webhook(mid: int, label: str) -> dict[str, Any]:
    return {
        "id": mid,
        "module": "gateway:CustomWebHook",
        "version": 1,
        "parameters": {"hook": None, "maxResults": 1},
        "mapper": {},
        "metadata": {"designer": {"x": 0, "y": 0, "name": label}},
    }


def settings(mid: int, x: int) -> dict[str, Any]:
    return {
        "id": mid,
        "module": "util:SetVariables",
        "version": 1,
        "parameters": {},
        "mapper": {
            "variables": [
                {"name": "api_base", "value": "https://YOUR-HUB.up.railway.app"},
                {"name": "automation_key", "value": "PASTE_YOUR_AUTOMATION_API_KEY"},
                {"name": "slack_webhook", "value": "https://hooks.slack.com/services/PASTE/YOUR/WEBHOOK"},
            ],
            "scope": "roundtrip",
        },
        "metadata": {"designer": {"x": x, "y": 0, "name": "Settings"}},
    }


def http(
    mid: int,
    label: str,
    url: str,
    *,
    x: int,
    y: int,
    qs: list[tuple[str, str]] | None = None,
    body: str = "{}",
    api_key: bool = True,
    onerror: list[dict[str, Any]] | None = None,
    filt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = [JSON_HEADER] + ([KEY_HEADER] if api_key else [])
    module: dict[str, Any] = {
        "id": mid,
        "module": "http:ActionSendData",
        "version": 3,
        "parameters": {"handleErrors": True, "useNewZLibDeCompress": True},
        "mapper": {
            "ca": "",
            "qs": [{"name": k, "value": v} for k, v in (qs or [])],
            "url": url,
            "data": body,
            "gzip": True,
            "method": "post",
            "headers": headers,
            "timeout": "40",
            "useMtls": False,
            "authPass": "",
            "authUser": "",
            "bodyType": "raw",
            "contentType": "application/json",
            "serializeUrl": False,
            "shareCookies": False,
            "parseResponse": True,
            "followRedirect": True,
            "useQuerystring": False,
            "followAllRedirects": False,
            "rejectUnauthorized": True,
        },
        "metadata": {
            "designer": {"x": x, "y": y, "name": label},
            "restore": {
                "expect": {
                    "qs": {"mode": "chose", "items": [None] * len(qs or [])},
                    "method": {"mode": "chose", "label": "POST"},
                    "headers": {"mode": "chose", "items": [None] * len(headers)},
                    "bodyType": {"label": "Raw"},
                    "contentType": {"label": "JSON (application/json)"},
                }
            },
            "parameters": [
                {"name": "handleErrors", "type": "boolean", "label": "Evaluate all states as errors (except for 2xx and 3xx )", "required": True},
                {"name": "useNewZLibDeCompress", "type": "hidden"},
            ],
        },
    }
    if filt:
        module["filter"] = filt
    if onerror:
        module["onerror"] = onerror
    return module


def ignore(mid: int, x: int, y: int) -> dict[str, Any]:
    """Make shows this directive as "Skip" (formerly "Ignore")."""
    return {"id": mid, "module": "builtin:Ignore", "version": 1, "mapper": None, "metadata": {"designer": {"x": x, "y": y}}}


def bool_filter(name: str, field: str) -> dict[str, Any]:
    return {"name": name, "conditions": [[{"a": field, "o": "boolean:equal", "b": "true"}]]}


def error_route(ids: list[int], *, workflow: str, module_label: str, run_ref: str, client_ref: str, x: int, y: int) -> list[dict[str, Any]]:
    """Error route: write the failure to automation_log via the API (which alerts Slack).
    If the API itself is down, a nested route posts straight to Slack."""
    log_id, backstop_id, backstop_ignore_id, ignore_id = ids
    backstop = http(
        backstop_id,
        "Slack backstop (API unreachable)",
        "{{2.slack_webhook}}",
        x=x + 300,
        y=y + 160,
        api_key=False,
        body=json.dumps(
            {"text": f":rotating_light: Northwind {workflow} failed at '{module_label}' and the hub API could not log it. Check the Make execution history."}
        ),
        onerror=[ignore(backstop_ignore_id, x + 600, y + 160)],
    )
    log = http(
        log_id,
        f"Log failure: {module_label}",
        f"{API}/api/automation/log",
        x=x,
        y=y,
        qs=[
            ("workflow", workflow),
            ("status", "failure"),
            ("module", module_label),
            ("error", "{{error.message}}"),
            ("run_id", run_ref),
            ("client_id", client_ref),
        ],
        onerror=[backstop],
    )
    return [log, ignore(ignore_id, x + 300, y)]


def scenario(name: str, flow: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "flow": flow,
        "metadata": {
            "instant": True,
            "version": 1,
            "scenario": {
                "roundtrips": 1,
                "maxErrors": 3,
                "autoCommit": True,
                "autoCommitTriggerLast": True,
                "sequential": False,
                "slots": None,
                "confidential": False,
                "dataloss": False,
                "dlq": False,
                "freshVariables": False,
            },
            "designer": {"orphans": []},
            "zone": "eu1.make.com",
            "notes": [],
        },
    }


# --------------------------------------------------------------------------- onboarding
def onboarding() -> dict[str, Any]:
    run = "{{3.data.run_id}}"
    cid = "{{3.data.client_id}}"
    sync = http(
        3,
        "Sync client to hub",
        f"{API}/api/automation/clients/sync",
        x=600,
        y=0,
        qs=[
            ("name", "{{1.name}}"),
            ("website", "{{1.website}}"),
            ("industry", "{{1.industry}}"),
            ("services", '{{join(1.services; ",")}}'),
            ("manager", "{{1.manager}}"),
            ("manager_email", "{{1.manager_email}}"),
            ("monthly_budget", "{{1.monthly_budget}}"),
            ("airtable_record_id", "{{1.airtable_record_id}}"),
            ("simulate_failure", "{{1.simulate_failure}}"),
            ("run_id", "{{1.run_id}}"),
        ],
        onerror=error_route([20, 21, 22, 23], workflow="client_onboarding", module_label="Sync client", run_ref="{{1.run_id}}", client_ref="", x=600, y=-320),
    )

    def branch(first_id: int, service: str, flag: str, y: int, err_ids: list[int]) -> dict[str, Any]:
        checklist = http(
            first_id,
            f"{service} checklist",
            f"{API}/api/automation/onboarding/checklist",
            x=1200,
            y=y,
            qs=[("client_id", cid), ("service", service), ("run_id", run)],
            filt=bool_filter(service, f"{{{{3.data.{flag}}}}}"),
            onerror=error_route(err_ids, workflow="client_onboarding", module_label=f"{service} checklist", run_ref=run, client_ref=cid, x=1200, y=y + 170),
        )
        slack = http(
            first_id + 1,
            f"Slack welcome ({service})",
            "{{2.slack_webhook}}",
            x=1500,
            y=y,
            api_key=False,
            body=f"{{{{{first_id}.data.slack_payload}}}}",
            onerror=[ignore(err_ids[-1] + 1, 1800, y)],
        )
        return {"flow": [checklist, slack]}

    brief = http(
        11,
        "Generate brief (AI) + save to Airtable + email AM",
        f"{API}/api/automation/onboarding/brief",
        x=1200,
        y=1050,
        qs=[("client_id", cid), ("run_id", run), ("simulate_failure", "{{3.data.simulate_failure}}")],
        onerror=error_route([40, 41, 42, 43], workflow="client_onboarding", module_label="Generate brief", run_ref=run, client_ref=cid, x=1200, y=1220),
    )
    summary = http(12, "Slack: onboarding complete", "{{2.slack_webhook}}", x=1500, y=1050, api_key=False, body="{{11.data.slack_payload}}", onerror=[ignore(44, 1500, 1220)])
    done = http(
        13,
        "Log success",
        f"{API}/api/automation/log",
        x=1800,
        y=1050,
        qs=[("workflow", "client_onboarding"), ("status", "success"), ("run_id", run), ("client_id", cid)],
    )
    router = {
        "id": 4,
        "module": "builtin:BasicRouter",
        "version": 1,
        "mapper": None,
        "metadata": {"designer": {"x": 900, "y": 0, "name": "Route by service"}},
        "routes": [
            branch(5, "SEO", "has_seo", 0, [24, 25, 26, 27]),
            branch(7, "Paid Ads", "has_paid_ads", 350, [29, 30, 31, 32]),
            branch(9, "Web Design", "has_web_design", 700, [34, 35, 36, 37]),
            {"flow": [brief, summary, done]},
        ],
    }
    return scenario("Northwind - Client onboarding", [webhook(1, "New client (Airtable / form)"), settings(2, 300), sync, router])


# --------------------------------------------------------------------------- off-boarding
def offboarding() -> dict[str, Any]:
    off = http(
        3,
        "Off-board client (close tasks, archive)",
        f"{API}/api/automation/offboarding",
        x=600,
        y=0,
        qs=[("client_id", "{{1.client_id}}"), ("airtable_record_id", "{{1.airtable_record_id}}"), ("run_id", "{{1.run_id}}")],
        onerror=error_route([20, 21, 22, 23], workflow="client_offboarding", module_label="Off-board client", run_ref="{{1.run_id}}", client_ref="{{1.client_id}}", x=600, y=200),
    )
    slack = http(4, "Slack: off-boarding summary", "{{2.slack_webhook}}", x=900, y=0, api_key=False, body="{{3.data.slack_payload}}", onerror=[ignore(24, 900, 200)])
    done = http(
        5,
        "Log success",
        f"{API}/api/automation/log",
        x=1200,
        y=0,
        qs=[("workflow", "client_offboarding"), ("status", "success"), ("run_id", "{{3.data.run_id}}"), ("client_id", "{{3.data.client.id}}")],
    )
    return scenario("Northwind - Client off-boarding", [webhook(1, "Client churned (Airtable status)"), settings(2, 300), off, slack, done])


# --------------------------------------------------------------------------- validation
def walk(modules: list[dict[str, Any]]):
    for m in modules:
        yield m
        for route in m.get("routes", []):
            yield from walk(route["flow"])
        yield from walk(m.get("onerror", []))


def validate(bp: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    mods = list(walk(bp["flow"]))
    ids = [m["id"] for m in mods]
    if len(ids) != len(set(ids)):
        problems.append(f"duplicate module ids in {bp['name']}")
    known = set(ids)
    text = json.dumps(bp)
    for ref in set(re.findall(r"\{\{(?:join\()?(\d+)\.", text)):
        if int(ref) not in known:
            problems.append(f"{bp['name']}: reference to missing module {ref}")
    for m in mods:
        for key in ("id", "module", "version", "metadata"):
            if key not in m:
                problems.append(f"{bp['name']}: module {m.get('id')} missing {key}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = {
        "northwind-client-onboarding.blueprint.json": onboarding(),
        "northwind-client-offboarding.blueprint.json": offboarding(),
    }
    failed = False
    for filename, bp in outputs.items():
        problems = validate(bp)
        if problems:
            print("\n".join(problems))
            failed = True
        rendered = json.dumps(bp, indent=2, ensure_ascii=False) + "\n"
        path = HERE / filename
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                print(f"{filename} is out of date; run python make/build_blueprints.py")
                failed = True
        else:
            path.write_text(rendered, encoding="utf-8")
            print(f"wrote {filename} ({len(list(walk(bp['flow'])))} modules)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
