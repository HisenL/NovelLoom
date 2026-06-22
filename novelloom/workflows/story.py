from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TypedDict

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ..domain import JobStatus, RunStatus
from ..persistence.database import Database
from ..persistence.models import Job, WorkflowRun
from ..persistence.repositories import RuntimeRepository
from ..services.core import BudgetExceeded, DomainError, NotFound
from ..services.reasoning import ReasoningService


class WorkflowState(TypedDict, total=False):
    project_id: str
    run_id: str
    world_decision_id: str
    event_decision_id: str
    outline_decision_id: str
    approved: bool
    step: str


class StoryWorkflow:
    """Durable graph-first planning workflow; state contains identifiers only."""

    def __init__(
        self,
        database: Database,
        reasoning: ReasoningService,
        checkpoint_path: str = "./data/checkpoints.db",
    ) -> None:
        self.database = database
        self.reasoning = reasoning
        target = Path(checkpoint_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_path = target
        self._checkpoint_connection: aiosqlite.Connection | None = None
        self._saver: AsyncSqliteSaver | None = None
        self.graph: Any | None = None

    async def _ensure_graph(self) -> Any:
        if self.graph is None:
            self._checkpoint_connection = await aiosqlite.connect(self._checkpoint_path)
            self._saver = AsyncSqliteSaver(self._checkpoint_connection)
            self.graph = self._build().compile(checkpointer=self._saver)
        return self.graph

    def _build(self) -> Any:
        graph = StateGraph(WorkflowState)

        async def world(state: WorkflowState) -> dict[str, Any]:
            result = await self.reasoning.propose_world(state["project_id"], run_id=state["run_id"])
            return {"world_decision_id": result["decision_id"], "step": "world_gate"}

        def world_gate(state: WorkflowState) -> dict[str, Any]:
            answer = interrupt({"gate": "world_final", "decision_id": state["world_decision_id"]})
            approved = answer.get("action") == "approve" if isinstance(answer, dict) else False
            note = answer.get("note", "") if isinstance(answer, dict) else ""
            self.reasoning.decide(state["world_decision_id"], approve=approved, note=note)
            return {"approved": approved, "step": "events" if approved else "stopped"}

        async def events(state: WorkflowState) -> dict[str, Any]:
            result = await self.reasoning.propose_events(
                state["project_id"], run_id=state["run_id"]
            )
            return {"event_decision_id": result["decision_id"], "step": "event_gate"}

        def event_gate(state: WorkflowState) -> dict[str, Any]:
            answer = interrupt({"gate": "event_final", "decision_id": state["event_decision_id"]})
            approved = answer.get("action") == "approve" if isinstance(answer, dict) else False
            note = answer.get("note", "") if isinstance(answer, dict) else ""
            self.reasoning.decide(state["event_decision_id"], approve=approved, note=note)
            return {"approved": approved, "step": "plan" if approved else "stopped"}

        async def plan(state: WorkflowState) -> dict[str, Any]:
            result = await self.reasoning.plan_books(state["project_id"], run_id=state["run_id"])
            return {"outline_decision_id": result["decision_id"], "step": "outline_gate"}

        def outline_gate(state: WorkflowState) -> dict[str, Any]:
            answer = interrupt(
                {"gate": "outline_final", "decision_id": state["outline_decision_id"]}
            )
            approved = answer.get("action") == "approve" if isinstance(answer, dict) else False
            note = answer.get("note", "") if isinstance(answer, dict) else ""
            self.reasoning.decide(state["outline_decision_id"], approve=approved, note=note)
            return {"approved": approved, "step": "done" if approved else "stopped"}

        def finish(state: WorkflowState) -> dict[str, Any]:
            with self.database.session() as session:
                run = session.get(WorkflowRun, state["run_id"])
                if run:
                    run.status = RunStatus.COMPLETED if state.get("approved") else RunStatus.PAUSED
                    run.current_step = state.get("step", "done")
                jobs = session.query(Job).filter(Job.run_id == state["run_id"]).all()
                for job in jobs:
                    job.status = JobStatus.COMPLETED if state.get("approved") else JobStatus.PAUSED
                    job.progress = 1.0 if state.get("approved") else job.progress
            return {"step": state.get("step", "done")}

        graph.add_node("world", world)
        graph.add_node("world_gate", world_gate)
        graph.add_node("events", events)
        graph.add_node("event_gate", event_gate)
        graph.add_node("plan", plan)
        graph.add_node("outline_gate", outline_gate)
        graph.add_node("finish", finish)

        graph.add_edge(START, "world")
        graph.add_edge("world", "world_gate")
        graph.add_conditional_edges(
            "world_gate", lambda state: "events" if state.get("approved") else "finish"
        )
        graph.add_edge("events", "event_gate")
        graph.add_conditional_edges(
            "event_gate", lambda state: "plan" if state.get("approved") else "finish"
        )
        graph.add_edge("plan", "outline_gate")
        graph.add_edge("outline_gate", "finish")
        graph.add_edge("finish", END)
        return graph

    async def start(self, project_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            active = (
                session.query(WorkflowRun)
                .filter(
                    WorkflowRun.project_id == project_id,
                    WorkflowRun.status.in_(
                        [RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_DECISION]
                    ),
                )
                .first()
            )
            if active:
                raise DomainError("当前项目已有运行中的工作流")
            repository = RuntimeRepository(session)
            run = repository.create_run(project_id=project_id, kind="story_planning", payload={})
            run.status = RunStatus.RUNNING
            job = repository.create_job(
                project_id=project_id,
                run_id=run.id,
                kind="story_planning",
                payload={},
                status=JobStatus.RUNNING,
            )
            run_id = run.id
            thread_id = run.checkpoint_thread_id
            job_id = job.id
        graph = await self._ensure_graph()
        try:
            result = await graph.ainvoke(
                {"project_id": project_id, "run_id": run_id, "step": "world"},
                {"configurable": {"thread_id": thread_id}},
            )
        except BudgetExceeded as error:
            self._mark_failed(run_id, str(error), paused=True)
            raise
        except Exception as error:
            self._mark_failed(run_id, str(error), paused=False)
            raise
        return {"run_id": run_id, "job_id": job_id, "state": result}

    async def resume(self, run_id: str, *, approve: bool, note: str = "") -> dict[str, Any]:
        with self.database.session() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                raise NotFound("工作流不存在")
            if run.status not in (RunStatus.WAITING_DECISION, RunStatus.PAUSED):
                raise DomainError("工作流当前不在可恢复状态")
            if run.status == RunStatus.PAUSED and run.current_step == "stopped":
                raise DomainError("已驳回的工作流不能直接恢复，请启动新的推演")
            run.status = RunStatus.RUNNING
            thread_id = run.checkpoint_thread_id
        graph = await self._ensure_graph()
        try:
            result = await graph.ainvoke(
                Command(resume={"action": "approve" if approve else "reject", "note": note}),
                {"configurable": {"thread_id": thread_id}},
            )
        except BudgetExceeded as error:
            self._mark_failed(run_id, str(error), paused=True)
            raise
        except Exception as error:
            self._mark_failed(run_id, str(error), paused=False)
            raise
        return {"run_id": run_id, "state": result}

    def _mark_failed(self, run_id: str, error: str, *, paused: bool) -> None:
        run_status = RunStatus.PAUSED if paused else RunStatus.FAILED
        job_status = JobStatus.PAUSED if paused else JobStatus.FAILED
        with self.database.session() as session:
            run = session.get(WorkflowRun, run_id)
            if run:
                run.status = run_status
                run.error = error
            jobs = session.query(Job).filter(Job.run_id == run_id).all()
            for job in jobs:
                job.status = job_status
                job.error = error

    def cancel(self, run_id: str) -> None:
        with self.database.session() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                raise NotFound("工作流不存在")
            run.status = RunStatus.CANCELLED
            jobs = session.query(Job).filter(Job.run_id == run_id).all()
            for job in jobs:
                job.status = JobStatus.CANCELLED

    def close(self) -> None:
        connection = self._checkpoint_connection
        self._checkpoint_connection = None
        if connection is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(connection.close())
        else:
            loop.create_task(connection.close())
