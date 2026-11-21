"""Module B analytics: KPIs, 30-day trend, channel mix, week-on-week CPA alerts, plus anomaly
detection, budget pacing and a simple spend forecast. All figures are computed from the
campaign_metrics table on every request (nothing is hard-coded)."""

from __future__ import annotations

import calendar
import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.context import Context
from app.db import campaign_metrics, clients, today_utc


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 2) if den else None


def _pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return round((new - old) / old, 4)


def latest_date(ctx: Context) -> date:
    with ctx.engine.connect() as conn:
        value = conn.execute(select(func.max(campaign_metrics.c.date))).scalar()
    if value is None:
        return today_utc() - timedelta(days=1)
    if isinstance(value, str):  # defensive: some drivers return ISO strings for aggregates
        value = date.fromisoformat(value[:10])
    return value


def _client_names(ctx: Context) -> dict[int, dict[str, Any]]:
    with ctx.engine.connect() as conn:
        rows = conn.execute(select(clients.c.id, clients.c.name, clients.c.status, clients.c.monthly_budget))
        return {r.id: {"name": r.name, "status": r.status, "monthly_budget": r.monthly_budget} for r in rows}


def _aggregate(ctx: Context, start: date, end: date, *, by: tuple[str, ...], client_id: int | None = None) -> list[dict[str, Any]]:
    cols = [getattr(campaign_metrics.c, b) for b in by]
    stmt = (
        select(
            *cols,
            func.sum(campaign_metrics.c.spend).label("spend"),
            func.sum(campaign_metrics.c.clicks).label("clicks"),
            func.sum(campaign_metrics.c.impressions).label("impressions"),
            func.sum(campaign_metrics.c.conversions).label("conversions"),
        )
        .where(campaign_metrics.c.date >= start, campaign_metrics.c.date <= end)
        .group_by(*cols)
    )
    if client_id:
        stmt = stmt.where(campaign_metrics.c.client_id == client_id)
    with ctx.engine.connect() as conn:
        out = []
        for r in conn.execute(stmt):
            m = dict(r._mapping)
            m["spend"] = float(m["spend"] or 0)
            m["clicks"] = int(m["clicks"] or 0)
            m["impressions"] = int(m["impressions"] or 0)
            m["conversions"] = int(m["conversions"] or 0)
            out.append(m)
        return out


def _kpis(spend: float, clicks: int, impressions: int, conversions: int) -> dict[str, Any]:
    return {
        "spend": round(spend, 2),
        "clicks": clicks,
        "impressions": impressions,
        "conversions": conversions,
        "cpa": _ratio(spend, conversions),
        "cpc": _ratio(spend, clicks),
        "ctr": round(clicks / impressions, 4) if impressions else None,
        "cvr": round(conversions / clicks, 4) if clicks else None,
    }


def _first_dates(ctx: Context) -> dict[int, date]:
    with ctx.engine.connect() as conn:
        rows = conn.execute(select(campaign_metrics.c.client_id, func.min(campaign_metrics.c.date)).group_by(campaign_metrics.c.client_id)).fetchall()
    return {r[0]: (r[1] if isinstance(r[1], date) else date.fromisoformat(str(r[1]))) for r in rows}


