"""Dependency container shared by the API, the scheduled job and the tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.engine import Engine

from app.config import Settings
from app.db import init_db, make_engine
from app.services.llm import LLM
from app.services.notify import Notifier
from app.services.research import Research


@dataclass
class Context:
    settings: Settings
    engine: Engine
    llm: LLM
    notifier: Notifier
    research: Research
    runner: Any = field(default=None)

    def integrations(self) -> dict[str, str]:
        s = self.settings
        return {
            "ai": f"live ({s.anthropic_model})" if self.llm.live else "offline planner (no API key)",
            "research": "Tavily web search" if self.research.source == "web" else "research cache (real public sources)",
            "database": "Supabase Postgres" if s.database_kind == "postgres" else "local SQLite",
            "slack": "live (internal channel)" if s.slack_live else "simulated (feed in the app)",
            "crm": "live (HubSpot)" if s.hubspot_live else "imported or sample CSV",
            "sending": "none: approved drafts are exported and sent by a person",
        }


def apply_settings(ctx: Context, settings: Settings) -> None:
    """Swap in new settings (keys saved from the Settings page) and rebuild the clients that use them."""
    ctx.settings = settings
    ctx.llm = LLM(settings)
    ctx.notifier = Notifier(settings, ctx.engine)
    ctx.research = Research(settings)


def build_context(settings: Settings, *, llm_client: Any = None, http: Any = None) -> Context:
    from app.agent.runner import AgentRunner

    engine = make_engine(settings.database_url)
    init_db(engine)
    ctx = Context(
        settings=settings,
        engine=engine,
        llm=LLM(settings, client=llm_client),
        notifier=Notifier(settings, engine),
        research=Research(settings, http=http),
    )
    ctx.runner = AgentRunner(ctx)
    return ctx
