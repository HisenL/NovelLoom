from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .base import ModelRequest, ModelResponse, ProviderAdapter, ProviderConnection


class MockProvider(ProviderAdapter):
    """Deterministic offline provider used by examples and contract tests."""

    name = "mock"

    def __init__(self, responder: Callable[[ModelRequest], object] | None = None) -> None:
        self.responder = responder

    async def generate(
        self, connection: ProviderConnection, request: ModelRequest
    ) -> ModelResponse:
        value = self.responder(request) if self.responder else self._default_response(request)
        content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return ModelResponse(
            content=content,
            structured=value if isinstance(value, (dict, list)) else None,
            input_tokens=sum(len(message.content) for message in request.messages) // 4,
            output_tokens=len(content) // 4,
            raw={"mock": True},
        )

    def _default_response(self, request: ModelRequest) -> object:
        if not request.response_schema:
            prompt = "\n".join(message.content for message in request.messages[-2:])
            if "只回复 OK" in prompt:
                return "OK"
            return (
                "伊澜在潮湿的码头醒来，雾像被谁翻动过的旧纸页。"
                "她握紧领航灯，听见雾港深处传来一个被抹去名字的回声。"
            )

        properties = request.response_schema.get("properties", {})
        if "summary" in properties and "nodes" in properties:
            return {
                "summary": "雾港以记忆缴纳通行税，领航员伊澜负责追查失踪者。",
                "nodes": [
                    {
                        "key": "character:yilan",
                        "kind": "character",
                        "label": "伊澜",
                        "payload": {"role": "退役领航员", "desire": "找回被城市删除的人"},
                    },
                    {
                        "key": "location:mist_port",
                        "kind": "location",
                        "label": "雾港",
                        "payload": {"rule": "每日黎明会重写一部分公共记忆"},
                    },
                    {
                        "key": "world_rule:memory_tax",
                        "kind": "world_rule",
                        "label": "记忆税",
                        "payload": {"effect": "进入雾港的人会被收取一段重要记忆"},
                    },
                ],
                "edges": [
                    {
                        "key": "located:yilan:port",
                        "source": "character:yilan",
                        "target": "location:mist_port",
                        "kind": "located_at",
                        "label": "居于",
                    },
                    {
                        "key": "rule:port:memory_tax",
                        "source": "location:mist_port",
                        "target": "world_rule:memory_tax",
                        "kind": "relationship",
                        "label": "受约束于",
                    },
                ],
            }
        if "overall_arc" in properties:
            return {
                "overall_arc": "伊澜抵达雾港，发现城市正在删除失踪者，并追查记忆税的源头。",
                "events": [
                    {
                        "key": "event:arrival",
                        "label": "抵达雾港",
                        "summary": "伊澜抵达雾港，发现港口登记簿上有被墨雾擦除的名字。",
                        "phase": "开端",
                        "order": 1,
                        "participant_keys": ["character:yilan"],
                        "location_key": "location:mist_port",
                    },
                    {
                        "key": "event:memory_tax",
                        "label": "记忆税显形",
                        "summary": "伊澜意识到失踪并非死亡，而是被城市当作税款收走。",
                        "phase": "发展",
                        "order": 2,
                        "participant_keys": ["character:yilan"],
                        "location_key": "location:mist_port",
                    },
                    {
                        "key": "event:choice",
                        "label": "领航灯抉择",
                        "summary": "伊澜选择点亮领航灯，保留真相但付出自己的关键记忆。",
                        "phase": "高潮",
                        "order": 3,
                        "participant_keys": ["character:yilan"],
                        "location_key": "location:mist_port",
                    },
                ],
                "edges": [
                    {
                        "source": "event:arrival",
                        "target": "event:memory_tax",
                        "kind": "causes",
                        "label": "发现线索",
                    },
                    {
                        "source": "event:memory_tax",
                        "target": "event:choice",
                        "kind": "causes",
                        "label": "迫使选择",
                    },
                ],
            }
        if "chapters" in properties:
            context = self._context_from_request(request)
            event_keys = [
                event.get("stable_key", "event:arrival")
                for event in context.get("events", [])
                if isinstance(event, dict)
            ] or ["event:arrival"]
            books = [
                book
                for book in context.get("books", [{"key": "main", "type": "main"}])
                if isinstance(book, dict)
            ]
            chapters: list[dict[str, Any]] = []
            for book in books:
                book_key = str(book.get("key", "main"))
                count = 12 if book.get("type") == "main" else 4
                for number in range(1, count + 1):
                    chapters.append(
                        {
                            "book_key": book_key,
                            "chapter_no": number,
                            "title": f"第{number}章：雾中回声",
                            "event_keys": [event_keys[(number - 1) % len(event_keys)]],
                            "viewpoint": "伊澜",
                            "scene": "雾港",
                            "plot_points": ["观察异常", "追索线索", "做出选择"],
                            "conflict": "个人记忆与公共事实互相冲突",
                            "ending_hook": "新的名字在登记簿上消失",
                            "target_words": 500,
                        }
                    )
            return {"chapters": chapters}
        if "facts" in properties:
            return {"summary": "伊澜记录了雾港的异常，并继续追查记忆税。", "facts": []}
        if "score" in properties:
            return {"status": "pass", "score": 9, "issues": [], "comment": "跨书事实一致。"}
        return {"ok": True}

    @staticmethod
    def _context_from_request(request: ModelRequest) -> dict[str, Any]:
        for message in reversed(request.messages):
            try:
                value = json.loads(message.content)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return {}
