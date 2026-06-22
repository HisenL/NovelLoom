from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..domain import ArtifactKind, RevisionStatus
from ..exporters import DocxExporter, ExportChapter, MarkdownExporter
from ..persistence.database import Database
from ..persistence.models import Artifact, ArtifactRevision, Book, Project
from .core import DomainError, NotFound


class ExportService:
    def __init__(self, database: Database, output_dir: str = "./exports") -> None:
        self.database = database
        self.output_dir = Path(output_dir)
        self.exporters = {"md": MarkdownExporter(), "docx": DocxExporter()}

    def export_project(
        self,
        project_id: str,
        *,
        formats: list[str] | None = None,
        allow_stale: bool = False,
    ) -> dict[str, Any]:
        formats = formats or ["md", "docx"]
        unknown = set(formats) - set(self.exporters)
        if unknown:
            raise DomainError(f"不支持的导出格式: {sorted(unknown)}")
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise NotFound("项目不存在")
            books = list(
                session.scalars(
                    select(Book).where(Book.project_id == project_id).order_by(Book.order)
                )
            )
            outputs: list[str] = []
            for book in books:
                stmt = (
                    select(Artifact, ArtifactRevision)
                    .join(ArtifactRevision, Artifact.current_revision_id == ArtifactRevision.id)
                    .where(
                        Artifact.project_id == project_id,
                        Artifact.book_id == book.id,
                        Artifact.kind == ArtifactKind.CHAPTER_PROSE,
                        ArtifactRevision.status == RevisionStatus.APPROVED,
                    )
                    .order_by(Artifact.order)
                )
                rows = list(session.execute(stmt))
                if not rows:
                    continue
                stale = [artifact for artifact, _ in rows if artifact.stale]
                if stale and not allow_stale:
                    raise DomainError(f"《{book.title}》包含 {len(stale)} 章过期正文，拒绝导出")
                chapters = [
                    ExportChapter(
                        order=artifact.order, title=revision.title, markdown=revision.markdown
                    )
                    for artifact, revision in rows
                ]
                folder = self.output_dir / self._safe_name(project.name)
                for format_name in formats:
                    target = folder / f"{self._safe_name(book.title)}.{format_name}"
                    path = self.exporters[format_name].export(
                        title=book.title, chapters=chapters, output=target
                    )
                    outputs.append(str(path))
            return {"project_id": project_id, "files": outputs}

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = re.sub(r"[\\/:*?\"<>|]", "_", value).strip().rstrip(".")
        return cleaned or "untitled"
