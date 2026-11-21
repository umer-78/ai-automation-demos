"""Database schema (SQLAlchemy Core) and helpers.

The same code runs on SQLite (zero-setup local demo) and on Supabase Postgres (set
DATABASE_URL to the Supabase Session pooler connection string). The canonical Postgres DDL
lives in ../supabase/schema.sql and mirrors these tables.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

metadata = MetaData()

ID = BigInteger().with_variant(Integer, "sqlite")  # SQLite only autoincrements INTEGER keys
JSONType = JSON().with_variant(JSONB(), "postgresql")
TS = DateTime(timezone=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_utc() -> date:
    return utcnow().date()


# ------------------------------------------------------------------------------- mock CRM
accounts = Table(
    "accounts",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("company", String(200), nullable=False, unique=True),
    Column("domain", String(200)),
    Column("industry", String(160)),
    Column("category", String(40)),
    Column("size", Integer),  # employees
    Column("region", String(40)),
    Column("cloud_provider", String(40)),
    Column("stage", String(30), nullable=False),  # Prospect | Discovery | Proposal | Customer
    Column("deal_value", Float),
    Column("arr", Float),
    Column("plan", String(30)),
    Column("cloud_accounts_used", Integer),
    Column("cloud_accounts_limit", Integer),
    Column("renewal_date", Date),
    Column("stage_entered_at", TS, nullable=False),
    Column("last_contact", TS),
    Column("owner", String(80), nullable=False),
    Column("contact_name", String(120)),
    Column("contact_title", String(120)),
    Column("contact_email", String(200)),
    Column("notes", Text),
    Column("score", Integer),
    Column("score_reason", Text),
    Column("score_parts", JSONType),
    Column("flags", JSONType),
    Column("flag_reasons", JSONType),
    Column("analyzed_at", TS),
    Column("created_at", TS, nullable=False, default=utcnow),
    Column("updated_at", TS, nullable=False, default=utcnow),
)

activity = Table(
    "activity",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("account_id", ID, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(20), nullable=False),  # email | call | meeting | note
    Column("direction", String(20), nullable=False),  # outbound | inbound | internal
    Column("summary", Text, nullable=False),
    Column("occurred_at", TS, nullable=False),
    Column("created_at", TS, nullable=False, default=utcnow),
)
Index("ix_activity_account", activity.c.account_id, activity.c.occurred_at)

# ------------------------------------------------------------------------------- agent output
leads = Table(
    "leads",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("company", String(200), nullable=False),
    Column("company_key", String(200), nullable=False, unique=True),  # normalised name, de-duplicates leads
    Column("domain", String(200)),
    Column("industry", String(200)),
    Column("category", String(40)),
    Column("size_band", String(20)),
    Column("region", String(40)),
    Column("cloud_native", String(10)),
    Column("source_url", String(800), nullable=False),
    Column("reason", Text, nullable=False),
    Column("facts", JSONType, nullable=False),
    Column("score", Integer, nullable=False),
    Column("score_reason", Text, nullable=False),
    Column("score_parts", JSONType),
    Column("status", String(20), nullable=False, default="new"),  # new | drafted | approved | contacted | excluded
    Column("excluded_reason", Text),
    Column("research_source", String(20)),  # web | cache
    Column("first_run_id", String(40)),
    Column("last_run_id", String(40)),
    Column("created_at", TS, nullable=False, default=utcnow),
    Column("updated_at", TS, nullable=False, default=utcnow),
)
Index("ix_leads_score", leads.c.score)

drafts = Table(
    "drafts",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("kind", String(20), nullable=False),  # outreach | follow_up
    Column("lead_id", ID, ForeignKey("leads.id", ondelete="CASCADE")),
    Column("account_id", ID, ForeignKey("accounts.id", ondelete="CASCADE")),
    Column("run_id", String(40)),
    Column("recipient", String(200)),  # follow-ups: the CRM contact; outreach: chosen by the rep at send time
    Column("recipient_name", String(120)),
    Column("subject", String(300), nullable=False),
    Column("body", Text, nullable=False),
    Column("original_subject", String(300), nullable=False),
    Column("original_body", Text, nullable=False),
    Column("cited_fact", Text),
    Column("source_url", String(800)),
    Column("next_step", Text),
    Column("send_date", Date),
    Column("status", String(20), nullable=False, default="pending"),  # pending | approved | edited | rejected | sent
    Column("lessons_applied", JSONType),
    Column("previous_draft_id", ID),
    Column("generated_by", String(20), nullable=False),  # ai | template
    Column("word_count", Integer),
    Column("reviewer", String(80)),
    Column("reviewed_at", TS),
    Column("sent_at", TS),
    Column("created_at", TS, nullable=False, default=utcnow),
    Column("updated_at", TS, nullable=False, default=utcnow),
)
Index("ix_drafts_status", drafts.c.status)

feedback = Table(
    "feedback",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("draft_id", ID, ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False),
    Column("action", String(20), nullable=False),  # approve | edit | reject | mark_sent
    Column("reason", Text),
    Column("edited_subject", String(300)),
    Column("edited_body", Text),
    Column("reviewer", String(80)),
    Column("created_at", TS, nullable=False, default=utcnow),
)
Index("ix_feedback_created", feedback.c.created_at)

agent_runs = Table(
    "agent_runs",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("trigger", String(20), nullable=False),  # manual | schedule | api
    Column("mode", String(20), nullable=False),  # live | offline
    Column("model", String(80)),
    Column("research_source", String(20)),  # web | cache
    Column("status", String(30), nullable=False),  # running | completed | completed_with_fallback | failed
    Column("outcome", Text),
    Column("started_at", TS, nullable=False),
    Column("finished_at", TS),
    Column("duration_ms", Integer),
    Column("tools_called", JSONType, nullable=False),
    Column("tool_call_count", Integer, nullable=False, default=0),
    Column("tokens", Integer, nullable=False, default=0),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("cost_usd", Float, nullable=False, default=0.0),
    Column("turns", Integer, nullable=False, default=0),
    Column("leads_scored", Integer, nullable=False, default=0),
    Column("leads_created", Integer, nullable=False, default=0),
    Column("drafts_created", Integer, nullable=False, default=0),
    Column("followups_created", Integer, nullable=False, default=0),
    Column("accounts_flagged", Integer, nullable=False, default=0),
    Column("feedback_ids", JSONType, nullable=False),
    Column("context_feedback", Text),
    Column("lessons", JSONType),
    Column("icp_version", Integer),
    Column("summary", Text),
    Column("error", Text),
)
Index("ix_agent_runs_started", agent_runs.c.started_at)

icp_versions = Table(
    "icp_versions",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("version", Integer, nullable=False, unique=True),
    Column("author", String(20), nullable=False),  # agent | rep
    Column("summary", Text, nullable=False),
    Column("criteria", JSONType, nullable=False),
    Column("note", Text),
    Column("run_id", String(40)),
    Column("created_at", TS, nullable=False, default=utcnow),
)

# ------------------------------------------------------------------------------- shared ops tables
automation_log = Table(
    "automation_log",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("run_id", String(40), nullable=False),
    Column("workflow", String(80), nullable=False),
    Column("status", String(20), nullable=False),  # success | failure
    Column("source", String(30), nullable=False, default="python"),  # python | api | cron
    Column("error", Text),
    Column("details", JSONType),
    Column("duration_ms", Integer),
    Column("created_at", TS, nullable=False, default=utcnow),
)
Index("ix_automation_log_created", automation_log.c.created_at)

notifications = Table(
    "notifications",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("channel", String(20), nullable=False),  # slack (internal only)
    Column("kind", String(40), nullable=False, default="message"),  # message | alert | report
    Column("recipient", String(200)),
    Column("body", Text, nullable=False),
    Column("status", String(20), nullable=False),  # sent | simulated | failed
    Column("error", Text),
    Column("run_id", String(40)),
    Column("created_at", TS, nullable=False, default=utcnow),
)
Index("ix_notifications_created", notifications.c.created_at)

app_secrets = Table(  # keys saved from the Settings page, Fernet-encrypted
    "app_secrets",
    metadata,
    Column("name", String(80), primary_key=True),
    Column("ciphertext", Text, nullable=False),
    Column("updated_at", TS, nullable=False, default=utcnow),
)

kv_store = Table(
    "kv_store",
    metadata,
    Column("key", String(120), primary_key=True),
    Column("value", JSONType),
    Column("updated_at", TS, nullable=False, default=utcnow),
)

ALL_TABLES = (
    "accounts, activity, leads, drafts, feedback, agent_runs, icp_versions, automation_log, notifications, kv_store, app_secrets"
)


# --------------------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------------------
def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_database_url(url)
    if url.startswith("sqlite"):
        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine
    # Supabase's transaction pooler (port 6543) does not support prepared statements,
    # so they are disabled; this is harmless on the session pooler / direct connection.
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args={"prepare_threshold": None})


def init_db(engine: Engine) -> None:
    metadata.create_all(engine)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def row_to_dict(row: Any) -> dict[str, Any]:
    return {k: to_jsonable(v) for k, v in row._mapping.items()}


def rows_to_dicts(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in rows]


def dialect_insert(conn: Any, table: Table):
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table)


def upsert(conn: Any, table: Table, rows: list[dict[str, Any]], conflict_cols: list[str], update_cols: list[str], chunk_size: int = 400) -> None:
    """INSERT ... ON CONFLICT (conflict_cols) DO UPDATE. Same SQL shape on SQLite and Postgres."""
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        if not chunk:
            continue
        stmt = dialect_insert(conn, table).values(chunk)
        stmt = stmt.on_conflict_do_update(index_elements=list(conflict_cols), set_={col: stmt.excluded[col] for col in update_cols})
        conn.execute(stmt)
