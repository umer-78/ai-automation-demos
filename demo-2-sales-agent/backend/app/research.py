"""Web research: live Tavily search, or a dated snapshot of real web results when no key is set."""
from __future__ import annotations

import json
import re

import httpx

from .config import DATA_DIR, Settings

TAVILY_URL = "https://api.tavily.com/search"
SNAPSHOT = json.loads((DATA_DIR / "research_snapshot.json").read_text(encoding="utf-8"))
_WORD = re.compile(r"[a-z0-9]+")


class ResearchError(RuntimeError):
    pass


class Research:
    def __init__(self, settings: Settings):
        self.key = settings.tavily_api_key
        self.live = bool(self.key)

    @property
    def label(self) -> str:
        if self.live:
            return "live web search (Tavily)"
        return f"research snapshot from {SNAPSHOT['taken_on']} (no Tavily key)"

    def search(self, query: str, max_results: int = 6) -> list[dict]:
        query = query.strip()[:300]
        if not query:
            raise ResearchError("Search query is empty.")
        return self._tavily(query, max_results) if self.live else self._snapshot(query)

    def _tavily(self, query: str, max_results: int) -> list[dict]:
        try:
            r = httpx.post(TAVILY_URL, timeout=30, headers={"Authorization": f"Bearer {self.key}"},
                           json={"query": query, "max_results": max_results, "search_depth": "basic", "topic": "general"})
        except httpx.HTTPError as exc:
            raise ResearchError(f"Tavily request failed: {exc.__class__.__name__}") from exc
        if r.status_code != 200:
            raise ResearchError(f"Tavily answered {r.status_code}: {r.text[:200]}")
        out = []
        for item in r.json().get("results", [])[:max_results]:
            out.append({"title": item.get("title", "")[:200], "url": item.get("url", ""),
                        "snippet": (item.get("content") or "")[:500], "published": item.get("published_date")})
        return out

    @staticmethod
    def _snapshot(query: str) -> list[dict]:
        """Return the stored results whose query shares the most words with this one."""
        words = set(_WORD.findall(query.lower()))
        best = max(SNAPSHOT["queries"], key=lambda q: len(words & set(_WORD.findall(q["query"].lower()))))
        return [dict(r) for r in best["results"]]


def snapshot_queries() -> list[str]:
    return [q["query"] for q in SNAPSHOT["queries"]]
