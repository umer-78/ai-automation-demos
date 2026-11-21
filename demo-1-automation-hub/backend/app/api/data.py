"""Where the numbers come from: demo data, your CSV exports, or live ad accounts.

Every figure on the site, and every pillar in the 3D world, is calculated from campaign_metrics
when a page opens. This module decides what goes into that table:

  demo mode   sample clients whose numbers follow published 2026 industry medians
  real mode   only what you load: CSV exports (Google Ads, Meta Ads, any reporting tool) and the
              Google Ads, Meta Ads, Search Console and Analytics accounts you connect
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
import time
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.deps import get_ctx, rate_limit
from app.api.settings import require_owner
from app.context import Context, apply_settings
from app.db import client_accounts, clients, today_utc, upsert, utcnow
from app.services import connectors, data_mode, secrets
from app.workflows.metrics_pipeline import PipelineError, run_daily_metrics
from app.workflows.synthetic import BENCHMARK_SOURCES, BENCHMARKS, CHANNELS, ORGANIC_CTR, benchmark_category

router = APIRouter()
MAX_BYTES = 5_000_000
PLATFORMS = ("google_ads", "meta_ads", "search_console", "ga4", "seo_fee")

HEADER_ALIASES = {
    "date": ("date", "day", "reporting starts", "reporting date", "date start"),
    "client": ("client", "client name", "account", "account name", "customer", "customer name"),
    "channel": ("channel", "platform", "network", "source"),
    "impressions": ("impressions", "impr.", "impr"),
    "clicks": ("clicks", "link clicks", "clicks (all)"),
    "spend": ("spend", "cost", "amount spent", "amount spent (usd)", "cost (usd)"),
    "conversions": ("conversions", "conv.", "results", "purchases", "leads"),
}
CHANNEL_ALIASES = {
    "google": "Google Ads", "google ads": "Google Ads", "adwords": "Google Ads", "search": "Google Ads",
    "meta": "Meta Ads", "meta ads": "Meta Ads", "facebook": "Meta Ads", "facebook ads": "Meta Ads", "instagram": "Meta Ads",
    "seo": "SEO", "organic": "SEO", "organic search": "SEO",
}
TEMPLATE = (
    "date,client,channel,impressions,clicks,spend,conversions\n"
    "2026-11-01,Your Client Ltd,Google Ads,12450,512,640.20,31\n"
    "2026-11-01,Your Client Ltd,Meta Ads,40210,388,410.75,22\n"
    "2026-11-01,Your Client Ltd,SEO,9800,301,120.00,14\n"
)


# --------------------------------------------------------------------------------------
# CSV import
# --------------------------------------------------------------------------------------
class ImportIn(BaseModel):
    csv: str = Field(min_length=10)


def _number(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if text in ("", "-", "--"):
        return "0"
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    float(cleaned)  # raises ValueError for text such as "n/a"
    return cleaned


SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")
TEXT_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y", "%d-%m-%Y")


def _slash_order(values: list[str]) -> str:
    """'dmy' or 'mdy' for a column of 01/02/2026 style dates, decided by the whole column."""
    first = second = 0
    for v in values:
        m = SLASH.match(v.strip())
        if m:
            first = max(first, int(m.group(1)))
            second = max(second, int(m.group(2)))
    if first > 12 and second <= 12:
        return "dmy"
    if second > 12 and first <= 12:
        return "mdy"
    if first > 12 and second > 12:
        raise ValueError("the date column mixes day-first and month-first dates")
    return "mdy"  # ambiguous everywhere: Google Ads and Meta default to US order


def _date(value: str, order: str) -> str:
    value = value.strip()
    m = SLASH.match(value)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        day, month = (a, b) if order == "dmy" else (b, a)
        return date(y, month, day).isoformat()
    head = value.split("T")[0].split(" ")[0] if re.match(r"^\d{4}-\d{2}-\d{2}", value) else value
    for fmt in TEXT_FORMATS:
        try:
            return datetime.strptime(head, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"'{value}' is not a date")


def parse_csv(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows in the pipeline's shape, and the reasons any rows were left out."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise HTTPException(422, "The file has no header row.")
    lookup = {h.strip().lower(): h for h in reader.fieldnames if h}
    columns: dict[str, str] = {}
    for key, names in HEADER_ALIASES.items():
        found = next((lookup[n] for n in names if n in lookup), None)
        if found:
            columns[key] = found
    missing = [k for k in ("date", "client", "channel", "clicks", "spend", "conversions") if k not in columns]
    if missing:
        raise HTTPException(422, f"Missing column(s): {', '.join(missing)}. Download the template to see the layout.")
    raw_rows = list(reader)
    try:
        order = _slash_order([str(r.get(columns["date"]) or "") for r in raw_rows])
    except ValueError as exc:
        raise HTTPException(422, f"Check the date column: {exc}.") from exc
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for i, raw in enumerate(raw_rows, start=2):
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue  # blank line
        try:
            client = str(raw.get(columns["client"]) or "").strip()
            if not client:
                raise ValueError("no client name")
            channel_raw = str(raw.get(columns["channel"]) or "").strip()
            channel = CHANNEL_ALIASES.get(channel_raw.lower(), channel_raw)
            if channel not in CHANNELS:
                raise ValueError(f"channel '{channel_raw}' is not Google Ads, Meta Ads or SEO")
            rows.append(
                {
                    "date": _date(str(raw.get(columns["date"]) or ""), order),
                    "client": client[:200],
                    "channel": channel,
                    "impressions": _number(raw.get(columns["impressions"])) if "impressions" in columns else "0",
                    "clicks": _number(raw.get(columns["clicks"])),
                    "spend": _number(raw.get(columns["spend"])),
                    "conversions": _number(raw.get(columns["conversions"])),
                }
            )
        except ValueError as exc:
            problems.append(f"line {i}: {exc}")
    return rows, problems


def _ensure_clients(ctx: Context, names_channels: dict[str, set[str]]) -> list[str]:
    with ctx.engine.begin() as conn:
        known = {r.name.lower(): r for r in conn.execute(select(clients.c.id, clients.c.name, clients.c.status))}
        created = []
        for name, channels in sorted(names_channels.items()):
            row = known.get(name.lower())
            if row is None:
                services = (["Paid Ads"] if channels & {"Google Ads", "Meta Ads"} else []) + (["SEO"] if "SEO" in channels else [])
                conn.execute(clients.insert().values(name=name, status="active", services=services, created_at=utcnow(), updated_at=utcnow()))
                created.append(name)
            elif row.status == "archived":
                conn.execute(clients.update().where(clients.c.id == row.id).values(status="active", updated_at=utcnow()))
    return created


@router.get("/api/data/template.csv", include_in_schema=False)
def template() -> Response:
    return Response(TEMPLATE, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="northwind-import-template.csv"'})


@router.post("/api/data/import", dependencies=[Depends(require_owner), Depends(rate_limit)])
def import_csv(body: ImportIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    if len(body.csv.encode()) > MAX_BYTES:
        raise HTTPException(413, "That file is over 5 MB. Split it by month and import each part.")
    rows, problems = parse_csv(body.csv)
    if not rows:
        raise HTTPException(422, problems[0] if problems else "No usable rows in the file.")
    if max(r["date"] for r in rows) > today_utc().isoformat():
        raise HTTPException(422, "Some rows are dated in the future. Check the date column.")

    switched = data_mode.get_mode(ctx) == "demo"
    if switched:
        data_mode.start_real_data(ctx)  # real numbers never sit next to sample ones
    wanted: dict[str, set[str]] = {}
    for r in rows:
        wanted.setdefault(r["client"], set()).add(r["channel"])
    new_clients = _ensure_clients(ctx, wanted)

    dates = sorted(r["date"] for r in rows)
    first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    try:
        result = run_daily_metrics(ctx, rows=rows, days=(last - first).days + 1, end=last, run_source="import", post_alerts=False)
    except PipelineError as exc:
        raise HTTPException(422, str(exc)) from exc
    skipped = problems + result.get("rejected_examples", [])
    return {
        "rows": len(rows),
        "inserted": result["inserted"],
        "updated": result["updated"],
        "new_clients": new_clients,
        "skipped": skipped[:20],
        "skipped_count": len(problems) + int(result.get("rejected", 0)),
        "period": {"start": dates[0], "end": dates[-1]},
        "demo_removed": switched,
    }


# --------------------------------------------------------------------------------------
# Mode and status
# --------------------------------------------------------------------------------------
@router.get("/api/data/status")
def status(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return data_mode.status(ctx)


@router.get("/api/data/benchmarks")
def benchmarks(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """The published medians the demo follows. Client names only while the demo is on."""
    out: dict[str, Any] = {"sources": BENCHMARK_SOURCES, "organic_ctr": ORGANIC_CTR, "clients": []}
    if data_mode.get_mode(ctx) != "demo":
        return out
    with ctx.engine.connect() as conn:
        rows = conn.execute(select(clients.c.name, clients.c.industry).where(clients.c.status != "archived").order_by(clients.c.name)).fetchall()
    for r in rows:
        cat = benchmark_category(r.industry)
        b = BENCHMARKS[cat]
        out["clients"].append(
            {
                "client": r.name,
                "industry": r.industry,
                "category": cat,
                "google": {"ctr": b["google"][0], "cpc": b["google"][1], "cpl": b["google"][2]},
                "meta": {"ctr": b["meta"][0], "cvr": b["meta"][1], "cpl": b["meta"][2]},
                "organic_cvr": b["organic_cvr"],
            }
        )
    return out


@router.post("/api/data/real", dependencies=[Depends(require_owner)])
def use_real_data(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Delete the demo clients and their numbers. Saved keys stay."""
    data_mode.start_real_data(ctx)
    return data_mode.status(ctx)


