from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from ..domain import ArtifactKind, DecisionStatus, ModelRole, RevisionStatus
from ..persistence.database import Database
from ..persistence.models import (
    Book,
    Decision,
    FactCandidate,
    utcnow,
)
from ..persistence.repositories import RuntimeRepository, new_id
from ..providers import ModelMessage, ModelRequest
from .core import ArtifactService, DomainError, GraphService, NotFound
from .prompts import PromptService
from .providers import ProviderService


class ExtractedFact(BaseModel):
    subject_key: str
    predicate: str
    object_key: str
    evidence: str = ""


class ExtractionResult(BaseModel):
    summary: str
    facts: list[ExtractedFact] = Field(default_factory=list)


class ReviewIssue(BaseModel):
    severity: str
    description: str
    artifact_keys: list[str] = Field(default_factory=list)


class BatchReview(BaseModel):
    status: str
    score: int = Field(ge=1, le=10)
    issues: list[ReviewIssue] = Field(default_factory=list)
    comment: str = ""


WRITER_SYSTEM = """你是长篇小说作者。严格按照批准的世界事实、事件和章节大纲写作。
不得改变事件结果，不得新增会影响全局的事实。只输出本章正文，不要输出说明或 Markdown 标题。"""

EXTRACTOR_SYSTEM = """从正文提取明确发生的候选事实和不超过300字的摘要。
subject_key/object_key 只能使用提供的世界实体 key。不要推测。"""

CRITIC_SYSTEM = """审核同一事件批次的多本小说正文。检查时间、事件结果、人物状态和共享事实是否一致。
返回结构化审核，不要改写正文。"""


