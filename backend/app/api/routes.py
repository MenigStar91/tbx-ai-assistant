from fastapi import APIRouter, Depends, HTTPException
from httpx import HTTPError

from app.assistant.service import AssistantService
from app.config import get_settings
from app.providers.factory import create_provider
from app.schemas import ChatRequest, ChatResponse
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1")


def get_assistant_service() -> AssistantService:
    settings = get_settings()
    return AssistantService(create_provider(settings), ToolRegistry())


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: AssistantService = Depends(get_assistant_service),
) -> ChatResponse:
    try:
        return await service.respond(request)
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail="AI provider unavailable") from exc

