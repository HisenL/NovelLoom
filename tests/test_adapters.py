from __future__ import annotations

import httpx
import pytest

from novelloom.providers import (
    ModelMessage,
    ModelRequest,
    ProviderCapabilities,
    ProviderConnection,
)
from novelloom.providers.anthropic import AnthropicProvider
from novelloom.providers.base import ProviderError
from novelloom.providers.gemini import GeminiProvider
from novelloom.providers.http_helpers import parse_structured
from novelloom.providers.openai_compatible import OpenAICompatibleProvider


class FakeClient:
    payload: dict[str, object] = {}
    status = 200
    captured: dict[str, object] = {}

    def __init__(self, **_kwargs: object) -> None:
        pass

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        FakeClient.captured = {"url": url, **kwargs}
        return httpx.Response(
            self.status,
            json=self.payload,
            request=httpx.Request("POST", url),
        )


def _request() -> ModelRequest:
    return ModelRequest(
        messages=[
            ModelMessage(role="system", content="system"),
            ModelMessage(role="user", content="user"),
        ],
        response_schema={"type": "object"},
    )


@pytest.mark.asyncio
async def test_openai_compatible_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    FakeClient.payload = {
        "choices": [{"message": {"content": '{"ok": true}'}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    connection = ProviderConnection(
        key="openai",
        provider="openai_compatible",
        model="model",
        base_url="https://example.test/v1/",
        api_key="secret",
        capabilities=ProviderCapabilities(structured_output=True),
    )
    response = await OpenAICompatibleProvider().generate(connection, _request())
    assert response.structured == {"ok": True}
    assert response.input_tokens == 3
    assert FakeClient.captured["url"] == "https://example.test/v1/chat/completions"
    assert FakeClient.captured["headers"]["Authorization"] == "Bearer secret"  # type: ignore[index]


@pytest.mark.asyncio
async def test_anthropic_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    FakeClient.payload = {
        "content": [{"type": "text", "text": '{"ok": true}'}],
        "usage": {"input_tokens": 4, "output_tokens": 5},
    }
    response = await AnthropicProvider().generate(
        ProviderConnection(key="a", provider="anthropic", model="claude", api_key="secret"),
        _request(),
    )
    assert response.structured == {"ok": True}
    assert response.output_tokens == 5
    assert FakeClient.captured["url"] == "https://api.anthropic.com/v1/messages"


@pytest.mark.asyncio
async def test_gemini_contract_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    FakeClient.payload = {
        "candidates": [{"content": {"parts": [{"text": '{"ok":'}, {"text": "true}"}]}}],
        "usageMetadata": {"promptTokenCount": 6, "candidatesTokenCount": 7},
    }
    connection = ProviderConnection(
        key="g", provider="google_gemini", model="gemini/flash", api_key="a key"
    )
    response = await GeminiProvider().generate(connection, _request())
    assert response.structured == {"ok": True}
    assert "gemini%2Fflash" in str(FakeClient.captured["url"])
    FakeClient.status = 429
    with pytest.raises(ProviderError, match="429"):
        await GeminiProvider().generate(connection, _request())
    FakeClient.status = 200


def test_structured_parser_handles_fences_and_invalid_values() -> None:
    assert parse_structured('```json\n{"ok": true}\n```') == {"ok": True}
    assert parse_structured("42") is None
    assert parse_structured("not-json") is None
