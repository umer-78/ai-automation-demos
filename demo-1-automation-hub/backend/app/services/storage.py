"""File storage for generated site drafts: Supabase Storage when configured, local disk otherwise.

Note: Supabase Storage deliberately serves .html objects as text/plain (anti-phishing), so the
dashboard previews drafts through the app's own /sites/{id}/preview route, which returns the
HTML with a strict, script-free Content-Security-Policy.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import Settings


class StorageError(RuntimeError):
    pass


class Storage:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.http = http or httpx.Client(timeout=20)

    @property
    def live(self) -> bool:
        return self.settings.storage_live

    def save_html(self, path: str, html: str) -> str:
        """Store the file and return its canonical URL (html_url)."""
        if ".." in path or path.startswith("/"):
            raise StorageError("invalid storage path")
        if self.live:
            base = self.settings.supabase_url.rstrip("/")
            bucket = self.settings.supabase_storage_bucket
            key = self.settings.supabase_service_role_key
            url = f"{base}/storage/v1/object/{bucket}/{quote(path)}"
            resp = self.http.post(
                url,
                content=html.encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {key}",
                    "apikey": key,
                    "Content-Type": "text/html; charset=utf-8",
                    "x-upsert": "true",
                    "cache-control": "max-age=60",
                },
            )
            if resp.status_code >= 300:
                raise StorageError(f"Supabase Storage HTTP {resp.status_code}: {resp.text[:300]}")
            return f"{base}/storage/v1/object/{bucket}/{quote(path)}"
        target = Path(self.settings.local_storage_dir) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        return f"local://{path}"
