"""LLM client wrapper (Anthropic Messages API).

Structured outputs use forced tool use: the model must answer by "calling" a tool whose
input_schema is the JSON shape we want, which gives reliable, schema-shaped JSON.
When ANTHROPIC_API_KEY is not set the app runs in offline mode: each feature falls back
to a deterministic template generator so the demo still runs end to end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw_stop_reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class LLM:
    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self._client = client

    @property
    def live(self) -> bool:
        return self._client is not None or self.settings.llm_live

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.settings.llm_live:
                raise LLMError("ANTHROPIC_API_KEY is not configured")
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self.settings.anthropic_api_key, max_retries=2, timeout=90)
        return self._client

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        tool_name: str,
        tool_description: str,
        schema: dict[str, Any],
        model: str | None = None,
        max_tokens: int = 2000,
    ) -> LLMResult:
        model = model or self.settings.anthropic_model
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[{"name": tool_name, "description": tool_description, "input_schema": schema}],
                tool_choice={"type": "tool", "name": tool_name},
            )
        except LLMError:
            raise
        except Exception as exc:  # API errors, timeouts, network errors
            raise LLMError(f"AI API call failed: {exc}") from exc

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                usage = getattr(response, "usage", None)
                return LLMResult(
                    data=dict(block.input),
                    model=model,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    raw_stop_reason=getattr(response, "stop_reason", None),
                )
        raise LLMError(f"The model did not return the '{tool_name}' structured output")
