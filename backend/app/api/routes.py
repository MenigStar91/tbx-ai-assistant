from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from httpx import HTTPError
from uuid import UUID
from functools import lru_cache

from app.assistant.service import AssistantService
from app.config import get_settings
from app.data.catalog import DatasetCatalog
from app.data.source_factory import create_catalog
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
    return AssistantService(create_provider(settings), ToolRegistry(), create_catalog(settings))


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/info")
async def info() -> dict:
    """Machine-readable demo contract for the UI and judges."""
    return {
        "purpose": "Grounded analytics over TBX bank, account and transaction data",
        "model_calls_per_answer": 1,
        "calculation_engine": "DuckDB deterministic SQL",
        "safe_datasets": ["bank", "account", "transaction"],
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
    return {"datasets": create_catalog(get_settings()).describe()}


@router.post("/datasets/upload")
async def upload_datasets(files: list[UploadFile] = File(...)) -> dict:
    catalog = create_catalog(get_settings())
    saved = []
    for upload in files:
        try:
            saved.append(catalog.save_upload(upload.filename or "dataset.csv", await upload.read()))
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
            # server-held state wins, but a client that tracks its own plan is
            # honoured when the store has nothing - otherwise a caller passing
            # previous_plan sees it silently ignored
            "previous_plan": (state.last_plan if state else None) or request.previous_plan,
        })
        response = await service.respond(request)
        conversations.append_turn(
            request.session_id, request.message, response.answer, response.query_plan
        )
        return response
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail="AI provider unavailable") from exc


@router.get("/sessions/{session_id}")
async def session(session_id: UUID, conversations: ConversationStore = Depends(get_conversation_store)) -> dict:
    state = conversations.load(session_id)
    return {"session_id": str(session_id), "history": state.history if state else []}
