from __future__ import annotations

import json
from typing import Any, Literal

import networkx as nx
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..domain import (
    ArtifactKind,
    DecisionStatus,
    EdgeKind,
    ModelRole,
    RevisionStatus,
    RunStatus,
)
from ..persistence.database import Database
from ..persistence.models import Artifact, Book, Decision, Project, WorkflowRun, utcnow
from ..persistence.repositories import RuntimeRepository
from ..providers import ModelMessage, ModelRequest
from .core import ArtifactService, DomainError, GraphService, GraphValidationError, NotFound
from .prompts import PromptService
from .providers import ProviderService


class ProposedNode(BaseModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]+$")
    kind: Literal["character", "organization", "location", "item", "concept", "world_rule"]
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ProposedEdge(BaseModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]+$")
    source: str
    target: str
    kind: Literal["relationship", "located_at", "contradicts"] = "relationship"
    label: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class WorldProposal(BaseModel):
    summary: str
    nodes: list[ProposedNode]
    edges: list[ProposedEdge] = Field(default_factory=list)


class ProposedEvent(BaseModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_.:-]+$")
    label: str
    summary: str
    phase: str
    order: int = Field(ge=1)
    participant_keys: list[str] = Field(default_factory=list)
    location_key: str | None = None


class ProposedEventEdge(BaseModel):
    source: str
    target: str
    kind: Literal["causes", "precedes"] = "causes"
    label: str = ""


class EventProposal(BaseModel):
    overall_arc: str
    events: list[ProposedEvent]
    edges: list[ProposedEventEdge]


class PlannedChapter(BaseModel):
    book_key: str
    chapter_no: int = Field(ge=1)
    title: str
    event_keys: list[str]
    viewpoint: str = ""
    scene: str = ""
    plot_points: list[str] = Field(default_factory=list)
    conflict: str = ""
    ending_hook: str = ""
    target_words: int = Field(default=2500, ge=500)


class MultiBookPlan(BaseModel):
    chapters: list[PlannedChapter]


WORLD_SYSTEM = """你是小说世界架构师。只提出可验证、可编辑的结构化世界事实。
角色、地点、组织、物品、概念和世界规则必须使用稳定英文 key。关系不能引用未声明节点。
输出必须符合 JSON Schema，不要输出正文。"""

EVENT_SYSTEM = """你是因果剧情推演器。基于已批准世界事实生成完整事件 DAG。
事件必须引用已有角色或地点 key；causes/precedes 边不能形成循环；事件顺序从 1 连续递增。
输出是结构化剧情推演，不要撰写章节正文。"""

BOOK_PLAN_SYSTEM = """你是多书同步规划师。把同一批共享事件映射为一个正本和多本伴生书的章节视角。
同一事实的结果和时间不得冲突。每个章节必须引用 event_keys。"""


