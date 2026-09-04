from app.config import Settings
from app.providers.base import LLMProvider
from app.providers.fallback import FallbackProvider
from app.providers.mock import MockProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.sarvam import SarvamProvider


def create_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "sarvam":
        primary: LLMProvider = SarvamProvider(settings)
    elif settings.llm_provider == "openai":
        primary = OpenAICompatibleProvider(settings)
    else:
        # "keyword" is the same router, named for what it is when reported
        return MockProvider()

    # the mock planner is deterministic and always available, so it is the
    # safety net rather than an error page
    return FallbackProvider(primary) if settings.llm_fallback_to_mock else primary
