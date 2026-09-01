import pytest

from app.assistant.service import AssistantService
from app.providers.mock import MockProvider
from app.schemas import ChatRequest
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_assistant_works_offline():
    service = AssistantService(MockProvider(), ToolRegistry())
    response = await service.respond(ChatRequest(message="Hello"))
    assert "Hello" in response.answer

