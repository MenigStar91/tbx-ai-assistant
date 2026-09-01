from app.providers.base import LLMProvider
from app.schemas import ChatRequest, ChatResponse, Message
from app.tools.registry import ToolRegistry


SYSTEM_PROMPT = """You are a careful financial assistant platform.
The final TBX problem statement is not known yet, so do not assume a product domain.
Clearly distinguish facts, calculations and assumptions. Never invent user data.
Consequential actions require explicit user confirmation."""


class AssistantService:
    def __init__(self, provider: LLMProvider, tools: ToolRegistry):
        self.provider = provider
        self.tools = tools

    async def respond(self, request: ChatRequest) -> ChatResponse:
        messages = [Message(role="system", content=SYSTEM_PROMPT)]
        messages.extend(request.history)
        messages.append(Message(role="user", content=request.message))
        response = await self.provider.generate(messages)
        return ChatResponse(
            session_id=request.session_id,
            answer=response.content,
        )

