"""Internal Slack notifications (failure alerts and the weekly report).

This is the only outbound channel in the app and it only points at the sales team's own
Slack incoming webhook. There is deliberately no email or customer-messaging client in this
codebase: drafts can only be approved, exported and marked as sent by a person
(see app/workflows/approvals.py).

Every notification is also written to the `notifications` table, so the UI can show a
"Slack feed" even when no workspace is connected (status = "simulated").
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.engine import Engine

from app.config import Settings
from app.db import notifications, utcnow

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, settings: Settings, engine: Engine, http: httpx.Client | None = None):
        self.settings = settings
        self.engine = engine
        self.http = http or httpx.Client(timeout=10)

    def slack(self, text: str, *, kind: str = "message", run_id: str | None = None) -> dict[str, Any]:
        status, error = "simulated", None
        if self.settings.slack_live:
            try:
                resp = self.http.post(self.settings.slack_webhook_url, json={"text": text})
                if resp.status_code >= 300:
                    status, error = "failed", f"Slack returned HTTP {resp.status_code}: {resp.text[:200]}"
                else:
                    status = "sent"
            except httpx.HTTPError as exc:  # network problems must never crash a workflow
                status, error = "failed", f"Slack request failed: {exc}"
        if error:
            log.warning(error)
        row = {
            "channel": "slack",
            "kind": kind,
            "recipient": self.settings.slack_channel_label,
            "body": text,
            "status": status,
            "error": error,
            "run_id": run_id,
            "created_at": utcnow(),
        }
        with self.engine.begin() as conn:
            result = conn.execute(notifications.insert().values(**row))
            row["id"] = result.inserted_primary_key[0]
        return row

    def alert(self, workflow: str, error: str, *, run_id: str | None = None, context: str = "") -> dict[str, Any]:
        logs_url = f"{self.settings.public_base_url.rstrip('/')}/runs"
        lines = [
            f":rotating_light: *Automation failure in `{workflow}`*",
            f"> {error[:600]}",
            context,
            f"Run `{run_id or 'n/a'}`. <{logs_url}|Open the run log>",
        ]
        return self.slack("\n".join(line for line in lines if line), kind="alert", run_id=run_id)
