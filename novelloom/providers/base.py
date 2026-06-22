from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProviderCapabilities(BaseModel):
    structured_output: bool = False
    streaming: bool = True
    tool_calls: bool = False
    reasoning: bool = False
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None
    input_cost_per_million: float = Field(default=0, ge=0)
    output_cost_per_million: float = Field(default=0, ge=0)


class ProviderConnection(BaseModel):
    key: str
    provider: str
    model: str
    base_url: str = ""
    api_key: str = Field(default="", repr=False)
    headers: dict[str, str] = Field(default_factory=dict)
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)


class ModelMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelRequest(BaseModel):
    messages: list[ModelMessage]
    response_schema: dict[str, Any] | None = None
    temperature: float = 0.7
    max_output_tokens: int = 4096
    extra: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    content: str
    structured: dict[str, Any] | list[Any] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


class ProviderAdapter(ABC):
    name: str

    @abstractmethod
    async def generate(
        self, connection: ProviderConnection, request: ModelRequest
    ) -> ModelResponse: ...

    async def stream(
        self, connection: ProviderConnection, request: ModelRequest
    ) -> AsyncIterator[str]:
        response = await self.generate(connection, request)
        yield response.content

    async def test_connection(self, connection: ProviderConnection) -> ModelResponse:
        return await self.generate(
            connection,
            ModelRequest(
                messages=[ModelMessage(role="user", content="只回复 OK")],
                temperature=0,
                max_output_tokens=8,
            ),
        )
