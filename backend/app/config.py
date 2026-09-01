from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TBX AI Assistant"
    environment: str = "development"
    llm_provider: Literal["mock", "sarvam"] = "mock"
    sarvam_api_key: str = ""
    sarvam_model: str = "sarvam-105b"
    sarvam_base_url: str = "https://api.sarvam.ai/v1"
    request_timeout_seconds: float = 45.0
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    return Settings()

