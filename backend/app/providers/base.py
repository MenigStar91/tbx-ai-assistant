from typing import Protocol

from app.schemas import Message, ProviderResponse


class LLMProvider(Protocol):
    async def generate(self, messages: list[Message]) -> ProviderResponse: ...

