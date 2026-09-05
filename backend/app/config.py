from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FiFi — Financial Findings"
    environment: str = "development"
    llm_provider: Literal["mock", "keyword", "sarvam", "openai"] = "sarvam"
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
    seed_directory: str = "data/uploads"
    upload_directory: str = "data/uploads"
    # DATA_BACKEND=mysql reads the three tables straight from MySQL with a
    # SELECT-only grant; anything else keeps the file/DuckDB path.
    data_backend: str = "files"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "tbx"
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_query_timeout_ms: int = 5_000
    mysql_max_query_cost: float = 100_000.0
    mysql_explain_analyze: bool = False
    require_time_filter_tables: str = "transaction"
    data_max_date: str = ""
    max_result_rows: int = 200
    conversation_db_path: str = "data/runtime/conversations.db"

    # uvicorn is usually launched from backend/, but .env lives at the repo
    # root - look in both so the same file works from either directory
    model_config = SettingsConfigDict(
        env_file=(".env", str(Path(__file__).resolve().parents[2] / ".env")),
        extra="ignore",
    )

    def _resolved_directory(self, value: str) -> str:
        candidate = Path(value)
        if candidate.is_absolute():
            return str(candidate)
        return str(Path(__file__).resolve().parents[2] / candidate)

    @property
    def resolved_seed_directory(self) -> str:
        return self._resolved_directory(self.seed_directory)

    @property
    def resolved_upload_directory(self) -> str:
        return self._resolved_directory(self.upload_directory)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def time_filter_tables(self) -> set[str]:
        return {name.strip() for name in self.require_time_filter_tables.split(",") if name.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
