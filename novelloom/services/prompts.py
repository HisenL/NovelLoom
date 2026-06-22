from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from ..domain import RevisionStatus
from ..persistence.database import Database
from ..persistence.models import Project, PromptRevision, PromptTemplate
from ..persistence.repositories import new_id
from .core import DomainError, NotFound


class PromptService:
    """Versioned project prompt templates with explicit rollback."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save(
        self,
        *,
        project_id: str,
        key: str,
        system_prompt: str,
        user_prompt: str,
        status: str = RevisionStatus.APPROVED,
    ) -> dict[str, Any]:
        if not key.strip() or not system_prompt.strip() or not user_prompt.strip():
            raise DomainError("Prompt key、system_prompt 和 user_prompt 不能为空")
        with self.database.session() as session:
            if session.get(Project, project_id) is None:
                raise NotFound("项目不存在")
            template = session.scalar(
                select(PromptTemplate).where(
                    PromptTemplate.project_id == project_id,
                    PromptTemplate.key == key,
                )
            )
            if template is None:
                template = PromptTemplate(id=new_id(), project_id=project_id, key=key)
                session.add(template)
                session.flush()
            current = (
                session.get(PromptRevision, template.current_revision_id)
                if template.current_revision_id
                else None
            )
            if current and current.status == RevisionStatus.APPROVED:
                current.status = RevisionStatus.SUPERSEDED
            version = session.scalar(
                select(func.coalesce(func.max(PromptRevision.version), 0)).where(
                    PromptRevision.template_id == template.id
                )
            )
            revision = PromptRevision(
                id=new_id(),
                template_id=template.id,
                version=int(version or 0) + 1,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                status=status,
            )
            session.add(revision)
            session.flush()
            template.current_revision_id = revision.id
            return self._dict(template, revision)

    def list(self, project_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            templates = session.scalars(
                select(PromptTemplate)
                .where(PromptTemplate.project_id == project_id)
                .order_by(PromptTemplate.key)
            )
            result = []
            for template in templates:
                if not template.current_revision_id:
                    continue
                revision = session.get(PromptRevision, template.current_revision_id)
                if revision:
                    result.append(self._dict(template, revision))
            return result

    def get(self, template_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            template = session.get(PromptTemplate, template_id)
            if template is None or not template.current_revision_id:
                raise NotFound("Prompt 模板不存在")
            current = session.get(PromptRevision, template.current_revision_id)
            if current is None:
                raise NotFound("Prompt 版本不存在")
            result = self._dict(template, current)
            revisions = session.scalars(
                select(PromptRevision)
                .where(PromptRevision.template_id == template_id)
                .order_by(PromptRevision.version.desc())
            )
            result["history"] = [self._revision_dict(revision) for revision in revisions]
            return result

    def rollback(self, template_id: str, revision_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            template = session.get(PromptTemplate, template_id)
            revision = session.get(PromptRevision, revision_id)
            if template is None or revision is None or revision.template_id != template_id:
                raise NotFound("要回滚的 Prompt 版本不存在")
            project_id = template.project_id
            key = template.key
            system_prompt = revision.system_prompt
            user_prompt = revision.user_prompt
        if project_id is None:
            raise DomainError("全局 Prompt 不能通过项目接口回滚")
        return self.save(
            project_id=project_id,
            key=key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def resolve(
        self,
        project_id: str,
        key: str,
        *,
        default_system: str,
        default_user: str,
        variables: dict[str, Any],
    ) -> tuple[str, str]:
        with self.database.session() as session:
            row = session.execute(
                select(PromptTemplate, PromptRevision)
                .join(
                    PromptRevision,
                    PromptTemplate.current_revision_id == PromptRevision.id,
                )
                .where(
                    PromptTemplate.project_id == project_id,
                    PromptTemplate.key == key,
                    PromptRevision.status == RevisionStatus.APPROVED,
                )
            ).first()
            system_prompt = row[1].system_prompt if row else default_system
            user_template = row[1].user_prompt if row else default_user
        try:
            return system_prompt.format_map(variables), user_template.format_map(variables)
        except (KeyError, ValueError) as error:
            raise DomainError(f"Prompt 模板变量错误: {error}") from error

    @staticmethod
    def _revision_dict(revision: PromptRevision) -> dict[str, Any]:
        return {
            "revision_id": revision.id,
            "version": revision.version,
            "system_prompt": revision.system_prompt,
            "user_prompt": revision.user_prompt,
            "status": revision.status,
            "created_at": revision.created_at.isoformat(),
        }

    @classmethod
    def _dict(cls, template: PromptTemplate, revision: PromptRevision) -> dict[str, Any]:
        return {
            "id": template.id,
            "project_id": template.project_id,
            "key": template.key,
            **cls._revision_dict(revision),
        }
