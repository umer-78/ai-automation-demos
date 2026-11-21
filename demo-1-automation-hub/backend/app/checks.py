"""Read-only integrity checks, data lineage and the training-data export.

Nothing in this module writes to the database: the idempotency check runs inside a transaction that
is always rolled back.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.engine import Engine

from . import mockdata
from .db import clients, jload, rows, summaries
from .reporting import SQL, Windows, alerts, kpis, params_for, trend, upsert_metrics


def integrity(engine: Engine, today: date, llm_label: str) -> dict:
    w = Windows(today)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    with engine.connect() as conn:
        n = rows(conn, "SELECT COUNT(*) AS n FROM campaign_metrics")[0]["n"]
        add("Metric rows present", n > 0, f"{n} rows in campaign_metrics")
        k = kpis(conn, w)
        raw = rows(conn, "SELECT SUM(spend) AS s, SUM(conversions) AS v FROM campaign_metrics "
                         "WHERE date >= :a AND date <= :b", a=w.last30[0], b=w.last30[1])[0]
        cents = lambda v: round(float(v or 0) * 100)  # noqa: E731
        add("30-day KPI equals a raw re-sum", cents(k["spend"]) == cents(raw["s"]) and k["conversions"] == int(raw["v"] or 0),
            f"KPI spend ${k['spend']:,.2f} vs raw ${float(raw['s'] or 0):,.2f}")
        t = trend(conn, w)
        add("Trend chart covers the same 30 days and sums to the KPI",
            len(t) == 30 and sum(cents(x["spend"]) for x in t) == cents(k["spend"]),
            f"{len(t)} days, chart total ${sum(x['spend'] for x in t):,.2f}")
        dup = int(rows(conn, SQL["duplicates"])[0]["n"])
        add("No duplicate client/date/channel rows", dup == 0, f"{dup} duplicates")
        a = alerts(conn, w)
        add("Cost-per-conversion alert fires for the planted jump", any(x["client_id"] == mockdata.JUMP_CLIENT
                                                                        and x["channel"] == mockdata.JUMP_CHANNEL for x in a),
            ", ".join(f"{x['client']} / {x['channel']} +{x['change_pct']}%" for x in a) or "no alerts")
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            ids = [r[0] for r in conn.execute(select(clients.c.id))]
            sample = mockdata.window_rows(today, 2, ids)
            before = rows(conn, "SELECT COUNT(*) AS n FROM campaign_metrics")[0]["n"]
            upsert_metrics(conn, sample)
            once = rows(conn, "SELECT COUNT(*) AS n FROM campaign_metrics")[0]["n"]
            upsert_metrics(conn, sample)
            twice = rows(conn, "SELECT COUNT(*) AS n FROM campaign_metrics")[0]["n"]
            add("Daily upsert is idempotent (tested in a rolled-back transaction)", twice == once,
                f"first run {once - before:+d} rows, second run {twice - once:+d} rows")
        finally:
            trans.rollback()
    add("Engine is labelled", True, llm_label)
    return {"all_ok": all(c["ok"] for c in checks), "checks": checks, "today": today.isoformat()}


def lineage(engine: Engine, today: date) -> list[dict]:
    """The exact SQL the dashboard runs, with its parameters and the value it returns right now."""
    w = Windows(today)
    out = []
    with engine.connect() as conn:
        for name, label in [("kpis", "Spend, clicks and conversions, last 30 days"), ("trend", "30-day trend"),
                            ("channels", "Channel breakdown"), ("by_client", "Per-client totals"), ("matrix", "Client x channel totals (3D towers)"),
                            ("wow", "Week-on-week cost per conversion (alert input)")]:
            params = params_for(name, w)
            result = rows(conn, SQL[name], **params)
            out.append({"metric": label, "sql": SQL[name], "params": {k: v.isoformat() for k, v in params.items()},
                        "rows": len(result), "sample": json.loads(json.dumps(result[:3], default=str))})
    out.append({"metric": "Cost per conversion", "sql": "spend / conversions, computed in Python from the rows above",
                "params": {}, "rows": 0, "sample": []})
    return out


def training_data(engine: Engine) -> str:
    """Stored briefs and summaries as JSONL, labelled honestly with the engine that produced them."""
    lines = []
    with engine.connect() as conn:
        for c in conn.execute(select(clients)).mappings():
            brief = jload(c["brief"])
            if brief:
                lines.append({"task": "client_brief", "input": {"client": c["name"], "industry": c["industry"],
                                                                "service": brief.get("service")},
                              "output": {k: brief[k] for k in ("audience", "tone", "quick_wins") if k in brief},
                              "engine": brief.get("engine"), "label": "unreviewed"})
        for s in conn.execute(select(summaries).order_by(summaries.c.id)).mappings():
            lines.append({"task": "weekly_summary", "input": {"client_id": s["client_id"], "week_end": str(s["week_end"])},
                          "output": jload(s["sentences"], []), "engine": s["engine"], "label": "unreviewed"})
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines)
