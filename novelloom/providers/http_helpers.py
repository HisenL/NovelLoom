from __future__ import annotations

import json
from typing import Any


def schema_instruction(schema: dict[str, Any]) -> str:
    return (
        "Return only valid JSON matching this JSON Schema. Do not wrap it in Markdown:\n"
        + json.dumps(schema, ensure_ascii=False)
    )


def parse_structured(content: str) -> dict[str, Any] | list[Any] | None:
    value = content.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, (dict, list)) else None
    except (TypeError, json.JSONDecodeError):
        return None
