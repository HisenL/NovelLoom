from __future__ import annotations

from typing import Any

from ..domain import ArtifactKind, JobStatus
from ..persistence.database import Database
from ..persistence.models import Artifact, Decision, Job, StoryEdge, StoryNode
from .core import BudgetExceeded, NotFound
from .reasoning import ReasoningService


class CascadeService:
    """Executes the structural half of invalidation without overwriting approved prose."""

    def __init__(self, database: Database, reasoning: ReasoningService) -> None:
        self.database = database
        self.reasoning = reasoning

    async def run(self, job_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None or job.kind != "cascade_recompute":
                raise NotFound("级联重算任务不存在")
            if job.status not in (JobStatus.QUEUED, JobStatus.PAUSED):
                return self._job_dict(job)
            job.status = JobStatus.RUNNING
            job.progress = 0.1
            project_id = job.project_id
            payload = dict(job.payload)

        try:
            structured = list(payload.get("structured_artifact_ids", []))
            stale_prose = list(payload.get("stale_prose_ids", []))
            if not structured:
                return self._pause_for_prose(job_id, stale_prose)

            source_scope = self._source_scope(
                project_id,
                str(payload.get("source_type", "")),
                str(payload.get("source_id", "")),
            )
            if source_scope == "world":
                result = await self.reasoning.propose_events(project_id)
                return self._wait_for_decision(job_id, result["decision_id"], "event_final")
            if source_scope in {"event", "event_plan"}:
                self.reasoning.refresh_event_plan(project_id)
                result = await self.reasoning.plan_books(project_id)
                return self._wait_for_decision(job_id, result["decision_id"], "outline_final")
            return self._pause_for_prose(job_id, stale_prose)
        except BudgetExceeded as error:
            return self._finish(job_id, JobStatus.PAUSED, str(error), 0.1)
        except Exception as error:
            return self._finish(job_id, JobStatus.FAILED, str(error), 0.1)

    async def continue_after_decision(
        self, decision_id: str, *, approved: bool
    ) -> dict[str, Any] | None:
        with self.database.session() as session:
            decision = session.get(Decision, decision_id)
            if decision is None:
                raise NotFound("人工决策不存在")
            job_id = str(decision.payload.get("cascade_job_id", ""))
            gate = decision.gate
            project_id = decision.project_id
        if not job_id:
            return None
        if not approved:
            return self._finish(job_id, JobStatus.PAUSED, "用户驳回了级联重算候选", 0.5)
        if gate == "event_final":
            try:
                result = await self.reasoning.plan_books(project_id)
                return self._wait_for_decision(job_id, result["decision_id"], "outline_final")
            except BudgetExceeded as error:
                return self._finish(job_id, JobStatus.PAUSED, str(error), 0.6)
            except Exception as error:
                return self._finish(job_id, JobStatus.FAILED, str(error), 0.6)
        if gate == "outline_final":
            return self._finish(job_id, JobStatus.COMPLETED, "", 1.0)
        return None

    def _source_scope(self, project_id: str, source_type: str, source_id: str) -> str:
        with self.database.session() as session:
            if source_type == "node":
                node = session.get(StoryNode, source_id)
                return "event" if node and node.kind == "event" else "world"
            if source_type == "edge":
                edge = session.get(StoryEdge, source_id)
                if edge:
                    source = session.get(StoryNode, edge.source_node_id)
                    target = session.get(StoryNode, edge.target_node_id)
                    if (source and source.kind == "event") or (target and target.kind == "event"):
                        return "event"
                return "world"
            if source_type == "artifact":
                artifact = session.get(Artifact, source_id)
                if artifact and artifact.kind == ArtifactKind.EVENT_PLAN:
                    return "event_plan"
                return "prose"
        return "world"

    def _wait_for_decision(self, job_id: str, decision_id: str, gate: str) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            decision = session.get(Decision, decision_id)
            if job is None or decision is None:
                raise NotFound("级联重算状态不存在")
            decision.payload = {**decision.payload, "cascade_job_id": job_id}
            job.payload = {**job.payload, "decision_id": decision_id, "gate": gate}
            job.status = JobStatus.PAUSED
            job.progress = 0.5 if gate == "event_final" else 0.8
            job.error = ""
            return self._job_dict(job)

    def _pause_for_prose(self, job_id: str, stale_prose_ids: list[str]) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise NotFound("级联重算任务不存在")
            if stale_prose_ids:
                job.payload = {
                    **job.payload,
                    "requires_confirmation": "rewrite_prose",
                    "stale_prose_ids": stale_prose_ids,
                }
                job.status = JobStatus.PAUSED
                job.progress = 0.9
            else:
                job.status = JobStatus.COMPLETED
                job.progress = 1.0
            return self._job_dict(job)

    def _finish(self, job_id: str, status: str, error: str, progress: float) -> dict[str, Any]:
        with self.database.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise NotFound("级联重算任务不存在")
            job.status = status
            job.error = error
            job.progress = progress
            return self._job_dict(job)

    @staticmethod
    def _job_dict(job: Job) -> dict[str, Any]:
        return {
            "id": job.id,
            "project_id": job.project_id,
            "kind": job.kind,
            "status": job.status,
            "payload": job.payload,
            "progress": job.progress,
            "error": job.error,
        }
