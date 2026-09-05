import time

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
            "temperature": 0,
            # The planner needs a short final JSON object, not a hidden reasoning
            # trace. Sarvam reasoning shares the max_tokens budget and can leave
            # message.content null when that budget is exhausted.
            "reasoning_effort": None,
            # a query plan is a small JSON object; asking for JSON directly keeps
            # output tokens down and removes prose we would only have to strip
            "response_format": {"type": "json_object"},
        }
        headers = {
            "api-subscription-key": self.settings.sarvam_api_key,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(
            base_url=self.settings.sarvam_base_url,
            timeout=self.settings.request_timeout_seconds,
        ) as client:
            started = time.monotonic()
            response = await client.post("/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
            latency_ms = int((time.monotonic() - started) * 1000)
        usage = body.get("usage") or {}
        choice = body["choices"][0]
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(
                "Sarvam returned no final content "
                f"(finish_reason={choice.get('finish_reason', 'unknown')})"
            )
        return ProviderResponse(
            content=content,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            model=body.get("model") or self.settings.sarvam_model,
        )
