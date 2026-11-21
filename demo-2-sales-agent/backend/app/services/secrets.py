"""API keys saved from the Settings page.

Keys are encrypted with Fernet (key derived from APP_SECRET) before they reach the database, are
never sent back to the browser (only the last four characters), and override the environment at
runtime: saving a key rebuilds the client that uses it, no restart needed. Plain settings such as
the company name use the same path but are shown in full.
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
        "company",
        "Your company",
        "Who the agent sells for and who signs the emails.",
        (
            Field("seller_company", "Company name", secret=False, placeholder="Acme Cloud Security"),
            Field("rep_name", "Rep name", secret=False, placeholder="Jordan Reyes"),
            Field("rep_title", "Rep title", secret=False, placeholder="Account Executive"),
        ),
        "company_set",
    ),
    Provider("anthropic", "Claude AI", "Writes the ideal customer profile, scores leads and drafts every email.", (Field("anthropic_api_key", "API key", placeholder="sk-ant-..."),), "llm_live"),
    Provider("tavily", "Tavily web search", "Live research: finds real companies with buying signals today, each with its source.", (Field("tavily_api_key", "API key", placeholder="tvly-..."),), "research_live"),
    Provider(
        "hubspot",
        "HubSpot CRM",
        "Reads your companies, open deals, owners and last contact dates, and re-reads them every hour.",
        (Field("hubspot_token", "Private app token", placeholder="pat-na1-..."),),
        "hubspot_live",
    ),
    Provider("slack", "Slack", "Run failures and the weekly report post to your channel.", (Field("slack_webhook_url", "Incoming webhook URL", placeholder="https://hooks.slack.com/services/..."),), "slack_live"),
)
FIELD_KEYS = {f.key for p in PROVIDERS for f in p.fields}


def _fernet(settings: Settings) -> Fernet:
    seed = settings.app_secret or settings.admin_token or "acme-local-development-only"
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
