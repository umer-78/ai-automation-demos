"""Module B: the reporting pipeline and every number the dashboard shows.

One set of windows and one set of SQL strings is used by the dashboard, the lineage panel and the
self-checks, so they can never disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.engine import Connection

from . import mockdata
from .db import campaign_metrics, clients, log_event, rows

ALERT_THRESHOLD_PCT = 25
RESTATE_DAYS = 14  # ad platforms restate recent days, so the job re-reads the last two weeks


@dataclass(frozen=True)
class Windows:
    today: date

    @property
    def last30(self) -> tuple[date, date]:
        return self.today - timedelta(days=29), self.today

    @property
    def cur7(self) -> tuple[date, date]:
        return self.today - timedelta(days=6), self.today

    @property
    def prev7(self) -> tuple[date, date]:
        return self.today - timedelta(days=13), self.today - timedelta(days=7)


SQL = {
    "kpis": ("SELECT COALESCE(SUM(spend),0) AS spend, COALESCE(SUM(clicks),0) AS clicks, "
             "COALESCE(SUM(conversions),0) AS conversions FROM campaign_metrics "
             "WHERE date BETWEEN :start AND :end"),
    "trend": ("SELECT date, SUM(spend) AS spend, SUM(conversions) AS conversions FROM campaign_metrics "
              "WHERE date BETWEEN :start AND :end GROUP BY date ORDER BY date"),
    "channels": ("SELECT channel, SUM(spend) AS spend, SUM(clicks) AS clicks, SUM(conversions) AS conversions "
                 "FROM campaign_metrics WHERE date BETWEEN :start AND :end GROUP BY channel ORDER BY channel"),
    "by_client": ("SELECT m.client_id, c.name, c.status, SUM(m.spend) AS spend, SUM(m.clicks) AS clicks, "
                  "SUM(m.conversions) AS conversions FROM campaign_metrics m JOIN clients c ON c.id = m.client_id "
                  "WHERE m.date BETWEEN :start AND :end GROUP BY m.client_id, c.name, c.status ORDER BY spend DESC"),
    "wow": ("SELECT m.client_id, c.name, m.channel, "
            "SUM(CASE WHEN m.date BETWEEN :cur_start AND :cur_end THEN m.spend ELSE 0 END) AS cur_spend, "
            "SUM(CASE WHEN m.date BETWEEN :cur_start AND :cur_end THEN m.conversions ELSE 0 END) AS cur_conv, "
            "SUM(CASE WHEN m.date BETWEEN :prev_start AND :prev_end THEN m.spend ELSE 0 END) AS prev_spend, "
            "SUM(CASE WHEN m.date BETWEEN :prev_start AND :prev_end THEN m.conversions ELSE 0 END) AS prev_conv "
            "FROM campaign_metrics m JOIN clients c ON c.id = m.client_id "
            "WHERE m.date BETWEEN :prev_start AND :cur_end GROUP BY m.client_id, c.name, m.channel "
            "ORDER BY m.client_id, m.channel"),
    "matrix": ("SELECT client_id, channel, SUM(spend) AS spend, SUM(conversions) AS conversions FROM campaign_metrics "
               "WHERE date BETWEEN :start AND :end GROUP BY client_id, channel ORDER BY client_id, channel"),
    "duplicates": ("SELECT COUNT(*) AS n FROM (SELECT client_id, date, channel, COUNT(*) AS c FROM campaign_metrics "
                   "GROUP BY client_id, date, channel HAVING COUNT(*) > 1) d"),
}


def usd(v) -> float:
    """Money from the database (Decimal, float or int) as dollars and cents."""
    return round(float(v or 0), 2)


def cpa(spend: float, conversions: float) -> float | None:
    """Cost per conversion (CPA). None when there were no conversions."""
    return round(float(spend) / float(conversions), 2) if conversions else None


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or not old:
        return None
    return round((new - old) / old * 100, 1)


def params_for(name: str, w: Windows) -> dict:
    if name == "wow":
        return {"cur_start": w.cur7[0], "cur_end": w.cur7[1], "prev_start": w.prev7[0], "prev_end": w.prev7[1]}
    if name == "duplicates":
        return {}
    return {"start": w.last30[0], "end": w.last30[1]}


def kpis(conn: Connection, w: Windows) -> dict:
    r = rows(conn, SQL["kpis"], **params_for("kpis", w))[0]
    spend, clicks, conv = usd(r["spend"]), int(r["clicks"]), int(r["conversions"])
    return {"spend": spend, "clicks": clicks, "conversions": conv, "cpa": cpa(spend, conv),
            "cpc": round(spend / clicks, 2) if clicks else None, "window": [d.isoformat() for d in w.last30]}


def trend(conn: Connection, w: Windows) -> list[dict]:
    found = {str(r["date"])[:10]: r for r in rows(conn, SQL["trend"], **params_for("trend", w))}
    out = []
    for back in range(29, -1, -1):
        d = (w.today - timedelta(days=back)).isoformat()
        r = found.get(d)
        out.append({"date": d, "spend": usd(r["spend"]) if r else 0, "conversions": int(r["conversions"]) if r else 0})
    return out


def channels(conn: Connection, w: Windows) -> list[dict]:
    return [{"channel": r["channel"], "spend": usd(r["spend"]), "clicks": int(r["clicks"]),
             "conversions": int(r["conversions"]), "cpa": cpa(r["spend"], r["conversions"])}
            for r in rows(conn, SQL["channels"], **params_for("channels", w))]


def wow(conn: Connection, w: Windows) -> list[dict]:
    out = []
    for r in rows(conn, SQL["wow"], **params_for("wow", w)):
        now_cpa, prev_cpa = cpa(r["cur_spend"], r["cur_conv"]), cpa(r["prev_spend"], r["prev_conv"])
        change = pct_change(now_cpa, prev_cpa)
        out.append({"client_id": r["client_id"], "client": r["name"], "channel": r["channel"],
                    "cpa_now": now_cpa, "cpa_prev": prev_cpa, "change_pct": change,
                    "alert": change is not None and change > ALERT_THRESHOLD_PCT})
    return out


def alerts(conn: Connection, w: Windows) -> list[dict]:
    return sorted([x for x in wow(conn, w) if x["alert"]], key=lambda x: -x["change_pct"])


def by_client(conn: Connection, w: Windows) -> list[dict]:
    weekly = {}
    for x in wow(conn, w):
        weekly.setdefault(x["client_id"], []).append(x)
    out = []
    for r in rows(conn, SQL["by_client"], **params_for("by_client", w)):
        ws = weekly.get(r["client_id"], [])
        out.append({"client_id": r["client_id"], "client": r["name"], "status": r["status"],
                    "spend": usd(r["spend"]), "clicks": int(r["clicks"]), "conversions": int(r["conversions"]),
                    "cpa": cpa(r["spend"], r["conversions"]),
                    "simulated": r["client_id"] in mockdata.SEED_IDS,
                    "wow": {x["channel"]: x["change_pct"] for x in ws},
                    "alerts": [x["channel"] for x in ws if x["alert"]]})
    return out


def client_week_numbers(conn: Connection, w: Windows) -> list[dict]:
    """Per-client inputs for the weekly summary (all channels together)."""
    agg: dict[str, dict] = {}
    for r in rows(conn, SQL["wow"], **params_for("wow", w)):
        a = agg.setdefault(r["client_id"], {"client_id": r["client_id"], "client": r["name"],
                                            "cur_spend": 0, "cur_conv": 0, "prev_spend": 0, "prev_conv": 0, "alerts": []})
        for k in ("cur_spend", "cur_conv", "prev_spend", "prev_conv"):
            a[k] += int(r[k])
    for x in alerts(conn, w):
        agg[x["client_id"]]["alerts"].append({"channel": x["channel"], "change_pct": x["change_pct"]})
    for a in agg.values():
        a["cpa_now"], a["cpa_prev"] = cpa(a["cur_spend"], a["cur_conv"]), cpa(a["prev_spend"], a["prev_conv"])
        a["change_pct"] = pct_change(a["cpa_now"], a["cpa_prev"])
    return list(agg.values())


def matrix(conn: Connection, w: Windows) -> list[dict]:
    return [{"client_id": r["client_id"], "channel": r["channel"], "spend": usd(r["spend"]),
             "conversions": int(r["conversions"]), "cpa": cpa(r["spend"], r["conversions"])}
            for r in rows(conn, SQL["matrix"], **params_for("matrix", w))]


def dashboard(conn: Connection, today: date) -> dict:
    w = Windows(today)
    return {"today": today.isoformat(), "kpis": kpis(conn, w), "trend": trend(conn, w), "channels": channels(conn, w),
            "by_client": by_client(conn, w), "matrix": matrix(conn, w), "alerts": alerts(conn, w),
            "threshold_pct": ALERT_THRESHOLD_PCT,
            "sample_basis": {"sources": mockdata.BENCHMARK_SOURCES, "clients": mockdata.benchmark_basis()},
            "windows": {"last30": [d.isoformat() for d in w.last30], "cur7": [d.isoformat() for d in w.cur7],
                        "prev7": [d.isoformat() for d in w.prev7]}}


def upsert_metrics(conn: Connection, metric_rows: list[dict]) -> int:
    if not metric_rows:
        return 0
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(campaign_metrics).values(metric_rows)
    stmt = stmt.on_conflict_do_update(index_elements=["client_id", "date", "channel"],
                                      set_={"spend": stmt.excluded.spend, "clicks": stmt.excluded.clicks,
                                            "conversions": stmt.excluded.conversions})
    conn.execute(stmt)
    return len(metric_rows)


def reportable_client_ids(conn: Connection) -> list[str]:
    return [r[0] for r in conn.execute(select(clients.c.id).where(clients.c.status != "Archived").order_by(clients.c.id))]


def run_daily_job(conn: Connection, today: date, source_rows: list[dict] | None = None, source: str = "mock ad API") -> dict:
    """Read the last RESTATE_DAYS of performance and upsert it. Safe to run any number of times."""
    ids = reportable_client_ids(conn)
    if source_rows is None:
        source_rows = mockdata.window_rows(today, RESTATE_DAYS, [i for i in ids if i in mockdata.SEED_IDS])
    known = set(ids)
    source_rows = [r for r in source_rows if r["client_id"] in known]
    n = upsert_metrics(conn, source_rows)
    dup = int(rows(conn, SQL["duplicates"])[0]["n"])
    days = sorted({r["date"] for r in source_rows})
    span = f"{days[0].isoformat()} to {days[-1].isoformat()}" if days else "no rows"
    log_event(conn, "reporting", "success", f"Daily job from the {source}: {n} rows upserted for {span}, {dup} duplicates")
    return {"upserted": n, "duplicate_rows": dup, "span": span, "source": source}


def latest_metric_date(conn: Connection) -> date | None:
    r = rows(conn, "SELECT MAX(date) AS d FROM campaign_metrics")[0]["d"]
    if r is None:
        return None
    return r if isinstance(r, date) else date.fromisoformat(str(r)[:10])
