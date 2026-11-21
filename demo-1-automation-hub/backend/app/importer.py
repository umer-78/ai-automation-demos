"""Import a real ad-platform export (Google Ads, Meta Ads or any CSV with the usual columns).

Headers are matched loosely ("Day" or "Date", "Cost" or "Amount spent (USD)", "Results" or "Conversions"),
money keeps its cents, and every skipped line is reported with the reason, so nothing is silently dropped.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from .mockdata import CHANNELS

MAX_BYTES = 2_000_000
MAX_ROWS = 20_000

HEADERS = {
    "date": ["date", "day", "reporting starts", "date start", "reporting date"],
    "client": ["client", "client id", "client_id", "account", "account name", "customer", "client name"],
    "channel": ["channel", "platform", "network", "source", "publisher platform"],
    "spend": ["spend", "cost", "amount spent", "amount spent usd", "cost usd", "spend usd"],
    "clicks": ["clicks", "link clicks", "clicks all"],
    "conversions": ["conversions", "results", "conv", "purchases", "leads", "all conv"],
}
CHANNEL_ALIASES = {"google": "Google Ads", "google ads": "Google Ads", "adwords": "Google Ads", "search": "Google Ads",
                   "meta": "Meta Ads", "meta ads": "Meta Ads", "facebook": "Meta Ads", "instagram": "Meta Ads",
                   "seo": "SEO", "organic": "SEO", "organic search": "SEO"}
DATE_FORMATS = ("%Y-%m-%d", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%m/%d/%Y", "%Y/%m/%d")


class ImportError_(ValueError):
    pass


def _norm(h: str) -> str:
    h = h.replace("﻿", "").strip().lower()
    h = re.sub(r"[()\[\]$€£.]", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def _number(raw: str, field: str) -> float:
    s = (raw or "").strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    if s in ("", "--", "-"):
        return 0.0
    try:
        v = float(s)
    except ValueError:
        raise ImportError_(f"{field} isn't a number: {raw!r}") from None
    if v < 0:
        raise ImportError_(f"{field} is negative: {raw!r}")
    return v


def _day(raw: str) -> date:
    s = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ImportError_(f"date isn't recognised: {raw!r} (use YYYY-MM-DD)")


def parse(text: str, clients: list[dict], default_channel: str | None, today: date) -> tuple[list[dict], dict]:
    """Return (rows ready to upsert, a report of what was read, used and skipped)."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ImportError_("The file is over 2 MB. Export a shorter date range.")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ImportError_("The file is empty.") from None
    names = [_norm(h) for h in header]
    col = {}
    for key, options in HEADERS.items():
        for i, n in enumerate(names):
            if n in options:
                col[key] = i
                break
    missing = [k for k in ("date", "client", "spend", "clicks", "conversions") if k not in col]
    if "channel" not in col and not default_channel:
        missing.append("channel (or pick one for the whole file)")
    if missing:
        raise ImportError_(f"Missing columns: {', '.join(missing)}. Found: {', '.join(h for h in header if h.strip())}.")
    if default_channel and default_channel not in CHANNELS:
        raise ImportError_(f"Channel must be one of {', '.join(CHANNELS)}.")

    by_key = {}
    for c in clients:
        by_key[c["id"].lower()] = c["id"]
        by_key[_norm(c["name"])] = c["id"]

    merged: dict[tuple, dict] = {}
    skipped, unknown, read = [], set(), 0
    for line_no, rec in enumerate(reader, start=2):
        if not any(cell.strip() for cell in rec):
            continue
        read += 1
        if read > MAX_ROWS:
            raise ImportError_(f"More than {MAX_ROWS:,} rows. Export a shorter date range.")
        try:
            cell = lambda k: rec[col[k]] if col.get(k) is not None and col[k] < len(rec) else ""  # noqa: E731
            if _norm(cell("date")) in ("total", "totals", "grand total"):
                continue
            day = _day(cell("date"))
            if day > today:
                raise ImportError_(f"date {day.isoformat()} is in the future")
            client_raw = cell("client").strip()
            client_id = by_key.get(client_raw.lower()) or by_key.get(_norm(client_raw))
            if not client_id:
                unknown.add(client_raw or "(blank)")
                raise ImportError_(f"no client called {client_raw!r}")
            channel = CHANNEL_ALIASES.get(_norm(cell("channel"))) if "channel" in col else default_channel
            if "channel" in col and not channel:
                channel = default_channel or None
            if channel not in CHANNELS:
                raise ImportError_(f"channel {cell('channel')!r} isn't Google Ads, Meta Ads or SEO")
            spend, clicks, conv = _number(cell("spend"), "spend"), _number(cell("clicks"), "clicks"), _number(cell("conversions"), "conversions")
        except ImportError_ as exc:
            skipped.append({"line": line_no, "reason": str(exc)})
            continue
        key = (client_id, day, channel)
        row = merged.setdefault(key, {"client_id": client_id, "date": day, "channel": channel, "spend": 0.0, "clicks": 0, "conversions": 0})
        # Campaign-level exports have several lines per day: add them up.
        row["spend"] = round(row["spend"] + spend, 2)
        row["clicks"] += round(clicks)
        row["conversions"] += round(conv)

    rows = sorted(merged.values(), key=lambda r: (r["date"], r["client_id"], r["channel"]))
    days = [r["date"] for r in rows]
    report = {"rows_read": read, "rows_used": read - len(skipped), "days_written": len(rows), "skipped": skipped[:50],
              "skipped_count": len(skipped), "unknown_clients": sorted(unknown),
              "date_range": [min(days).isoformat(), max(days).isoformat()] if days else None,
              "clients": sorted({r["client_id"] for r in rows})}
    if not rows:
        raise ImportError_("No usable rows. " + (f"First problem: line {skipped[0]['line']}: {skipped[0]['reason']}." if skipped else ""))
    return rows, report
