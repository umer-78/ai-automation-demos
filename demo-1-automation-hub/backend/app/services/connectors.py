"""Live numbers from Google Ads, Meta Ads, Search Console and Google Analytics 4.

Every fetcher returns rows in the pipeline's shape (date, impressions, clicks, spend, conversions)
straight from the platform's reporting API. Nothing is estimated: a day the platform does not
report is a day with no row.

  Google Ads       REST GoogleAdsService.searchStream, one row per day per account
  Meta Ads         Marketing API insights, level=account, time_increment=1
  Search Console   searchAnalytics.query, dimension=date (organic clicks and impressions)
  Google Analytics Data API runReport, key events from the Organic Search channel (SEO conversions)

Google uses one OAuth sign-in (refresh token saved encrypted from the Settings page); Meta uses a
Business Manager system user token with ads_read.
"""

from __future__ import annotations

import calendar
import json
import re
import threading
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.config import Settings

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/adwords",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
)
GOOGLE_ADS_BASE = "https://googleads.googleapis.com"
META_BASE = "https://graph.facebook.com"
SEARCH_CONSOLE_BASE = "https://www.googleapis.com/webmasters/v3"
GA4_DATA_BASE = "https://analyticsdata.googleapis.com/v1beta"
GA4_ADMIN_BASE = "https://analyticsadmin.googleapis.com/v1beta"

TRANSPORT: httpx.BaseTransport | None = None  # tests swap in httpx.MockTransport
_tokens: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


class ConnectorError(RuntimeError):
    """A platform refused or failed a request; the message says which account and why."""


def _http() -> httpx.Client:
    return httpx.Client(timeout=30, transport=TRANSPORT)


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}"
    if isinstance(body, list) and body:
        body = body[0]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        msg = err.get("message") or err.get("status") or ""
        details = err.get("details") or []
        for d in details if isinstance(details, list) else []:
            for e in (d.get("errors") or []) if isinstance(d, dict) else []:
                if e.get("message"):
                    msg = e["message"]
                    break
        return f"{msg} (HTTP {resp.status_code})" if msg else f"HTTP {resp.status_code}"
    if isinstance(err, str):
        return f"{body.get('error_description') or err} (HTTP {resp.status_code})"
    return f"HTTP {resp.status_code}"


