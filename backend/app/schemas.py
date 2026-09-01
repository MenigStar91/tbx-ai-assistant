from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatRequest(BaseModel):
    session_id: UUID = Field(default_factory=uuid4)
    message: str = Field(min_length=1, max_length=10_000)
    history: list[Message] = Field(default_factory=list, max_length=30)


class ToolExecution(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class ChatResponse(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    answer: str
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class ProviderResponse(BaseModel):
    content: str

