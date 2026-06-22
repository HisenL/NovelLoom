from __future__ import annotations

import pytest

from novelloom.engine import NovelLoomEngine
from novelloom.services.core import DomainError, GraphValidationError, NotFound


def test_project_requires_exactly_one_main(engine: NovelLoomEngine) -> None:
    with pytest.raises(Exception, match="只能包含一本正本"):
        engine.projects.create_project(
            name="错误项目",
            premise="测试",
            books=[{"key": "side", "type": "biography", "title": "外传"}],
        )
    with pytest.raises(DomainError, match="项目名称不能为空"):
        engine.projects.create_project(
            name=" ",
            premise="测试",
            books=[{"key": "main", "type": "main", "title": "测试"}],
        )
    with pytest.raises(DomainError, match="故事梗概不能为空"):
        engine.projects.create_project(
            name="测试",
            premise=" ",
            books=[{"key": "main", "type": "main", "title": "测试"}],
        )
    with pytest.raises(DomainError, match="source_book"):
        engine.projects.create_project(
            name="测试",
            premise="测试",
            books=[
                {"key": "main", "type": "main", "title": "测试"},
                {"key": "bio", "type": "biography", "title": "传记"},
            ],
        )
    with pytest.raises(NotFound):
        engine.projects.get_project("missing")


