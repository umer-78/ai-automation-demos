"""Minimal Airtable Web API client (records + webhooks).

Field names used in the "Clients" table (see ../../airtable/README.md):
  Name, Website, Industry, Services (multiple select), Account Manager, Manager Email,
  Status (single select: New, Onboarding, Active, Churned, Archived), Brief (long text),
  Hub Client ID (number), Onboarded At (date)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings

log = logging.getLogger(__name__)
API = "https://api.airtable.com/v0"


class AirtableError(RuntimeError):
    pass


class AirtableClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.http = http or httpx.Client(timeout=15)

    @property
    def live(self) -> bool:
        return self.settings.airtable_live

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.airtable_token}", "Content-Type": "application/json"}

    def _table_url(self) -> str:
        return f"{API}/{self.settings.airtable_base_id}/{quote(self.settings.airtable_table, safe='')}"

    def _check(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code >= 300:
            raise AirtableError(f"Airtable HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    # ---------------------------------------------------------------- records
    def get_record(self, record_id: str) -> dict[str, Any]:
        return self._check(self.http.get(f"{self._table_url()}/{record_id}", headers=self._headers()))

    def create_record(self, fields: dict[str, Any]) -> dict[str, Any]:
        body = {"fields": fields, "typecast": True}
        return self._check(self.http.post(self._table_url(), headers=self._headers(), json=body))

    def update_record(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        body = {"fields": fields, "typecast": True}
        return self._check(self.http.patch(f"{self._table_url()}/{record_id}", headers=self._headers(), json=body))

    # ---------------------------------------------------------------- webhooks (free-plan bridge)
    def create_webhook(self, notification_url: str) -> dict[str, Any]:
        spec = {
            "options": {
                "filters": {
                    "dataTypes": ["tableData"],
                    "changeTypes": ["add", "update"],
                }
            }
        }
        url = f"{API}/bases/{self.settings.airtable_base_id}/webhooks"
        return self._check(
            self.http.post(url, headers=self._headers(), json={"notificationUrl": notification_url, "specification": spec})
        )

    def refresh_webhook(self, webhook_id: str) -> dict[str, Any]:
        url = f"{API}/bases/{self.settings.airtable_base_id}/webhooks/{webhook_id}/refresh"
        return self._check(self.http.post(url, headers=self._headers()))

    def list_payloads(self, webhook_id: str, cursor: int | None) -> dict[str, Any]:
        url = f"{API}/bases/{self.settings.airtable_base_id}/webhooks/{webhook_id}/payloads"
        params = {"cursor": cursor} if cursor else None
        return self._check(self.http.get(url, headers=self._headers(), params=params))


def verify_webhook_mac(secret_b64: str, body: bytes, header_value: str | None) -> bool:
    """Airtable signs pings with HMAC-SHA256 using the base64 MAC secret from webhook creation."""
    if not header_value or not secret_b64:
        return False
    digest = hmac.new(base64.b64decode(secret_b64), body, hashlib.sha256).hexdigest()
    expected = f"hmac-sha256={digest}"
    return hmac.compare_digest(expected, header_value)


def changed_record_ids(payload_page: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return (created_record_ids, updated_record_ids) from a list-payloads response page."""
    created: set[str] = set()
    updated: set[str] = set()
    for payload in payload_page.get("payloads", []):
        for table in (payload.get("changedTablesById") or {}).values():
            created.update((table.get("createdRecordsById") or {}).keys())
            updated.update((table.get("changedRecordsById") or {}).keys())
    return created, updated - created
