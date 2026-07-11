"""Anthropic client wrapper: model routing, retries, JSON extraction, vision.

The wrapper degrades gracefully: if no API key is configured it reports itself
as unavailable so callers can fall back to heuristics (keeps the pipeline and
seed import runnable offline / in CI).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import Any, Literal

from majak.config import settings

logger = logging.getLogger(__name__)

Route = Literal["extract", "synth", "vision"]

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMClient:
    def __init__(self) -> None:
        self._client: Any | None = None
        self._model = {
            "extract": settings.claude_model_extract,
            "synth": settings.claude_model_synth,
            "vision": settings.claude_model_vision,
        }

    @property
    def available(self) -> bool:
        return bool(settings.anthropic_api_key)

    def _get_client(self) -> Any:
        if self._client is None:
            # Imported lazily so the package imports without the SDK installed.
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def complete(
        self,
        prompt: str,
        *,
        route: Route = "extract",
        system: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        images: list[bytes] | None = None,
        max_retries: int = 3,
    ) -> str:
        """Single-turn completion with exponential-backoff retries."""
        if not self.available:
            raise LLMUnavailable("ANTHROPIC_API_KEY not configured")

        client = self._get_client()
        content: list[dict[str, Any]] = []
        for img in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(img).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                msg = await client.messages.create(
                    model=self._model[route],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system or "",
                    messages=[{"role": "user", "content": content}],
                )
                return "".join(
                    block.text for block in msg.content if getattr(block, "type", "") == "text"
                )
            except Exception as exc:  # noqa: BLE001 — retry any transient failure
                last_exc = exc
                logger.warning("LLM call failed (attempt %d/%d): %s", attempt + 1, max_retries, exc)
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
        raise LLMError(f"LLM call failed after {max_retries} attempts") from last_exc

    async def complete_json(self, prompt: str, **kwargs: Any) -> Any:
        """Complete and parse a JSON object/array from the response."""
        text = await self.complete(prompt, **kwargs)
        return parse_json(text)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    pass


def parse_json(text: str) -> Any:
    """Best-effort JSON extraction from a model response."""
    text = text.strip()
    block = _JSON_BLOCK_RE.search(text)
    if block:
        text = block.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the first {...} or [...] span.
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
    raise LLMError("Could not parse JSON from model response")


_client_singleton: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LLMClient()
    return _client_singleton
