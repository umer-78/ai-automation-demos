"""Request hardening: security headers, a per-IP rate limit, and the integration token check."""
from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

APP_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
           "font-src 'self' data:; connect-src 'self'; frame-src 'self'; worker-src 'self' blob:; "
           "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'")
# Generated drafts are shown in a sandbox: no scripts, no forms, no network except images.
PREVIEW_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; font-src data:"


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", APP_CSP)
        if "/preview" not in request.url.path:
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return response


class RateLimiter:
    """Sliding one-minute window per client IP. Enough to stop a public demo being hammered."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, request: Request, cost: int = 1) -> None:
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else "unknown"))
        now = time.monotonic()
        q = self.hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) + cost > self.per_minute:
            raise HTTPException(429, "Too many requests from your address. Please wait a minute.")
        for _ in range(cost):
            q.append(now)


def require_token(request: Request, expected: str) -> None:
    """Integration endpoints (Make.com, cron) must send X-Hub-Token. Without a configured token they are closed."""
    if not expected:
        raise HTTPException(503, "Integration endpoints are disabled until HUB_API_TOKEN is set.")
    sent = request.headers.get("x-hub-token", "")
    if not hmac.compare_digest(sent, expected):
        raise HTTPException(401, "Missing or wrong X-Hub-Token.")
