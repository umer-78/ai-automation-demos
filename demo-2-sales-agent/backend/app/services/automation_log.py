"""Automation run logging + failure alerts (same module as Demo 1).

Rule from the spec: *every automation logs success and failure to a table, and failures send
an alert*. Wrap any workflow in ``AutomationRun`` and both happen automatically:

    with AutomationRun(engine, notifier, "weekly_report") as run:
        run.step("report_built", leads=12)
        ...

Steps are also kept in an in-process registry so the dashboard can show live progress.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from sqlalchemy.engine import Engine

from app.db import automation_log, utcnow
from app.services.notify import Notifier

_LIVE: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_MAX_LIVE = 200


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def live_run(run_id: str) -> dict[str, Any] | None:
    with _LOCK:
        run = _LIVE.get(run_id)
        return {**run, "steps": list(run["steps"])} if run else None


def write_log(
    engine: Engine,
    *,
    workflow: str,
    status: str,
    run_id: str | None = None,
    source: str = "python",
    error: str | None = None,
    details: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    row = {
        "run_id": run_id or new_run_id(),
        "workflow": workflow,
        "status": status,
        "source": source,
        "error": error,
        "details": details or {},
        "duration_ms": duration_ms,
        "created_at": utcnow(),
    }
    with engine.begin() as conn:
        result = conn.execute(automation_log.insert().values(**row))
        row["id"] = result.inserted_primary_key[0]
    return row


def log_and_alert(
    engine: Engine,
    notifier: Notifier,
    *,
    workflow: str,
    status: str,
    run_id: str | None = None,
    source: str = "python",
    error: str | None = None,
    details: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    row = write_log(
        engine,
        workflow=workflow,
        status=status,
        run_id=run_id,
        source=source,
        error=error,
        details=details,
        duration_ms=duration_ms,
    )
    if status == "failure":
        notifier.alert(workflow, error or "Unknown error", run_id=row["run_id"], context=f"Source: {source}")
    return row


def finish_live_run(run_id: str | None, status: str, error: str | None = None) -> None:
    if not run_id:
        return
    with _LOCK:
        if run_id in _LIVE:
            _LIVE[run_id].update(status=status, error=error)


class AutomationRun:
    def __init__(
        self,
        engine: Engine,
        notifier: Notifier,
        workflow: str,
        *,
        source: str = "python",
        run_id: str | None = None,
        ):
        self.engine = engine
        self.notifier = notifier
        self.workflow = workflow
        self.source = source
        self.run_id = run_id or new_run_id()
        self.details: dict[str, Any] = {}
        self.steps: list[dict[str, Any]] = []
        self._t0 = 0.0
        self.log_row: dict[str, Any] | None = None

    def __enter__(self) -> "AutomationRun":
        self._t0 = time.perf_counter()
        with _LOCK:
            if len(_LIVE) >= _MAX_LIVE:
                _LIVE.pop(next(iter(_LIVE)))
            _LIVE[self.run_id] = {
                "run_id": self.run_id,
                "workflow": self.workflow,
                "status": "running",
                "steps": [],
                "started_at": utcnow().isoformat(),
                "error": None,
            }
        return self

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)

    def step(self, label: str, /, **info: Any) -> None:
        entry = {"step": label, "at_ms": self.elapsed_ms, **info}
        self.steps.append(entry)
        with _LOCK:
            if self.run_id in _LIVE:
                _LIVE[self.run_id]["steps"].append(entry)

    def set(self, **details: Any) -> None:
        self.details.update(details)

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration = self.elapsed_ms
        details = {**self.details, "steps": self.steps}
        if exc is None:
            self.log_row = write_log(
                self.engine,
                workflow=self.workflow,
                status="success",
                run_id=self.run_id,
                source=self.source,
                details=details,
                duration_ms=duration,
            )
            final = "success"
            error = None
        else:
            error = str(exc) or exc_type.__name__
            self.log_row = log_and_alert(
                self.engine,
                self.notifier,
                workflow=self.workflow,
                status="failure",
                run_id=self.run_id,
                source=self.source,
                error=f"{exc_type.__name__}: {error}",
                details=details,
                duration_ms=duration,
            )
            final = "failure"
        with _LOCK:
            if self.run_id in _LIVE:
                _LIVE[self.run_id].update(status=final, error=error, duration_ms=duration)
        return False  # never swallow the exception; callers decide how to respond
