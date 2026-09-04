from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TBX AI Assistant"
    environment: str = "development"
    llm_provider: Literal["mock", "keyword", "sarvam", "openai"] = "mock"
    # when the configured provider fails, degrade to the mock planner instead of
    # returning a 502 mid-demo
    llm_fallback_to_mock: bool = True
    sarvam_api_key: str = ""
    sarvam_model: str = "sarvam-105b"
    sarvam_base_url: str = "https://api.sarvam.ai/v1"
    # OpenAI-compatible endpoint: Ollama, vLLM, LM Studio, Groq, OpenAI...
    openai_base_url: str = "http://localhost:11434/v1"
    openai_api_key: str = ""
    openai_model: str = "qwen2.5:1.5b"
    request_timeout_seconds: float = 45.0
    cors_origins: str = "http://localhost:5173"
    data_directory: str = "data/uploads"
    max_result_rows: int = 200

    # uvicorn is usually launched from backend/, but .env lives at the repo
    # root - look in both so the same file works from either directory
    model_config = SettingsConfigDict(
        env_file=(".env", str(Path(__file__).resolve().parents[2] / ".env")),
        extra="ignore",
    )

    @property
    def resolved_data_directory(self) -> str:
        """DATA_DIRECTORY is written relative to the repo root, but uvicorn is
        usually launched from backend/. Resolving against the project root means
        the same .env works from either directory."""
        candidate = Path(self.data_directory)
        if candidate.is_absolute():
            return str(candidate)
        root = Path(__file__).resolve().parents[2]
        rooted = root / candidate
        return str(rooted if rooted.exists() else candidate)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()
