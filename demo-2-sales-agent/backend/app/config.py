"""Runtime configuration. Every secret comes from environment variables (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App -----------------------------------------------------------------------
    app_name: str = "Acme Cloud Security Sales Agent"
    environment: str = "development"  # development | production
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'acme.db').as_posix()}"
    public_base_url: str = "http://localhost:8000"
    auto_seed: bool = True  # load the mock CRM on first start when the database is empty
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Security ----------------------------------------------------------------------
    automation_api_key: str = ""  # X-Automation-Key header for cron / scheduled runs
    admin_token: str = ""  # X-Admin-Token header for the reset endpoint
    owner_token: str = ""  # access code for Settings and, once real CRM data is in, for the whole app
    viewer_token: str = ""  # optional read-only access code for teammates
    app_secret: str = ""  # encrypts keys saved from the Settings page
    agent_runs_per_hour: int = 6  # "Run agent" clicks per visitor IP per hour (public demo guard)
    review_actions_per_hour: int = 300  # approve / edit / reject actions per IP per hour
    live_runs_per_day: int = 40  # cap on paid AI runs per day; extra runs use offline mode
    trust_proxy_headers: bool = True

    # --- Agent brain (Anthropic Messages API with tool use) -------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    agent_max_turns: int = 16
    agent_time_budget_s: int = 150  # hard stop, leaves room for the fallback inside 3 minutes
    agent_target_leads: int = 12
    agent_outreach_drafts: int = 5
    agent_followups: int = 5
    feedback_context_size: int = 20  # last N feedback items placed in the next run's prompt
    price_input_per_mtok: float = 3.0  # for the cost estimate shown per run (USD)
    price_output_per_mtok: float = 15.0

    # --- Research ---------------------------------------------------------------------------
    tavily_api_key: str = ""
    research_max_results: int = 6
    research_cache_path: str = str(BACKEND_DIR / "data" / "research_snapshot.json")

    # --- Seller identity used in drafts ------------------------------------------------------
    seller_company: str = "Acme Cloud Security"
    rep_name: str = "Jordan Reyes"
    rep_title: str = "Account Executive"

    # --- Internal alerts (never customer-facing) -----------------------------------------------
    slack_webhook_url: str = ""
    slack_channel_label: str = "#acme-sales-ops"

    # --- Live CRM ---------------------------------------------------------------------------
    hubspot_token: str = ""  # HubSpot private app token (crm.objects.companies/deals/contacts.read, crm.objects.owners.read)
    hubspot_sync_minutes: int = 60  # in real-data mode, how often HubSpot is read again; 0 turns it off

    # --- Mock CRM -----------------------------------------------------------------------------
    crm_accounts_csv: str = str(BACKEND_DIR / "data" / "crm_accounts.csv")
    crm_activity_csv: str = str(BACKEND_DIR / "data" / "crm_activity.csv")

    # -------------------------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def llm_live(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def research_live(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def slack_live(self) -> bool:
        return bool(self.slack_webhook_url)

    @property
    def company_set(self) -> bool:
        return self.seller_company != "Acme Cloud Security"

    @property
    def hubspot_live(self) -> bool:
        return bool(self.hubspot_token)

    @property
    def database_kind(self) -> str:
        return "sqlite" if self.database_url.startswith("sqlite") else "postgres"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
