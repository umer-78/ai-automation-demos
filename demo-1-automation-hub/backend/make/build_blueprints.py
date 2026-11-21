"""Write the Make.com scenario blueprints (importable JSON).

    python make/build_blueprints.py                                   # placeholders, as committed
    python make/build_blueprints.py --api https://hub.onrender.com --token <HUB_API_TOKEN> --out /tmp/ready

In Make: Scenarios > Create > ... > Import Blueprint, pick a file, then click the webhook module and
create a webhook (copy its URL into the matching Airtable automation script).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
API_PLACEHOLDER, TOKEN_PLACEHOLDER = "https://YOUR-HUB.onrender.com", "YOUR_HUB_API_TOKEN"


def http_post(mid: int, x: int, y: int, url: str, token: str, body: str, onerror: list | None = None,
              flt: dict | None = None) -> dict:
    mod = {
        "id": mid, "module": "http:ActionSendData", "version": 3, "parameters": {"handleErrors": False},
        "mapper": {"url": url, "serializeUrl": False, "method": "post",
                   "headers": [{"name": "X-Hub-Token", "value": token}], "qs": [], "bodyType": "raw",
                   "parseResponse": True, "authUser": "", "authPass": "", "timeout": "60", "shareCookies": False,
                   "ca": "", "rejectUnauthorized": True, "followRedirect": True, "useQuerystring": False,
                   "gzip": True, "useMtls": False, "contentType": "application/json", "data": body,
                   "followAllRedirects": False},
        "metadata": {"designer": {"x": x, "y": y}},
    }
    if flt:
        mod["filter"] = flt
    if onerror:
        mod["onerror"] = onerror
    return mod


def error_route(start_id: int, x: int, y: int, api: str, token: str, scenario: str, what: str) -> list:
    body = ('{"scenario": "' + scenario + '", "error": "Make.com could not complete the call to the hub '
            '(details in the Make execution log)", "detail": "' + what + ', Airtable record {{1.record_id}}"}')
    return [http_post(start_id, x, y + 200, f"{api}/api/hooks/make/failure", token, body),
            {"id": start_id + 1, "module": "builtin:Ignore", "version": 1, "metadata": {"designer": {"x": x + 300, "y": y + 200}}}]


def webhook(mid: int) -> dict:
    return {"id": mid, "module": "gateway:CustomWebHook", "version": 1, "parameters": {"hook": None, "maxResults": 1},
            "mapper": {}, "metadata": {"designer": {"x": 0, "y": 0}}}


SCENARIO_META = {"instant": True, "version": 1, "scenario": {
    "roundtrips": 1, "maxErrors": 3, "autoCommit": True, "autoCommitTriggerLast": True, "sequential": False,
    "slots": None, "confidential": False, "dataloss": False, "dlq": False, "freshVariables": False},
    "designer": {"orphans": []}}

CLIENT_BODY = ('{{"record_id": "{{{{1.record_id}}}}", "name": "{{{{1.name}}}}", "website": "{{{{1.website}}}}", '
               '"industry": "{{{{1.industry}}}}", "services": "{{{{1.services}}}}", "manager": "{{{{1.manager}}}}", '
               '"manager_email": "{{{{1.manager_email}}}}", "service": "{service}"}}')


def onboarding(api: str, token: str) -> dict:
    routes = []
    for i, service in enumerate(["SEO", "Paid Ads", "Web Design"]):
        mid = 10 + i * 10
        flt = {"name": f"Bought {service}", "conditions": [[{"a": "{{1.services}}", "o": "text:contain", "b": service}]]}
        routes.append({"flow": [http_post(
            mid, 600, i * 300, f"{api}/api/hooks/make/onboarding", token, CLIENT_BODY.format(service=service),
            onerror=error_route(mid + 1, 600, i * 300, api, token, "onboarding", f"{service} branch"), flt=flt)]})
    return {"name": "Northwind — Client onboarding (Airtable row → router → Python + Claude → Slack)",
            "flow": [webhook(1), {"id": 2, "module": "builtin:BasicRouter", "version": 1, "mapper": None,
                                  "metadata": {"designer": {"x": 300, "y": 0}}, "routes": routes}],
            "metadata": SCENARIO_META}


def offboarding(api: str, token: str) -> dict:
    return {"name": "Northwind — Client off-boarding (Status = Churned)",
            "flow": [webhook(1), http_post(2, 300, 0, f"{api}/api/hooks/make/offboarding", token,
                                           '{"record_id": "{{1.record_id}}"}',
                                           onerror=error_route(3, 300, 0, api, token, "offboarding", "off-boarding"))],
            "metadata": SCENARIO_META}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=API_PLACEHOLDER)
    ap.add_argument("--token", default=TOKEN_PLACEHOLDER)
    ap.add_argument("--out", default=str(HERE))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in [("onboarding", onboarding), ("offboarding", offboarding)]:
        (out / f"{name}.blueprint.json").write_text(json.dumps(fn(a.api.rstrip("/"), a.token), indent=2) + "\n")
        print(f"wrote {out / f'{name}.blueprint.json'}")


if __name__ == "__main__":
    main()
