"""OpenAI-compatible chat provider.

One adapter, many backends: Ollama, vLLM, LM Studio, llama.cpp server, Groq,
Together, OpenAI itself. They all speak POST /chat/completions with the same
body, so pointing OPENAI_BASE_URL somewhere else is the entire switch.

This is the path for the lightweight-model constraint in Section 7 ("lowest
possible model, highest possible accuracy", 20B parameter ceiling): run a small
local model, measure it with evals/run.py, and ship the smallest one that clears
the accuracy bar.
"""

from __future__ import annotations

import time

import httpx

from app.config import Settings
from app.schemas import Message, ProviderResponse


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.openai_base_url.rstrip("/"),
                timeout=self.settings.request_timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _payload(self, messages: list[Message], json_mode: bool) -> dict:
        payload: dict = {
            "model": self.settings.openai_model,
            "messages": [message.model_dump() for message in messages],
            "temperature": 0,
            # a query plan is a small object; a low ceiling keeps a rambling
            # small model from burning output tokens on prose we discard
            "max_tokens": 400,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def generate(self, messages: list[Message]) -> ProviderResponse:
        headers = {"content-type": "application/json"}
        if self.settings.openai_api_key:
            headers["authorization"] = f"Bearer {self.settings.openai_api_key}"

        client = self._http_client()
        started = time.monotonic()
        response = await client.post(
            "/chat/completions", json=self._payload(messages, True), headers=headers
        )
        # not every OpenAI-compatible server implements response_format;
        # the ones that don't reject the whole request, so retry plainly
        if response.status_code in (400, 422):
            response = await client.post(
                "/chat/completions", json=self._payload(messages, False), headers=headers
            )
        response.raise_for_status()
        body = response.json()
        latency_ms = int((time.monotonic() - started) * 1000)

        usage = body.get("usage") or {}
        return ProviderResponse(
            content=body["choices"][0]["message"]["content"] or "",
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            model=body.get("model") or self.settings.openai_model,
        )
