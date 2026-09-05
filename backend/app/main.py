from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import get_assistant_service, router
from app.config import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Avoid constructing the service during shutdown if no chat request used it.
    if get_assistant_service.cache_info().currsize:
        close = getattr(get_assistant_service().provider, "aclose", None)
        if callable(close):
            await close()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
