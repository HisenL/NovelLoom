from __future__ import annotations

import json
from collections.abc import Callable

from .base import ModelRequest, ModelResponse, ProviderAdapter, ProviderConnection


class MockProvider(ProviderAdapter):
    """Deterministic offline provider used by examples and contract tests."""

    name = "mock"

    def __init__(self, responder: Callable[[ModelRequest], object] | None = None) -> None:
        self.responder = responder

    async def generate(
        self, connection: ProviderConnection, request: ModelRequest
    ) -> ModelResponse:
        value = self.responder(request) if self.responder else {"ok": True}
        content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return ModelResponse(
            content=content,
            structured=value if isinstance(value, (dict, list)) else None,
            input_tokens=sum(len(message.content) for message in request.messages) // 4,
            output_tokens=len(content) // 4,
            raw={"mock": True},
        )