@router.post("/api/data/demo", dependencies=[Depends(require_owner)])
def use_demo_data(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Wipe everything and load the demo again (handy before showing the hub to a prospect)."""
    data_mode.back_to_demo(ctx)
    return data_mode.status(ctx)


@router.post("/api/data/sync", dependencies=[Depends(require_owner), Depends(rate_limit)])
def sync_now(days: int = Query(0, ge=0, le=400), ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    if data_mode.get_mode(ctx) != "real":
        raise HTTPException(409, "Switch to real data first; the demo has no live accounts.")
    if not data_mode.live_available(ctx):
        raise HTTPException(409, "Connect an ad account and link it to a client first.")
    try:
        return run_daily_metrics(ctx, source="live", days=days or data_mode.sync_days(ctx), run_source="dashboard")
    except PipelineError as exc:
        raise HTTPException(502, str(exc)) from exc


# --------------------------------------------------------------------------------------
# Which account feeds which client
# --------------------------------------------------------------------------------------
class AccountsIn(BaseModel):
    client_id: int | None = None
    name: str | None = Field(default=None, max_length=200)
    accounts: dict[str, str] = Field(default_factory=dict)


def _accounts_payload(ctx: Context) -> dict[str, Any]:
    with ctx.engine.connect() as conn:
        rows = conn.execute(select(clients.c.id, clients.c.name, clients.c.status).where(clients.c.status != "archived").order_by(clients.c.name)).fetchall()
        links = conn.execute(select(client_accounts.c.client_id, client_accounts.c.platform, client_accounts.c.ref)).fetchall()
    by_client: dict[int, dict[str, str]] = {}
    for link in links:
        by_client.setdefault(link.client_id, {})[link.platform] = link.ref
    s = ctx.settings
    return {
        "clients": [{"id": r.id, "name": r.name, "status": r.status, "accounts": by_client.get(r.id, {})} for r in rows],
        "ready": {p: data_mode.platform_ready(ctx, p) for p in ("google_ads", "meta_ads", "search_console", "ga4")},
        "google_signed_in": s.google_live,
        "google_oauth_ready": bool(s.google_oauth_client_id and s.google_oauth_client_secret),
    }


def _clean_ref(platform: str, value: str) -> str:
    v = value.strip()
    if not v:
        return ""
    if platform == "google_ads":
        d = connectors.digits(v)
        if len(d) != 10:
            raise HTTPException(422, f"Google Ads customer IDs have 10 digits (got '{value}').")
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    if platform == "meta_ads":
        d = connectors.digits(v)
        if not d:
            raise HTTPException(422, f"'{value}' is not a Meta ad account ID.")
        return f"act_{d}"
    if platform == "search_console":
        if not (v.startswith("sc-domain:") or re.match(r"^https?://", v)):
            raise HTTPException(422, "Search Console properties look like https://example.com/ or sc-domain:example.com.")
        return v
    if platform == "ga4":
        d = connectors.digits(v)
        if not d:
            raise HTTPException(422, f"'{value}' is not a Google Analytics property ID.")
        return d
    if platform == "seo_fee":
        try:
            fee = float(_number(v))
        except ValueError as exc:
            raise HTTPException(422, "The SEO fee must be a number (monthly amount).") from exc
        return f"{fee:.2f}"
    raise HTTPException(422, f"Unknown platform '{platform}'.")


@router.get("/api/data/accounts", dependencies=[Depends(require_owner)])
def get_accounts(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    return _accounts_payload(ctx)


@router.put("/api/data/accounts", dependencies=[Depends(require_owner), Depends(rate_limit)])
def put_accounts(body: AccountsIn, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    if data_mode.get_mode(ctx) != "real":
        raise HTTPException(409, "Switch to real data first, so live numbers never mix with the demo.")
    unknown = set(body.accounts) - set(PLATFORMS)
    if unknown:
        raise HTTPException(422, f"Unknown platform(s): {', '.join(sorted(unknown))}.")
    refs = {p: _clean_ref(p, v) for p, v in body.accounts.items()}
    with ctx.engine.begin() as conn:
        client_id = body.client_id
        if client_id is None:
            name = (body.name or "").strip()
            if not name:
                raise HTTPException(422, "Give the new client a name.")
            existing = conn.execute(select(clients.c.id).where(clients.c.name == name)).scalar()
            if existing:
                client_id = existing
            else:
                services = (["Paid Ads"] if refs.get("google_ads") or refs.get("meta_ads") else []) + (["SEO"] if refs.get("search_console") else [])
                client_id = conn.execute(
                    clients.insert().values(name=name, status="active", services=services or ["Paid Ads"], created_at=utcnow(), updated_at=utcnow())
                ).inserted_primary_key[0]
        elif not conn.execute(select(clients.c.id).where(clients.c.id == client_id)).scalar():
            raise HTTPException(404, "Client not found.")
        for platform, ref in refs.items():
            conn.execute(delete(client_accounts).where(client_accounts.c.client_id == client_id, client_accounts.c.platform == platform))
            if ref:
                conn.execute(client_accounts.insert().values(client_id=client_id, platform=platform, ref=ref, updated_at=utcnow()))
    return _accounts_payload(ctx)


@router.get("/api/data/discover", dependencies=[Depends(require_owner), Depends(rate_limit)])
def discover(ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    """Accounts the saved credentials can read, so Settings can offer them in a list."""
    s = ctx.settings
    out: dict[str, Any] = {}
    jobs = {
        "google_ads": (s.google_ads_live, connectors.google_ads_accounts),
        "meta_ads": (s.meta_live, connectors.meta_accounts),
        "search_console": (s.google_live, connectors.search_console_sites),
        "ga4": (s.google_live, connectors.ga4_properties),
    }
    for platform, (ready, fn) in jobs.items():
        if not ready:
            out[platform] = {"items": [], "error": None, "ready": False}
            continue
        try:
            out[platform] = {"items": fn(s), "error": None, "ready": True}
        except (connectors.ConnectorError, OSError) as exc:
            out[platform] = {"items": [], "error": str(exc), "ready": True}
    return out


# --------------------------------------------------------------------------------------
# Sign in with Google (fills the refresh token)
# --------------------------------------------------------------------------------------
STATE_TTL = 900


def _redirect_uri(request: Request, ctx: Context) -> str:
    base = ctx.settings.public_base_url.rstrip("/") if ctx.settings.is_production else str(request.base_url).rstrip("/")
    return f"{base}/api/data/google/callback"


def _sign(ctx: Context, payload: str) -> str:
    key = hashlib.sha256(f"google-oauth|{ctx.settings.app_secret or ctx.settings.owner_token or 'dev'}".encode()).digest()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]


@router.post("/api/data/google/start", dependencies=[Depends(require_owner)])
def google_start(request: Request, ctx: Context = Depends(get_ctx)) -> dict[str, Any]:
    s = ctx.settings
    if not (s.google_oauth_client_id and s.google_oauth_client_secret):
        raise HTTPException(409, "Save the OAuth client ID and secret first.")
    ts = str(int(time.time()))
    redirect = _redirect_uri(request, ctx)
    return {"url": connectors.google_auth_url(s, redirect, f"{ts}.{_sign(ctx, ts)}"), "redirect_uri": redirect}


@router.get("/api/data/google/redirect-uri")
def google_redirect_uri(request: Request, ctx: Context = Depends(get_ctx)) -> dict[str, str]:
    return {"redirect_uri": _redirect_uri(request, ctx)}


@router.get("/api/data/google/callback", include_in_schema=False)
def google_callback(request: Request, code: str = "", state: str = "", error: str = "", ctx: Context = Depends(get_ctx)) -> RedirectResponse:
    def back(result: str) -> RedirectResponse:
        return RedirectResponse(f"/settings?google={result}", status_code=303)

    if error:
        return back("cancelled")
    ts, _, sig = state.partition(".")
    if not (ts.isdigit() and hmac.compare_digest(sig, _sign(ctx, ts)) and time.time() - int(ts) < STATE_TTL):
        return back("expired")
    try:
        token = connectors.google_exchange_code(ctx.settings, code, _redirect_uri(request, ctx))
    except (connectors.ConnectorError, OSError):
        return back("failed")
    base = request.app.state.base_settings
    secrets.save(ctx.engine, base, {"google_oauth_refresh_token": token})
    apply_settings(ctx, secrets.effective(base, secrets.load_saved(ctx.engine, base)))
    return back("connected")
