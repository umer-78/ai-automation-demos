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

    # --- App -----------------------------------------------------------------
    app_name: str = "Northwind Digital Automation Hub"
    environment: str = "development"  # development | production
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'northwind.db').as_posix()}"
    public_base_url: str = "http://localhost:8000"
    seed_history: bool = True  # also run a week of real workflows on first start (onboarding, site draft, pipeline)
    auto_seed: bool = True  # seed demo data on first start when the database is empty
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Security --------------------------------------------------------------
    automation_api_key: str = ""  # X-Automation-Key header expected from Make.com / cron
    admin_token: str = ""  # X-Admin-Token header for admin endpoints (reset, webhook registration)
    owner_token: str = ""  # X-Owner-Token header for saving API keys from the Settings page
    app_secret: str = ""  # encrypts API keys saved from the Settings page (required in production)
    rate_limit_per_hour: int = 30  # public AI / write actions per IP per hour
    trust_proxy_headers: bool = True  # use X-Forwarded-For behind Railway / Render

    # --- AI model (Anthropic API) -------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_fast_model: str = "claude-haiku-5-5"

    # --- Alerts & email ----------------------------------------------------------
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "Northwind Automation <automation@northwind-digital.example>"

    # --- Airtable ----------------------------------------------------------------
    airtable_token: str = ""
    airtable_base_id: str = ""
    airtable_table: str = "Clients"

    # --- Make.com -----------------------------------------------------------------
    make_onboarding_webhook_url: str = ""
    make_offboarding_webhook_url: str = ""

    # --- Supabase storage (Postgres itself is DATABASE_URL) ---------------------------
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "site-drafts"
    local_storage_dir: str = str(BACKEND_DIR / "data" / "storage")

    # --- Reporting pipeline ----------------------------------------------------------
    metrics_source: str = "mock"  # mock | http | csv
    metrics_api_url: str = ""  # used when metrics_source=http
    metrics_csv_path: str = str(BACKEND_DIR / "data" / "sample_ad_performance.csv")
    metrics_lookback_days: int = 14  # ad platforms restate recent days; upserts make this safe
    cpa_alert_threshold: float = 0.25  # alert when cost per conversion rises > 25% week on week
    report_currency: str = "USD"  # every connected ad account must report in this currency

    # --- Live ad platform data (saved from Settings, or set here) ---------------------
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_refresh_token: str = ""  # written by "Sign in with Google" on the Settings page
    google_ads_developer_token: str = ""
    google_ads_login_customer_id: str = ""  # manager (MCC) account ID, optional
    google_ads_api_version: str = "v26"
    meta_access_token: str = ""  # Meta Business system user token with ads_read
    meta_api_version: str = "v26.0"
    meta_conversion_actions: str = "lead,purchase"  # Meta action types counted as conversions
    live_sync_minutes: int = 60  # how often the app pulls fresh numbers in live mode; 0 turns it off
    live_sync_days: int = 3  # recent days re-pulled on each sync (platforms restate conversions)
    viewer_token: str = ""  # optional read-only access code for teammates once real data is in

    # ---------------------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def llm_live(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def slack_live(self) -> bool:
        return bool(self.slack_webhook_url)

    @property
    def email_live(self) -> bool:
        return bool(self.smtp_host)

    @property
    def airtable_live(self) -> bool:
        return bool(self.airtable_token and self.airtable_base_id)

    @property
    def make_live(self) -> bool:
        return bool(self.make_onboarding_webhook_url)

    @property
    def storage_live(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def google_live(self) -> bool:
        return bool(self.google_oauth_client_id and self.google_oauth_client_secret and self.google_oauth_refresh_token)

    @property
    def google_ads_live(self) -> bool:
        return self.google_live and bool(self.google_ads_developer_token)

    @property
    def meta_live(self) -> bool:
        return bool(self.meta_access_token)

    @property
    def database_kind(self) -> str:
        return "sqlite" if self.database_url.startswith("sqlite") else "postgres"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
