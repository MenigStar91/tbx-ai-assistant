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


class QueryFilter(BaseModel):
    column: str
    operator: Literal["eq", "neq", "contains", "gte", "lte", "gt", "lt"]
    value: str | int | float | bool


class QueryPlan(BaseModel):
    dataset: str
    operation: Literal["list", "count", "sum", "average", "minimum", "maximum"]
    measure: str | None = None
    group_by: list[str] = Field(default_factory=list, max_length=3)
    filters: list[QueryFilter] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=50, ge=1, le=200)


class Evidence(BaseModel):
    dataset: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    calculation: str
    export_id: str | None = None


class ChatResponse(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    answer: str
    confidence: Literal["high", "medium", "low"] = "medium"
    evidence: Evidence | None = None
    clarification_needed: bool = False
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)


class ProviderResponse(BaseModel):
    content: str
