"""Module B: the "Weekly summary" button. Three plain-English sentences per client,
written from the live numbers (AI when configured, a deterministic template otherwise)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import select

from app.context import Context
from app.db import rows_to_dicts, utcnow, weekly_summaries
from app.services.automation_log import AutomationRun
from app.workflows.analytics import client_week_stats

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "client_id": {"type": "integer"},
                    "sentences": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
                },
                "required": ["client_id", "sentences"],
            },
        }
    },
    "required": ["summaries"],
}

SUMMARY_SYSTEM = (
    "You write weekly performance notes for a marketing agency's account managers. For each client "
    "write exactly 3 sentences in plain English: (1) the headline result with spend, conversions and "
    "cost per conversion versus last week; (2) the main driver, naming the channel; (3) one concrete "
    "action for this week. Use only the numbers provided, round sensibly, no jargon, no hype."
)


def _money(v: float | None) -> str:
    return f"${v:,.0f}" if v is not None and v >= 100 else f"${v:,.2f}" if v is not None else "n/a"


def _pct(v: float | None) -> str:
    return f"{abs(v):.0%}" if v is not None else "n/a"


def offline_sentences(c: dict[str, Any]) -> list[str]:
    cpa_dir = "up" if (c["cpa_change"] or 0) > 0 else "down"
    s1 = (
        f"{c['client']} spent {_money(c['spend'])} last week for {c['conversions']} conversions, "
        f"a cost per conversion of {_money(c['cpa'])} ({cpa_dir} {_pct(c['cpa_change'])} on the week before)."
    )
    chans = [ch for ch in c["channels"] if ch["cpa"] is not None]
    if chans:
        best = min(chans, key=lambda ch: ch["cpa"])
        moved = max(chans, key=lambda ch: abs(ch["cpa_change"] or 0))
        direction = "rose" if (moved["cpa_change"] or 0) > 0 else "fell"
        s2 = (
            f"{best['channel']} was the most efficient channel at {_money(best['cpa'])} per conversion, "
            f"while {moved['channel']} cost per conversion {direction} {_pct(moved['cpa_change'])} to {_money(moved['cpa'])}."
        )
    else:
        s2 = "There was not enough conversion data this week to compare channels."
    if c["alerts"]:
        a = c["alerts"][0]
        s3 = (
            f"Action: review {a['channel']} audiences, creative and bids this week, because its cost per "
            f"conversion is up {_pct(a['change'])} week on week."
        )
    elif (c["cpa_change"] or 0) < -0.05 and chans:
        best = min(chans, key=lambda ch: ch["cpa"])
        s3 = f"Action: keep budgets steady and move about 10% more spend to {best['channel']} if it holds for another week."
    else:
        s3 = "Action: no urgent issues; refresh the oldest ad creative and keep monitoring daily."
    return [s1, s2, s3]


def _sanitize_sentences(items: Any, fallback: list[str]) -> list[str]:
    sentences = [str(s).strip() for s in (items or []) if str(s).strip()]
    if len(sentences) < 3:
        sentences += fallback[len(sentences) :]
    return sentences[:3]


def generate_weekly_summary(ctx: Context, *, source: str = "dashboard") -> dict[str, Any]:
    with AutomationRun(ctx.engine, ctx.notifier, "weekly_summary", source=source) as run:
        stats = client_week_stats(ctx)
        clients = stats["clients"]
        run.step("stats_ready", clients=len(clients))
        by_id: dict[int, list[str]] = {}
        generated_by = "offline-template"
        model = None
        if ctx.llm.live and clients:
            compact = [
                {k: c[k] for k in ("client_id", "client", "spend", "spend_last_week", "conversions", "conversions_last_week", "cpa", "cpa_last_week", "cpa_change")}
                | {
                    "channels": c["channels"],
                    "alerts": [{"channel": a["channel"], "reason": a["reason"]} for a in c["alerts"]],
                }
                for c in clients
            ]
            result = ctx.llm.structured(
                system=SUMMARY_SYSTEM,
                prompt=(
                    f"Week {stats['week']['start']} to {stats['week']['end']} compared with the previous 7 days.\n"
                    f"Client data (JSON):\n{json.dumps(compact, default=str)}\n\n"
                    "Return one entry per client_id with exactly 3 sentences, using submit_summaries."
                ),
                tool_name="submit_summaries",
                tool_description="Submit the weekly summaries, 3 sentences per client.",
                schema=SUMMARY_SCHEMA,
                model=ctx.settings.anthropic_fast_model,
                max_tokens=2500,
            )
            for item in result.data.get("summaries", []):
                try:
                    by_id[int(item["client_id"])] = item.get("sentences") or []
                except (KeyError, TypeError, ValueError):
                    continue
            generated_by, model = "ai", result.model
            run.step("ai_written", model=model, tokens=result.input_tokens + result.output_tokens)

        out = []
        now = utcnow()
        period_start = date.fromisoformat(stats["week"]["start"])
        period_end = date.fromisoformat(stats["week"]["end"])
        rows = []
        for c in clients:
            fallback = offline_sentences(c)
            sentences = _sanitize_sentences(by_id.get(c["client_id"]), fallback) if c["client_id"] in by_id else fallback
            by = generated_by if c["client_id"] in by_id else "offline-template"
            out.append({"client_id": c["client_id"], "client": c["client"], "sentences": sentences, "generated_by": by, "stats": c})
            rows.append(
                {
                    "run_id": run.run_id,
                    "client_id": c["client_id"],
                    "period_start": period_start,
                    "period_end": period_end,
                    "sentences": sentences,
                    "generated_by": by,
                    "created_at": now,
                }
            )
        if rows:
            with ctx.engine.begin() as conn:
                conn.execute(weekly_summaries.insert(), rows)
        run.set(clients=len(out), generated_by=generated_by, model=model)
    return {"run_id": run.run_id, "week": stats["week"], "generated_by": generated_by, "model": model, "summaries": out}


def latest_summary(ctx: Context) -> dict[str, Any] | None:
    with ctx.engine.connect() as conn:
        last = conn.execute(select(weekly_summaries.c.run_id).order_by(weekly_summaries.c.id.desc()).limit(1)).scalar()
        if not last:
            return None
        rows = rows_to_dicts(conn.execute(select(weekly_summaries).where(weekly_summaries.c.run_id == last)))
    return {"run_id": last, "summaries": rows}
