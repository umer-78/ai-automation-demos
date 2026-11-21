"""Outbound integrations: Slack, Airtable, Supabase Storage, email and website fetching.

Each call returns a small status dict instead of raising, so a missing key never breaks the demo,
and the UI can show exactly what happened ("sent", "not configured", "failed: ...").
"""
from __future__ import annotations

import ipaddress
import smtplib
import socket
from email.message import EmailMessage
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from .config import Settings

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _status(sent: bool, detail: str) -> dict:
    return {"sent": sent, "detail": detail}


class Slack:
    def __init__(self, settings: Settings):
        self.url = settings.slack_webhook_url if settings.slack_enabled else ""

    def post(self, text: str) -> dict:
        if not self.url:
            return _status(False, "not sent: SLACK_WEBHOOK_URL not configured")
        try:
            r = httpx.post(self.url, json={"text": text}, timeout=TIMEOUT)
            return _status(r.status_code == 200, f"Slack responded {r.status_code}")
        except httpx.HTTPError as exc:
            return _status(False, f"failed: {exc.__class__.__name__}")


class Airtable:
    """Minimal Airtable Web API client for the Clients table."""

    def __init__(self, settings: Settings):
        self.enabled = settings.airtable_enabled
        self.base = f"https://api.airtable.com/v0/{settings.airtable_base_id}/{settings.airtable_table}"
        self.headers = {"Authorization": f"Bearer {settings.airtable_token}", "Content-Type": "application/json"}

    def create_client(self, client: dict) -> dict:
        if not self.enabled:
            return {**_status(False, "Airtable not configured"), "record_id": None}
        fields = {"Name": client["name"], "Website": client.get("website") or "", "Industry": client.get("industry") or "",
                  "Services": client.get("services") or [], "Account Manager": client.get("manager") or "",
                  "Manager Email": client.get("manager_email") or "", "Status": "Active"}
        try:
            r = httpx.post(self.base, headers=self.headers, json={"fields": fields, "typecast": True}, timeout=TIMEOUT)
            r.raise_for_status()
            return {**_status(True, "created in Airtable"), "record_id": r.json()["id"]}
        except (httpx.HTTPError, KeyError) as exc:
            return {**_status(False, f"failed: {exc}"), "record_id": None}

    def update(self, record_id: str | None, fields: dict) -> dict:
        if not self.enabled:
            return _status(False, "Airtable not configured")
        if not record_id:
            return _status(False, "client has no Airtable record")
        try:
            r = httpx.patch(f"{self.base}/{record_id}", headers=self.headers, json={"fields": fields, "typecast": True},
                            timeout=TIMEOUT)
            r.raise_for_status()
            return _status(True, "saved to Airtable")
        except httpx.HTTPError as exc:
            return _status(False, f"failed: {exc}")


class Storage:
    """Supabase Storage upload for Module C drafts."""

    def __init__(self, settings: Settings):
        self.enabled = settings.storage_enabled
        self.url, self.key, self.bucket = settings.supabase_url, settings.supabase_service_key, settings.supabase_bucket

    def upload_html(self, path: str, html: str) -> dict:
        if not self.enabled:
            return {**_status(False, "Supabase Storage not configured; draft kept in the database"), "url": None}
        try:
            r = httpx.post(f"{self.url}/storage/v1/object/{self.bucket}/{path}", content=html.encode("utf-8"),
                           headers={"Authorization": f"Bearer {self.key}", "apikey": self.key,
                                    "Content-Type": "text/html; charset=utf-8", "x-upsert": "true"}, timeout=TIMEOUT)
            r.raise_for_status()
            return {**_status(True, "saved to Supabase Storage"),
                    "url": f"{self.url}/storage/v1/object/public/{self.bucket}/{path}"}
        except httpx.HTTPError as exc:
            return {**_status(False, f"failed: {exc}"), "url": None}


class Mailer:
    def __init__(self, settings: Settings):
        self.s = settings

    def send(self, to: str | None, subject: str, body: str) -> dict:
        if not self.s.smtp_enabled:
            return _status(False, "saved as a draft; SMTP not configured")
        if not to:
            return _status(False, "saved as a draft; no account manager email")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(msg)
            return _status(True, f"emailed to {to}")
        except (OSError, smtplib.SMTPException) as exc:
            return _status(False, f"failed: {exc.__class__.__name__}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data):  # noqa: ANN001
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _public_http_url(url: str) -> str | None:
    """Return a reason string if the URL must not be fetched (SSRF guard), else None."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not host:
        return "not an http(s) URL"
    if host.endswith((".example", ".test", ".invalid", ".localhost", ".local")) or host == "localhost":
        return "fictional or local domain, not fetched"
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError:
        return "domain does not resolve"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "private address, not fetched"
    return None


def fetch_site_text(url: str | None) -> tuple[str | None, str]:
    """Read a client's homepage text for the brief. Fictional and private addresses are never fetched."""
    if not url:
        return None, "no website given"
    try:
        for _ in range(4):  # follow up to 3 redirects, re-checking every hop
            reason = _public_http_url(url)
            if reason:
                return None, reason
            r = httpx.get(url, timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": "NorthwindHub/1.0"})
            if r.is_redirect and r.headers.get("location"):
                url = str(httpx.URL(url).join(r.headers["location"]))
                continue
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                return None, f"site returned {r.status_code}"
            p = _TextExtractor()
            p.feed(r.text[:400_000])
            return " ".join(p.parts)[:6000], "homepage read"
        return None, "too many redirects"
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"could not read site ({exc.__class__.__name__})"
