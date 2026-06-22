from __future__ import annotations

import pytest

from novelloom.engine import NovelLoomEngine
from novelloom.providers import ModelMessage, ModelRequest
from novelloom.providers.mock import MockProvider
from novelloom.services.core import BudgetExceeded, DomainError


@pytest.mark.asyncio
async def test_token_budget_stops_before_provider_call(engine: NovelLoomEngine) -> None:
    project = engine.projects.create_project(
        name="低预算",
        premise="测试预算暂停",
        books=[{"key": "main", "type": "main", "title": "测试"}],
        token_budget=1,
    )
    calls = 0

    def responder(_request: ModelRequest) -> str:
        nonlocal calls
        calls += 1
        return "不应被调用"

    engine.providers.registry.register(MockProvider(responder))
    profile = engine.providers.save_profile(
        project_id=project["id"], key="mock", provider="mock", model="fixture"
    )
    engine.providers.set_route(
        project_id=project["id"], role="writer", primary_profile_id=profile["id"]
    )
    with pytest.raises(BudgetExceeded):
        await engine.providers.generate(
            project_id=project["id"],
            role="writer",
            request=ModelRequest(
                messages=[ModelMessage(role="user", content="测试")], max_output_tokens=8
            ),
        )
    assert calls == 0


@pytest.mark.asyncio
async def test_cost_budget_can_choose_cheaper_fallback(
    engine: NovelLoomEngine,
) -> None:
    project = engine.projects.create_project(
        name="回退链",
        premise="测试费用路由",
        books=[{"key": "main", "type": "main", "title": "测试"}],
        cost_budget=0.001,
    )
    engine.providers.registry.register(MockProvider(lambda _request: "fallback-ok"))
    expensive = engine.providers.save_profile(
        project_id=project["id"],
        key="expensive",
        provider="mock",
        model="expensive",
        capabilities={"output_cost_per_million": 1000},
    )
    cheap = engine.providers.save_profile(
        project_id=project["id"], key="cheap", provider="mock", model="cheap"
    )
    engine.providers.set_route(
        project_id=project["id"],
        role="writer",
        primary_profile_id=expensive["id"],
        fallback_profile_ids=[cheap["id"]],
    )
    response = await engine.providers.generate(
        project_id=project["id"],
        role="writer",
        request=ModelRequest(
            messages=[ModelMessage(role="user", content="测试")], max_output_tokens=100
        ),
    )
    assert response.content == "fallback-ok"


def test_sensitive_headers_are_rejected(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    with pytest.raises(DomainError, match="敏感请求头"):
        engine.providers.save_profile(
            project_id=str(project["id"]),
            key="unsafe",
            provider="mock",
            model="fixture",
            headers={"Authorization": "Bearer plaintext"},
        )
