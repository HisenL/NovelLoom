from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from novelloom.domain import ModelRole
from novelloom.engine import NovelLoomEngine
from novelloom.persistence.models import Decision, Job, WorkflowRun
from novelloom.providers.mock import MockProvider
from novelloom.services.core import BudgetExceeded, DomainError, NotFound


def _fixture_response(request: object) -> object:
    schema = getattr(request, "response_schema", None)
    properties = (schema or {}).get("properties", {})
    if "summary" in properties and "nodes" in properties:
        return {
            "summary": "雾港以记忆缴纳通行税，领航员伊澜负责追查失踪者。",
            "nodes": [
                {"key": "character:yilan", "kind": "character", "label": "伊澜"},
                {"key": "location:mist_port", "kind": "location", "label": "雾港"},
            ],
            "edges": [
                {
                    "key": "located:yilan:port",
                    "source": "character:yilan",
                    "target": "location:mist_port",
                    "kind": "located_at",
                    "label": "居于",
                }
            ],
        }
    if "overall_arc" in properties:
        return {
            "overall_arc": "伊澜进入雾港并发现城市正在删除失踪者。",
            "events": [
                {
                    "key": "event:arrival",
                    "label": "抵达雾港",
                    "summary": "伊澜抵达雾港。",
                    "phase": "开端",
                    "order": 1,
                    "participant_keys": ["character:yilan"],
                    "location_key": "location:mist_port",
                }
            ],
            "edges": [],
        }
    if "chapters" in properties:
        chapters = []
        for book_key, count in (("main", 12), ("bio", 4)):
            for number in range(1, count + 1):
                chapters.append(
                    {
                        "book_key": book_key,
                        "chapter_no": number,
                        "title": f"第{number}章",
                        "event_keys": ["event:arrival"],
                        "viewpoint": "伊澜",
                        "scene": "雾港",
                        "plot_points": ["观察", "选择"],
                        "conflict": "记忆与事实冲突",
                        "ending_hook": "新的名字被抹去",
                        "target_words": 500,
                    }
                )
        return {"chapters": chapters}
    if "facts" in properties:
        return {"summary": "伊澜记录了雾港的异常。", "facts": []}
    if "score" in properties:
        return {"status": "pass", "score": 9, "issues": [], "comment": "跨书事实一致。"}
    return "伊澜在潮湿的码头醒来。雾从石阶上缓慢退去。"


def _configure_mock(engine: NovelLoomEngine, project_id: str) -> None:
    engine.providers.registry.register(MockProvider(_fixture_response))
    profile = engine.providers.save_profile(
        project_id=project_id,
        key="offline-fixture",
        provider="mock",
        model="deterministic",
        capabilities={"structured_output": True},
    )
    for role in ModelRole:
        engine.providers.set_route(
            project_id=project_id,
            role=role,
            primary_profile_id=profile["id"],
        )


