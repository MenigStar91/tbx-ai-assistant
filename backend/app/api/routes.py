from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from httpx import HTTPError

from app.assistant.service import AssistantService
from app.config import get_settings
from app.data.catalog import DatasetCatalog
from app.data.exports import export_store
from app.providers.factory import create_provider
from app.schemas import ChatRequest, ChatResponse
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1")


def get_assistant_service() -> AssistantService:
    settings = get_settings()
    return AssistantService(create_provider(settings), ToolRegistry(), DatasetCatalog(settings.data_directory))


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/datasets")
async def datasets() -> dict:
    return {"datasets": DatasetCatalog(get_settings().data_directory).describe()}


@router.post("/datasets/upload")
async def upload_datasets(files: list[UploadFile] = File(...)) -> dict:
    catalog = DatasetCatalog(get_settings().data_directory)
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
