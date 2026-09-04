import pytest

from app.assistant.service import AssistantService
from app.data.catalog import DatasetCatalog
from app.providers.mock import MockProvider
from app.schemas import ChatRequest
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_assistant_requires_grounding(tmp_path):
    service = AssistantService(MockProvider(), ToolRegistry(), DatasetCatalog(str(tmp_path)))
    response = await service.respond(ChatRequest(message="Hello"))
    assert response.clarification_needed
    assert "not been provided" in response.answer
