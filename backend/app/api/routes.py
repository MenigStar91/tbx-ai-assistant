from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from httpx import HTTPError

from app.assistant.service import AssistantService
from app.config import get_settings
from app.data.catalog import DatasetCatalog
from app.data.exports import export_store
from app.data.metrics import metrics_store
from app.providers.factory import create_provider
from app.schemas import ChatRequest, ChatResponse
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1")


def get_assistant_service() -> AssistantService:
    settings = get_settings()
    return AssistantService(create_provider(settings), ToolRegistry(), DatasetCatalog(settings.resolved_data_directory))


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
    return {"datasets": DatasetCatalog(get_settings().resolved_data_directory).describe()}


@router.post("/datasets/upload")
async def upload_datasets(files: list[UploadFile] = File(...)) -> dict:
    catalog = DatasetCatalog(get_settings().resolved_data_directory)
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
) -> ChatResponse:
    try:
        return await service.respond(request)
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail="AI provider unavailable") from exc
