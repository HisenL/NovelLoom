from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Artifact,
    ArtifactDependency,
    ArtifactRevision,
    Book,
    Decision,
    EdgeRevision,
    Job,
    NodeRevision,
    Project,
    StoryEdge,
    StoryNode,
    StorySnapshot,
    UsageRecord,
    WorkflowRun,
    utcnow,
)


def new_id() -> str:
    return str(uuid4())


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        name: str,
        premise: str,
        language: str,
        token_budget: int,
        cost_budget: float | None,
        books: list[dict[str, Any]],
    ) -> Project:
        project = Project(
            id=new_id(),
            name=name,
            premise=premise,
            language=language,
            token_budget=token_budget,
            cost_budget=cost_budget,
        )
        self.session.add(project)
        self.session.flush()
        book_by_key: dict[str, Book] = {}
        for index, spec in enumerate(books):
            source_key = spec.get("source_book")
            book = Book(
                id=new_id(),
                project_id=project.id,
                key=spec["key"],
                type=spec["type"],
                title=spec["title"],
                perspective_node_id=spec.get("perspective_node_id"),
                source_book_id=book_by_key[source_key].id if source_key in book_by_key else None,
                order=index,
            )
            self.session.add(book)
            book_by_key[book.key] = book
        self.session.flush()
        return project

    def get(self, project_id: str) -> Project | None:
        return self.session.get(Project, project_id)

    def list(self) -> list[Project]:
        return list(self.session.scalars(select(Project).order_by(Project.updated_at.desc())))


class GraphRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_nodes(self, project_id: str, *, include_deleted: bool = False) -> list[StoryNode]:
        stmt = select(StoryNode).where(StoryNode.project_id == project_id)
        if not include_deleted:
            stmt = stmt.where(StoryNode.deleted.is_(False))
        return list(self.session.scalars(stmt.order_by(StoryNode.created_at.asc())))

    def list_edges(self, project_id: str, *, include_deleted: bool = False) -> list[StoryEdge]:
        stmt = select(StoryEdge).where(StoryEdge.project_id == project_id)
        if not include_deleted:
            stmt = stmt.where(StoryEdge.deleted.is_(False))
        return list(self.session.scalars(stmt.order_by(StoryEdge.created_at.asc())))

    def current_node_revision(self, node: StoryNode) -> NodeRevision | None:
        return (
            self.session.get(NodeRevision, node.current_revision_id)
            if node.current_revision_id
            else None
        )

    def current_edge_revision(self, edge: StoryEdge) -> EdgeRevision | None:
        return (
            self.session.get(EdgeRevision, edge.current_revision_id)
            if edge.current_revision_id
            else None
        )

    def create_node(
        self,
        *,
        project_id: str,
        stable_key: str,
        kind: str,
        label: str,
        payload: dict[str, Any],
        status: str,
        author: str,
    ) -> StoryNode:
        existing = self.session.scalar(
            select(StoryNode).where(
                StoryNode.project_id == project_id, StoryNode.stable_key == stable_key
            )
        )
        if existing is not None:
            current = self.current_node_revision(existing)
            if (
                not existing.deleted
                and current
                and current.status == "approved"
                and status != "draft"
            ):
                raise ValueError(f"节点 stable_key 已存在: {stable_key}")
            if current and current.status == "draft":
                current.status = "superseded"
            existing.deleted = False
            existing.kind = kind
            self.add_node_revision(
                existing, label=label, payload=payload, status=status, author=author
            )
            return existing
        node = StoryNode(id=new_id(), project_id=project_id, stable_key=stable_key, kind=kind)
        self.session.add(node)
        self.session.flush()
        self.add_node_revision(node, label=label, payload=payload, status=status, author=author)
        return node

    def add_node_revision(
        self,
        node: StoryNode,
        *,
        label: str,
        payload: dict[str, Any],
        status: str,
        author: str,
    ) -> NodeRevision:
        version = self.session.scalar(
            select(func.coalesce(func.max(NodeRevision.version), 0)).where(
                NodeRevision.node_id == node.id
            )
        )
        revision = NodeRevision(
            id=new_id(),
            node_id=node.id,
            version=int(version or 0) + 1,
            label=label,
            payload=payload,
            status=status,
            author=author,
        )
        self.session.add(revision)
        self.session.flush()
        node.current_revision_id = revision.id
        node.updated_at = utcnow()
        return revision

    def create_edge(
        self,
        *,
        project_id: str,
        stable_key: str,
        source_node_id: str,
        target_node_id: str,
        kind: str,
        label: str,
        payload: dict[str, Any],
        status: str,
        author: str,
    ) -> StoryEdge:
        existing = self.session.scalar(
            select(StoryEdge).where(
                StoryEdge.project_id == project_id, StoryEdge.stable_key == stable_key
            )
        )
        if existing is not None:
            current = self.current_edge_revision(existing)
            if (
                not existing.deleted
                and current
                and current.status == "approved"
                and status != "draft"
            ):
                raise ValueError(f"关系 stable_key 已存在: {stable_key}")
            if current and current.status == "draft":
                current.status = "superseded"
            existing.deleted = False
            existing.source_node_id = source_node_id
            existing.target_node_id = target_node_id
            existing.kind = kind
            self.add_edge_revision(
                existing, label=label, payload=payload, status=status, author=author
            )
            return existing
        edge = StoryEdge(
            id=new_id(),
            project_id=project_id,
            stable_key=stable_key,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            kind=kind,
        )
        self.session.add(edge)
        self.session.flush()
        self.add_edge_revision(edge, label=label, payload=payload, status=status, author=author)
        return edge

    def add_edge_revision(
        self,
        edge: StoryEdge,
        *,
        label: str,
        payload: dict[str, Any],
        status: str,
        author: str,
    ) -> EdgeRevision:
        version = self.session.scalar(
            select(func.coalesce(func.max(EdgeRevision.version), 0)).where(
                EdgeRevision.edge_id == edge.id
            )
        )
        revision = EdgeRevision(
            id=new_id(),
            edge_id=edge.id,
            version=int(version or 0) + 1,
            label=label,
            payload=payload,
            status=status,
            author=author,
        )
        self.session.add(revision)
        self.session.flush()
        edge.current_revision_id = revision.id
        edge.updated_at = utcnow()
        return revision

    def create_snapshot(self, project_id: str) -> StorySnapshot:
        nodes = self.list_nodes(project_id)
        edges = self.list_edges(project_id)
        node_revision_ids: list[str] = []
        for node in nodes:
            if not node.current_revision_id:
                continue
            node_revision = self.session.get(NodeRevision, node.current_revision_id)
            if node_revision and node_revision.status == "approved":
                node_revision_ids.append(node_revision.id)
        edge_revision_ids: list[str] = []
        for edge in edges:
            if not edge.current_revision_id:
                continue
            edge_revision = self.session.get(EdgeRevision, edge.current_revision_id)
            if edge_revision and edge_revision.status == "approved":
                edge_revision_ids.append(edge_revision.id)
        version = self.session.scalar(
            select(func.coalesce(func.max(StorySnapshot.version), 0)).where(
                StorySnapshot.project_id == project_id
            )
        )
        snapshot = StorySnapshot(
            id=new_id(),
            project_id=project_id,
            version=int(version or 0) + 1,
            status="approved",
            node_revision_ids=node_revision_ids,
            edge_revision_ids=edge_revision_ids,
            approved_at=utcnow(),
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot


class ArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(
        self,
        *,
        project_id: str,
        stable_key: str,
        kind: str,
        book_id: str | None = None,
        order: int = 0,
    ) -> Artifact:
        artifact = self.session.scalar(
            select(Artifact).where(
                Artifact.project_id == project_id, Artifact.stable_key == stable_key
            )
        )
        if artifact:
            return artifact
        artifact = Artifact(
            id=new_id(),
            project_id=project_id,
            book_id=book_id,
            stable_key=stable_key,
            kind=kind,
            order=order,
        )
        self.session.add(artifact)
        self.session.flush()
        return artifact

    def add_revision(
        self,
        artifact: Artifact,
        *,
        title: str,
        document: dict[str, Any],
        markdown: str,
        status: str,
        author: str,
    ) -> ArtifactRevision:
        version = self.session.scalar(
            select(func.coalesce(func.max(ArtifactRevision.version), 0)).where(
                ArtifactRevision.artifact_id == artifact.id
            )
        )
        revision = ArtifactRevision(
            id=new_id(),
            artifact_id=artifact.id,
            version=int(version or 0) + 1,
            title=title,
            document=document,
            markdown=markdown,
            status=status,
            author=author,
        )
        self.session.add(revision)
        self.session.flush()
        artifact.current_revision_id = revision.id
        artifact.stale = False
        artifact.stale_reason = ""
        return revision

    def add_dependencies(
        self,
        *,
        project_id: str,
        target_artifact_id: str,
        sources: Iterable[tuple[str, str]],
    ) -> None:
        for source_type, source_id in sources:
            existing = self.session.scalar(
                select(ArtifactDependency).where(
                    ArtifactDependency.source_type == source_type,
                    ArtifactDependency.source_id == source_id,
                    ArtifactDependency.target_artifact_id == target_artifact_id,
                )
            )
            if existing is None:
                self.session.add(
                    ArtifactDependency(
                        id=new_id(),
                        project_id=project_id,
                        source_type=source_type,
                        source_id=source_id,
                        target_artifact_id=target_artifact_id,
                    )
                )

    def downstream(self, project_id: str, source_type: str, source_id: str) -> list[Artifact]:
        result: dict[str, Artifact] = {}
        frontier = [(source_type, source_id)]
        seen = set(frontier)
        while frontier:
            current_type, current_id = frontier.pop(0)
            dependencies = self.session.scalars(
                select(ArtifactDependency).where(
                    ArtifactDependency.project_id == project_id,
                    ArtifactDependency.source_type == current_type,
                    ArtifactDependency.source_id == current_id,
                )
            )
            for dependency in dependencies:
                artifact = self.session.get(Artifact, dependency.target_artifact_id)
                if artifact is None or artifact.id in result:
                    continue
                result[artifact.id] = artifact
                marker = ("artifact", artifact.id)
                if marker not in seen:
                    seen.add(marker)
                    frontier.append(marker)
        return list(result.values())


class RuntimeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job(
        self,
        *,
        project_id: str,
        kind: str,
        payload: dict[str, Any],
        estimated_tokens: int = 0,
        run_id: str | None = None,
        status: str = "queued",
    ) -> Job:
        job = Job(
            id=new_id(),
            project_id=project_id,
            run_id=run_id,
            kind=kind,
            status=status,
            payload=payload,
            estimated_tokens=estimated_tokens,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def create_run(self, *, project_id: str, kind: str, payload: dict[str, Any]) -> WorkflowRun:
        run_id = new_id()
        run = WorkflowRun(
            id=run_id,
            project_id=project_id,
            kind=kind,
            status="pending",
            checkpoint_thread_id=f"novelloom-{project_id}-{run_id}",
            payload=payload,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def create_decision(
        self,
        *,
        project_id: str,
        gate: str,
        payload: dict[str, Any],
        run_id: str | None = None,
    ) -> Decision:
        decision = Decision(
            id=new_id(), project_id=project_id, run_id=run_id, gate=gate, payload=payload
        )
        self.session.add(decision)
        self.session.flush()
        return decision

    def record_usage(
        self,
        *,
        project: Project,
        role: str,
        provider_key: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        run_id: str | None = None,
    ) -> UsageRecord:
        record = UsageRecord(
            id=new_id(),
            project_id=project.id,
            run_id=run_id,
            role=role,
            provider_key=provider_key,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )
        project.tokens_used += input_tokens + output_tokens
        project.cost_used += cost
        self.session.add(record)
        return record
