"""Dependency container shared by the API, the cron job and the tests."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Engine

from app.config import Settings
from app.db import init_db, make_engine
from app.services.airtable import AirtableClient
from app.services.llm import LLM
from app.services.notify import Notifier
from app.services.storage import Storage


@dataclass
class Context:
    settings: Settings
    engine: Engine
    llm: LLM
    notifier: Notifier
    airtable: AirtableClient
    storage: Storage

    def integrations(self) -> dict[str, str]:
        s = self.settings
        return {
            "ai": "live" if self.llm.live else "offline templates",
            "database": "supabase postgres" if s.database_kind == "postgres" else "local sqlite",
            "slack": "live" if s.slack_live else "simulated (feed in dashboard)",
            "email": "live smtp" if s.email_live else "simulated (outbox in dashboard)",
            "airtable": "live" if s.airtable_live else "not connected (dashboard form)",
            "make": "live" if s.make_live else "local orchestrator (mirrors the Make scenario)",
            "storage": "supabase storage" if s.storage_live else "local disk",
            "google": "live" if s.google_live else "not connected",
            "meta": "live" if s.meta_live else "not connected",
        }


def build_context(settings: Settings, *, llm_client=None) -> Context:
    engine = make_engine(settings.database_url)
    init_db(engine)
    notifier = Notifier(settings, engine)
    return Context(
        settings=settings,
        engine=engine,
        llm=LLM(settings, client=llm_client),
        notifier=notifier,
        airtable=AirtableClient(settings),
        storage=Storage(settings),
    )


def apply_settings(ctx: Context, settings: Settings) -> None:
    """Swap in new settings (keys saved from the Settings page) and rebuild the clients that use them."""
    ctx.settings = settings
    ctx.llm = LLM(settings)
    ctx.notifier = Notifier(settings, ctx.engine)
    ctx.airtable = AirtableClient(settings)
    ctx.storage = Storage(settings)
