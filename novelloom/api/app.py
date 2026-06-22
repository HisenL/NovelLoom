from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from ..engine import NovelLoomEngine
from ..persistence.models import Decision, Job, ModelRoute, UsageRecord, WorkflowRun
from ..services.core import DomainError
from .schemas import (
    ArtifactSave,
    BatchWriteInput,
    DecisionInput,
    EdgeCreate,
    EdgeUpdate,
    ExportInput,
    NodeCreate,
    NodeUpdate,
    ProjectCreate,
    PromptSave,
    ProviderProfileInput,
    RollbackInput,
    RouteInput,
)


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(row, field)
        result[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return result


def create_app(engine: NovelLoomEngine | None = None) -> FastAPI:
    owned_engine = engine is None
    runtime = engine or NovelLoomEngine()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if owned_engine:
            runtime.close()

    app = FastAPI(
        title="NovelLoom API",
        version="0.1.0",
        description="图谱驱动的多书联动创作系统",
        lifespan=lifespan,
    )
    app.state.engine = runtime

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": "0.1.0", "database": "sqlite"}

    @app.get("/api/providers/adapters")
    async def adapters() -> dict[str, Any]:
        return {"items": runtime.providers.list_adapters()}

    @app.get("/api/projects")
    async def list_projects() -> dict[str, Any]:
        return {"items": runtime.projects.list_projects()}

    @app.post("/api/projects", status_code=201)
    async def create_project(body: ProjectCreate) -> dict[str, Any]:
        return runtime.projects.create_project(**body.model_dump())

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str) -> dict[str, Any]:
        return runtime.projects.get_project(project_id)

    @app.get("/api/projects/{project_id}/graph")
    async def get_graph(project_id: str) -> dict[str, Any]:
        return runtime.graph.get_graph(project_id)

    @app.post("/api/projects/{project_id}/graph/nodes", status_code=201)
    async def create_node(
        project_id: str, body: NodeCreate, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        result = runtime.graph.create_node(
            project_id=project_id, author="user", **body.model_dump()
        )
        if result.get("cascade_job_id"):
            background_tasks.add_task(runtime.cascade.run, result["cascade_job_id"])
        return result

    @app.put("/api/graph/nodes/{node_id}")
    async def update_node(
        node_id: str, body: NodeUpdate, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        result = runtime.graph.update_node(node_id, author="user", **body.model_dump())
        if result.get("cascade_job_id"):
            background_tasks.add_task(runtime.cascade.run, result["cascade_job_id"])
        return result

    @app.get("/api/graph/nodes/{node_id}")
    async def get_node(node_id: str) -> dict[str, Any]:
        return runtime.graph.get_node(node_id)

    @app.post("/api/graph/nodes/{node_id}/rollback")
    async def rollback_node(
        node_id: str, body: RollbackInput, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        result = runtime.graph.rollback_node(node_id, body.revision_id)
        if result.get("cascade_job_id"):
            background_tasks.add_task(runtime.cascade.run, result["cascade_job_id"])
        return result

    @app.post("/api/projects/{project_id}/graph/edges", status_code=201)
    async def create_edge(
        project_id: str, body: EdgeCreate, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        result = runtime.graph.create_edge(
            project_id=project_id, author="user", **body.model_dump()
        )
        if result.get("cascade_job_id"):
            background_tasks.add_task(runtime.cascade.run, result["cascade_job_id"])
        return result

    @app.put("/api/graph/edges/{edge_id}")
    async def update_edge(
        edge_id: str, body: EdgeUpdate, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        result = runtime.graph.update_edge(edge_id, author="user", **body.model_dump())
        if result.get("cascade_job_id"):
            background_tasks.add_task(runtime.cascade.run, result["cascade_job_id"])
        return result

    @app.get("/api/graph/edges/{edge_id}")
    async def get_edge(edge_id: str) -> dict[str, Any]:
        return runtime.graph.get_edge(edge_id)

    @app.post("/api/graph/edges/{edge_id}/rollback")
    async def rollback_edge(
        edge_id: str, body: RollbackInput, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        result = runtime.graph.rollback_edge(edge_id, body.revision_id)
        if result.get("cascade_job_id"):
            background_tasks.add_task(runtime.cascade.run, result["cascade_job_id"])
        return result

    @app.post("/api/projects/{project_id}/graph/snapshots")
    async def snapshot(project_id: str) -> dict[str, Any]:
        return runtime.graph.snapshot(project_id)

    @app.get("/api/projects/{project_id}/artifacts")
    async def list_artifacts(
        project_id: str,
        book_id: str | None = None,
        kind: str | None = None,
    ) -> dict[str, Any]:
        return {"items": runtime.artifacts.list_artifacts(project_id, book_id=book_id, kind=kind)}

    @app.post("/api/projects/{project_id}/artifacts", status_code=201)
    async def save_artifact(
        project_id: str, body: ArtifactSave, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        data = body.model_dump()
        data["dependencies"] = [tuple(item) for item in data["dependencies"]]
        result = runtime.artifacts.save_artifact(project_id=project_id, author="user", **data)
        if result.get("cascade_job_id"):
            background_tasks.add_task(runtime.cascade.run, result["cascade_job_id"])
        return result

    @app.get("/api/artifacts/{artifact_id}")
    async def get_artifact(artifact_id: str) -> dict[str, Any]:
        return runtime.artifacts.get_artifact(artifact_id)

    @app.post("/api/artifacts/{artifact_id}/rollback")
    async def rollback_artifact(
        artifact_id: str, body: RollbackInput, background_tasks: BackgroundTasks
    ) -> dict[str, Any]:
        result = runtime.artifacts.rollback_artifact(artifact_id, body.revision_id)
        if result.get("cascade_job_id"):
            background_tasks.add_task(runtime.cascade.run, result["cascade_job_id"])
        return result

    @app.get("/api/projects/{project_id}/providers")
    async def list_profiles(project_id: str) -> dict[str, Any]:
        return {"items": runtime.providers.list_profiles(project_id)}

    @app.get("/api/projects/{project_id}/prompts")
    async def list_prompts(project_id: str) -> dict[str, Any]:
        return {"items": runtime.prompts.list(project_id)}

    @app.post("/api/projects/{project_id}/prompts", status_code=201)
    async def save_prompt(project_id: str, body: PromptSave) -> dict[str, Any]:
        return runtime.prompts.save(project_id=project_id, **body.model_dump())

    @app.get("/api/prompts/{template_id}")
    async def get_prompt(template_id: str) -> dict[str, Any]:
        return runtime.prompts.get(template_id)

    @app.post("/api/prompts/{template_id}/rollback")
    async def rollback_prompt(template_id: str, body: RollbackInput) -> dict[str, Any]:
        return runtime.prompts.rollback(template_id, body.revision_id)

    @app.post("/api/projects/{project_id}/providers", status_code=201)
    async def save_profile(project_id: str, body: ProviderProfileInput) -> dict[str, Any]:
        data = body.model_dump()
        data["api_key"] = data.pop("secret_value")
        return runtime.providers.save_profile(project_id=project_id, **data)

    @app.post("/api/providers/{profile_id}/test")
    async def test_profile(profile_id: str) -> dict[str, Any]:
        return await runtime.providers.test_profile(profile_id)

    @app.put("/api/projects/{project_id}/routes/{role}")
    async def set_route(project_id: str, role: str, body: RouteInput) -> dict[str, Any]:
        return runtime.providers.set_route(project_id=project_id, role=role, **body.model_dump())

    @app.get("/api/projects/{project_id}/routes")
    async def list_routes(project_id: str) -> dict[str, Any]:
        with runtime.database.session() as session:
            rows = session.scalars(
                select(ModelRoute)
                .where(ModelRoute.project_id == project_id)
                .order_by(ModelRoute.role)
            )
            return {
                "items": [
                    _row_dict(
                        row,
                        (
                            "id",
                            "project_id",
                            "role",
                            "primary_profile_id",
                            "fallback_profile_ids",
                            "parameters",
                        ),
                    )
                    for row in rows
                ]
            }

    @app.post("/api/projects/{project_id}/workflow/start")
    async def start_workflow(project_id: str) -> dict[str, Any]:
        return await runtime.workflow.start(project_id)

    @app.post("/api/runs/{run_id}/resume")
    async def resume_workflow(run_id: str, body: DecisionInput) -> dict[str, Any]:
        return await runtime.workflow.resume(run_id, approve=body.approve, note=body.note)

    @app.post("/api/runs/{run_id}/cancel", status_code=204)
    async def cancel_workflow(run_id: str) -> None:
        runtime.workflow.cancel(run_id)

    @app.get("/api/projects/{project_id}/runs")
    async def list_runs(project_id: str) -> dict[str, Any]:
        with runtime.database.session() as session:
            rows = session.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.project_id == project_id)
                .order_by(WorkflowRun.created_at.desc())
            )
            fields = (
                "id",
                "project_id",
                "kind",
                "status",
                "current_step",
                "payload",
                "error",
                "created_at",
                "updated_at",
            )
            return {"items": [_row_dict(row, fields) for row in rows]}

    @app.get("/api/projects/{project_id}/jobs")
    async def list_jobs(project_id: str) -> dict[str, Any]:
        with runtime.database.session() as session:
            rows = session.scalars(
                select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())
            )
            fields = (
                "id",
                "project_id",
                "run_id",
                "kind",
                "status",
                "payload",
                "progress",
                "estimated_tokens",
                "error",
                "created_at",
                "updated_at",
            )
            return {"items": [_row_dict(row, fields) for row in rows]}

    @app.get("/api/projects/{project_id}/jobs/stream")
    async def stream_jobs(project_id: str) -> EventSourceResponse:
        async def events() -> AsyncIterator[dict[str, str]]:
            previous = ""
            while True:
                items = await list_jobs(project_id)
                payload = json.dumps(items, ensure_ascii=False)
                if payload != previous:
                    previous = payload
                    yield {"event": "jobs", "data": payload}
                await asyncio.sleep(1)

        return EventSourceResponse(events(), ping=15)

    @app.get("/api/projects/{project_id}/decisions")
    async def list_decisions(
        project_id: str, status: str | None = Query(default=None)
    ) -> dict[str, Any]:
        with runtime.database.session() as session:
            stmt = select(Decision).where(Decision.project_id == project_id)
            if status:
                stmt = stmt.where(Decision.status == status)
            rows = session.scalars(stmt.order_by(Decision.created_at.desc()))
            fields = (
                "id",
                "project_id",
                "run_id",
                "gate",
                "status",
                "payload",
                "note",
                "created_at",
                "decided_at",
            )
            return {"items": [_row_dict(row, fields) for row in rows]}

    @app.post("/api/decisions/{decision_id}")
    async def decide(decision_id: str, body: DecisionInput) -> dict[str, Any]:
        result = runtime.reasoning.decide(decision_id, approve=body.approve, note=body.note)
        cascade = await runtime.cascade.continue_after_decision(decision_id, approved=body.approve)
        if cascade:
            result["cascade"] = cascade
        return result

    @app.post("/api/projects/{project_id}/writing/batches")
    async def write_batch(project_id: str, body: BatchWriteInput) -> dict[str, Any]:
        return await runtime.writing.write_batch(project_id=project_id, event_keys=body.event_keys)

    @app.post("/api/writing/decisions/{decision_id}")
    async def decide_batch(decision_id: str, body: DecisionInput) -> dict[str, Any]:
        return runtime.writing.decide_batch(decision_id, approve=body.approve, note=body.note)

    @app.get("/api/projects/{project_id}/usage")
    async def usage(project_id: str) -> dict[str, Any]:
        with runtime.database.session() as session:
            rows = session.scalars(
                select(UsageRecord)
                .where(UsageRecord.project_id == project_id)
                .order_by(UsageRecord.created_at.desc())
            )
            fields = (
                "id",
                "run_id",
                "role",
                "provider_key",
                "model",
                "input_tokens",
                "output_tokens",
                "cost",
                "created_at",
            )
            return {"items": [_row_dict(row, fields) for row in rows]}

    @app.post("/api/projects/{project_id}/exports")
    async def export_project(project_id: str, body: ExportInput) -> dict[str, Any]:
        return runtime.exporting.export_project(
            project_id, formats=list(body.formats), allow_stale=body.allow_stale
        )

    web_root = _find_web_root()
    if web_root:
        assets = web_root / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            target = web_root / path
            if path and target.is_file():
                return FileResponse(target)
            return FileResponse(web_root / "index.html")

    return app


def _find_web_root() -> Path | None:
    development = Path(__file__).resolve().parents[2] / "web" / "dist"
    if (development / "index.html").exists():
        return development
    try:
        packaged = Path(str(files("novelloom").joinpath("web_dist")))
    except (FileNotFoundError, TypeError):
        return None
    return packaged if (packaged / "index.html").exists() else None
