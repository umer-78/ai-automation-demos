"""Database schema and helpers (SQLite locally, Supabase Postgres in production).

Tables follow the spec's data model (accounts, leads, drafts, feedback, agent_runs) plus the
rep-editable ICP, a per-run event stream for the live view, and the shared activity log.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (Column, Date, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, create_engine,
                        event)
from sqlalchemy.engine import Connection, Engine

metadata = MetaData()

meta = Table(
    "meta", metadata,
    Column("key", String(60), primary_key=True),
    Column("value", Text, nullable=False),
)

icp = Table(
    "icp", metadata,
    Column("id", Integer, primary_key=True),
    Column("summary", Text, nullable=False),
    Column("industries", Text, nullable=False),
    Column("size_min", Integer, nullable=False),
    Column("size_max", Integer, nullable=False),
    Column("regions", Text, nullable=False),
    Column("signals", Text, nullable=False),
    Column("exclusions", Text, nullable=False),
    Column("edited_by", String(10), nullable=False),          # "agent" or "rep"
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

accounts = Table(
    "accounts", metadata,
    Column("id", String(10), primary_key=True),
    Column("company", String(200), nullable=False),
    Column("industry", String(120), nullable=False),
    Column("size", Integer, nullable=False),
    Column("stage", String(20), nullable=False),               # Prospecting, Proposal, Negotiation, Customer
    Column("deal_value", Integer, nullable=False),
    Column("owner", String(80), nullable=False),
    Column("last_contact", Date, nullable=False),
    Column("stage_changed", Date, nullable=False),
    Column("notes", Text, nullable=False),
    Column("expansion_signal", Text),
    Column("score", Integer),
    Column("score_reason", Text),
)

agent_runs = Table(
    "agent_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", String(12), nullable=False),              # running, succeeded, failed
    Column("engine", String(80), nullable=False),
    Column("research", String(80), nullable=False),
    Column("tools_called", Text, nullable=False, default="[]"),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("feedback_used", Integer, nullable=False, default=0),
    Column("outcome", Text),
    Column("error", Text),
)

run_events = Table(
    "run_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("kind", String(12), nullable=False),                # tool, note, error, done
    Column("tool", String(40)),
    Column("summary", Text, nullable=False),
    Column("ms", Integer),
    Column("at", DateTime(timezone=True), nullable=False),
)

leads = Table(
    "leads", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("company", String(200), nullable=False),
    Column("company_key", String(200), nullable=False, unique=True),
    Column("website", String(300)),
    Column("industry", String(200)),
    Column("employees", Integer),
    Column("employees_note", String(40)),
    Column("source_url", String(600), nullable=False),
    Column("reason", Text, nullable=False),
    Column("fact", Text, nullable=False),
    Column("fact_url", String(600), nullable=False),
    Column("fact_date", Date),
    Column("fact_precision", String(8), nullable=False, default="none"),  # day, month, year or none: how exact fact_date is
    Column("signals", Text, nullable=False, default="[]"),
    Column("score", Integer, nullable=False),
    Column("score_reason", Text, nullable=False),
    Column("score_parts", Text, nullable=False),
    Column("status", String(12), nullable=False, default="new"),
    Column("run_id", Integer),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

drafts = Table(
    "drafts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("lead_id", Integer, ForeignKey("leads.id", ondelete="CASCADE")),
    Column("account_id", String(10), ForeignKey("accounts.id", ondelete="CASCADE")),
    Column("kind", String(12), nullable=False),                # first_touch, follow_up
    Column("subject", String(300), nullable=False),
    Column("body", Text, nullable=False),
    Column("fact", Text, nullable=False),
    Column("fact_url", String(600), nullable=False),
    Column("next_step", Text),
    Column("due_date", Date),
    Column("status", String(12), nullable=False),              # pending, edited, approved, rejected, superseded
    Column("original_subject", String(300), nullable=False),
    Column("original_body", Text, nullable=False),
    Column("engine", String(80), nullable=False),
    Column("run_id", Integer),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True)),
)

feedback = Table(
    "feedback", metadata,
    Column("id", String(36), primary_key=True),
    Column("draft_id", Integer, ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False),
    Column("action", String(10), nullable=False),              # approve, edit, reject
    Column("reason", Text),
    Column("edited_subject", String(300)),
    Column("edited_body", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

activity_log = Table(
    "activity_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("workflow", String(60), nullable=False),
    Column("status", String(12), nullable=False),              # success, failure
    Column("detail", Text),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# Children first, so deletes respect foreign keys.
ALL_TABLES = [feedback, drafts, leads, run_events, agent_runs, accounts, icp, activity_log, meta]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):  # noqa: ANN001
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            dbapi_conn.execute("PRAGMA busy_timeout=5000")
        return engine
    # Supabase's pooler runs in transaction mode, which can't keep prepared statements.
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args={"prepare_threshold": None})


@contextmanager
def tx(engine: Engine) -> Iterator[Connection]:
    """One transaction: commits on success, rolls back on error, always closes."""
    with engine.begin() as conn:
        yield conn


def log_activity(conn: Connection, workflow: str, status: str, detail: str | None = None, error: str | None = None) -> None:
    conn.execute(activity_log.insert().values(workflow=workflow, status=status, detail=detail, error=error,
                                              created_at=now_utc()))


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def jload(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def as_dict(row: Any) -> dict:
    """Row mapping to a JSON-friendly dict (dates as ISO strings)."""
    out = {}
    for k, v in dict(row).items():
        out[k] = v.isoformat() if isinstance(v, (date, datetime)) else v
    return out
