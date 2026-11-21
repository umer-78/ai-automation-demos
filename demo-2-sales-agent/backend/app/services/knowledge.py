"""The seller's own notes the agent reads first: product.md, competitors.md and deal notes.

The demo reads Acme's files in app/knowledge. Once the app runs on real data, the notes come from
Settings (stored in kv_store as knowledge:<name>) and the Acme files are never used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import kv_store, upsert, utcnow

KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "knowledge"
DOCS = {
    "product": "What we sell, pricing and the ideal customer",
    "competitors": "Competitors and where we win or lose",
    "deal_notes": "Won and lost deals",
}
PREFIX = "knowledge:"
MAX_CHARS = 40_000


def deal_files() -> list[Path]:
    deals = sorted((KNOWLEDGE_DIR / "deals").glob("*.md"))
    return sorted(deals, key=lambda p: (not p.name.startswith("won"), p.name))


def _file_doc(name: str) -> str:
    if name == "product":
        return (KNOWLEDGE_DIR / "product.md").read_text(encoding="utf-8")
    if name == "competitors":
        return (KNOWLEDGE_DIR / "competitors.md").read_text(encoding="utf-8")
    if name == "deal_notes":
        return "\n\n".join(p.read_text(encoding="utf-8").strip() for p in deal_files())
    raise KeyError(name)


def _real_mode(engine: Engine) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(kv_store.c.value).where(kv_store.c.key == "data_mode")).scalar() == "real"


def saved_notes(engine: Engine) -> dict[str, dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(select(kv_store.c.key, kv_store.c.value, kv_store.c.updated_at).where(kv_store.c.key.like(f"{PREFIX}%")))
        return {r.key[len(PREFIX):]: {"text": (r.value or {}).get("text", ""), "updated_at": r.updated_at} for r in rows}


def save_note(engine: Engine, name: str, text: str) -> None:
    if name not in DOCS:
        raise KeyError(name)
    with engine.begin() as conn:
        upsert(conn, kv_store, [{"key": PREFIX + name, "value": {"text": text.strip()[:MAX_CHARS]}, "updated_at": utcnow()}], ["key"], ["value", "updated_at"])


def read_doc(name: str, engine: Engine | None = None) -> str:
    """Real mode: the seller's saved notes (empty until written). Demo mode: Acme's files."""
    if name not in DOCS:
        raise KeyError(name)
    if engine is not None and _real_mode(engine):
        return saved_notes(engine).get(name, {}).get("text", "")
    return _file_doc(name)


def missing_notes(engine: Engine) -> list[str]:
    """Docs the agent needs before a real-data run (product notes are required)."""
    if not _real_mode(engine):
        return []
    return [] if saved_notes(engine).get("product", {}).get("text", "").strip() else ["product"]


def list_docs(engine: Engine | None = None) -> list[dict]:
    real = engine is not None and _real_mode(engine)
    out = []
    for name, title in DOCS.items():
        text = read_doc(name, engine)
        files = (["saved in Settings"] if real else [f"deals/{p.name}" for p in deal_files()] if name == "deal_notes" else [f"{name}.md"])
        out.append({"name": name, "title": title, "files": files, "characters": len(text), "content": text})
    return out
