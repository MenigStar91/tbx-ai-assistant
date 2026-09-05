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
    # Populated by the API from trusted server-side session state. Direct client
    # values are overwritten at the route boundary.
    previous_plan: "QueryPlan | None" = None
    selection: "ClarificationSelection | None" = None
    pending_clarification: "PendingClarification | None" = None


class ClarificationSelection(BaseModel):
    clarification_id: UUID
    value: str = Field(min_length=1, max_length=255)


class ClarificationOption(BaseModel):
    label: str
    value: str
    description: str | None = None


class ClarificationRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    kind: Literal["field", "value", "date_range", "dataset", "permission"]
    slot: str
    prompt: str
    options: list[ClarificationOption] = Field(default_factory=list, max_length=8)
    allow_search: bool = False
    search_url: str | None = None


class PendingClarification(BaseModel):
    request: ClarificationRequest
    original_question: str
    partial_plan: dict[str, Any]
    attempts: int = Field(default=0, ge=0, le=2)


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
    select: list[str] = Field(default_factory=list, max_length=12)
    filters: list[QueryFilter] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=50, ge=1, le=200)


class Evidence(BaseModel):
    dataset: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int          # rows matching the filters in the dataset, NOT rows returned
    returned_rows: int = 0   # rows actually shown, after any limit
    total_groups: int | None = None
    calculation: str
    sql: str | None = None
    reconciles: bool | None = None   # None = the check does not apply to this shape
    reconcile_note: str = ""
    matches_ignoring_direction: int | None = None
    export_id: str | None = None


class ChatResponse(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    answer: str
    confidence: Literal["high", "medium", "low"] = "medium"
    evidence: Evidence | None = None
    clarification_needed: bool = False
    refusal_reason: str | None = None
    plan_repairs: list[str] = Field(default_factory=list)
    numbers_verified: bool = True
    orphan_numbers: list[str] = Field(default_factory=list)
    language: str = "en"
    usage: dict[str, Any] | None = None
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    query_plan: QueryPlan | None = None
    clarification: ClarificationRequest | None = None
    pending_clarification: PendingClarification | None = Field(default=None, exclude=True)


class ConversationState(BaseModel):
    session_id: UUID
    history: list[Message] = Field(default_factory=list, max_length=12)
    last_plan: QueryPlan | None = None
    pending_clarification: PendingClarification | None = None


class ProviderResponse(BaseModel):
    content: str
    # usage is never optional: "model efficiency" is a scored criterion, so every
    # call reports what it cost
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    model: str = "unknown"


class QueryMetrics(BaseModel):
    queries: int
    refusals: int
    avg_tokens_in: float
    avg_tokens_out: float
    avg_tokens_total: float
    avg_latency_ms: float
    p50_tokens_total: float
    p95_tokens_total: float
    p50_latency_ms: float
    p95_latency_ms: float
    by_model: list[dict[str, Any]]
