"""Read-only endpoints used by the dashboard. Everything is computed from live database rows."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func, select

from app import __version__
from app.api.deps import get_ctx
from app.api.settings import access_problem
from app.services import data_mode
from app.context import Context
from app.db import automation_log, campaign_metrics, clients, notifications, rows_to_dicts, site_drafts, today_utc, utcnow
from app.services.automation_log import live_run
from app.workflows import analytics
from app.workflows.clients import NotFound, client_tasks_for, get_client, list_clients
from app.workflows.metrics_pipeline import export_csv_rows
from app.workflows.site_generator import get_draft, list_drafts
from app.workflows.synthetic import synth_rows
from app.workflows.weekly_summary import latest_summary

router = APIRouter()
DaysQ = Query(30, ge=7, le=90)


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/api/status")
def status(request: Request, ctx: Context = Depends(get_ctx), x_owner_token: str | None = Header(default=None)) -> dict[str, Any]:
    data = data_mode.status(ctx)
    if data["mode"] == "real" and access_problem(request.app.state.base_settings, ctx, x_owner_token):
        return {"app": ctx.settings.app_name, "version": __version__, "data": data, "locked": True, "integrations": ctx.integrations()}
    with ctx.engine.connect() as conn:
        counts = {
            "clients": conn.execute(select(func.count()).select_from(clients)).scalar_one(),
            "metric_rows": conn.execute(select(func.count()).select_from(campaign_metrics)).scalar_one(),
            "automation_runs": conn.execute(select(func.count()).select_from(automation_log)).scalar_one(),
            "site_drafts": conn.execute(select(func.count(func.distinct(site_drafts.c.group_id)))).scalar_one(),
        }
        last_pipeline = conn.execute(
            select(automation_log)
            .where(automation_log.c.workflow == "daily_metrics_pipeline")
            .order_by(automation_log.c.id.desc())
            .limit(1)
        ).first()
    return {
        "app": ctx.settings.app_name,
        "version": __version__,
        "environment": ctx.settings.environment,
        "integrations": ctx.integrations(),
        "data": data,
        "locked": False,
        "counts": counts,
        "latest_data_date": analytics.latest_date(ctx).isoformat() if counts["metric_rows"] else None,
        "last_pipeline_run": rows_to_dicts([last_pipeline])[0] if last_pipeline else None,
        "cpa_alert_threshold": ctx.settings.cpa_alert_threshold,
    }


# --------------------------------------------------------------------------- clients
@router.get("/api/clients")
def clients_list(ctx: Context = Depends(get_ctx)) -> list[dict[str, Any]]:
    return list_clients(ctx)


@router.get("/api/clients/{client_id}")
def client_detail(client_id: int, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    try:
        client = get_client(ctx, client_id)
    except NotFound:
        raise HTTPException(404, "client not found")
    with ctx.engine.connect() as conn:
        logs = rows_to_dicts(
            conn.execute(
                select(automation_log).where(automation_log.c.client_id == client_id).order_by(automation_log.c.id.desc()).limit(20)
            )
        )
    return {"client": client, "tasks": client_tasks_for(ctx, client_id), "runs": logs}


# --------------------------------------------------------------------------- metrics
@router.get("/api/metrics/overview")
def metrics_overview(days: int = DaysQ, client_id: int | None = None, ctx: Context = Depends(get_ctx)):
    return analytics.overview(ctx, days=days, client_id=client_id)


@router.get("/api/metrics/trend")
def metrics_trend(days: int = DaysQ, client_id: int | None = None, ctx: Context = Depends(get_ctx)):
    return analytics.trend(ctx, days=days, client_id=client_id)


@router.get("/api/metrics/channels")
def metrics_channels(days: int = DaysQ, client_id: int | None = None, ctx: Context = Depends(get_ctx)):
    return analytics.channels(ctx, days=days, client_id=client_id)


@router.get("/api/metrics/cube")
def metrics_cube(
    days: int = DaysQ,
    by: str = Query("client", pattern="^(client|campaign)$"),
    client_id: int | None = None,
    ctx: Context = Depends(get_ctx),
):
    return analytics.cube(ctx, days=days, by=by, client_id=client_id)


@router.get("/api/metrics/alerts")
def metrics_alerts(ctx: Context = Depends(get_ctx)):
    return {"threshold": ctx.settings.cpa_alert_threshold, "alerts": analytics.cpa_alerts(ctx)}


@router.get("/api/metrics/insights")
def metrics_insights(client_id: int | None = None, ctx: Context = Depends(get_ctx)):
    return {
        "anomalies": analytics.anomalies(ctx),
        "pacing": analytics.pacing(ctx),
        "forecast": analytics.forecast(ctx, client_id=client_id),
    }


@router.get("/api/metrics/export.csv")
def metrics_export(days: int = Query(60, ge=1, le=400), ctx: Context = Depends(get_ctx)):
    end = analytics.latest_date(ctx)
    rows = export_csv_rows(ctx, start=end - timedelta(days=days - 1), end=end)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["date", "client", "channel", "impressions", "clicks", "spend", "conversions"])
    writer.writeheader()
    for r in rows:
        writer.writerow({**r, "date": r["date"].isoformat() if isinstance(r["date"], date) else r["date"]})
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="campaign_metrics_{end.isoformat()}.csv"'},
    )


# --------------------------------------------------------------------------- automations
@router.get("/api/automation/logs")
def automation_logs(
    limit: int = Query(50, ge=1, le=500),
    workflow: str | None = None,
    status: str | None = Query(None, pattern="^(success|failure)$"),
    ctx: Context = Depends(get_ctx),
):
    stmt = select(automation_log).order_by(automation_log.c.id.desc()).limit(limit)
    if workflow:
        stmt = stmt.where(automation_log.c.workflow == workflow)
    if status:
        stmt = stmt.where(automation_log.c.status == status)
    with ctx.engine.connect() as conn:
        return rows_to_dicts(conn.execute(stmt))


@router.get("/api/automation/stats")
def automation_stats(days: int = Query(7, ge=1, le=90), ctx: Context = Depends(get_ctx)):
    since = utcnow() - timedelta(days=days)
    stmt = (
        select(
            automation_log.c.workflow,
            automation_log.c.status,
            func.count().label("runs"),
            func.avg(automation_log.c.duration_ms).label("avg_ms"),
            func.max(automation_log.c.created_at).label("last_run"),
        )
        .where(automation_log.c.created_at >= since)
        .group_by(automation_log.c.workflow, automation_log.c.status)
    )
    workflows: dict[str, dict[str, Any]] = {}
    with ctx.engine.connect() as conn:
        for r in conn.execute(stmt):
            w = workflows.setdefault(r.workflow, {"workflow": r.workflow, "success": 0, "failure": 0, "avg_ms": None, "last_run": None})
            w[r.status] = int(r.runs)
            if r.avg_ms is not None:
                w["avg_ms"] = int(r.avg_ms) if w["avg_ms"] is None else int((w["avg_ms"] + r.avg_ms) / 2)
            last = rows_to_dicts([r])[0]["last_run"]
            if last and (w["last_run"] is None or last > w["last_run"]):
                w["last_run"] = last
    total_s = sum(w["success"] for w in workflows.values())
    total_f = sum(w["failure"] for w in workflows.values())
    return {
        "days": days,
        "success": total_s,
        "failure": total_f,
        "success_rate": round(total_s / (total_s + total_f), 4) if (total_s + total_f) else None,
        "workflows": sorted(workflows.values(), key=lambda w: w["workflow"]),
    }


@router.get("/api/automation/runs/{run_id}")
def automation_run(run_id: str, ctx: Context = Depends(get_ctx)):
    live = live_run(run_id)
    with ctx.engine.connect() as conn:
        rows = rows_to_dicts(conn.execute(select(automation_log).where(automation_log.c.run_id == run_id).order_by(automation_log.c.id)))
    if not live and not rows:
        raise HTTPException(404, "run not found")
    status_value = rows[-1]["status"] if rows else (live or {}).get("status", "running")
    return {"run_id": run_id, "status": status_value, "live": live, "log": rows}


@router.get("/api/notifications")
def notifications_feed(
    channel: str | None = Query(None, pattern="^(slack|email)$"),
    limit: int = Query(30, ge=1, le=200),
    ctx: Context = Depends(get_ctx),
):
    stmt = select(notifications).order_by(notifications.c.id.desc()).limit(limit)
    if channel:
        stmt = stmt.where(notifications.c.channel == channel)
    with ctx.engine.connect() as conn:
        return rows_to_dicts(conn.execute(stmt))


@router.get("/api/summaries/latest")
def summaries_latest(ctx: Context = Depends(get_ctx)):
    return latest_summary(ctx) or {"run_id": None, "summaries": []}


# --------------------------------------------------------------------------- site drafts
@router.get("/api/sites")
def sites_list(ctx: Context = Depends(get_ctx)):
    return list_drafts(ctx)


@router.get("/api/sites/{group_id}")
def site_detail(group_id: str, ctx: Context = Depends(get_ctx)):
    draft = get_draft(ctx, group_id)
    if not draft:
        raise HTTPException(404, "draft not found")
    draft.pop("html", None)
    draft["preview_url"] = f"/sites/{group_id}/preview?v={draft['version']}"
    return draft


PREVIEW_CSP = (
    "default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src data: https:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors {ancestors}"
)


def _origin(url: str) -> str | None:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme in ("http", "https") and parsed.netloc else None


@router.get("/sites/{group_id}/preview", response_class=HTMLResponse)
def site_preview(request: Request, group_id: str, v: int | None = Query(None, ge=1), ctx: Context = Depends(get_ctx)):
    draft = get_draft(ctx, group_id, version=v)
    if not draft:
        raise HTTPException(404, "draft not found")
    # The dashboard shows previews in a sandboxed iframe. A sandboxed document has an opaque
    # origin, so 'self' alone would block it; list the app's real origins explicitly.
    origins = {"'self'"}
    for candidate in (str(request.base_url), ctx.settings.public_base_url, *ctx.settings.cors_origin_list):
        origin = _origin(candidate) if candidate != "*" else None
        if origin:
            origins.add(origin)
    return HTMLResponse(
        draft["html"],
        headers={"Content-Security-Policy": PREVIEW_CSP.format(ancestors=" ".join(sorted(origins))), "Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------- mock ad platform API
@router.get("/mock-api/ad-performance", tags=["mock ad platform"])
def mock_ad_platform(
    start: date | None = None,
    end: date | None = None,
    ctx: Context = Depends(get_ctx),
):
    """Synthetic ad-platform API (fake data). Same numbers on every call for the same day."""
    end = end or today_utc() - timedelta(days=1)
    start = start or end - timedelta(days=6)
    if (end - start).days > 92 or end < start:
        raise HTTPException(400, "date range must be 1-93 days")
    with ctx.engine.connect() as conn:
        active = [
            dict(r._mapping)
            for r in conn.execute(
                select(clients.c.name, clients.c.industry, clients.c.services, clients.c.monthly_budget).where(clients.c.status == "active")
            )
        ]
    rows = synth_rows(active, start, end, anchor=today_utc())
    for r in rows:
        r["date"] = r["date"].isoformat()
    return {"source": "mock-ad-platform", "start": start.isoformat(), "end": end.isoformat(), "rows": rows}
