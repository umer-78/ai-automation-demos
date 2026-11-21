"""Database schema (SQLAlchemy Core) and helpers.

The same code runs on SQLite (zero-setup local demo) and on Supabase Postgres
(set DATABASE_URL to the Supabase *Session pooler* connection string).
The canonical Postgres DDL lives in ../supabase/schema.sql and mirrors these tables.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

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
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine

metadata = MetaData()

ID = BigInteger().with_variant(Integer, "sqlite")  # SQLite only autoincrements INTEGER keys
JSONType = JSON().with_variant(JSONB(), "postgresql")
TS = DateTime(timezone=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today_utc() -> date:
    return utcnow().date()


clients = Table(
    "clients",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("name", String(200), nullable=False, unique=True),
    Column("website", String(500)),
    Column("industry", String(120)),
    Column("services", JSONType, nullable=False),
    Column("manager", String(120)),
    Column("manager_email", String(200)),
    Column("status", String(30), nullable=False, default="new"),
    Column("brief", Text),
    Column("brief_data", JSONType),
    Column("monthly_budget", Float),
    Column("airtable_record_id", String(40), unique=True),
    Column("created_at", TS, nullable=False, default=utcnow),
    Column("updated_at", TS, nullable=False, default=utcnow),
    Column("archived_at", TS),
)

client_tasks = Table(
    "client_tasks",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("client_id", ID, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
    Column("service", String(40), nullable=False),
    Column("title", String(300), nullable=False),
    Column("position", Integer, nullable=False, default=0),
    Column("status", String(20), nullable=False, default="open"),  # open | done | closed
    Column("due_date", Date),
    Column("created_at", TS, nullable=False, default=utcnow),
    Column("closed_at", TS),
    UniqueConstraint("client_id", "service", "title", name="uq_task_client_service_title"),
)

campaign_metrics = Table(
    "campaign_metrics",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("client_id", ID, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
    Column("date", Date, nullable=False),
    Column("channel", String(40), nullable=False),
    Column("impressions", Integer, nullable=False, default=0),
    Column("clicks", Integer, nullable=False, default=0),
    Column("spend", Float, nullable=False, default=0.0),
    Column("conversions", Float, nullable=False, default=0.0),  # Google Ads reports fractional conversions
    Column("created_at", TS, nullable=False, default=utcnow),
    Column("updated_at", TS, nullable=False, default=utcnow),
    UniqueConstraint("client_id", "date", "channel", name="uq_metrics_client_date_channel"),
)
Index("ix_metrics_date", campaign_metrics.c.date)

automation_log = Table(
    "automation_log",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("run_id", String(40), nullable=False),
    Column("workflow", String(80), nullable=False),
    Column("status", String(20), nullable=False),  # success | failure
    Column("source", String(30), nullable=False, default="python"),  # python | make | api | cron | airtable
    Column("error", Text),
    Column("details", JSONType),
    Column("duration_ms", Integer),
    Column("client_id", ID),
    Column("created_at", TS, nullable=False, default=utcnow),
)
Index("ix_automation_log_created", automation_log.c.created_at)
Index("ix_automation_log_run", automation_log.c.run_id)

site_drafts = Table(
    "site_drafts",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("group_id", String(40), nullable=False),  # all versions of one draft share a group_id
    Column("client_id", ID, ForeignKey("clients.id", ondelete="SET NULL")),
    Column("business_name", String(200), nullable=False),
    Column("inputs", JSONType, nullable=False),
    Column("sections", JSONType, nullable=False),
    Column("html", Text, nullable=False),
    Column("html_url", String(600), nullable=False),
    Column("storage_path", String(300), nullable=False),
    Column("version", Integer, nullable=False),
    Column("changed_section", String(40)),
    Column("generated_by", String(30), nullable=False),
    Column("created_at", TS, nullable=False, default=utcnow),
    UniqueConstraint("group_id", "version", name="uq_site_draft_version"),
)

notifications = Table(
    "notifications",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("channel", String(20), nullable=False),  # slack | email
    Column("kind", String(40), nullable=False, default="message"),  # message | alert | draft | summary
    Column("recipient", String(200)),
    Column("subject", String(300)),
    Column("body", Text, nullable=False),
    Column("status", String(20), nullable=False),  # sent | simulated | failed
    Column("error", Text),
    Column("run_id", String(40)),
    Column("created_at", TS, nullable=False, default=utcnow),
)
Index("ix_notifications_created", notifications.c.created_at)

weekly_summaries = Table(
    "weekly_summaries",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("run_id", String(40), nullable=False),
    Column("client_id", ID, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("sentences", JSONType, nullable=False),
    Column("generated_by", String(30), nullable=False),
    Column("created_at", TS, nullable=False, default=utcnow),
)

client_accounts = Table(  # which ad account / property feeds each client's live numbers
    "client_accounts",
    metadata,
    Column("client_id", ID, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True),
    Column("platform", String(30), primary_key=True),  # google_ads | meta_ads | search_console | ga4 | seo_fee
    Column("ref", String(300), nullable=False),
    Column("updated_at", TS, nullable=False, default=utcnow),
)

app_secrets = Table(
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


def dialect_insert(conn: Connection, table: Table):
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table)


def upsert(
    conn: Connection,
    table: Table,
    rows: Sequence[dict[str, Any]],
    conflict_cols: Sequence[str],
    update_cols: Sequence[str],
    chunk_size: int = 400,
) -> None:
    """INSERT ... ON CONFLICT (conflict_cols) DO UPDATE. Same SQL shape on SQLite and Postgres."""
    for start in range(0, len(rows), chunk_size):
        chunk = list(rows[start : start + chunk_size])
        if not chunk:
            continue
        stmt = dialect_insert(conn, table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_cols),
            set_={col: stmt.excluded[col] for col in update_cols},
        )
        conn.execute(stmt)


def insert_ignore(conn: Connection, table: Table, rows: Sequence[dict[str, Any]], conflict_cols: Sequence[str]) -> None:
    if not rows:
        return
    stmt = dialect_insert(conn, table).values(list(rows)).on_conflict_do_nothing(index_elements=list(conflict_cols))
    conn.execute(stmt)
