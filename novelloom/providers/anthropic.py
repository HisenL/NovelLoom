from __future__ import annotations

from typing import Any

import httpx

from .base import (
    ModelRequest,
    ModelResponse,
    ProviderAdapter,
    ProviderConnection,
    ProviderError,
)
from .http_helpers import parse_structured, schema_instruction


class AnthropicProvider(ProviderAdapter):
    name = "anthropic"

    async def generate(
        self, connection: ProviderConnection, request: ModelRequest
    ) -> ModelResponse:
        base_url = (connection.base_url or "https://api.anthropic.com").rstrip("/")
        system_parts = [message.content for message in request.messages if message.role == "system"]
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role != "system"
        ]
        if request.response_schema:
            system_parts.append(schema_instruction(request.response_schema))
        body: dict[str, Any] = {
            "model": connection.model,
            "messages": messages,
            "system": "\n\n".join(system_parts),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            **request.extra,
        }
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": connection.api_key,
            **connection.headers,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{base_url}/v1/messages", headers=headers, json=body)
        if response.is_error:
            raise ProviderError(f"Provider returned {response.status_code}: {response.text[:500]}")
        raw = response.json()
        blocks = raw.get("content") or []
        content = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        usage = raw.get("usage") or {}
        return ModelResponse(
            content=content,
            structured=parse_structured(content) if request.response_schema else None,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            raw=raw,
        )
