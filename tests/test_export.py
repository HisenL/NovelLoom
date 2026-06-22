from __future__ import annotations

from pathlib import Path

from docx import Document

from novelloom.engine import NovelLoomEngine


def test_markdown_and_docx_have_same_chapter_order(
    engine: NovelLoomEngine, project: dict[str, object]
) -> None:
    project_id = str(project["id"])
    book_id = str(engine.projects.get_project(project_id)["books"][0]["id"])
    for order, title in [(2, "第二章"), (1, "第一章")]:
        engine.artifacts.save_artifact(
            project_id=project_id,
            book_id=book_id,
            stable_key=f"prose:main:{order}",
            kind="chapter_prose",
            title=title,
            document={"type": "doc"},
            markdown=f"{title}正文",
            order=order,
            status="approved",
        )
    result = engine.exporting.export_project(project_id)
    markdown_path = Path(next(path for path in result["files"] if path.endswith(".md")))
    docx_path = Path(next(path for path in result["files"] if path.endswith(".docx")))
    markdown = markdown_path.read_text(encoding="utf-8")
    paragraphs = [paragraph.text for paragraph in Document(docx_path).paragraphs]
    assert markdown.index("第一章") < markdown.index("第二章")
    assert paragraphs.index("第一章") < paragraphs.index("第二章")
