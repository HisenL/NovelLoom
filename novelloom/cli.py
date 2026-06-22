from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console

from .config import generate_default_config, load_config
from .engine import NovelLoomEngine

app = typer.Typer(help="NovelLoom 图谱驱动多书创作系统", no_args_is_help=True)
console = Console()


def _show(value: object) -> None:
    console.print_json(json.dumps(value, ensure_ascii=False, default=str))


@app.command("init")
def init_config(
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("novelloom.config.yaml"),
) -> None:
    """生成不包含密钥的默认配置。"""
    if output.exists() and not typer.confirm(f"{output} 已存在，是否覆盖？"):
        raise typer.Abort()
    generate_default_config(output)
    console.print(f"已生成 {output}")


@app.command()
def serve(
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("novelloom.config.yaml"),
) -> None:
    """在 localhost 启动 Web 与 REST API。"""
    settings = load_config(config)
    uvicorn.run(
        "novelloom.server:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=False,
    )


@app.command("project-create")
def project_create(
    name: Annotated[str, typer.Option(prompt=True)],
    premise: Annotated[str, typer.Option(prompt=True)],
    main_title: Annotated[str, typer.Option("--main-title")] = "正本",
    companion: Annotated[list[str] | None, typer.Option("--companion")] = None,
    language: str = "zh-CN",
    token_budget: int = 1_000_000,
    cost_budget: float | None = None,
) -> None:
    books: list[dict[str, object]] = [
        {"key": "main", "type": "main", "title": main_title, "source_book": None}
    ]
    for index, title in enumerate(companion or [], start=1):
        books.append(
            {
                "key": f"companion_{index}",
                "type": "biography",
                "title": title,
                "source_book": "main",
            }
        )
    with NovelLoomEngine() as engine:
        _show(
            engine.projects.create_project(
                name=name,
                premise=premise,
                books=books,
                language=language,
                token_budget=token_budget,
                cost_budget=cost_budget,
            )
        )


@app.command("project-list")
def project_list() -> None:
    with NovelLoomEngine() as engine:
        _show(engine.projects.list_projects())


@app.command("start")
def start(project_id: str) -> None:
    with NovelLoomEngine() as engine:
        _show(asyncio.run(engine.workflow.start(project_id)))


@app.command("resume")
def resume(
    run_id: str,
    approve: Annotated[bool, typer.Option("--approve/--reject")] = True,
    note: str = "",
) -> None:
    with NovelLoomEngine() as engine:
        _show(asyncio.run(engine.workflow.resume(run_id, approve=approve, note=note)))


@app.command("export")
def export(
    project_id: str,
    formats: Annotated[list[str] | None, typer.Option("--format", "-f")] = None,
    allow_stale: bool = False,
) -> None:
    with NovelLoomEngine() as engine:
        _show(
            engine.exporting.export_project(
                project_id, formats=formats or ["md", "docx"], allow_stale=allow_stale
            )
        )


if __name__ == "__main__":
    app()