class WritingService:
    def __init__(
        self,
        database: Database,
        providers: ProviderService,
        artifacts: ArtifactService,
        graph: GraphService,
        prompts: PromptService | None = None,
    ) -> None:
        self.database = database
        self.providers = providers
        self.artifacts = artifacts
        self.graph = graph
        self.prompts = prompts or PromptService(database)

    async def write_batch(
        self,
        *,
        project_id: str,
        event_keys: list[str],
        run_id: str | None = None,
    ) -> dict[str, Any]:
        context = self._load_context(project_id, event_keys)
        outlines = self._matching_outlines(project_id, event_keys)
        if not outlines:
            raise DomainError("没有找到对应事件批次的已批准章节大纲")
        prose_artifacts: list[dict[str, Any]] = []
        summary_artifacts: list[dict[str, Any]] = []
        fact_ids: list[str] = []
        for outline in outlines:
            book = context["books_by_id"].get(outline["book_id"])
            previous = self._previous_summaries(project_id, outline["book_id"], outline["order"])
            writing_context = json.dumps(
                {
                    "book": book,
                    "world": context["world"],
                    "events": context["events"],
                    "outline": outline["document"],
                    "previous_summaries": previous,
                },
                ensure_ascii=False,
            )
            system_prompt, user_prompt = self.prompts.resolve(
                project_id,
                "writer",
                default_system=WRITER_SYSTEM,
                default_user="{context}",
                variables={"context": writing_context},
            )
            response = await self.providers.generate(
                project_id=project_id,
                role=ModelRole.WRITER,
                run_id=run_id,
                request=ModelRequest(
                    messages=[
                        ModelMessage(role="system", content=system_prompt),
                        ModelMessage(role="user", content=user_prompt),
                    ],
                    temperature=0.8,
                    max_output_tokens=max(
                        2000, int(outline["document"].get("target_words", 2500) * 2.2)
                    ),
                ),
            )
            prose = self.artifacts.save_artifact(
                project_id=project_id,
                book_id=outline["book_id"],
                stable_key=outline["stable_key"].replace(":outline", ":prose"),
                kind=ArtifactKind.CHAPTER_PROSE,
                order=outline["order"],
                title=outline["title"],
                document=self._plain_text_document(response.content),
                markdown=response.content,
                status=RevisionStatus.DRAFT,
                dependencies=[("artifact", outline["id"])],
            )
            prose_artifacts.append(prose)
            extraction, created_fact_ids = await self._extract(
                project_id=project_id,
                prose=prose,
                known_keys=context["known_keys"],
                run_id=run_id,
            )
            fact_ids.extend(created_fact_ids)
            summary_artifacts.append(
                self.artifacts.save_artifact(
                    project_id=project_id,
                    book_id=outline["book_id"],
                    stable_key=outline["stable_key"].replace(":outline", ":summary"),
                    kind=ArtifactKind.CHAPTER_SUMMARY,
                    order=outline["order"],
                    title=f"{outline['title']}·摘要",
                    document=self._plain_text_document(extraction.summary),
                    markdown=extraction.summary,
                    status=RevisionStatus.DRAFT,
                    dependencies=[("artifact", prose["id"])],
                )
            )
        review = await self._review_batch(
            project_id=project_id,
            event_keys=event_keys,
            prose_artifacts=prose_artifacts,
            run_id=run_id,
        )
        review_artifact = self.artifacts.save_artifact(
            project_id=project_id,
            stable_key=f"batch-review:{':'.join(event_keys)}",
            kind=ArtifactKind.REVIEW,
            title="批次一致性审核",
            document=review.model_dump(),
            markdown=review.comment,
            status=RevisionStatus.DRAFT,
            dependencies=[("artifact", prose["id"]) for prose in prose_artifacts],
        )
        decision = self._create_batch_decision(
            project_id=project_id,
            run_id=run_id,
            artifact_ids=[item["id"] for item in prose_artifacts + summary_artifacts]
            + [review_artifact["id"]],
            fact_ids=fact_ids,
            review=review.model_dump(),
        )
        return {
            "decision_id": decision.id,
            "prose": prose_artifacts,
            "summaries": summary_artifacts,
            "review": review.model_dump(),
            "fact_ids": fact_ids,
        }

    def decide_batch(self, decision_id: str, *, approve: bool, note: str = "") -> dict[str, Any]:
        with self.database.session() as session:
            decision = session.get(Decision, decision_id)
            if decision is None or decision.gate != "batch_review":
                raise NotFound("批次审核不存在")
            if decision.status != DecisionStatus.PENDING:
                raise DomainError("该批次已经审核")
            decision.status = DecisionStatus.APPROVED if approve else DecisionStatus.REJECTED
            decision.note = note
            decision.decided_at = utcnow()
            payload = dict(decision.payload)
            project_id = decision.project_id
        artifacts = self.artifacts.decide_candidates(payload["artifact_ids"], approve=approve)
        published_edges: list[dict[str, Any]] = []
        with self.database.session() as session:
            candidates = list(
                session.scalars(
                    select(FactCandidate).where(FactCandidate.id.in_(payload["fact_ids"]))
                )
            )
            for candidate in candidates:
                candidate.status = RevisionStatus.APPROVED if approve else RevisionStatus.REJECTED
        if approve:
            graph = self.graph.get_graph(project_id)
            by_key = {node["stable_key"]: node for node in graph["nodes"]}
            with self.database.session() as session:
                candidates = list(
                    session.scalars(
                        select(FactCandidate).where(FactCandidate.id.in_(payload["fact_ids"]))
                    )
                )
                serialized: list[dict[str, Any]] = [
                    {
                        "id": candidate.id,
                        "subject_key": candidate.subject_key,
                        "predicate": candidate.predicate,
                        "object_key": candidate.object_key,
                        "payload": candidate.payload,
                    }
                    for candidate in candidates
                ]
            for serialized_candidate in serialized:
                if (
                    serialized_candidate["subject_key"] not in by_key
                    or serialized_candidate["object_key"] not in by_key
                ):
                    continue
                published_edges.append(
                    self.graph.create_edge(
                        project_id=project_id,
                        stable_key=f"fact:{serialized_candidate['id']}",
                        source_node_id=by_key[serialized_candidate["subject_key"]]["id"],
                        target_node_id=by_key[serialized_candidate["object_key"]]["id"],
                        kind="relationship",
                        label=serialized_candidate["predicate"],
                        payload=serialized_candidate["payload"],
                        author="approved_model",
                        approved=True,
                    )
                )
            self.graph.snapshot(project_id)
        return {"approved": approve, "artifacts": artifacts, "published_edges": published_edges}

    async def _extract(
        self,
        *,
        project_id: str,
        prose: dict[str, Any],
        known_keys: list[str],
        run_id: str | None,
    ) -> tuple[ExtractionResult, list[str]]:
        extraction_context = json.dumps(
            {"known_keys": known_keys, "prose": prose["markdown"][:16_000]},
            ensure_ascii=False,
        )
        system_prompt, user_prompt = self.prompts.resolve(
            project_id,
            "extractor",
            default_system=EXTRACTOR_SYSTEM,
            default_user="{context}",
            variables={"context": extraction_context},
        )
        response = await self.providers.generate(
            project_id=project_id,
            role=ModelRole.EXTRACTOR,
            run_id=run_id,
            request=ModelRequest(
                messages=[
                    ModelMessage(role="system", content=system_prompt),
                    ModelMessage(role="user", content=user_prompt),
                ],
                response_schema=ExtractionResult.model_json_schema(),
                temperature=0.2,
                max_output_tokens=2500,
            ),
        )
        if response.structured is None:
            raise DomainError("Extractor 没有返回合法结构化结果")
        extraction = ExtractionResult.model_validate(response.structured)
        fact_ids: list[str] = []
        known = set(known_keys)
        with self.database.session() as session:
            for fact in extraction.facts:
                if fact.subject_key not in known or fact.object_key not in known:
                    continue
                candidate = FactCandidate(
                    id=new_id(),
                    project_id=project_id,
                    run_id=run_id,
                    source_artifact_id=prose["id"],
                    subject_key=fact.subject_key,
                    predicate=fact.predicate,
                    object_key=fact.object_key,
                    payload={"evidence": fact.evidence},
                )
                session.add(candidate)
                fact_ids.append(candidate.id)
        return extraction, fact_ids

    async def _review_batch(
        self,
        *,
        project_id: str,
        event_keys: list[str],
        prose_artifacts: list[dict[str, Any]],
        run_id: str | None,
    ) -> BatchReview:
        review_context = json.dumps(
            {
                "event_keys": event_keys,
                "chapters": [
                    {"key": item["stable_key"], "text": item["markdown"][:10_000]}
                    for item in prose_artifacts
                ],
            },
            ensure_ascii=False,
        )
        system_prompt, user_prompt = self.prompts.resolve(
            project_id,
            "critic",
            default_system=CRITIC_SYSTEM,
            default_user="{context}",
            variables={"context": review_context},
        )
        response = await self.providers.generate(
            project_id=project_id,
            role=ModelRole.CRITIC,
            run_id=run_id,
            request=ModelRequest(
                messages=[
                    ModelMessage(role="system", content=system_prompt),
                    ModelMessage(role="user", content=user_prompt),
                ],
                response_schema=BatchReview.model_json_schema(),
                temperature=0.2,
                max_output_tokens=2500,
            ),
        )
        if response.structured is None:
            raise DomainError("Critic 没有返回合法结构化结果")
        return BatchReview.model_validate(response.structured)

    def _load_context(self, project_id: str, event_keys: list[str]) -> dict[str, Any]:
        graph = self.graph.get_graph(project_id)
        nodes = [node for node in graph["nodes"] if node["status"] == "approved"]
        events = [
            node for node in nodes if node["kind"] == "event" and node["stable_key"] in event_keys
        ]
        if len(events) != len(set(event_keys)):
            raise DomainError("事件批次包含未知或未批准事件")
        with self.database.session() as session:
            books = list(session.scalars(select(Book).where(Book.project_id == project_id)))
        return {
            "world": [node for node in nodes if node["kind"] != "event"],
            "events": events,
            "known_keys": [node["stable_key"] for node in nodes],
            "books_by_id": {
                book.id: {"id": book.id, "key": book.key, "type": book.type, "title": book.title}
                for book in books
            },
        }

    def _matching_outlines(self, project_id: str, event_keys: list[str]) -> list[dict[str, Any]]:
        outlines = self.artifacts.list_artifacts(project_id, kind=ArtifactKind.CHAPTER_OUTLINE)
        wanted = set(event_keys)
        return [
            outline
            for outline in outlines
            if outline["status"] == RevisionStatus.APPROVED
            and wanted.intersection(outline["document"].get("event_keys", []))
        ]

    def _previous_summaries(self, project_id: str, book_id: str | None, order: int) -> list[str]:
        summaries = self.artifacts.list_artifacts(
            project_id, book_id=book_id, kind=ArtifactKind.CHAPTER_SUMMARY
        )
        return [
            summary["markdown"]
            for summary in summaries
            if summary["order"] < order and summary["status"] == RevisionStatus.APPROVED
        ][-3:]

    def _create_batch_decision(
        self,
        *,
        project_id: str,
        run_id: str | None,
        artifact_ids: list[str],
        fact_ids: list[str],
        review: dict[str, Any],
    ) -> Decision:
        with self.database.session() as session:
            return RuntimeRepository(session).create_decision(
                project_id=project_id,
                run_id=run_id,
                gate="batch_review",
                payload={"artifact_ids": artifact_ids, "fact_ids": fact_ids, "review": review},
            )

    @staticmethod
    def _plain_text_document(text: str) -> dict[str, Any]:
        return {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": paragraph}]}
                for paragraph in text.split("\n")
                if paragraph.strip()
            ],
        }
