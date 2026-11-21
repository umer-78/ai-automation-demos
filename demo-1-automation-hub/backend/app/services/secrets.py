"""API keys saved from the Settings page.

Keys are encrypted with Fernet (key derived from APP_SECRET) before they reach the database, are
never sent back to the browser (only the last four characters), and override the environment at
runtime: saving a key rebuilds the client that uses it, no restart needed.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select

from app.config import Settings
from app.db import app_secrets, utcnow


@dataclass(frozen=True)
class Field:
    key: str  # Settings attribute
    label: str
    secret: bool = True
    placeholder: str = ""


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    description: str
    fields: tuple[Field, ...]
    live_flag: str  # Settings property that says the integration is live


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "google",
        "Google sign-in",
        "One sign-in reads Google Ads, Search Console and Analytics for your clients.",
        (
            Field("google_oauth_client_id", "OAuth client ID", secret=False, placeholder="1234-abc.apps.googleusercontent.com"),
            Field("google_oauth_client_secret", "OAuth client secret", placeholder="GOCSPX-..."),
            Field("google_oauth_refresh_token", "Refresh token (Sign in with Google fills this)", placeholder="1//0..."),
        ),
        "google_live",
    ),
    Provider(
        "google_ads",
        "Google Ads",
        "Daily spend, clicks and conversions from each client's Google Ads account.",
        (Field("google_ads_developer_token", "Developer token"), Field("google_ads_login_customer_id", "Manager account ID (optional)", secret=False, placeholder="123-456-7890")),
        "google_ads_live",
    ),
    Provider(
        "meta_ads",
        "Meta Ads",
        "Daily spend, link clicks and leads from each client's ad account.",
        (Field("meta_access_token", "System user access token", placeholder="EAAB..."),),
        "meta_live",
    ),
    Provider("anthropic", "Claude AI", "Writes client briefs, weekly summaries and website copy.", (Field("anthropic_api_key", "API key", placeholder="sk-ant-..."),), "llm_live"),
    Provider(
        "airtable",
        "Airtable",
        "New rows in your Clients table start onboarding.",
        (Field("airtable_token", "Personal access token", placeholder="pat..."), Field("airtable_base_id", "Base ID", secret=False, placeholder="app...")),
        "airtable_live",
    ),
    Provider("slack", "Slack", "Run failures and cost alerts post to your channel.", (Field("slack_webhook_url", "Incoming webhook URL", placeholder="https://hooks.slack.com/services/..."),), "slack_live"),
    Provider(
        "email",
        "Email (SMTP)",
        "Welcome emails and brief drafts go to real inboxes.",
        (Field("smtp_host", "SMTP host", secret=False, placeholder="smtp.example.com"), Field("smtp_username", "Username", secret=False), Field("smtp_password", "Password")),
        "email_live",
    ),
    Provider(
        "make",
        "Make",
        "Hands onboarding and off-boarding to your Make scenarios.",
        (Field("make_onboarding_webhook_url", "Onboarding webhook URL", placeholder="https://hook.eu1.make.com/..."), Field("make_offboarding_webhook_url", "Off-boarding webhook URL")),
        "make_live",
    ),
    Provider(
        "supabase",
        "Supabase storage",
        "Stores generated website drafts in your bucket.",
        (Field("supabase_url", "Project URL", secret=False, placeholder="https://xyz.supabase.co"), Field("supabase_service_role_key", "Service role key")),
        "storage_live",
    ),
)
FIELD_KEYS = {f.key for p in PROVIDERS for f in p.fields}


def _fernet(settings: Settings) -> Fernet:
    seed = settings.app_secret or settings.admin_token or "northwind-local-development-only"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()))


def can_store(settings: Settings) -> tuple[bool, str]:
    if settings.is_production and not settings.app_secret:
        return False, "Set APP_SECRET on the server to save keys."
    return True, ""


def load_saved(engine, settings: Settings) -> dict[str, str]:
    f = _fernet(settings)
    out: dict[str, str] = {}
    with engine.connect() as conn:
        for name, token in conn.execute(select(app_secrets.c.name, app_secrets.c.ciphertext)):
            if name not in FIELD_KEYS:
                continue
            try:
                out[name] = f.decrypt(token.encode()).decode()
            except InvalidToken:
                continue  # APP_SECRET changed; the key has to be saved again
    return out


def save(engine, settings: Settings, values: dict[str, str]) -> None:
    f = _fernet(settings)
    with engine.begin() as conn:
        for name, value in values.items():
            if name not in FIELD_KEYS:
                raise ValueError(f"unknown setting {name}")
            conn.execute(delete(app_secrets).where(app_secrets.c.name == name))
            if value.strip():
                conn.execute(app_secrets.insert().values(name=name, ciphertext=f.encrypt(value.strip().encode()).decode(), updated_at=utcnow()))


def effective(base: Settings, saved: dict[str, str]) -> Settings:
    return base.model_copy(update={k: v for k, v in saved.items() if v}) if saved else base


def mask(value: str) -> str:
    v = value.strip()
    return "" if not v else ("•" * 6 + v[-4:] if len(v) > 8 else "•" * len(v))


def describe(base: Settings, current: Settings, saved: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for p in PROVIDERS:
        fields = []
        for fd in p.fields:
            value = str(getattr(current, fd.key) or "")
            source = "saved" if saved.get(fd.key) else ("environment" if getattr(base, fd.key) else "none")
            fields.append(
                {
                    "key": fd.key,
                    "label": fd.label,
                    "secret": fd.secret,
                    "placeholder": fd.placeholder,
                    "set": bool(value),
                    "source": source,
                    "preview": (mask(value) if fd.secret else value) if value else "",
                }
            )
        out.append({"id": p.id, "label": p.label, "description": p.description, "live": bool(getattr(current, p.live_flag)), "fields": fields})
    return out
