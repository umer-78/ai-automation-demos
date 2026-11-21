"""Runtime settings. Everything comes from environment variables; nothing secret lives in the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = BACKEND_DIR.parent
DATA_DIR = Path(__file__).resolve().parent / "data"


def _get(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def normalise_db_url(url: str) -> str:
    """Supabase hands out postgres:// URLs; SQLAlchemy needs the psycopg driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: normalise_db_url(
        _get("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'agent.db'}")))
    anthropic_api_key: str = field(default_factory=lambda: _get("ANTHROPIC_API_KEY") or _get("CLAUDE_API_KEY"))
    claude_model: str = field(default_factory=lambda: _get("CLAUDE_MODEL", "claude-sonnet-5-5"))
    tavily_api_key: str = field(default_factory=lambda: _get("TAVILY_API_KEY"))
    slack_webhook_url: str = field(default_factory=lambda: _get("SLACK_WEBHOOK_URL"))
    frontend_dist: str = field(default_factory=lambda: _get("FRONTEND_DIST", str(DEMO_DIR / "frontend" / "dist")))
    rate_limit_per_minute: int = field(default_factory=lambda: int(_get("RATE_LIMIT_PER_MINUTE", "40") or 40))
    run_timeout_s: int = field(default_factory=lambda: int(_get("AGENT_RUN_TIMEOUT_S", "170") or 170))
    max_turns: int = field(default_factory=lambda: int(_get("AGENT_MAX_TURNS", "40") or 40))
    # The offline agent finishes in a fraction of a second; a short pause per tool call lets the page show each step.
    offline_step_s: float = field(default_factory=lambda: float(_get("OFFLINE_STEP_SECONDS", "0.35") or 0))
    # On an empty database, run the offline agent once at start-up so the demo opens with real work.
    seed_first_run: bool = field(default_factory=lambda: _get("SEED_FIRST_RUN", "1") not in ("0", "false", "no"))

    @property
    def live_model(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def live_search(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def slack_enabled(self) -> bool:
        return self.slack_webhook_url.startswith("https://hooks.slack.com/")

    @property
    def database_kind(self) -> str:
        return "Supabase Postgres" if self.database_url.startswith("postgresql") else "SQLite (local)"


def get_settings() -> Settings:
    return Settings()
