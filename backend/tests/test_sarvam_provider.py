import pytest

from app.config import Settings
from app.providers.sarvam import SarvamProvider
from app.schemas import Message


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, _path, json, headers):
        self.payload = json
        return FakeResponse(self.body)


@pytest.mark.asyncio
async def test_sarvam_reserves_the_budget_for_structured_output(monkeypatch):
    client = FakeClient({
        "model": "sarvam-105b",
        "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    })
    monkeypatch.setattr("app.providers.sarvam.httpx.AsyncClient", lambda **_: client)

    provider = SarvamProvider(Settings(sarvam_api_key="test-key"))
    response = await provider.generate([Message(role="user", content="plan this")])

    assert response.content == "{}"
    assert client.payload["reasoning_effort"] is None
    assert client.payload["response_format"] == {"type": "json_object"}
    assert client.payload["max_tokens"] == 800


@pytest.mark.asyncio
async def test_sarvam_empty_final_content_reports_finish_reason(monkeypatch):
    client = FakeClient({
        "choices": [{
            "finish_reason": "length",
            "message": {"content": None, "reasoning_content": "internal trace"},
        }],
        "usage": {"completion_tokens": 800},
    })
    monkeypatch.setattr("app.providers.sarvam.httpx.AsyncClient", lambda **_: client)

    provider = SarvamProvider(Settings(sarvam_api_key="test-key"))
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        await provider.generate([Message(role="user", content="plan this")])
