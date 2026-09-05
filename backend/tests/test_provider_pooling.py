import pytest

from app.config import Settings
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.schemas import Message


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "model": "qwen",
            "choices": [{"message": {"content": "{}"}}],
            "usage": {},
        }


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.closed = False

    async def post(self, *_args, **_kwargs):
        self.calls += 1
        return FakeResponse()

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_openai_provider_reuses_and_closes_one_http_client(monkeypatch):
    clients = []

    def make_client(**_kwargs):
        client = FakeClient()
        clients.append(client)
        return client

    monkeypatch.setattr("app.providers.openai_compatible.httpx.AsyncClient", make_client)
    provider = OpenAICompatibleProvider(Settings(openai_model="qwen"))

    await provider.generate([Message(role="user", content="first")])
    await provider.generate([Message(role="user", content="second")])
    await provider.aclose()

    assert len(clients) == 1
    assert clients[0].calls == 2
    assert clients[0].closed is True