@pytest.mark.asyncio
async def test_durable_workflow_and_12_plus_4_batch(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    _configure_mock(engine, project_id)
    started = await engine.workflow.start(project_id)
    run_id = started["run_id"]
    await engine.workflow.resume(run_id, approve=True)
    await engine.workflow.resume(run_id, approve=True)
    finished = await engine.workflow.resume(run_id, approve=True)
    assert finished["state"]["step"] == "done"
    outlines = engine.artifacts.list_artifacts(project_id, kind="chapter_outline")
    assert len(outlines) == 16
    batch = await engine.writing.write_batch(
        project_id=project_id, event_keys=["event:arrival"], run_id=run_id
    )
    assert len(batch["prose"]) == 16
    engine.writing.decide_batch(batch["decision_id"], approve=True)
    prose = engine.artifacts.list_artifacts(project_id, kind="chapter_prose")
    assert len(prose) == 16
    assert all(item["status"] == "approved" for item in prose)


@pytest.mark.asyncio
async def test_default_mock_provider_can_drive_web_demo_workflow(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    profile = engine.providers.save_profile(
        project_id=project_id,
        key="mock-demo",
        provider="mock",
        model="fixture",
        capabilities={"structured_output": True},
    )
    for role in ModelRole:
        engine.providers.set_route(
            project_id=project_id,
            role=role,
            primary_profile_id=profile["id"],
        )

    started = await engine.workflow.start(project_id)
    await engine.workflow.resume(started["run_id"], approve=True)
    await engine.workflow.resume(started["run_id"], approve=True)
    finished = await engine.workflow.resume(started["run_id"], approve=True)
    assert finished["state"]["step"] == "done"
    assert len(engine.artifacts.list_artifacts(project_id, kind="chapter_outline")) == 16


@pytest.mark.asyncio
async def test_rejected_world_can_be_regenerated_without_duplicate_rows(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    _configure_mock(engine, project_id)
    first = await engine.reasoning.propose_world(project_id)
    engine.reasoning.decide(first["decision_id"], approve=False, note="调整设定")
    second = await engine.reasoning.propose_world(project_id)
    assert set(second["node_ids"]) == set(first["node_ids"])
    graph = engine.graph.get_graph(project_id)
    assert len(graph["nodes"]) == 2
    assert all(node["version"] == 2 for node in graph["nodes"])
    engine.reasoning.decide(second["decision_id"], approve=True)
    third = await engine.reasoning.propose_world(project_id)
    engine.reasoning.decide(third["decision_id"], approve=False)
    restored = engine.graph.get_graph(project_id)
    assert all(node["status"] == "approved" and node["version"] == 2 for node in restored["nodes"])


@pytest.mark.asyncio
async def test_world_edit_recomputes_event_and_outline_candidates(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    _configure_mock(engine, project_id)
    started = await engine.workflow.start(project_id)
    await engine.workflow.resume(started["run_id"], approve=True)
    await engine.workflow.resume(started["run_id"], approve=True)
    await engine.workflow.resume(started["run_id"], approve=True)

    world_node = next(
        node for node in engine.graph.get_graph(project_id)["nodes"] if node["kind"] == "character"
    )
    update = engine.graph.update_node(
        world_node["id"], label=world_node["label"], payload={"age": 32}
    )
    job_id = update["cascade_job_id"]
    assert job_id
    assert all(
        outline["stale"]
        for outline in engine.artifacts.list_artifacts(project_id, kind="chapter_outline")
    )

    waiting_event = await engine.cascade.run(job_id)
    assert waiting_event["status"] == "paused"
    event_decision_id = waiting_event["payload"]["decision_id"]
    engine.reasoning.decide(event_decision_id, approve=True)
    waiting_outline = await engine.cascade.continue_after_decision(event_decision_id, approved=True)
    assert waiting_outline and waiting_outline["payload"]["gate"] == "outline_final"
    outline_decision_id = waiting_outline["payload"]["decision_id"]
    engine.reasoning.decide(outline_decision_id, approve=True)
    completed = await engine.cascade.continue_after_decision(outline_decision_id, approved=True)
    assert completed and completed["status"] == "completed"
    outlines = engine.artifacts.list_artifacts(project_id, kind="chapter_outline")
    assert all(item["version"] == 2 and not item["stale"] for item in outlines)
    with engine.database.session() as session:
        decisions = session.scalars(select(Decision).where(Decision.project_id == project_id))
        assert sum(1 for decision in decisions if decision.payload.get("cascade_job_id")) == 2


@pytest.mark.asyncio
async def test_workflow_reject_cancel_and_invalid_resume_states(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    _configure_mock(engine, project_id)
    started = await engine.workflow.start(project_id)
    with pytest.raises(DomainError, match="已有运行"):
        await engine.workflow.start(project_id)
    rejected = await engine.workflow.resume(
        started["run_id"], approve=False, note="世界规则需要重做"
    )
    assert rejected["state"]["step"] == "stopped"
    with pytest.raises(DomainError, match="不能直接恢复"):
        await engine.workflow.resume(started["run_id"], approve=True)
    engine.workflow.cancel(started["run_id"])
    with pytest.raises(NotFound):
        engine.workflow.cancel("missing")
    with pytest.raises(NotFound):
        await engine.workflow.resume("missing", approve=True)


@pytest.mark.asyncio
async def test_budget_and_invalid_model_output_update_run_status(
    engine: NovelLoomEngine,
) -> None:
    budget_project = engine.projects.create_project(
        name="预算暂停",
        premise="测试",
        books=[{"key": "main", "type": "main", "title": "测试"}],
        token_budget=1,
    )
    engine.providers.registry.register(MockProvider(_fixture_response))
    profile = engine.providers.save_profile(
        project_id=budget_project["id"], key="mock", provider="mock", model="fixture"
    )
    engine.providers.set_route(
        project_id=budget_project["id"],
        role=ModelRole.WORLD_BUILDER,
        primary_profile_id=profile["id"],
    )
    with pytest.raises(BudgetExceeded):
        await engine.workflow.start(budget_project["id"])
    with engine.database.session() as session:
        paused = session.scalar(
            select(WorkflowRun).where(WorkflowRun.project_id == budget_project["id"])
        )
        paused_job = session.scalar(select(Job).where(Job.run_id == paused.id))
        assert paused.status == "paused" and paused_job.status == "paused"

    invalid_project = engine.projects.create_project(
        name="非法输出",
        premise="测试",
        books=[{"key": "main", "type": "main", "title": "测试"}],
    )
    engine.providers.registry.register(MockProvider(lambda _request: {}))
    invalid_profile = engine.providers.save_profile(
        project_id=invalid_project["id"], key="mock", provider="mock", model="invalid"
    )
    engine.providers.set_route(
        project_id=invalid_project["id"],
        role=ModelRole.WORLD_BUILDER,
        primary_profile_id=invalid_profile["id"],
    )
    with pytest.raises((RuntimeError, ValidationError)):
        await engine.workflow.start(invalid_project["id"])
    with engine.database.session() as session:
        failed = session.scalar(
            select(WorkflowRun).where(WorkflowRun.project_id == invalid_project["id"])
        )
        assert failed.status == "failed"
