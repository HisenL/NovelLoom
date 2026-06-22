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


class OpenAICompatibleProvider(ProviderAdapter):
    name = "openai_compatible"

    async def generate(
        self, connection: ProviderConnection, request: ModelRequest
    ) -> ModelResponse:
        base_url = connection.base_url.rstrip("/")
        if not base_url:
            raise ProviderError("OpenAI-compatible provider requires base_url")
        messages = [message.model_dump() for message in request.messages]
        if request.response_schema:
            messages.append(
                {"role": "system", "content": schema_instruction(request.response_schema)}
            )
        body: dict[str, Any] = {
            "model": connection.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            **request.extra,
        }
        if request.response_schema and connection.capabilities.structured_output:
            body.setdefault("response_format", {"type": "json_object"})
        headers = {"Content-Type": "application/json", **connection.headers}
        if connection.api_key:
            headers["Authorization"] = f"Bearer {connection.api_key}"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
        if response.is_error:
            raise ProviderError(f"Provider returned {response.status_code}: {response.text[:500]}")
        raw = response.json()
        try:
            content = raw["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "Provider response did not contain choices[0].message.content"
            ) from error
        usage = raw.get("usage") or {}
        return ModelResponse(
            content=content,
            structured=parse_structured(content) if request.response_schema else None,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            raw=raw,
        )
