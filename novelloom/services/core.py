from __future__ import annotations

from typing import Any

import networkx as nx
from sqlalchemy import select

from ..domain import ArtifactKind, BookType, EdgeKind, RevisionStatus
from ..persistence.database import Database
from ..persistence.models import (
    Artifact,
    ArtifactRevision,
    Book,
    EdgeRevision,
    Job,
    NodeRevision,
    Project,
    StoryEdge,
    StoryNode,
)
from ..persistence.repositories import (
    ArtifactRepository,
    GraphRepository,
    ProjectRepository,
    RuntimeRepository,
)


class DomainError(RuntimeError):
    pass


class NotFound(DomainError):
    pass


class GraphValidationError(DomainError):
    pass


class BudgetExceeded(DomainError):
    pass


def queue_cascade(
    session: Any,
    project_id: str,
    source_type: str,
    source_id: str,
    reason: str,
) -> Job | None:
    """Mark the transitive artifact projection stale and enqueue one recompute job."""
    artifacts = ArtifactRepository(session).downstream(project_id, source_type, source_id)
    if not artifacts:
        return None
    structured: list[str] = []
    prose: list[str] = []
    for artifact in artifacts:
        artifact.stale = True
        artifact.stale_reason = reason
        if artifact.kind == ArtifactKind.CHAPTER_PROSE:
            prose.append(artifact.id)
        else:
            structured.append(artifact.id)
    return RuntimeRepository(session).create_job(
        project_id=project_id,
        kind="cascade_recompute",
        payload={
            "source_type": source_type,
            "source_id": source_id,
            "structured_artifact_ids": structured,
            "stale_prose_ids": prose,
        },
        estimated_tokens=max(0, len(structured) * 1_500),
    )