# --------------------------------------------------------------------------------------
# Google sign-in
# --------------------------------------------------------------------------------------
def google_auth_url(s: Settings, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": s.google_oauth_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def google_exchange_code(s: Settings, code: str, redirect_uri: str) -> str:
    with _http() as http:
        r = http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": s.google_oauth_client_id,
                "client_secret": s.google_oauth_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        raise ConnectorError(f"Google sign-in failed: {_error(r)}")
    token = r.json().get("refresh_token")
    if not token:
        raise ConnectorError("Google did not return a refresh token. Remove the app's access in your Google account and sign in again.")
    return token


def google_access_token(s: Settings) -> str:
    key = s.google_oauth_refresh_token
    with _lock:
        hit = _tokens.get(key)
        if hit and hit[1] > time.time() + 60:
            return hit[0]
    with _http() as http:
        r = http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": s.google_oauth_client_id,
                "client_secret": s.google_oauth_client_secret,
                "refresh_token": s.google_oauth_refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if r.status_code != 200:
        raise ConnectorError(f"Google sign-in expired or was revoked: {_error(r)}. Sign in with Google again in Settings.")
    body = r.json()
    with _lock:
        _tokens[key] = (body["access_token"], time.time() + float(body.get("expires_in", 3600)))
    return body["access_token"]


def _google_headers(s: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {google_access_token(s)}"}


# --------------------------------------------------------------------------------------
# Google Ads
# --------------------------------------------------------------------------------------
def _ads_headers(s: Settings) -> dict[str, str]:
    h = {**_google_headers(s), "developer-token": s.google_ads_developer_token}
    if digits(s.google_ads_login_customer_id):
        h["login-customer-id"] = digits(s.google_ads_login_customer_id)
    return h


def _ads_query(s: Settings, customer_id: str, query: str) -> list[dict[str, Any]]:
    url = f"{GOOGLE_ADS_BASE}/{s.google_ads_api_version}/customers/{digits(customer_id)}/googleAds:searchStream"
    with _http() as http:
        r = http.post(url, headers=_ads_headers(s), json={"query": query})
    if r.status_code != 200:
        raise ConnectorError(f"Google Ads account {customer_id}: {_error(r)}")
    return [res for batch in r.json() for res in batch.get("results", [])]


def google_ads_rows(s: Settings, customer_id: str, start: date, end: date) -> list[dict[str, Any]]:
    results = _ads_query(
        s,
        customer_id,
        "SELECT segments.date, customer.currency_code, metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions "
        f"FROM customer WHERE segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'",
    )
    rows = []
    for res in results:
        m, seg = res.get("metrics", {}), res.get("segments", {})
        rows.append(
            {
                "date": seg["date"],
                "impressions": int(m.get("impressions", 0)),
                "clicks": int(m.get("clicks", 0)),
                "spend": round(int(m.get("costMicros", 0)) / 1_000_000, 2),
                "conversions": round(float(m.get("conversions", 0)), 2),
                "currency": res.get("customer", {}).get("currencyCode"),
            }
        )
    return rows


def google_ads_accounts(s: Settings) -> list[dict[str, Any]]:
    """Accounts this sign-in can read. Under a manager account: its client accounts."""
    if digits(s.google_ads_login_customer_id):
        results = _ads_query(
            s,
            s.google_ads_login_customer_id,
            "SELECT customer_client.id, customer_client.descriptive_name, customer_client.currency_code, customer_client.manager "
            "FROM customer_client WHERE customer_client.level <= 1 AND customer_client.status = 'ENABLED'",
        )
        return [
            {"id": str(c["id"]), "name": c.get("descriptiveName") or str(c["id"]), "currency": c.get("currencyCode")}
            for c in (r.get("customerClient", {}) for r in results)
            if not c.get("manager")
        ]
    with _http() as http:
        r = http.get(f"{GOOGLE_ADS_BASE}/{s.google_ads_api_version}/customers:listAccessibleCustomers", headers=_ads_headers(s))
    if r.status_code != 200:
        raise ConnectorError(f"Google Ads: {_error(r)}")
    out = []
    for name in r.json().get("resourceNames", [])[:50]:
        cid = name.split("/")[-1]
        try:
            res = _ads_query(s, cid, "SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.manager FROM customer LIMIT 1")
        except ConnectorError:
            continue
        c = res[0].get("customer", {}) if res else {}
        if not c.get("manager"):
            out.append({"id": cid, "name": c.get("descriptiveName") or cid, "currency": c.get("currencyCode")})
    return out


# --------------------------------------------------------------------------------------
# Meta Ads
# --------------------------------------------------------------------------------------
def _meta_get(s: Settings, path_or_url: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    url = path_or_url if path_or_url.startswith("http") else f"{META_BASE}/{s.meta_api_version}/{path_or_url}"
    out: list[dict[str, Any]] = []
    with _http() as http:
        while url:
            r = http.get(url, params=params, headers={"Authorization": f"Bearer {s.meta_access_token}"})
            if r.status_code != 200:
                raise ConnectorError(_error(r))
            body = r.json()
            out += body.get("data", [])
            url, params = body.get("paging", {}).get("next"), None  # the next link carries its own query
    return out


def meta_account_path(account_id: str) -> str:
    return account_id.strip() if account_id.strip().startswith("act_") else f"act_{digits(account_id)}"


def meta_rows(s: Settings, account_id: str, start: date, end: date) -> list[dict[str, Any]]:
    wanted = {a.strip() for a in s.meta_conversion_actions.split(",") if a.strip()}
    try:
        data = _meta_get(
            s,
            f"{meta_account_path(account_id)}/insights",
            {
                "level": "account",
                "time_increment": 1,
                "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
                "fields": "date_start,impressions,clicks,inline_link_clicks,spend,actions,account_currency",
                "limit": 500,
            },
        )
    except ConnectorError as exc:
        raise ConnectorError(f"Meta ad account {account_id}: {exc}") from exc
    return [
        {
            "date": d["date_start"],
            "impressions": int(d.get("impressions") or 0),
            "clicks": int(d.get("inline_link_clicks") or d.get("clicks") or 0),
            "spend": round(float(d.get("spend") or 0), 2),
            "conversions": round(sum(float(a.get("value") or 0) for a in d.get("actions") or [] if a.get("action_type") in wanted), 2),
            "currency": d.get("account_currency"),
        }
        for d in data
    ]


def meta_accounts(s: Settings) -> list[dict[str, Any]]:
    data = _meta_get(s, "me/adaccounts", {"fields": "name,account_id,currency,account_status", "limit": 200})
    return [{"id": d["account_id"], "name": d.get("name") or d["account_id"], "currency": d.get("currency")} for d in data if d.get("account_status", 1) == 1]


# --------------------------------------------------------------------------------------
# Search Console and Google Analytics 4 (the SEO channel)
# --------------------------------------------------------------------------------------
def search_console_rows(s: Settings, site_url: str, start: date, end: date) -> list[dict[str, Any]]:
    with _http() as http:
        r = http.post(
            f"{SEARCH_CONSOLE_BASE}/sites/{quote(site_url, safe='')}/searchAnalytics/query",
            headers=_google_headers(s),
            json={"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": ["date"], "rowLimit": 25000},
        )
    if r.status_code != 200:
        raise ConnectorError(f"Search Console property {site_url}: {_error(r)}")
    return [{"date": row["keys"][0], "impressions": int(row.get("impressions", 0)), "clicks": int(row.get("clicks", 0))} for row in r.json().get("rows", [])]


def search_console_sites(s: Settings) -> list[dict[str, Any]]:
    with _http() as http:
        r = http.get(f"{SEARCH_CONSOLE_BASE}/sites", headers=_google_headers(s))
    if r.status_code != 200:
        raise ConnectorError(f"Search Console: {_error(r)}")
    return [{"id": e["siteUrl"], "name": e["siteUrl"]} for e in r.json().get("siteEntry", []) if e.get("permissionLevel") != "siteUnverifiedUser"]


def ga4_organic_conversions(s: Settings, property_id: str, start: date, end: date) -> dict[str, float]:
    with _http() as http:
        r = http.post(
            f"{GA4_DATA_BASE}/properties/{digits(property_id)}:runReport",
            headers=_google_headers(s),
            json={
                "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
                "dimensions": [{"name": "date"}],
                "metrics": [{"name": "keyEvents"}],
                "dimensionFilter": {"filter": {"fieldName": "sessionDefaultChannelGroup", "stringFilter": {"matchType": "EXACT", "value": "Organic Search"}}},
                "limit": 1000,
            },
        )
    if r.status_code != 200:
        raise ConnectorError(f"Google Analytics property {property_id}: {_error(r)}")
    out = {}
    for row in r.json().get("rows", []):
        raw = row["dimensionValues"][0]["value"]  # YYYYMMDD
        out[f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"] = round(float(row["metricValues"][0]["value"]), 2)
    return out


def ga4_properties(s: Settings) -> list[dict[str, Any]]:
    with _http() as http:
        r = http.get(f"{GA4_ADMIN_BASE}/accountSummaries", headers=_google_headers(s), params={"pageSize": 200})
    if r.status_code != 200:
        raise ConnectorError(f"Google Analytics: {_error(r)}")
    return [
        {"id": p["property"].split("/")[-1], "name": f"{p.get('displayName', '')} ({a.get('displayName', '')})".strip()}
        for a in r.json().get("accountSummaries", [])
        for p in a.get("propertySummaries", [])
    ]


def seo_fee_per_day(monthly_fee: float, day: date) -> float:
    return round(monthly_fee / calendar.monthrange(day.year, day.month)[1], 2)


# --------------------------------------------------------------------------------------
# One sync across every mapped client
# --------------------------------------------------------------------------------------
def collect(s: Settings, accounts: dict[int, dict[str, Any]], start: date, end: date) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows for every client/platform mapping, plus a note for each account that failed."""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    currency = s.report_currency.upper()

    def add(name: str, channel: str, fetched: list[dict[str, Any]]) -> None:
        other = sorted({r["currency"] for r in fetched if r.get("currency") and r["currency"].upper() != currency})
        if other:
            problems.append(f"{name} {channel} reports in {', '.join(other)}, not {currency}; its rows were left out so totals stay in one currency.")
            return
        rows.extend({**{k: v for k, v in r.items() if k != "currency"}, "client": name, "channel": channel} for r in fetched)

    for acc in accounts.values():
        name = acc["name"]
        try:
            if acc.get("google_ads") and s.google_ads_live:
                add(name, "Google Ads", google_ads_rows(s, acc["google_ads"], start, end))
        except ConnectorError as exc:
            problems.append(str(exc))
        try:
            if acc.get("meta_ads") and s.meta_live:
                add(name, "Meta Ads", meta_rows(s, acc["meta_ads"], start, end))
        except ConnectorError as exc:
            problems.append(str(exc))
        try:
            if acc.get("search_console") and s.google_live:
                organic = search_console_rows(s, acc["search_console"], start, end)
                conv = ga4_organic_conversions(s, acc["ga4"], start, end) if acc.get("ga4") else {}
                fee = float(acc.get("seo_fee") or 0)
                add(
                    name,
                    "SEO",
                    [
                        {**r, "spend": seo_fee_per_day(fee, datetime.strptime(r["date"], "%Y-%m-%d").date()) if fee else 0.0, "conversions": conv.get(r["date"], 0.0)}
                        for r in organic
                    ],
                )
        except ConnectorError as exc:
            problems.append(str(exc))
    return rows, problems


def test_google(s: Settings) -> str:
    google_access_token(s)
    return "Signed in to Google."


def test_google_ads(s: Settings) -> str:
    n = len(google_ads_accounts(s))
    return f"Google Ads answered: {n} account{'s' if n != 1 else ''} available."


def test_meta(s: Settings) -> str:
    n = len(meta_accounts(s))
    return f"Meta answered: {n} ad account{'s' if n != 1 else ''} available."
