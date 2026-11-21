"""Module B: daily ad-performance pipeline.

Reads rows from the mock ad-platform API (default), an HTTP endpoint or a CSV file, validates
them and upserts into campaign_metrics on (client_id, date, channel). Ad platforms restate the
last days (late conversions), so every run reloads a lookback window; the upsert makes reruns
safe: running the job twice never creates duplicate rows.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import and_, func, select

from app.context import Context
from app.db import campaign_metrics, client_accounts, clients, today_utc, upsert, utcnow
from app.services import connectors
from app.services.data_mode import get_mode, live_available
from app.services.automation_log import AutomationRun
from app.workflows import analytics
from app.workflows.synthetic import CHANNELS, synth_rows


class PipelineError(RuntimeError):
    pass


def _active_clients(ctx: Context) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        rows = conn.execute(
            select(clients.c.id, clients.c.name, clients.c.industry, clients.c.services, clients.c.monthly_budget).where(clients.c.status == "active")
        )
        return [dict(r._mapping) for r in rows]


def live_accounts(ctx: Context) -> dict[int, dict[str, Any]]:
    """{client_id: {"name": ..., "google_ads": "123-...", "meta_ads": "act_...", ...}} for current clients."""
    out: dict[int, dict[str, Any]] = {}
    with ctx.engine.connect() as conn:
        q = select(client_accounts.c.client_id, client_accounts.c.platform, client_accounts.c.ref, clients.c.name).join(
            clients, clients.c.id == client_accounts.c.client_id
        ).where(clients.c.status != "archived")
        for r in conn.execute(q):
            out.setdefault(r.client_id, {"name": r.name})[r.platform] = r.ref
    return out


def default_source(ctx: Context) -> str:
    if get_mode(ctx) == "real":
        return "live" if live_available(ctx) else "none"
    return ctx.settings.metrics_source


def fetch_rows(ctx: Context, source: str, start: date, end: date) -> list[dict[str, Any]]:
    if source == "mock":
        if get_mode(ctx) == "real":
            raise PipelineError("Sample data is switched off because this hub now runs on real data.")
        return synth_rows(_active_clients(ctx), start, end, anchor=today_utc())
    if source == "http":
        if not ctx.settings.metrics_api_url:
            raise PipelineError("METRICS_API_URL is not set")
        resp = httpx.get(
            ctx.settings.metrics_api_url,
            params={"start": start.isoformat(), "end": end.isoformat()},
            timeout=30,
        )
        if resp.status_code >= 300:
            raise PipelineError(f"Metrics API returned HTTP {resp.status_code}")
        payload = resp.json()
        return payload["rows"] if isinstance(payload, dict) else payload
    if source == "csv":
        path = Path(ctx.settings.metrics_csv_path)
        if not path.exists():
            raise PipelineError(f"CSV not found: {path}")
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    raise PipelineError(f"unknown metrics source '{source}'")


def _clean(row: dict[str, Any], client_ids: dict[str, int]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        name = str(row.get("client") or "").strip()
        cid = client_ids.get(name.lower())
        if not cid:
            return None, f"unknown client '{name}'"
        day = row["date"] if isinstance(row["date"], date) else date.fromisoformat(str(row["date"])[:10])
        channel = str(row["channel"]).strip()
        if channel not in CHANNELS:
            return None, f"unknown channel '{channel}'"
        clean = {
            "client_id": cid,
            "date": day,
            "channel": channel,
            "impressions": int(float(row.get("impressions") or 0)),
            "clicks": int(float(row["clicks"])),
            "spend": round(float(row["spend"]), 2),
            "conversions": round(float(row["conversions"]), 2),
        }
    except (KeyError, ValueError, TypeError) as exc:
        return None, f"invalid row: {exc}"
    if min(clean["impressions"], clean["clicks"], clean["spend"], clean["conversions"]) < 0:
        return None, "negative value"
    return clean, None


def run_daily_metrics(
    ctx: Context,
    *,
    source: str | None = None,
    days: int | None = None,
    end: date | None = None,
    run_source: str = "cron",
    post_alerts: bool = True,
    simulate_failure: bool = False,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch, validate and upsert one window of ad metrics. Passing `rows` loads them instead of fetching."""
    source = source or default_source(ctx)
    days = days or ctx.settings.metrics_lookback_days
    end = end or (today_utc() - timedelta(days=1))
    start = end - timedelta(days=days - 1)

    with AutomationRun(ctx.engine, ctx.notifier, "daily_metrics_pipeline", source=run_source) as run:
        if simulate_failure:
            raise PipelineError("Deliberate test failure: ad platform API timed out (simulate_failure=true)")
        warnings: list[str] = []
        if rows is not None:
            raw = rows
        elif source == "live":
            raw, warnings = connectors.collect(ctx.settings, live_accounts(ctx), start, end)
            if warnings and not raw:
                raise PipelineError("; ".join(warnings[:3]))
        elif source == "none":
            raw = []  # real-data mode with no connected accounts: nothing to pull, nothing invented
        else:
            raw = fetch_rows(ctx, source, start, end)
        run.step("fetched", rows=len(raw), source=source, **({"warnings": warnings[:5]} if warnings else {}))
        if warnings and post_alerts:
            ctx.notifier.slack(":warning: Live sync skipped some accounts:\n" + "\n".join(f"• {w}" for w in warnings[:5]), kind="alert", run_id=run.run_id)

        with ctx.engine.connect() as conn:
            client_ids = {r.name.lower(): r.id for r in conn.execute(select(clients.c.id, clients.c.name))}
        prepared: dict[tuple[int, date, str], dict[str, Any]] = {}
        rejected: list[str] = []
        now = utcnow()
        for row in raw:
            clean, error = _clean(row, client_ids)
            if error:
                rejected.append(error)
                continue
            clean["created_at"] = now
            clean["updated_at"] = now
            prepared[(clean["client_id"], clean["date"], clean["channel"])] = clean  # last one wins
        if raw and not prepared:
            raise PipelineError(f"all {len(raw)} rows were rejected, e.g. {rejected[0]}")

        rows = list(prepared.values())
        inserted = updated = 0
        if rows:
            keys = list(prepared.keys())
            dates = [k[1] for k in keys]
            with ctx.engine.begin() as conn:
                existing = {
                    (r.client_id, r.date, r.channel)
                    for r in conn.execute(
                        select(campaign_metrics.c.client_id, campaign_metrics.c.date, campaign_metrics.c.channel).where(
                            and_(campaign_metrics.c.date >= min(dates), campaign_metrics.c.date <= max(dates))
                        )
                    )
                }
                inserted = sum(1 for k in keys if k not in existing)
                updated = len(keys) - inserted
                upsert(
                    conn,
                    campaign_metrics,
                    rows,
                    conflict_cols=("client_id", "date", "channel"),
                    update_cols=("impressions", "clicks", "spend", "conversions", "updated_at"),
                )
        run.step("upserted", inserted=inserted, updated=updated, rejected=len(rejected))

        with ctx.engine.connect() as conn:
            total_rows = conn.execute(select(func.count()).select_from(campaign_metrics)).scalar_one()
        alerts = analytics.cpa_alerts(ctx)
        if post_alerts and alerts:
            lines = [
                f"• *{a['client']}*, {a['channel']}: {a['reason']} "
                f"(from ${a['cpa_last_week'] or 0:,.2f} to ${a['cpa_this_week'] or 0:,.2f})"
                for a in alerts[:5]
            ]
            ctx.notifier.slack(
                f":chart_with_downwards_trend: Daily report: {len(alerts)} campaign(s) need attention\n" + "\n".join(lines),
                kind="alert",
                run_id=run.run_id,
            )
        run.step("alerts_checked", alerts=len(alerts))
        run.set(
            source=source,
            window={"start": start.isoformat(), "end": end.isoformat()},
            fetched=len(raw),
            inserted=inserted,
            updated=updated,
            rejected=len(rejected),
            rejected_examples=rejected[:5],
            warnings=warnings[:5],
            total_rows=total_rows,
            alerts=len(alerts),
        )
    return {
        "run_id": run.run_id,
        "status": "success",
        "source": source,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "fetched": len(raw),
        "inserted": inserted,
        "updated": updated,
        "rejected": len(rejected),
        "rejected_examples": rejected[:5],
        "warnings": warnings,
        "total_rows": total_rows,
        "alerts": len(alerts),
        "duration_ms": run.log_row["duration_ms"] if run.log_row else None,
    }


def export_csv_rows(ctx: Context, *, start: date | None = None, end: date | None = None) -> list[dict[str, Any]]:
    stmt = (
        select(
            campaign_metrics.c.date,
            clients.c.name.label("client"),
            campaign_metrics.c.channel,
            campaign_metrics.c.impressions,
            campaign_metrics.c.clicks,
            campaign_metrics.c.spend,
            campaign_metrics.c.conversions,
        )
        .select_from(campaign_metrics.join(clients, clients.c.id == campaign_metrics.c.client_id))
        .order_by(campaign_metrics.c.date, clients.c.name, campaign_metrics.c.channel)
    )
    if start:
        stmt = stmt.where(campaign_metrics.c.date >= start)
    if end:
        stmt = stmt.where(campaign_metrics.c.date <= end)
    with ctx.engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(stmt)]
