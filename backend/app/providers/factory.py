from app.config import Settings
from app.providers.base import LLMProvider
from app.providers.mock import MockProvider
from app.providers.sarvam import SarvamProvider


def create_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "sarvam":
        return SarvamProvider(settings)
    return MockProvider()