class ProjectService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_project(
        self,
        *,
        name: str,
        premise: str,
        books: list[dict[str, Any]],
        language: str = "zh-CN",
        token_budget: int = 1_000_000,
        cost_budget: float | None = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise DomainError("项目名称不能为空")
        if not premise.strip():
            raise DomainError("故事梗概不能为空")
        if sum(1 for book in books if book.get("type") == BookType.MAIN) != 1:
            raise DomainError("一个项目必须且只能包含一本正本")
        keys = [str(book.get("key", "")) for book in books]
        if any(not key for key in keys) or len(keys) != len(set(keys)):
            raise DomainError("书籍 key 必须存在且在项目内唯一")
        known: set[str] = set()
        for book in books:
            source = book.get("source_book")
            if book.get("type") != BookType.MAIN and source not in known:
                raise DomainError("伴生书 source_book 必须引用排在其前面的正本")
            known.add(book["key"])
        with self.database.session() as session:
            project = ProjectRepository(session).create(
                name=name.strip(),
                premise=premise.strip(),
                language=language,
                token_budget=token_budget,
                cost_budget=cost_budget,
                books=books,
            )
            return self._project_dict(project)

    def list_projects(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            return [self._project_dict(project) for project in ProjectRepository(session).list()]

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            project = ProjectRepository(session).get(project_id)
            if project is None:
                raise NotFound("项目不存在")
            books = list(
                session.scalars(
                    select(Book).where(Book.project_id == project_id).order_by(Book.order)
                )
            )
            result = self._project_dict(project)
            result["books"] = [
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
            return result

    @staticmethod
    def _project_dict(project: Project) -> dict[str, Any]:
        return {
            "id": project.id,
            "name": project.name,
            "premise": project.premise,
            "language": project.language,
            "token_budget": project.token_budget,
            "cost_budget": project.cost_budget,
            "tokens_used": project.tokens_used,
            "cost_used": project.cost_used,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
        }


class GraphService:
    """Versioned story graph with deterministic causal validation."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def get_graph(self, project_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise NotFound("项目不存在")
            repository = GraphRepository(session)
            nodes = []
            for node in repository.list_nodes(project_id):
                node_revision = repository.current_node_revision(node)
                if node_revision:
                    nodes.append(self._node_dict(node, node_revision))
            edges = []
            for edge in repository.list_edges(project_id):
                edge_revision = repository.current_edge_revision(edge)
                if edge_revision:
                    edges.append(self._edge_dict(edge, edge_revision))
            return {"project_id": project_id, "nodes": nodes, "edges": edges}

    def get_node(self, node_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            node = session.get(StoryNode, node_id)
            if node is None or node.deleted or not node.current_revision_id:
                raise NotFound("图谱节点不存在")
            current = session.get(NodeRevision, node.current_revision_id)
            if current is None:
                raise NotFound("图谱节点版本不存在")
            result = self._node_dict(node, current)
            revisions = session.scalars(
                select(NodeRevision)
                .where(NodeRevision.node_id == node_id)
                .order_by(NodeRevision.version.desc())
            )
            result["history"] = [
                {
                    "id": revision.id,
                    "version": revision.version,
                    "label": revision.label,
                    "payload": revision.payload,
                    "status": revision.status,
                    "author": revision.author,
                    "created_at": revision.created_at.isoformat(),
                }
                for revision in revisions
            ]
            return result

    def rollback_node(self, node_id: str, revision_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            revision = session.get(NodeRevision, revision_id)
            if revision is None or revision.node_id != node_id:
                raise NotFound("要回滚的节点版本不存在")
            label = revision.label
            payload = dict(revision.payload)
        return self.update_node(node_id, label=label, payload=payload, author="user", approved=True)

    def get_edge(self, edge_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            edge = session.get(StoryEdge, edge_id)
            if edge is None or edge.deleted or not edge.current_revision_id:
                raise NotFound("图谱关系不存在")
            current = session.get(EdgeRevision, edge.current_revision_id)
            if current is None:
                raise NotFound("图谱关系版本不存在")
            result = self._edge_dict(edge, current)
            revisions = session.scalars(
                select(EdgeRevision)
                .where(EdgeRevision.edge_id == edge_id)
                .order_by(EdgeRevision.version.desc())
            )
            result["history"] = [
                {
                    "id": revision.id,
                    "version": revision.version,
                    "label": revision.label,
                    "payload": revision.payload,
                    "status": revision.status,
                    "author": revision.author,
                    "created_at": revision.created_at.isoformat(),
                }
                for revision in revisions
            ]
            return result

    def rollback_edge(self, edge_id: str, revision_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            revision = session.get(EdgeRevision, revision_id)
            if revision is None or revision.edge_id != edge_id:
                raise NotFound("要回滚的关系版本不存在")
            label = revision.label
            payload = dict(revision.payload)
        return self.update_edge(edge_id, label=label, payload=payload, author="user", approved=True)

    def create_node(
        self,
        *,
        project_id: str,
        stable_key: str,
        kind: str,
        label: str,
        payload: dict[str, Any] | None = None,
        author: str = "user",
        approved: bool | None = None,
    ) -> dict[str, Any]:
        status = (
            RevisionStatus.APPROVED
            if (approved if approved is not None else author == "user")
            else RevisionStatus.DRAFT
        )
        with self.database.session() as session:
            self._require_project(session, project_id)
            repository = GraphRepository(session)
            try:
                node = repository.create_node(
                    project_id=project_id,
                    stable_key=stable_key,
                    kind=kind,
                    label=label,
                    payload=payload or {},
                    status=status,
                    author=author,
                )
            except ValueError as error:
                raise DomainError(str(error)) from error
            revision = repository.current_node_revision(node)
            assert revision is not None
            cascade_job = None
            if status == RevisionStatus.APPROVED:
                cascade_job = self._cascade(
                    session, project_id, "node", node.id, f"节点 {label} 已更新"
                )
            result = self._node_dict(node, revision)
            result["cascade_job_id"] = cascade_job.id if cascade_job else None
            return result

    def update_node(
        self,
        node_id: str,
        *,
        label: str,
        payload: dict[str, Any],
        author: str = "user",
        approved: bool | None = None,
    ) -> dict[str, Any]:
        status = (
            RevisionStatus.APPROVED
            if (approved if approved is not None else author == "user")
            else RevisionStatus.DRAFT
        )
        with self.database.session() as session:
            node = session.get(StoryNode, node_id)
            if node is None or node.deleted:
                raise NotFound("图谱节点不存在")
            repository = GraphRepository(session)
            previous = repository.current_node_revision(node)
            if previous and status == RevisionStatus.APPROVED:
                previous.status = RevisionStatus.SUPERSEDED
            revision = repository.add_node_revision(
                node, label=label, payload=payload, status=status, author=author
            )
            cascade_job = None
            if status == RevisionStatus.APPROVED:
                cascade_job = self._cascade(
                    session, node.project_id, "node", node.id, f"节点 {label} 已更新"
                )
            result = self._node_dict(node, revision)
            result["cascade_job_id"] = cascade_job.id if cascade_job else None
            return result

    def create_edge(
        self,
        *,
        project_id: str,
        stable_key: str,
        source_node_id: str,
        target_node_id: str,
        kind: str,
        label: str = "",
        payload: dict[str, Any] | None = None,
        author: str = "user",
        approved: bool | None = None,
    ) -> dict[str, Any]:
        if source_node_id == target_node_id and kind in (EdgeKind.CAUSES, EdgeKind.PRECEDES):
            raise GraphValidationError("事件不能因果或时序指向自身")
        status = (
            RevisionStatus.APPROVED
            if (approved if approved is not None else author == "user")
            else RevisionStatus.DRAFT
        )
        with self.database.session() as session:
            self._require_project(session, project_id)
            source = session.get(StoryNode, source_node_id)
            target = session.get(StoryNode, target_node_id)
            if (
                not source
                or not target
                or source.project_id != project_id
                or target.project_id != project_id
            ):
                raise GraphValidationError("边的端点必须是当前项目中的有效节点")
            repository = GraphRepository(session)
            try:
                edge = repository.create_edge(
                    project_id=project_id,
                    stable_key=stable_key,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    kind=kind,
                    label=label,
                    payload=payload or {},
                    status=status,
                    author=author,
                )
            except ValueError as error:
                raise DomainError(str(error)) from error
            cascade_job = None
            if status == RevisionStatus.APPROVED:
                self._validate_causal_graph(repository, project_id)
                cascade_job = self._cascade(
                    session, project_id, "edge", edge.id, f"关系 {label or kind} 已更新"
                )
            revision = repository.current_edge_revision(edge)
            assert revision is not None
            result = self._edge_dict(edge, revision)
            result["cascade_job_id"] = cascade_job.id if cascade_job else None
            return result

    def update_edge(
        self,
        edge_id: str,
        *,
        label: str,
        payload: dict[str, Any],
        author: str = "user",
        approved: bool | None = None,
    ) -> dict[str, Any]:
        status = (
            RevisionStatus.APPROVED
            if (approved if approved is not None else author == "user")
            else RevisionStatus.DRAFT
        )
        with self.database.session() as session:
            edge = session.get(StoryEdge, edge_id)
            if edge is None or edge.deleted:
                raise NotFound("图谱关系不存在")
            repository = GraphRepository(session)
            previous = repository.current_edge_revision(edge)
            if previous and status == RevisionStatus.APPROVED:
                previous.status = RevisionStatus.SUPERSEDED
            revision = repository.add_edge_revision(
                edge, label=label, payload=payload, status=status, author=author
            )
            cascade_job = None
            if status == RevisionStatus.APPROVED:
                self._validate_causal_graph(repository, edge.project_id)
                cascade_job = self._cascade(
                    session, edge.project_id, "edge", edge.id, f"关系 {label or edge.kind} 已更新"
                )
            result = self._edge_dict(edge, revision)
            result["cascade_job_id"] = cascade_job.id if cascade_job else None
            return result

    def snapshot(self, project_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            self._require_project(session, project_id)
            snapshot = GraphRepository(session).create_snapshot(project_id)
            return {
                "id": snapshot.id,
                "project_id": snapshot.project_id,
                "version": snapshot.version,
                "node_revision_ids": snapshot.node_revision_ids,
                "edge_revision_ids": snapshot.edge_revision_ids,
                "approved_at": snapshot.approved_at.isoformat() if snapshot.approved_at else None,
            }

    def decide_candidates(
        self,
        *,
        project_id: str,
        node_ids: list[str],
        edge_ids: list[str],
        approve: bool,
        replace_event_graph: bool = False,
    ) -> dict[str, Any]:
        """Publish or reject model-created current revisions as a single atomic decision."""
        with self.database.session() as session:
            repository = GraphRepository(session)
            self._require_project(session, project_id)
            for node_id in node_ids:
                node = session.get(StoryNode, node_id)
                if node is None or node.project_id != project_id:
                    raise GraphValidationError("候选节点不属于当前项目")
                node_revision = repository.current_node_revision(node)
                if node_revision is None:
                    raise GraphValidationError("候选节点缺少版本")
                previous_node = session.scalar(
                    select(NodeRevision)
                    .where(
                        NodeRevision.node_id == node.id,
                        NodeRevision.id != node_revision.id,
                        NodeRevision.status == RevisionStatus.APPROVED,
                    )
                    .order_by(NodeRevision.version.desc())
                )
                if approve:
                    if previous_node:
                        previous_node.status = RevisionStatus.SUPERSEDED
                    node_revision.status = RevisionStatus.APPROVED
                else:
                    node_revision.status = RevisionStatus.REJECTED
                    if previous_node:
                        node.current_revision_id = previous_node.id
                    else:
                        node.deleted = True
            for edge_id in edge_ids:
                edge = session.get(StoryEdge, edge_id)
                if edge is None or edge.project_id != project_id:
                    raise GraphValidationError("候选关系不属于当前项目")
                edge_revision = repository.current_edge_revision(edge)
                if edge_revision is None:
                    raise GraphValidationError("候选关系缺少版本")
                previous_edge = session.scalar(
                    select(EdgeRevision)
                    .where(
                        EdgeRevision.edge_id == edge.id,
                        EdgeRevision.id != edge_revision.id,
                        EdgeRevision.status == RevisionStatus.APPROVED,
                    )
                    .order_by(EdgeRevision.version.desc())
                )
                if approve:
                    if previous_edge:
                        previous_edge.status = RevisionStatus.SUPERSEDED
                    edge_revision.status = RevisionStatus.APPROVED
                else:
                    edge_revision.status = RevisionStatus.REJECTED
                    if previous_edge:
                        edge.current_revision_id = previous_edge.id
                    else:
                        edge.deleted = True
            if not approve:
                return {"approved": False, "snapshot": None}
            if replace_event_graph:
                selected_nodes = set(node_ids)
                selected_edges = set(edge_ids)
                for node in repository.list_nodes(project_id):
                    if node.kind == "event" and node.id not in selected_nodes:
                        node.deleted = True
                for edge in repository.list_edges(project_id):
                    source = session.get(StoryNode, edge.source_node_id)
                    target = session.get(StoryNode, edge.target_node_id)
                    touches_event = bool(
                        (source and source.kind == "event") or (target and target.kind == "event")
                    )
                    if touches_event and edge.id not in selected_edges:
                        edge.deleted = True
            self._validate_causal_graph(repository, project_id)
            snapshot = repository.create_snapshot(project_id)
            return {
                "approved": True,
                "snapshot": {
                    "id": snapshot.id,
                    "version": snapshot.version,
                    "approved_at": snapshot.approved_at.isoformat()
                    if snapshot.approved_at
                    else None,
                },
            }

    def _cascade(
        self, session: Any, project_id: str, source_type: str, source_id: str, reason: str
    ) -> Job | None:
        return queue_cascade(session, project_id, source_type, source_id, reason)

    @staticmethod
    def _validate_causal_graph(repository: GraphRepository, project_id: str) -> None:
        graph: nx.DiGraph[Any] = nx.DiGraph()
        nodes = repository.list_nodes(project_id)
        event_ids = {node.id for node in nodes if node.kind == "event"}
        graph.add_nodes_from(event_ids)
        for edge in repository.list_edges(project_id):
            if edge.kind in (EdgeKind.CAUSES, EdgeKind.PRECEDES):
                if edge.source_node_id not in event_ids or edge.target_node_id not in event_ids:
                    raise GraphValidationError("因果和时序边只能连接事件节点")
                graph.add_edge(edge.source_node_id, edge.target_node_id)
        if not nx.is_directed_acyclic_graph(graph):
            cycle = nx.find_cycle(graph)
            raise GraphValidationError(f"事件因果图存在循环: {cycle}")

    @staticmethod
    def _require_project(session: Any, project_id: str) -> Project:
        project: Project | None = session.get(Project, project_id)
        if project is None:
            raise NotFound("项目不存在")
        return project

    @staticmethod
    def _node_dict(node: StoryNode, revision: NodeRevision) -> dict[str, Any]:
        return {
            "id": node.id,
            "project_id": node.project_id,
            "stable_key": node.stable_key,
            "kind": node.kind,
            "revision_id": revision.id,
            "version": revision.version,
            "label": revision.label,
            "payload": revision.payload,
            "status": revision.status,
            "author": revision.author,
            "updated_at": node.updated_at.isoformat(),
        }

    @staticmethod
    def _edge_dict(edge: StoryEdge, revision: EdgeRevision) -> dict[str, Any]:
        return {
            "id": edge.id,
            "project_id": edge.project_id,
            "stable_key": edge.stable_key,
            "source": edge.source_node_id,
            "target": edge.target_node_id,
            "kind": edge.kind,
            "revision_id": revision.id,
            "version": revision.version,
            "label": revision.label,
            "payload": revision.payload,
            "status": revision.status,
            "author": revision.author,
            "updated_at": edge.updated_at.isoformat(),
        }


class ArtifactService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_artifact(
        self,
        *,
        project_id: str,
        stable_key: str,
        kind: str,
        title: str,
        document: dict[str, Any],
        markdown: str,
        book_id: str | None = None,
        order: int = 0,
        status: str = "draft",
        author: str = "model",
        dependencies: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        with self.database.session() as session:
            if session.get(Project, project_id) is None:
                raise NotFound("项目不存在")
            repository = ArtifactRepository(session)
            artifact = repository.get_or_create(
                project_id=project_id,
                stable_key=stable_key,
                kind=kind,
                book_id=book_id,
                order=order,
            )
            previous = (
                session.get(ArtifactRevision, artifact.current_revision_id)
                if artifact.current_revision_id
                else None
            )
            if (
                previous
                and previous.status == RevisionStatus.APPROVED
                and status == RevisionStatus.APPROVED
            ):
                previous.status = RevisionStatus.SUPERSEDED
            revision = repository.add_revision(
                artifact,
                title=title,
                document=document,
                markdown=markdown,
                status=status,
                author=author,
            )
            repository.add_dependencies(
                project_id=project_id,
                target_artifact_id=artifact.id,
                sources=dependencies or [],
            )
            cascade_job = None
            if author == "user" and status == RevisionStatus.APPROVED:
                cascade_job = queue_cascade(
                    session,
                    project_id,
                    "artifact",
                    artifact.id,
                    f"内容 {title} 已更新",
                )
            result = self._artifact_dict(artifact, revision)
            result["cascade_job_id"] = cascade_job.id if cascade_job else None
            return result

    def list_artifacts(
        self, project_id: str, *, book_id: str | None = None, kind: str | None = None
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            stmt = select(Artifact).where(Artifact.project_id == project_id)
            if book_id:
                stmt = stmt.where(Artifact.book_id == book_id)
            if kind:
                stmt = stmt.where(Artifact.kind == kind)
            artifacts = list(session.scalars(stmt.order_by(Artifact.order, Artifact.created_at)))
            result = []
            for artifact in artifacts:
                revision = session.get(ArtifactRevision, artifact.current_revision_id)
                if revision:
                    result.append(self._artifact_dict(artifact, revision))
            return result

    def decide_candidates(self, artifact_ids: list[str], *, approve: bool) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with self.database.session() as session:
            for artifact_id in artifact_ids:
                artifact = session.get(Artifact, artifact_id)
                if artifact is None or not artifact.current_revision_id:
                    raise NotFound("候选内容不存在")
                revision = session.get(ArtifactRevision, artifact.current_revision_id)
                if revision is None:
                    raise NotFound("候选内容版本不存在")
                previous = session.scalar(
                    select(ArtifactRevision)
                    .where(
                        ArtifactRevision.artifact_id == artifact.id,
                        ArtifactRevision.id != revision.id,
                        ArtifactRevision.status == RevisionStatus.APPROVED,
                    )
                    .order_by(ArtifactRevision.version.desc())
                )
                if approve:
                    if previous:
                        previous.status = RevisionStatus.SUPERSEDED
                    revision.status = RevisionStatus.APPROVED
                    artifact.stale = False
                    artifact.stale_reason = ""
                    selected = revision
                else:
                    revision.status = RevisionStatus.REJECTED
                    if previous:
                        artifact.current_revision_id = previous.id
                        artifact.stale = False
                        artifact.stale_reason = ""
                        selected = previous
                    else:
                        artifact.stale = True
                        artifact.stale_reason = "候选内容被驳回"
                        selected = revision
                results.append(self._artifact_dict(artifact, selected))
        return results

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            artifact = session.get(Artifact, artifact_id)
            if artifact is None or not artifact.current_revision_id:
                raise NotFound("内容不存在")
            revision = session.get(ArtifactRevision, artifact.current_revision_id)
            if revision is None:
                raise NotFound("内容版本不存在")
            result = self._artifact_dict(artifact, revision)
            history = list(
                session.scalars(
                    select(ArtifactRevision)
                    .where(ArtifactRevision.artifact_id == artifact_id)
                    .order_by(ArtifactRevision.version.desc())
                )
            )
            result["history"] = [
                {
                    "id": item.id,
                    "version": item.version,
                    "title": item.title,
                    "markdown": item.markdown,
                    "document": item.document,
                    "status": item.status,
                    "author": item.author,
                    "created_at": item.created_at.isoformat(),
                }
                for item in history
            ]
            return result

    def rollback_artifact(self, artifact_id: str, revision_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            artifact = session.get(Artifact, artifact_id)
            revision = session.get(ArtifactRevision, revision_id)
            if artifact is None or revision is None or revision.artifact_id != artifact_id:
                raise NotFound("要回滚的内容版本不存在")
            current = (
                session.get(ArtifactRevision, artifact.current_revision_id)
                if artifact.current_revision_id
                else None
            )
            if current and current.status == RevisionStatus.APPROVED:
                current.status = RevisionStatus.SUPERSEDED
            created = ArtifactRepository(session).add_revision(
                artifact,
                title=revision.title,
                document=dict(revision.document),
                markdown=revision.markdown,
                status=RevisionStatus.APPROVED,
                author="user",
            )
            cascade_job = queue_cascade(
                session,
                artifact.project_id,
                "artifact",
                artifact.id,
                f"内容 {created.title} 已回滚",
            )
            result = self._artifact_dict(artifact, created)
            result["cascade_job_id"] = cascade_job.id if cascade_job else None
            return result

    @staticmethod
    def _artifact_dict(artifact: Artifact, revision: ArtifactRevision) -> dict[str, Any]:
        return {
            "id": artifact.id,
            "project_id": artifact.project_id,
            "book_id": artifact.book_id,
            "stable_key": artifact.stable_key,
            "kind": artifact.kind,
            "order": artifact.order,
            "stale": artifact.stale,
            "stale_reason": artifact.stale_reason,
            "revision_id": revision.id,
            "version": revision.version,
            "title": revision.title,
            "document": revision.document,
            "markdown": revision.markdown,
            "status": revision.status,
            "author": revision.author,
        }
