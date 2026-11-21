"""Runtime settings. Everything comes from environment variables; nothing secret lives in the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = BACKEND_DIR.parent


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def normalise_db_url(url: str) -> str:
    """Supabase hands out postgres:// URLs; SQLAlchemy needs the psycopg driver named."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: normalise_db_url(
        _get("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'hub.db'}")))
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY") or _get("CLAUDE_API_KEY"))
    claude_model: str = field(default_factory=lambda: _get("CLAUDE_MODEL", "claude-sonnet-5-5"))
    slack_webhook_url: str = field(default_factory=lambda: _get("SLACK_WEBHOOK_URL"))
    airtable_token: str = field(default_factory=lambda: _get("AIRTABLE_TOKEN"))
    airtable_base_id: str = field(default_factory=lambda: _get("AIRTABLE_BASE_ID"))
    airtable_table: str = field(default_factory=lambda: _get("AIRTABLE_CLIENTS_TABLE", "Clients"))
    supabase_url: str = field(default_factory=lambda: _get("SUPABASE_URL").rstrip("/"))
    supabase_service_key: str = field(default_factory=lambda: _get("SUPABASE_SERVICE_KEY"))
    supabase_bucket: str = field(default_factory=lambda: _get("SUPABASE_BUCKET", "site-drafts"))
    hub_api_token: str = field(default_factory=lambda: _get("HUB_API_TOKEN"))
    smtp_host: str = field(default_factory=lambda: _get("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_get("SMTP_PORT", "587") or 587))
    smtp_user: str = field(default_factory=lambda: _get("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _get("SMTP_PASSWORD"))
    smtp_from: str = field(default_factory=lambda: _get("SMTP_FROM"))
    frontend_dist: str = field(default_factory=lambda: _get("FRONTEND_DIST", str(DEMO_DIR / "frontend" / "dist")))
    rate_limit_per_minute: int = field(default_factory=lambda: int(_get("RATE_LIMIT_PER_MINUTE", "30") or 30))

    @property
    def live_model(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def airtable_enabled(self) -> bool:
        return bool(self.airtable_token and self.airtable_base_id)

    @property
    def slack_enabled(self) -> bool:
        return self.slack_webhook_url.startswith("https://hooks.slack.com/")

    @property
    def storage_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def database_kind(self) -> str:
        return "Supabase Postgres" if self.database_url.startswith("postgresql") else "SQLite (local)"


def get_settings() -> Settings:
    return Settings()
