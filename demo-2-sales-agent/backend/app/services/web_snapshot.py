"""Fetch a short, text-only snapshot of a public web page so the agent can confirm a fact.

Hardened against SSRF: only http(s), public IPs only (re-checked on every redirect),
reserved demo TLDs are skipped, small timeout and body cap.
"""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

RESERVED_TLDS = (".example", ".test", ".invalid", ".localhost", ".local", ".internal")
MAX_BYTES = 400_000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.headings: list[str] = []
        self.paragraphs: list[str] = []
        self._stack: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag == "meta" and (a.get("name", "").lower() == "description" or a.get("property", "").lower() == "og:description"):
            if not self.description and a.get("content"):
                self.description = a["content"].strip()[:400]
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        if self._skip:
            return
        text = " ".join(data.split())
        if not text:
            return
        current = self._stack[-1] if self._stack else ""
        if current == "title" and not self.title:
            self.title = text[:200]
        elif current in ("h1", "h2") and len(self.headings) < 10:
            self.headings.append(text[:160])
        elif current in ("p", "li") and sum(len(p) for p in self.paragraphs) < 1500 and len(text) > 30:
            self.paragraphs.append(text[:400])


def is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


def validate_url(url: str) -> str | None:
    """Return a normalised URL if it is safe to fetch, else None."""
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return None
    if host == "localhost" or host.endswith(RESERVED_TLDS):
        return None
    try:
        ipaddress.ip_address(host)
        return None  # raw IPs are never needed for company research
    except ValueError:
        pass
    return url


def fetch_snapshot(url: str, *, timeout: float = 6.0, max_redirects: int = 3) -> dict | None:
    safe = validate_url(url)
    if not safe:
        return None
    current = safe
    with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": "AcmeResearchBot/1.0"}) as client:
        for _ in range(max_redirects + 1):
            host = urlparse(current).hostname or ""
            if not is_public_host(host):
                return None
            try:
                with client.stream("GET", current) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        nxt = validate_url(urljoin(current, resp.headers["location"]))
                        if not nxt:
                            return None
                        current = nxt
                        continue
                    if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", ""):
                        return None
                    body = b""
                    for chunk in resp.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            break
            except httpx.HTTPError:
                return None
            parser = _TextExtractor()
            try:
                parser.feed(body.decode(resp.encoding or "utf-8", errors="replace"))
            except Exception:  # malformed HTML should never break a run
                return None
            return {
                "url": current,
                "title": parser.title,
                "description": parser.description,
                "headings": parser.headings,
                "excerpt": " ".join(parser.paragraphs)[:1500],
            }
    return None