def test_node_revision_is_immutable_and_cascades(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    node = engine.graph.create_node(
        project_id=project_id,
        stable_key="character:yilan",
        kind="character",
        label="伊澜",
        payload={"age": 31},
    )
    artifact = engine.artifacts.save_artifact(
        project_id=project_id,
        stable_key="prose:main:1",
        kind="chapter_prose",
        title="第一章",
        document={"type": "doc"},
        markdown="旧正文",
        status="approved",
        dependencies=[("node", str(node["id"]))],
    )
    updated = engine.graph.update_node(str(node["id"]), label="伊澜", payload={"age": 32})
    assert updated["version"] == 2
    current = engine.artifacts.get_artifact(str(artifact["id"]))
    assert current["stale"] is True
    assert current["markdown"] == "旧正文"
    assert current["status"] == "approved"


def test_causal_edges_must_be_dag(engine: NovelLoomEngine, project: dict[str, object]) -> None:
    project_id = str(project["id"])
    events = [
        engine.graph.create_node(
            project_id=project_id,
            stable_key=f"event:{index}",
            kind="event",
            label=f"事件 {index}",
        )
        for index in range(3)
    ]
    engine.graph.create_edge(
        project_id=project_id,
        stable_key="cause:0:1",
        source_node_id=str(events[0]["id"]),
        target_node_id=str(events[1]["id"]),
        kind="causes",
    )
    engine.graph.create_edge(
        project_id=project_id,
        stable_key="cause:1:2",
        source_node_id=str(events[1]["id"]),
        target_node_id=str(events[2]["id"]),
        kind="causes",
    )
    with pytest.raises(GraphValidationError, match="存在循环"):
        engine.graph.create_edge(
            project_id=project_id,
            stable_key="cause:2:0",
            source_node_id=str(events[2]["id"]),
            target_node_id=str(events[0]["id"]),
            kind="causes",
        )
    assert len(engine.graph.get_graph(project_id)["edges"]) == 2
    with pytest.raises(GraphValidationError, match="指向自身"):
        engine.graph.create_edge(
            project_id=project_id,
            stable_key="self",
            source_node_id=str(events[0]["id"]),
            target_node_id=str(events[0]["id"]),
            kind="causes",
        )
    world = engine.graph.create_node(
        project_id=project_id,
        stable_key="location:port",
        kind="location",
        label="雾港",
    )
    with pytest.raises(GraphValidationError, match="只能连接事件"):
        engine.graph.create_edge(
            project_id=project_id,
            stable_key="bad-cause",
            source_node_id=str(events[0]["id"]),
            target_node_id=str(world["id"]),
            kind="causes",
        )
    with pytest.raises(GraphValidationError, match="端点"):
        engine.graph.create_edge(
            project_id=project_id,
            stable_key="missing-endpoint",
            source_node_id=str(events[0]["id"]),
            target_node_id="missing",
            kind="relationship",
        )


def test_graph_snapshot_only_contains_approved_revisions(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    approved = engine.graph.create_node(
        project_id=project_id,
        stable_key="location:port",
        kind="location",
        label="雾港",
    )
    engine.graph.create_node(
        project_id=project_id,
        stable_key="location:draft",
        kind="location",
        label="候选地点",
        author="model",
        approved=False,
    )
    snapshot = engine.graph.snapshot(project_id)
    assert approved["revision_id"] in snapshot["node_revision_ids"]
    assert len(snapshot["node_revision_ids"]) == 1


def test_hundred_event_plan_projection(engine: NovelLoomEngine, project: dict[str, object]) -> None:
    project_id = str(project["id"])
    previous = None
    for index in range(100):
        current = engine.graph.create_node(
            project_id=project_id,
            stable_key=f"event:{index:03d}",
            kind="event",
            label=f"事件 {index + 1}",
        )
        if previous:
            engine.graph.create_edge(
                project_id=project_id,
                stable_key=f"precedes:{index - 1}:{index}",
                source_node_id=str(previous["id"]),
                target_node_id=str(current["id"]),
                kind="precedes",
            )
        previous = current
    graph = engine.graph.get_graph(project_id)
    assert len(graph["nodes"]) == 100
    assert len(graph["edges"]) == 99


def test_candidate_decisions_and_artifact_history(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    candidate = engine.graph.create_node(
        project_id=project_id,
        stable_key="item:compass",
        kind="item",
        label="失忆罗盘",
        author="model",
        approved=False,
    )
    rejected = engine.graph.decide_candidates(
        project_id=project_id,
        node_ids=[str(candidate["id"])],
        edge_ids=[],
        approve=False,
    )
    assert rejected["approved"] is False
    assert engine.graph.get_graph(project_id)["nodes"] == []
    regenerated = engine.graph.create_node(
        project_id=project_id,
        stable_key="item:compass",
        kind="item",
        label="潮汐罗盘",
        author="model",
        approved=False,
    )
    approved = engine.graph.decide_candidates(
        project_id=project_id,
        node_ids=[str(regenerated["id"])],
        edge_ids=[],
        approve=True,
    )
    assert approved["snapshot"]["version"] == 1
    artifact = engine.artifacts.save_artifact(
        project_id=project_id,
        stable_key="outline:1",
        kind="chapter_outline",
        title="初稿",
        document={},
        markdown="初稿",
    )
    engine.artifacts.save_artifact(
        project_id=project_id,
        stable_key="outline:1",
        kind="chapter_outline",
        title="二稿",
        document={},
        markdown="二稿",
    )
    history = engine.artifacts.get_artifact(str(artifact["id"]))
    assert [item["version"] for item in history["history"]] == [2, 1]
    rejected_artifact = engine.artifacts.decide_candidates([str(artifact["id"])], approve=False)[0]
    assert rejected_artifact["stale"] is True
    with pytest.raises(NotFound):
        engine.artifacts.get_artifact("missing")


def test_graph_and_artifact_rollback_create_new_versions(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    left = engine.graph.create_node(
        project_id=project_id,
        stable_key="character:left",
        kind="character",
        label="旧名",
    )
    right = engine.graph.create_node(
        project_id=project_id,
        stable_key="character:right",
        kind="character",
        label="右",
    )
    edge = engine.graph.create_edge(
        project_id=project_id,
        stable_key="relation:left:right",
        source_node_id=str(left["id"]),
        target_node_id=str(right["id"]),
        kind="relationship",
        label="相识",
    )
    engine.graph.update_node(str(left["id"]), label="新名", payload={})
    engine.graph.update_edge(str(edge["id"]), label="敌对", payload={})
    node_history = engine.graph.get_node(str(left["id"]))
    edge_history = engine.graph.get_edge(str(edge["id"]))
    node_rollback = engine.graph.rollback_node(str(left["id"]), node_history["history"][-1]["id"])
    edge_rollback = engine.graph.rollback_edge(str(edge["id"]), edge_history["history"][-1]["id"])
    assert node_rollback["version"] == 3 and node_rollback["label"] == "旧名"
    assert edge_rollback["version"] == 3 and edge_rollback["label"] == "相识"
    artifact = engine.artifacts.save_artifact(
        project_id=project_id,
        stable_key="prose:rollback",
        kind="chapter_prose",
        title="旧稿",
        document={"type": "doc"},
        markdown="旧稿",
        status="approved",
    )
    latest = engine.artifacts.save_artifact(
        project_id=project_id,
        stable_key="prose:rollback",
        kind="chapter_prose",
        title="新稿",
        document={"type": "doc"},
        markdown="新稿",
        status="approved",
    )
    rolled_back = engine.artifacts.rollback_artifact(
        str(artifact["id"]), str(artifact["revision_id"])
    )
    assert latest["version"] == 2
    assert rolled_back["version"] == 3 and rolled_back["markdown"] == "旧稿"


def test_ledger_rejects_missing_and_duplicate_resources(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    assert engine.projects.list_projects()[0]["id"] == project_id
    with pytest.raises(DomainError, match="key"):
        engine.projects.create_project(
            name="重复书籍",
            premise="测试",
            books=[
                {"key": "same", "type": "main", "title": "正本"},
                {
                    "key": "same",
                    "type": "biography",
                    "title": "传记",
                    "source_book": "same",
                },
            ],
        )
    with pytest.raises(NotFound):
        engine.graph.get_graph("missing")
    with pytest.raises(NotFound):
        engine.graph.get_node("missing")
    with pytest.raises(NotFound):
        engine.graph.get_edge("missing")
    with pytest.raises(NotFound):
        engine.graph.rollback_node("missing", "missing")
    with pytest.raises(NotFound):
        engine.graph.rollback_edge("missing", "missing")
    with pytest.raises(NotFound):
        engine.graph.update_node("missing", label="无", payload={})
    with pytest.raises(NotFound):
        engine.graph.update_edge("missing", label="无", payload={})

    left = engine.graph.create_node(
        project_id=project_id, stable_key="character:duplicate", kind="character", label="甲"
    )
    right = engine.graph.create_node(
        project_id=project_id, stable_key="character:right2", kind="character", label="乙"
    )
    with pytest.raises(DomainError, match="stable_key"):
        engine.graph.create_node(
            project_id=project_id,
            stable_key="character:duplicate",
            kind="character",
            label="重名",
        )
    engine.graph.create_edge(
        project_id=project_id,
        stable_key="relationship:duplicate",
        source_node_id=str(left["id"]),
        target_node_id=str(right["id"]),
        kind="relationship",
    )
    with pytest.raises(DomainError, match="stable_key"):
        engine.graph.create_edge(
            project_id=project_id,
            stable_key="relationship:duplicate",
            source_node_id=str(left["id"]),
            target_node_id=str(right["id"]),
            kind="relationship",
        )

    with pytest.raises(NotFound):
        engine.artifacts.save_artifact(
            project_id="missing",
            stable_key="missing",
            kind="chapter_outline",
            title="无",
            document={},
            markdown="",
        )
    with pytest.raises(NotFound):
        engine.artifacts.decide_candidates(["missing"], approve=True)
    with pytest.raises(NotFound):
        engine.artifacts.rollback_artifact("missing", "missing")


def test_rejected_artifact_candidate_restores_approved_revision(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    approved = engine.artifacts.save_artifact(
        project_id=project_id,
        stable_key="outline:restore",
        kind="chapter_outline",
        title="权威版",
        document={"value": 1},
        markdown="权威版",
        status="approved",
    )
    engine.artifacts.save_artifact(
        project_id=project_id,
        stable_key="outline:restore",
        kind="chapter_outline",
        title="候选版",
        document={"value": 2},
        markdown="候选版",
        status="draft",
    )
    restored = engine.artifacts.decide_candidates([str(approved["id"])], approve=False)[0]
    assert restored["version"] == 1
    assert restored["status"] == "approved"
    assert restored["markdown"] == "权威版"
