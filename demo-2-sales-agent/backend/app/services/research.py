"""Web research for the agent.

* With TAVILY_API_KEY set, `search` calls the Tavily Search API (1 credit per basic search;
  the free plan includes 1,000 credits a month).
* Without it, `search` runs over data/research_snapshot.json: a cache of real public pages
  (press releases and news) gathered for this demo. Same result shape, so the agent and
  its provenance checks behave identically.

`read_page` fetches a public page (SSRF-safe) so the agent can confirm a fact; offline it
returns the cached summary for known URLs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings
from app.services.web_snapshot import fetch_snapshot

TAVILY_URL = "https://api.tavily.com/search"
STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "in", "on", "to", "with", "by", "is", "are", "at", "from", "as", "or",
    "that", "this", "it", "its", "their", "company", "companies", "firms", "firm", "new", "recent", "recently",
    "news", "2025", "2026", "2027", "who", "which", "what", "has", "have", "announces", "announced",
}
PHRASES = ("soc 2", "type ii", "iso 27001", "series b", "chief information security officer", "ciso", "cloud-native")


class ResearchError(RuntimeError):
    pass


def normalize_url(url: str) -> str:
    """Canonical form used for provenance checks (scheme/host lower-case, no fragment or trailing slash)."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") if parts.path not in ("", "/") else ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9$][a-z0-9.$+-]*", text.lower()) if t not in STOPWORDS and len(t) > 1}


class CachedResearch:
    name = "cache"

    def __init__(self, path: str | Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.meta: dict[str, Any] = data.get("_meta", {})
        self.entries: list[dict[str, Any]] = data["results"]
        self._index = []
        for entry in self.entries:
            text = " ".join(
                str(entry.get(k, "")) for k in ("company", "industry", "fact", "title", "keywords", "category")
            ).lower()
            self._index.append((text, tokenize(text)))
        self._by_url = {normalize_url(e["url"]): e for e in self.entries}

    def search(self, query: str, max_results: int = 6) -> list[dict[str, Any]]:
        q_tokens = tokenize(query)
        q_lower = query.lower()
        scored = []
        for entry, (text, tokens) in zip(self.entries, self._index):
            hits = len(q_tokens & tokens)
            bonus = sum(2 for phrase in PHRASES if phrase in q_lower and phrase in text)
            score = hits + bonus
            if score >= 2:
                scored.append((score, entry["date"], entry))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [self.as_result(e) for _, _, e in scored[:max_results]]

    @staticmethod
    def as_result(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": entry["title"],
            "url": entry["url"],
            "content": entry["snippet"],
            "published_date": entry["date"],
            "source": "cache",
        }

    def entry_for_url(self, url: str) -> dict[str, Any] | None:
        return self._by_url.get(normalize_url(url))


class TavilyResearch:
    name = "web"

    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=20)

    def search(self, query: str, max_results: int = 6) -> list[dict[str, Any]]:
        payload = {
            "query": query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": max(1, min(max_results, 10)),
            "time_range": "year",
            "include_published_date": True,
            "include_answer": False,
        }
        try:
            resp = self.http.post(TAVILY_URL, json=payload, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as exc:
            raise ResearchError(f"Tavily request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise ResearchError(f"Tavily returned HTTP {resp.status_code}: {resp.text[:200]}")
        results = []
        for item in resp.json().get("results", []):
            if not item.get("url"):
                continue
            results.append(
                {
                    "title": (item.get("title") or "")[:200],
                    "url": item["url"],
                    "content": " ".join((item.get("content") or "").split())[:700],
                    "published_date": item.get("published_date"),
                    "source": "web",
                }
            )
        return results


class Research:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.cache = CachedResearch(settings.research_cache_path)
        self.web = TavilyResearch(settings.tavily_api_key, http) if settings.research_live else None

    @property
    def source(self) -> str:
        return "web" if self.web else "cache"

    def search(self, query: str, *, use_cache: bool = False) -> list[dict[str, Any]]:
        max_results = self.settings.research_max_results
        if self.web and not use_cache:
            return self.web.search(query, max_results)
        return self.cache.search(query, max(max_results, 8))

    def read_page(self, url: str) -> dict[str, Any] | None:
        cached = self.cache.entry_for_url(url)
        if not self.web:
            if not cached:
                return None
            return {"url": cached["url"], "title": cached["title"], "excerpt": cached["snippet"], "source": "cache"}
        snap = fetch_snapshot(url)
        if snap is None and cached:
            return {"url": cached["url"], "title": cached["title"], "excerpt": cached["snippet"], "source": "cache"}
        if snap is None:
            return None
        return {**snap, "source": "web"}
