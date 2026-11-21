"""Thin wrapper around the Anthropic Messages API, used by the agent loop.

When ANTHROPIC_API_KEY is not set the app runs in offline mode: the agent runner executes
the same tools with a deterministic planner, so the demo still works end to end.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self._client = client

    @property
    def live(self) -> bool:
        return self._client is not None or self.settings.llm_live

    @property
    def model(self) -> str:
        return self.settings.anthropic_model

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.settings.llm_live:
                raise LLMError("ANTHROPIC_API_KEY is not configured")
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self.settings.anthropic_api_key, max_retries=2, timeout=60)
        return self._client

    def create(self, **kwargs: Any) -> Any:
        try:
            return self.client.messages.create(**kwargs)
        except LLMError:
            raise
        except Exception as exc:  # API errors, timeouts, network errors
            raise LLMError(f"AI API call failed: {exc}") from exc
