"""Slack + email notifications.

Every notification is also written to the `notifications` table, so the dashboard can show a
live "Slack feed" and the email outbox even when no Slack workspace or SMTP server is connected
(status = "simulated").
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
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

    # ------------------------------------------------------------------ Slack
    def slack(
        self,
        text: str,
        *,
        kind: str = "message",
        blocks: list[dict[str, Any]] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        status, error = "simulated", None
        if self.settings.slack_live:
            payload: dict[str, Any] = {"text": text}
            if blocks:
                payload["blocks"] = blocks
            try:
                resp = self.http.post(self.settings.slack_webhook_url, json=payload)
                if resp.status_code >= 300:
                    status, error = "failed", f"Slack returned HTTP {resp.status_code}: {resp.text[:200]}"
                else:
                    status = "sent"
            except httpx.HTTPError as exc:  # network problems must never crash a workflow
                status, error = "failed", f"Slack request failed: {exc}"
        if error:
            log.warning(error)
        return self._record("slack", kind, "#northwind-ops", None, text, status, error, run_id)

    def alert(self, workflow: str, error: str, *, run_id: str | None = None, context: str = "") -> dict[str, Any]:
        logs_url = f"{self.settings.public_base_url.rstrip('/')}/automations"
        lines = [
            f":rotating_light: *Automation failure in `{workflow}`*",
            f"> {error[:600]}",
            context,
            f"Run `{run_id or 'n/a'}`. <{logs_url}|Open the automation log>",
        ]
        text = "\n".join(line for line in lines if line)
        return self.slack(text, kind="alert", run_id=run_id)

    # ------------------------------------------------------------------ Email
    def email(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        kind: str = "draft",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Internal email (e.g. brief draft to the account manager). Never used for customers."""
        status, error = "simulated", None
        if self.settings.email_live and to:
            msg = EmailMessage()
            msg["From"] = self.settings.smtp_from
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)
            try:
                with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    if self.settings.smtp_username:
                        smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                    smtp.send_message(msg)
                status = "sent"
            except (smtplib.SMTPException, OSError) as exc:
                status, error = "failed", f"SMTP send failed: {exc}"
                log.warning(error)
        return self._record("email", kind, to, subject, body, status, error, run_id)

    # ------------------------------------------------------------------ storage
    def _record(
        self,
        channel: str,
        kind: str,
        recipient: str | None,
        subject: str | None,
        body: str,
        status: str,
        error: str | None,
        run_id: str | None,
    ) -> dict[str, Any]:
        row = {
            "channel": channel,
            "kind": kind,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "status": status,
            "error": error,
            "run_id": run_id,
            "created_at": utcnow(),
        }
        with self.engine.begin() as conn:
            result = conn.execute(notifications.insert().values(**row))
            row["id"] = result.inserted_primary_key[0]
        return row
