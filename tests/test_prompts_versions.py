from __future__ import annotations

import pytest

from novelloom.engine import NovelLoomEngine
from novelloom.services.core import DomainError


def test_prompt_versions_resolve_and_rollback(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    first = engine.prompts.save(
        project_id=project_id,
        key="writer",
        system_prompt="风格：{style}",
        user_prompt="材料：{context}",
    )
    second = engine.prompts.save(
        project_id=project_id,
        key="writer",
        system_prompt="克制的风格：{style}",
        user_prompt="材料：{context}",
    )
    system, user = engine.prompts.resolve(
        project_id,
        "writer",
        default_system="default",
        default_user="{context}",
        variables={"style": "冷峻", "context": "大纲"},
    )
    assert system == "克制的风格：冷峻"
    assert user == "材料：大纲"
    history = engine.prompts.get(second["id"])
    assert [item["version"] for item in history["history"]] == [2, 1]
    rolled_back = engine.prompts.rollback(second["id"], first["revision_id"])
    assert rolled_back["version"] == 3
    assert rolled_back["system_prompt"] == "风格：{style}"


def test_prompt_variable_errors_fail_before_model_call(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    engine.prompts.save(
        project_id=project_id,
        key="critic",
        system_prompt="{missing}",
        user_prompt="{context}",
    )
    with pytest.raises(DomainError, match="变量错误"):
        engine.prompts.resolve(
            project_id,
            "critic",
            default_system="default",
            default_user="default",
            variables={"context": "正文"},
        )
