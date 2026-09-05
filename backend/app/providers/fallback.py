"""Keeps the demo alive when the model backend does not.

If the configured provider raises - Ollama not started, model still pulling,
network gone, rate limit - the request degrades to the deterministic mock
planner instead of returning a 502. A slightly worse answer beats a broken
screen in front of judges.

The response still reports which model actually served it, so a fallback is
visible in /api/v1/metrics rather than silently flattering the numbers.
"""

from __future__ import annotations

import logging

from app.providers.base import LLMProvider
from app.providers.mock import MockProvider
from app.schemas import Message, ProviderResponse

logger = logging.getLogger(__name__)


class FallbackProvider:
    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None = None):
        self.primary = primary
        self.fallback = fallback or MockProvider()

    async def generate(self, messages: list[Message]) -> ProviderResponse:
        try:
            return await self.primary.generate(messages)
        except Exception as exc:  # noqa: BLE001 - any provider failure degrades the same way
            logger.warning("primary model provider failed (%s); falling back to mock", exc)
            response = await self.fallback.generate(messages)
            response.model = f"{response.model} (fallback)"
            return response

    async def aclose(self) -> None:
        close = getattr(self.primary, "aclose", None)
        if callable(close):
            await close()