class ReasoningService:
    def __init__(
        self,
        database: Database,
        provider_service: ProviderService,
        *,
        graph_service: GraphService | None = None,
        artifact_service: ArtifactService | None = None,
        prompt_service: PromptService | None = None,
    ) -> None:
        self.database = database
        self.providers = provider_service
        self.graph = graph_service or GraphService(database)
        self.artifacts = artifact_service or ArtifactService(database)
        self.prompts = prompt_service or PromptService(database)

    async def propose_world(self, project_id: str, *, run_id: str | None = None) -> dict[str, Any]:
        project = self._project(project_id)
        system_prompt, user_prompt = self.prompts.resolve(
            project_id,
            "world_builder",
            default_system=WORLD_SYSTEM,
            default_user="作品语言: {language}\n故事梗概:\n{premise}",
            variables=project,
        )
        response = await self.providers.generate(
            project_id=project_id,
            role=ModelRole.WORLD_BUILDER,
            run_id=run_id,
            request=ModelRequest(
                messages=[
                    ModelMessage(role="system", content=system_prompt),
                    ModelMessage(role="user", content=user_prompt),
                ],
                response_schema=WorldProposal.model_json_schema(),
                temperature=0.5,
                max_output_tokens=6000,
            ),
        )
        if response.structured is None:
            raise DomainError("世界构建模型没有返回合法结构化结果")
        proposal = WorldProposal.model_validate(response.structured)
        self._validate_world(proposal)
        node_ids: list[str] = []
        edge_ids: list[str] = []
        node_map: dict[str, str] = {}
        for proposed_node in proposal.nodes:
            node = self.graph.create_node(
                project_id=project_id,
                stable_key=proposed_node.key,
                kind=proposed_node.kind,
                label=proposed_node.label,
                payload=proposed_node.payload,
                author="model",
                approved=False,
            )
            node_ids.append(node["id"])
            node_map[proposed_node.key] = node["id"]
        for proposed_edge in proposal.edges:
            edge = self.graph.create_edge(
                project_id=project_id,
                stable_key=proposed_edge.key,
                source_node_id=node_map[proposed_edge.source],
                target_node_id=node_map[proposed_edge.target],
                kind=proposed_edge.kind,
                label=proposed_edge.label,
                payload=proposed_edge.payload,
                author="model",
                approved=False,
            )
            edge_ids.append(edge["id"])
        world_artifact = self.artifacts.save_artifact(
            project_id=project_id,
            stable_key="world-bible",
            kind=ArtifactKind.WORLD_BIBLE,
            title="世界圣经",
            document={"type": "doc", "content": [{"type": "paragraph", "text": proposal.summary}]},
            markdown=proposal.summary,
            dependencies=[("node", node_id) for node_id in node_ids]
            + [("edge", edge_id) for edge_id in edge_ids],
        )
        decision = self._create_decision(
            project_id,
            "world_final",
            {"node_ids": node_ids, "edge_ids": edge_ids, "artifact_id": world_artifact["id"]},
            run_id,
        )
        return {"decision_id": decision.id, "node_ids": node_ids, "edge_ids": edge_ids}

    async def propose_events(self, project_id: str, *, run_id: str | None = None) -> dict[str, Any]:
        graph = self.graph.get_graph(project_id)
        approved_nodes = [
            node
            for node in graph["nodes"]
            if node["status"] == "approved" and node["kind"] != "event"
        ]
        approved_edges = [edge for edge in graph["edges"] if edge["status"] == "approved"]
        if not approved_nodes:
            raise DomainError("请先批准世界图谱")
        context = json.dumps(
            {"nodes": approved_nodes, "edges": approved_edges}, ensure_ascii=False, default=str
        )
        system_prompt, user_prompt = self.prompts.resolve(
            project_id,
            "plot_reasoner",
            default_system=EVENT_SYSTEM,
            default_user="已批准世界图谱:\n{context}",
            variables={"context": context},
        )
        response = await self.providers.generate(
            project_id=project_id,
            role=ModelRole.PLOT_REASONER,
            run_id=run_id,
            request=ModelRequest(
                messages=[
                    ModelMessage(role="system", content=system_prompt),
                    ModelMessage(role="user", content=user_prompt),
                ],
                response_schema=EventProposal.model_json_schema(),
                temperature=0.55,
                max_output_tokens=8000,
            ),
        )
        if response.structured is None:
            raise DomainError("事件推演模型没有返回合法结构化结果")
        proposal = EventProposal.model_validate(response.structured)
        self._validate_events(proposal, {node["stable_key"] for node in approved_nodes})
        node_ids: list[str] = []
        edge_ids: list[str] = []
        key_to_id = {node["stable_key"]: node["id"] for node in approved_nodes}
        for event in sorted(proposal.events, key=lambda value: value.order):
            node = self.graph.create_node(
                project_id=project_id,
                stable_key=event.key,
                kind="event",
                label=event.label,
                payload=event.model_dump(exclude={"key", "label"}),
                author="model",
                approved=False,
            )
            node_ids.append(node["id"])
            key_to_id[event.key] = node["id"]
        for event in proposal.events:
            for participant in event.participant_keys:
                edge = self.graph.create_edge(
                    project_id=project_id,
                    stable_key=f"participates:{event.key}:{participant}",
                    source_node_id=key_to_id[event.key],
                    target_node_id=key_to_id[participant],
                    kind=EdgeKind.PARTICIPATES,
                    label="参与",
                    author="model",
                    approved=False,
                )
                edge_ids.append(edge["id"])
            if event.location_key:
                edge = self.graph.create_edge(
                    project_id=project_id,
                    stable_key=f"located:{event.key}:{event.location_key}",
                    source_node_id=key_to_id[event.key],
                    target_node_id=key_to_id[event.location_key],
                    kind=EdgeKind.LOCATED_AT,
                    label="发生于",
                    author="model",
                    approved=False,
                )
                edge_ids.append(edge["id"])
        for index, link in enumerate(proposal.edges):
            edge = self.graph.create_edge(
                project_id=project_id,
                stable_key=f"{link.kind}:{link.source}:{link.target}:{index}",
                source_node_id=key_to_id[link.source],
                target_node_id=key_to_id[link.target],
                kind=link.kind,
                label=link.label,
                author="model",
                approved=False,
            )
            edge_ids.append(edge["id"])
        artifact = self.artifacts.save_artifact(
            project_id=project_id,
            stable_key="event-plan",
            kind=ArtifactKind.EVENT_PLAN,
            title="事件总纲",
            document={"overall_arc": proposal.overall_arc},
            markdown=proposal.overall_arc,
            dependencies=[("node", node["id"]) for node in approved_nodes]
            + [("edge", edge["id"]) for edge in approved_edges]
            + [("node", node_id) for node_id in node_ids]
            + [("edge", edge_id) for edge_id in edge_ids],
        )
        decision = self._create_decision(
            project_id,
            "event_final",
            {"node_ids": node_ids, "edge_ids": edge_ids, "artifact_id": artifact["id"]},
            run_id,
        )
        return {"decision_id": decision.id, "node_ids": node_ids, "edge_ids": edge_ids}

    async def plan_books(self, project_id: str, *, run_id: str | None = None) -> dict[str, Any]:
        project = self._project(project_id)
        graph = self.graph.get_graph(project_id)
        events = [
            node
            for node in graph["nodes"]
            if node["kind"] == "event" and node["status"] == "approved"
        ]
        if not events:
            raise DomainError("请先批准事件图")
        books = self._books(project_id)
        request_context = {"project": project, "books": books, "events": events}
        serialized_context = json.dumps(request_context, ensure_ascii=False, default=str)
        system_prompt, user_prompt = self.prompts.resolve(
            project_id,
            "chapter_planner",
            default_system=BOOK_PLAN_SYSTEM,
            default_user="{context}",
            variables={"context": serialized_context},
        )
        response = await self.providers.generate(
            project_id=project_id,
            role=ModelRole.CHAPTER_PLANNER,
            run_id=run_id,
            request=ModelRequest(
                messages=[
                    ModelMessage(role="system", content=system_prompt),
                    ModelMessage(role="user", content=user_prompt),
                ],
                response_schema=MultiBookPlan.model_json_schema(),
                temperature=0.5,
                max_output_tokens=10_000,
            ),
        )
        if response.structured is None:
            raise DomainError("章节规划模型没有返回合法结构化结果")
        plan = MultiBookPlan.model_validate(response.structured)
        book_map = {book["key"]: book for book in books}
        event_map = {event["stable_key"]: event for event in events}
        with self.database.session() as session:
            event_plan_id = session.scalar(
                select(Artifact.id).where(
                    Artifact.project_id == project_id,
                    Artifact.stable_key == "event-plan",
                )
            )
        created = []
        seen: set[tuple[str, int]] = set()
        for chapter in sorted(
            plan.chapters, key=lambda item: (book_map[item.book_key]["order"], item.chapter_no)
        ):
            if chapter.book_key not in book_map:
                raise GraphValidationError(f"章节引用未知书籍: {chapter.book_key}")
            if (chapter.book_key, chapter.chapter_no) in seen:
                raise GraphValidationError("同一本书存在重复章节号")
            missing = set(chapter.event_keys) - set(event_map)
            if missing:
                raise GraphValidationError(f"章节引用未知事件: {sorted(missing)}")
            seen.add((chapter.book_key, chapter.chapter_no))
            book = book_map[chapter.book_key]
            created.append(
                self.artifacts.save_artifact(
                    project_id=project_id,
                    book_id=book["id"],
                    stable_key=f"{chapter.book_key}:chapter:{chapter.chapter_no}:outline",
                    kind=ArtifactKind.CHAPTER_OUTLINE,
                    order=chapter.chapter_no,
                    title=chapter.title,
                    document=chapter.model_dump(),
                    markdown=self._outline_markdown(chapter),
                    dependencies=[("node", event_map[key]["id"]) for key in chapter.event_keys]
                    + ([("artifact", event_plan_id)] if event_plan_id else []),
                )
            )
        decision = self._create_decision(
            project_id,
            "outline_final",
            {"artifact_ids": [artifact["id"] for artifact in created]},
            run_id,
        )
        return {"decision_id": decision.id, "artifacts": created}

    def refresh_event_plan(self, project_id: str) -> dict[str, Any]:
        """Rebuild the editable event-plan projection from approved graph facts."""
        graph = self.graph.get_graph(project_id)
        events = sorted(
            (
                node
                for node in graph["nodes"]
                if node["kind"] == "event" and node["status"] == RevisionStatus.APPROVED
            ),
            key=lambda node: int(node["payload"].get("order", 0)),
        )
        if not events:
            raise DomainError("请先批准事件图")
        event_ids = {event["id"] for event in events}
        event_edges = [
            edge
            for edge in graph["edges"]
            if edge["status"] == RevisionStatus.APPROVED
            and (edge["source"] in event_ids or edge["target"] in event_ids)
        ]
        lines = [f"- {event['payload'].get('order', '?')}. {event['label']}" for event in events]
        dependencies = [("node", event["id"]) for event in events] + [
            ("edge", edge["id"]) for edge in event_edges
        ]
        return self.artifacts.save_artifact(
            project_id=project_id,
            stable_key="event-plan",
            kind=ArtifactKind.EVENT_PLAN,
            title="事件总纲",
            document={"events": events, "edges": event_edges},
            markdown="# 事件总纲\n\n" + "\n".join(lines),
            status=RevisionStatus.APPROVED,
            author="system",
            dependencies=dependencies,
        )

    def decide(self, decision_id: str, *, approve: bool, note: str = "") -> dict[str, Any]:
        with self.database.session() as session:
            decision = session.get(Decision, decision_id)
            if decision is None:
                raise NotFound("人工决策不存在")
            if decision.status != DecisionStatus.PENDING:
                raise DomainError("该人工门已经处理")
            decision.status = DecisionStatus.APPROVED if approve else DecisionStatus.REJECTED
            decision.note = note
            decision.decided_at = utcnow()
            payload = dict(decision.payload)
            project_id = decision.project_id
            run_id = decision.run_id
        graph_result = None
        if payload.get("node_ids") or payload.get("edge_ids"):
            graph_result = self.graph.decide_candidates(
                project_id=project_id,
                node_ids=payload.get("node_ids", []),
                edge_ids=payload.get("edge_ids", []),
                approve=approve,
                replace_event_graph=decision.gate == "event_final",
            )
        artifact_result = None
        artifact_ids = list(payload.get("artifact_ids", []))
        if payload.get("artifact_id"):
            artifact_ids.append(payload["artifact_id"])
        if artifact_ids:
            artifact_result = self.artifacts.decide_candidates(artifact_ids, approve=approve)
        if run_id:
            with self.database.session() as session:
                run = session.get(WorkflowRun, run_id)
                if run:
                    run.status = RunStatus.RUNNING if approve else RunStatus.PAUSED
        return {
            "decision_id": decision_id,
            "approved": approve,
            "graph": graph_result,
            "artifacts": artifact_result,
            "cascade_job_id": payload.get("cascade_job_id"),
            "gate": decision.gate,
        }

    def _create_decision(
        self, project_id: str, gate: str, payload: dict[str, Any], run_id: str | None
    ) -> Decision:
        with self.database.session() as session:
            decision = RuntimeRepository(session).create_decision(
                project_id=project_id, gate=gate, payload=payload, run_id=run_id
            )
            if run_id:
                run = session.get(WorkflowRun, run_id)
                if run:
                    run.status = RunStatus.WAITING_DECISION
                    run.current_step = gate
            return decision

    def _project(self, project_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise NotFound("项目不存在")
            return {
                "id": project.id,
                "name": project.name,
                "premise": project.premise,
                "language": project.language,
            }

    def _books(self, project_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            books = session.scalars(
                select(Book).where(Book.project_id == project_id).order_by(Book.order)
            )
            return [
                {
                    "id": book.id,
                    "key": book.key,
                    "type": book.type,
                    "title": book.title,
                    "perspective_node_id": book.perspective_node_id,
                    "source_book_id": book.source_book_id,
                    "order": book.order,
                }
                for book in books
            ]

    @staticmethod
    def _validate_world(proposal: WorldProposal) -> None:
        keys = [node.key for node in proposal.nodes]
        if len(keys) != len(set(keys)):
            raise GraphValidationError("世界图谱包含重复节点 key")
        known = set(keys)
        for edge in proposal.edges:
            if edge.source not in known or edge.target not in known:
                raise GraphValidationError(f"关系 {edge.key} 引用了未知节点")

    @staticmethod
    def _validate_events(proposal: EventProposal, world_keys: set[str]) -> None:
        event_keys = [event.key for event in proposal.events]
        if len(event_keys) != len(set(event_keys)):
            raise GraphValidationError("事件图包含重复事件 key")
        known_events = set(event_keys)
        orders = sorted(event.order for event in proposal.events)
        if orders != list(range(1, len(orders) + 1)):
            raise GraphValidationError("事件 order 必须从 1 连续递增")
        graph: nx.DiGraph[str] = nx.DiGraph()
        graph.add_nodes_from(event_keys)
        for event in proposal.events:
            if set(event.participant_keys) - world_keys:
                raise GraphValidationError(f"事件 {event.key} 引用了未知参与者")
            if event.location_key and event.location_key not in world_keys:
                raise GraphValidationError(f"事件 {event.key} 引用了未知地点")
        for edge in proposal.edges:
            if edge.source not in known_events or edge.target not in known_events:
                raise GraphValidationError("因果边引用未知事件")
            graph.add_edge(edge.source, edge.target)
        if not nx.is_directed_acyclic_graph(graph):
            raise GraphValidationError("模型生成的事件因果图存在循环")

    @staticmethod
    def _outline_markdown(chapter: PlannedChapter) -> str:
        points = "\n".join(f"- {point}" for point in chapter.plot_points)
        return (
            f"# {chapter.title}\n\n"
            f"视角：{chapter.viewpoint}\n\n场景：{chapter.scene}\n\n"
            f"事件：{', '.join(chapter.event_keys)}\n\n{points}\n\n"
            f"冲突：{chapter.conflict}\n\n章末钩子：{chapter.ending_hook}"
        )
