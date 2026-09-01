import httpx

from app.config import Settings
from app.schemas import Message, ProviderResponse


class SarvamProvider:
    def __init__(self, settings: Settings):
        if not settings.sarvam_api_key:
            raise ValueError("SARVAM_API_KEY is required when LLM_PROVIDER=sarvam")
        self.settings = settings

    async def generate(self, messages: list[Message]) -> ProviderResponse:
        payload = {
            "model": self.settings.sarvam_model,
            "messages": [message.model_dump() for message in messages],
            "max_tokens": 800,
        }
        headers = {
            "api-subscription-key": self.settings.sarvam_api_key,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(
            base_url=self.settings.sarvam_base_url,
            timeout=self.settings.request_timeout_seconds,
        ) as client:
            response = await client.post("/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
        return ProviderResponse(content=body["choices"][0]["message"]["content"])