def overview(ctx: Context, days: int = 30, client_id: int | None = None) -> dict[str, Any]:
    """Totals for the window and change against the window before it. A change is only given when
    the data covers the whole earlier window; otherwise it would compare a full month with a
    partial one."""
    end = latest_date(ctx)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    names = _client_names(ctx)
    cur = {r["client_id"]: r for r in _aggregate(ctx, start, end, by=("client_id",), client_id=client_id)}
    prev = {r["client_id"]: r for r in _aggregate(ctx, prev_start, prev_end, by=("client_id",), client_id=client_id)}
    alerts = cpa_alerts(ctx)
    alert_count: dict[int, int] = defaultdict(int)
    for a in alerts:
        alert_count[a["client_id"]] += 1

    first = _first_dates(ctx)
    covered = {cid for cid, d in first.items() if d <= prev_start}
    rows = []
    tot = {"spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0}
    ctot = {"spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0}  # like for like: clients with a full earlier window
    ptot = {"spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0}
    for cid, r in cur.items():
        k = _kpis(r["spend"], r["clicks"], r["impressions"], r["conversions"])
        p = prev.get(cid) if cid in covered else None
        pk = _kpis(p["spend"], p["clicks"], p["impressions"], p["conversions"]) if p else None
        for key in tot:
            tot[key] += r[key]
            if p:
                ctot[key] += r[key]
                ptot[key] += p[key]
        rows.append(
            {
                "client_id": cid,
                "client": names.get(cid, {}).get("name", f"Client {cid}"),
                "status": names.get(cid, {}).get("status"),
                **k,
                "change": {
                    "spend": _pct_change(k["spend"], pk["spend"] if pk else None),
                    "conversions": _pct_change(k["conversions"], pk["conversions"] if pk else None),
                    "cpa": _pct_change(k["cpa"], pk["cpa"] if pk else None),
                },
                "alerts": alert_count.get(cid, 0),
            }
        )
    rows.sort(key=lambda x: x["spend"], reverse=True)
    totals = _kpis(tot["spend"], tot["clicks"], tot["impressions"], tot["conversions"])
    ptotals = _kpis(ptot["spend"], ptot["clicks"], ptot["impressions"], ptot["conversions"])
    ctotals = _kpis(ctot["spend"], ctot["clicks"], ctot["impressions"], ctot["conversions"])
    any_prev = ptot["spend"] > 0 or ptot["conversions"] > 0
    totals["change"] = {
        "spend": _pct_change(ctotals["spend"], ptotals["spend"]) if any_prev else None,
        "conversions": _pct_change(ctotals["conversions"], ptotals["conversions"]) if any_prev else None,
        "cpa": _pct_change(ctotals["cpa"], ptotals["cpa"]) if any_prev else None,
    }
    totals["change_basis"] = "like for like: clients with data for the whole earlier window"
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "previous_period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "totals": totals,
        "clients": rows,
        "alerts_total": len(alerts),
    }


def trend(ctx: Context, days: int = 30, client_id: int | None = None) -> dict[str, Any]:
    end = latest_date(ctx)
    start = end - timedelta(days=days - 1)
    by_day = {r["date"]: r for r in _aggregate(ctx, start, end, by=("date",), client_id=client_id)}
    by_day_channel = _aggregate(ctx, start, end, by=("date", "channel"), client_id=client_id)
    channel_spend: dict[date, dict[str, float]] = defaultdict(dict)
    for r in by_day_channel:
        channel_spend[r["date"]][r["channel"]] = round(r["spend"], 2)
    series = []
    day = start
    while day <= end:
        r = by_day.get(day)
        spend = r["spend"] if r else 0.0
        conv = r["conversions"] if r else 0
        series.append(
            {
                "date": day.isoformat(),
                "spend": round(spend, 2),
                "conversions": conv,
                "clicks": r["clicks"] if r else 0,
                "cpa": _ratio(spend, conv),
                "by_channel": channel_spend.get(day, {}),
            }
        )
        day += timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(), "series": series}


def channels(ctx: Context, days: int = 30, client_id: int | None = None) -> dict[str, Any]:
    end = latest_date(ctx)
    start = end - timedelta(days=days - 1)
    rows = _aggregate(ctx, start, end, by=("channel",), client_id=client_id)
    total_spend = sum(r["spend"] for r in rows) or 1.0
    out = []
    for r in sorted(rows, key=lambda x: x["spend"], reverse=True):
        k = _kpis(r["spend"], r["clicks"], r["impressions"], r["conversions"])
        out.append({"channel": r["channel"], **k, "share_of_spend": round(r["spend"] / total_spend, 4)})
    return {"start": start.isoformat(), "end": end.isoformat(), "channels": out}


ALERT_P_VALUE = 0.05  # alert only when a drop this large would happen by chance less than 1 time in 20


def poisson_cdf(k: float, lam: float) -> float:
    """P(X <= k) for X ~ Poisson(lam), computed in log space so large counts do not underflow."""
    if lam <= 0:
        return 1.0
    kk = int(math.floor(k + 1e-9))
    if kk < 0:
        return 0.0
    log_terms = [-lam + i * math.log(lam) - math.lgamma(i + 1) for i in range(kk + 1)]
    top = max(log_terms)
    return min(1.0, math.exp(top) * sum(math.exp(t - top) for t in log_terms))


def cpa_alerts(ctx: Context, threshold: float | None = None) -> list[dict[str, Any]]:
    """Campaign = client x channel. Alert when CPA this week is > threshold above last week, or a
    campaign spent money this week with zero conversions, and in both cases only when the drop in
    conversions is statistically real: at last week's CPA this week's spend should have bought
    `expected` conversions, and seeing this few by chance has probability p (Poisson). Low-volume
    campaigns (a few conversions a week) swing 30% on noise alone; they are not flagged for that."""
    threshold = ctx.settings.cpa_alert_threshold if threshold is None else threshold
    end = latest_date(ctx)
    this_start = end - timedelta(days=6)
    last_end = this_start - timedelta(days=1)
    last_start = last_end - timedelta(days=6)
    names = _client_names(ctx)
    cur = {(r["client_id"], r["channel"]): r for r in _aggregate(ctx, this_start, end, by=("client_id", "channel"))}
    prev = {(r["client_id"], r["channel"]): r for r in _aggregate(ctx, last_start, last_end, by=("client_id", "channel"))}
    alerts = []
    for key, r in cur.items():
        if names.get(key[0], {}).get("status") == "archived":
            continue
        p = prev.get(key)
        if not p:
            continue
        cpa_now = _ratio(r["spend"], r["conversions"])
        cpa_before = _ratio(p["spend"], p["conversions"])
        if not cpa_before or r["spend"] <= 0:
            continue
        expected = r["spend"] / cpa_before
        p_value = poisson_cdf(r["conversions"], expected)
        if p_value >= ALERT_P_VALUE:
            continue
        if r["conversions"] == 0:
            change, reason = None, "Spend with zero conversions this week"
        else:
            change = (cpa_now - cpa_before) / cpa_before
            if change <= threshold:
                continue
            reason = f"Cost per conversion up {change:.0%} week on week"
        alerts.append(
            {
                "client_id": key[0],
                "client": names.get(key[0], {}).get("name", f"Client {key[0]}"),
                "channel": key[1],
                "cpa_this_week": cpa_now,
                "cpa_last_week": cpa_before,
                "change": round(change, 4) if change is not None else None,
                "spend_this_week": round(r["spend"], 2),
                "conversions_this_week": r["conversions"],
                "conversions_last_week": p["conversions"],
                "reason": reason,
                "expected_conversions": round(expected, 1),
                "p_value": round(p_value, 4),
                "severity": "critical" if change is None or change > 0.5 else "warning",
                "week": {"start": this_start.isoformat(), "end": end.isoformat()},
            }
        )
    alerts.sort(key=lambda a: (a["change"] is not None, -(a["change"] or 0)))
    return alerts


def anomalies(ctx: Context, z_threshold: float = 2.5) -> list[dict[str, Any]]:
    """Daily CPA outliers in the last 7 days vs a 28-day baseline (z-score)."""
    end = latest_date(ctx)
    start = end - timedelta(days=34)
    names = _client_names(ctx)
    rows = _aggregate(ctx, start, end, by=("client_id", "channel", "date"))
    series: dict[tuple[int, str], dict[date, float]] = defaultdict(dict)
    for r in rows:
        if r["conversions"]:
            series[(r["client_id"], r["channel"])][r["date"]] = r["spend"] / r["conversions"]
    volume: dict[tuple[int, str], float] = defaultdict(float)
    for r in rows:
        if r["date"] <= end - timedelta(days=7):
            volume[(r["client_id"], r["channel"])] += r["conversions"]
    out = []
    for key, points in series.items():
        baseline = [v for d, v in points.items() if d <= end - timedelta(days=7)]
        if len(baseline) < 14 or volume[key] / 28 < 3:  # a daily CPA built on one or two conversions is noise
            continue
        mean = sum(baseline) / len(baseline)
        std = math.sqrt(sum((v - mean) ** 2 for v in baseline) / (len(baseline) - 1)) or 1e-9
        for d, v in sorted(points.items()):
            if d > end - timedelta(days=7):
                z = (v - mean) / std
                if z >= z_threshold:
                    out.append(
                        {
                            "client_id": key[0],
                            "client": names.get(key[0], {}).get("name"),
                            "channel": key[1],
                            "date": d.isoformat(),
                            "cpa": round(v, 2),
                            "baseline_cpa": round(mean, 2),
                            "z_score": round(z, 2),
                        }
                    )
    out.sort(key=lambda a: -a["z_score"])
    return out


def pacing(ctx: Context) -> list[dict[str, Any]]:
    """Month-to-date spend against each client's monthly budget."""
    end = latest_date(ctx)
    month_start = end.replace(day=1)
    days_in_month = calendar.monthrange(end.year, end.month)[1]
    names = _client_names(ctx)
    spend = {r["client_id"]: r["spend"] for r in _aggregate(ctx, month_start, end, by=("client_id",))}
    out = []
    for cid, info in names.items():
        budget = info.get("monthly_budget")
        if not budget or info.get("status") == "archived":
            continue
        mtd = spend.get(cid, 0.0)
        elapsed = end.day
        expected = budget * elapsed / days_in_month
        projected = mtd / elapsed * days_in_month if elapsed else 0.0
        ratio = mtd / expected if expected else None
        out.append(
            {
                "client_id": cid,
                "client": info["name"],
                "monthly_budget": round(budget, 2),
                "spend_mtd": round(mtd, 2),
                "expected_mtd": round(expected, 2),
                "projected_month": round(projected, 2),
                "pacing": round(ratio, 4) if ratio is not None else None,
                "status": "over" if ratio and ratio > 1.1 else "under" if ratio and ratio < 0.9 else "on track",
            }
        )
    out.sort(key=lambda x: -(x["pacing"] or 0))
    return out


def forecast(ctx: Context, client_id: int | None = None, horizon: int = 14) -> dict[str, Any]:
    """Least-squares line through the last 28 days of spend, projected `horizon` days ahead."""
    series = trend(ctx, days=28, client_id=client_id)["series"]
    ys = [p["spend"] for p in series]
    n = len(ys)
    if n < 2 or not any(ys):
        return {"points": [], "slope_per_day": 0.0}
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    intercept = my - slope * mx
    last = date.fromisoformat(series[-1]["date"])
    points = [
        {"date": (last + timedelta(days=i)).isoformat(), "spend": round(max(0.0, intercept + slope * (n - 1 + i)), 2)}
        for i in range(1, horizon + 1)
    ]
    return {"points": points, "slope_per_day": round(slope, 2), "projected_total": round(sum(p["spend"] for p in points), 2)}


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def cube(ctx: Context, days: int = 30, by: str = "client", client_id: int | None = None) -> dict[str, Any]:
    """Day-by-row grid for the 3D spend landscape.

    One row per client (or per client and channel when by="campaign"), one cell per day, each with
    spend, conversions and cost per conversion. Every row also carries its own median cost per
    conversion, so a day can be coloured by how it compares with that campaign's normal level
    rather than with campaigns that simply cost more.
    """
    end = latest_date(ctx)
    start = end - timedelta(days=days - 1)
    names = _client_names(ctx)
    keys = ("client_id", "date") if by == "client" else ("client_id", "channel", "date")
    raw = _aggregate(ctx, start, end, by=keys, client_id=client_id)
    cells: dict[tuple, dict[date, dict[str, Any]]] = defaultdict(dict)
    for r in raw:
        row_key = (r["client_id"],) if by == "client" else (r["client_id"], r["channel"])
        cells[row_key][_as_date(r["date"])] = r
    dates = [start + timedelta(days=i) for i in range(days)]
    rows = []
    for row_key, by_day in cells.items():
        values = []
        for d in dates:
            r = by_day.get(d)
            spend = round(r["spend"], 2) if r else 0.0
            conversions = r["conversions"] if r else 0
            values.append({"spend": spend, "conversions": conversions, "cpa": _ratio(spend, conversions)})
        cpas = [v["cpa"] for v in values if v["cpa"] is not None]
        client = names.get(row_key[0], {}).get("name", f"Client {row_key[0]}")
        rows.append(
            {
                "key": "-".join(str(k) for k in row_key),
                "client_id": row_key[0],
                "client": client,
                "channel": row_key[1] if by != "client" else None,
                "label": client if by == "client" else f"{client}, {row_key[1]}",
                "total_spend": round(sum(v["spend"] for v in values), 2),
                "total_conversions": sum(v["conversions"] for v in values),
                "median_cpa": round(statistics.median(cpas), 2) if cpas else None,
                "days": values,
            }
        )
    rows.sort(key=lambda r: r["total_spend"], reverse=True)
    return {
        "by": by,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "dates": [d.isoformat() for d in dates],
        "max_spend": max((v["spend"] for r in rows for v in r["days"]), default=0.0),
        "max_conversions": max((v["conversions"] for r in rows for v in r["days"]), default=0),
        "rows": rows,
    }


def client_week_stats(ctx: Context) -> dict[str, Any]:
    """Per-client this-week vs last-week numbers (input for the weekly AI summary)."""
    end = latest_date(ctx)
    this_start = end - timedelta(days=6)
    last_end = this_start - timedelta(days=1)
    last_start = last_end - timedelta(days=6)
    names = _client_names(ctx)
    cur = _aggregate(ctx, this_start, end, by=("client_id", "channel"))
    prev = {(r["client_id"], r["channel"]): r for r in _aggregate(ctx, last_start, last_end, by=("client_id", "channel"))}
    alerts = cpa_alerts(ctx)
    per_client: dict[int, dict[str, Any]] = {}
    for r in cur:
        cid = r["client_id"]
        if names.get(cid, {}).get("status") == "archived":
            continue
        c = per_client.setdefault(
            cid,
            {"client_id": cid, "client": names.get(cid, {}).get("name"), "this": defaultdict(float), "last": defaultdict(float), "channels": []},
        )
        p = prev.get((cid, r["channel"]), {"spend": 0.0, "conversions": 0, "clicks": 0})
        for k in ("spend", "conversions", "clicks"):
            c["this"][k] += r[k]
            c["last"][k] += p[k]
        c["channels"].append(
            {
                "channel": r["channel"],
                "spend": round(r["spend"], 2),
                "conversions": r["conversions"],
                "cpa": _ratio(r["spend"], r["conversions"]),
                "cpa_last_week": _ratio(p["spend"], p["conversions"]),
                "cpa_change": _pct_change(_ratio(r["spend"], r["conversions"]), _ratio(p["spend"], p["conversions"])),
            }
        )
    out = []
    for cid, c in per_client.items():
        this_cpa = _ratio(c["this"]["spend"], c["this"]["conversions"])
        last_cpa = _ratio(c["last"]["spend"], c["last"]["conversions"])
        out.append(
            {
                "client_id": cid,
                "client": c["client"],
                "spend": round(c["this"]["spend"], 2),
                "spend_last_week": round(c["last"]["spend"], 2),
                "conversions": int(c["this"]["conversions"]),
                "conversions_last_week": int(c["last"]["conversions"]),
                "cpa": this_cpa,
                "cpa_last_week": last_cpa,
                "cpa_change": _pct_change(this_cpa, last_cpa),
                "channels": sorted(c["channels"], key=lambda x: -x["spend"]),
                "alerts": [a for a in alerts if a["client_id"] == cid],
            }
        )
    out.sort(key=lambda x: -x["spend"])
    return {"week": {"start": this_start.isoformat(), "end": end.isoformat()}, "previous_week": {"start": last_start.isoformat(), "end": last_end.isoformat()}, "clients": out}
