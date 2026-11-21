"""Failure alerts to Slack (shared rule: every automation logs failures and sends an alert)."""
from __future__ import annotations

import httpx

from .config import Settings


def slack_alert(settings: Settings, text: str) -> dict:
    if not settings.slack_enabled:
        return {"sent": False, "detail": "Slack isn't set up (SLACK_WEBHOOK_URL is empty)"}
    try:
        r = httpx.post(settings.slack_webhook_url, json={"text": text}, timeout=10)
        return {"sent": r.status_code == 200, "detail": f"Slack answered {r.status_code}"}
    except httpx.HTTPError as exc:
        return {"sent": False, "detail": f"Slack request failed: {exc.__class__.__name__}"}
