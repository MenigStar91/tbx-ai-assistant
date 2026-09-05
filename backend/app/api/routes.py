from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from httpx import HTTPError
from uuid import UUID
from functools import lru_cache

from app.assistant.service import AssistantService
from app.config import get_settings
from app.data.factory import get_dataset_catalog
from app.data.exports import export_store
from app.data.metrics import metrics_store
from app.data.conversations import ConversationStore
from app.providers.factory import create_provider
from app.schemas import ChatRequest, ChatResponse
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1")


@lru_cache
def get_conversation_store() -> ConversationStore:
    settings = get_settings()
    return ConversationStore(settings.conversation_db_path)


def get_assistant_service() -> AssistantService:
    settings = get_settings()
    return AssistantService(create_provider(settings), ToolRegistry(), get_dataset_catalog())


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/info")
async def info() -> dict:
    """Machine-readable demo contract for the UI and judges."""
    settings = get_settings()
    return {
        "purpose": "Grounded analytics over an introspected financial database",
        "model_calls_per_answer": 1,
        "active_provider": settings.llm_provider,
        "configured_model": (
            settings.sarvam_model if settings.llm_provider == "sarvam"
            else settings.openai_model if settings.llm_provider == "openai"
            else "keyword-baseline"
        ),
        "calculation_engine": "MySQL parameterized deterministic SQL",
        "schema_source": "cached INFORMATION_SCHEMA extraction; POST /datasets/refresh after DDL changes",
        "safe_datasets": list(get_dataset_catalog().describe()),
        "protected_fields": {
            "account_number": "last four only",
            "utr_number": "not exposed or plaintext-searchable",
        },
        "known_missing_data": {
            "vendor_spend": "vendor master and transaction-to-vendor mapping",
            "double_entry_reconciliation": "immutable debit/credit journal lines",
            "cross_currency_totals": "currency and approved dated FX rates",
        },
        "metrics_endpoint": "/api/v1/metrics",
        "conversation_memory": {
            "stored_messages": 12,
            "stored_state": "compact messages and last validated query plan",
            "evidence_rows_stored": False,
        },
        "query_safeguards": {
            "runtime_user": "read-only MySQL account",
            "read_endpoint": settings.mysql_read_host,
            "required_time_filter_tables": sorted(settings.time_filter_tables),
            "max_evidence_or_group_rows": settings.max_result_rows,
            "query_timeout_ms": settings.mysql_query_timeout_ms,
            "max_estimated_query_cost": settings.mysql_max_query_cost,
            "runtime_explain": "EXPLAIN FORMAT=JSON",
            "explain_analyze": "controlled benchmark only" if not settings.mysql_explain_analyze else "enabled",
        },
        "evaluation": "evals/questions.json and docs/evaluation/MODEL_SCORECARD.md",
    }


@router.get("/metrics")
async def metrics() -> dict:
    """Measured token and latency cost per query, overall and per model.

    This is what the model-efficiency criterion and the model-choice slide are
    argued from - estimates are not good enough.
    """
    return metrics_store.summary()


@router.get("/datasets")
async def datasets() -> dict:
    return {"datasets": get_dataset_catalog().describe()}


@router.get("/datasets/{dataset}/values")
async def dataset_values(
    dataset: str,
    column: str,
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict:
    """Bounded type-ahead for clarification choices; never sent to the LLM."""
    try:
        values, has_more = get_dataset_catalog().search_values(dataset, column, q, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"values": values, "has_more": has_more}


@router.post("/datasets/refresh")
async def refresh_datasets() -> dict:
    return {"datasets": get_dataset_catalog().refresh()}


@router.post("/datasets/upload")
async def upload_datasets(files: list[UploadFile] = File(...)) -> dict:
    catalog = get_dataset_catalog()
    saved = []
    for upload in files:
        try:
            saved.append(catalog.import_csv(upload.filename or "dataset.csv", await upload.read()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"uploaded": saved, "catalog": catalog.describe()}


@router.get("/exports/{export_id}.csv")
async def export_csv(export_id: str) -> Response:
    content = export_store.get(export_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Export expired or not found")
    return Response(content=content, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="tbx-breakdown-{export_id}.csv"'})


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: AssistantService = Depends(get_assistant_service),
    conversations: ConversationStore = Depends(get_conversation_store),
) -> ChatResponse:
    try:
        state = conversations.load(request.session_id)
        request = request.model_copy(update={
            "history": state.history if state else request.history[-12:],
            "previous_plan": state.last_plan if state else None,
            "pending_clarification": state.pending_clarification if state else None,
        })
        response = await service.respond(request)
        conversations.append_turn(
            request.session_id, request.message, response.answer, response.query_plan,
            response.pending_clarification,
        )
        return response
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail="AI provider unavailable") from exc


@router.get("/sessions/{session_id}")
async def session(session_id: UUID, conversations: ConversationStore = Depends(get_conversation_store)) -> dict:
    state = conversations.load(session_id)
    return {
        "session_id": str(session_id),
        "history": state.history if state else [],
        "clarification": state.pending_clarification.request if state and state.pending_clarification else None,
    }
