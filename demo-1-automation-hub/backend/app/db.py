"""Database schema and connection helpers (SQLite locally, Supabase Postgres in production)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (Boolean, Column, Numeric, Date, DateTime, ForeignKey, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, bindparam, create_engine, event, text)
from sqlalchemy.engine import Connection, Engine

metadata = MetaData()

clients = Table(
    "clients", metadata,
    Column("id", String(40), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("website", String(300)),
    Column("industry", String(200)),
    Column("services", Text, nullable=False, default="[]"),
    Column("manager", String(120)),
    Column("manager_email", String(200)),
    Column("status", String(20), nullable=False, default="Active"),
    Column("brief", Text),
    Column("airtable_record_id", String(40), unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("archived_at", DateTime(timezone=True)),
)

tasks = Table(
    "tasks", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("client_id", String(40), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
    Column("service", String(40), nullable=False),
    Column("title", String(200), nullable=False),
    Column("status", String(20), nullable=False, default="open"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True)),
)

campaign_metrics = Table(
    "campaign_metrics", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("client_id", String(40), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
    Column("date", Date, nullable=False),
    Column("channel", String(40), nullable=False),
    Column("spend", Numeric(14, 2), nullable=False),  # dollars and cents
    Column("clicks", Integer, nullable=False),
    Column("conversions", Integer, nullable=False),
    UniqueConstraint("client_id", "date", "channel", name="uq_metrics_client_date_channel"),
)

automation_log = Table(
    "automation_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("workflow", String(60), nullable=False),
    Column("status", String(20), nullable=False),
    Column("error", Text),
    Column("detail", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

site_drafts = Table(
    "site_drafts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("site_id", String(40), nullable=False),
    Column("client_id", String(40)),
    Column("business_name", String(200), nullable=False),
    Column("industry", String(200)),
    Column("tone", String(60)),
    Column("services", Text),
    Column("colour", String(20)),
    Column("html", Text, nullable=False),
    Column("html_url", String(500)),
    Column("version", Integer, nullable=False),
    Column("section", String(20)),
    Column("engine", String(80)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

email_drafts = Table(
    "email_drafts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("client_id", String(40)),
    Column("to_addr", String(200)),
    Column("subject", String(300), nullable=False),
    Column("body", Text, nullable=False),
    Column("delivery", String(120), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

summaries = Table(
    "summaries", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("client_id", String(40), nullable=False),
    Column("week_end", Date, nullable=False),
    Column("sentences", Text, nullable=False),
    Column("engine", String(80), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

ALL_TABLES = [summaries, email_drafts, site_drafts, automation_log, campaign_metrics, tasks, clients]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # noqa: ANN001
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
        return engine
    # Supabase's pooler runs in transaction mode, which can't keep prepared statements.
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5,
                         connect_args={"prepare_threshold": None})


@contextmanager
def tx(engine: Engine) -> Iterator[Connection]:
    """One transaction: commits on success, rolls back on error, always closes."""
    with engine.begin() as conn:
        yield conn


def rows(conn: Connection, sql: str, **params: Any) -> list[dict]:
    """Run a raw SQL string with date params typed correctly on SQLite and Postgres."""
    binds = [bindparam(k, type_=Date) for k, v in params.items() if isinstance(v, date) and not isinstance(v, datetime)]
    stmt = text(sql).bindparams(*binds) if binds else text(sql)
    return [dict(r) for r in conn.execute(stmt, params).mappings().all()]


def log_event(conn: Connection, workflow: str, status: str, detail: str | None = None, error: str | None = None) -> None:
    conn.execute(automation_log.insert().values(workflow=workflow, status=status, detail=detail, error=error,
                                                created_at=now_utc()))


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def jload(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default
