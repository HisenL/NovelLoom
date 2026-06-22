from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .base import (
    ModelRequest,
    ModelResponse,
    ProviderAdapter,
    ProviderConnection,
    ProviderError,
)
from .http_helpers import parse_structured, schema_instruction


class GeminiProvider(ProviderAdapter):
    name = "google_gemini"

    async def generate(
        self, connection: ProviderConnection, request: ModelRequest
    ) -> ModelResponse:
        base_url = (connection.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        system_parts = [message.content for message in request.messages if message.role == "system"]
        if request.response_schema:
            system_parts.append(schema_instruction(request.response_schema))
        contents = []
        for message in request.messages:
            if message.role == "system":
                continue
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
            **request.extra,
        }
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        url = (
            f"{base_url}/v1beta/models/{quote(connection.model, safe='')}:generateContent"
            f"?key={quote(connection.api_key, safe='')}"
        )
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=connection.headers, json=body)
        if response.is_error:
            raise ProviderError(f"Provider returned {response.status_code}: {response.text[:500]}")
        raw = response.json()
        try:
            parts = raw["candidates"][0]["content"]["parts"]
            content = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("Gemini response did not contain candidate text") from error
        usage = raw.get("usageMetadata") or {}
        return ModelResponse(
            content=content,
            structured=parse_structured(content) if request.response_schema else None,
            input_tokens=int(usage.get("promptTokenCount", 0) or 0),
            output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
            raw=raw,
        )
