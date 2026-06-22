from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BookInput(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    type: Literal["main", "biography", "side_story", "alternate_pov"]
    title: str = Field(min_length=1, max_length=300)
    perspective_node_id: str | None = None
    source_book: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    premise: str = Field(min_length=1)
    language: str = "zh-CN"
    token_budget: int = Field(default=1_000_000, ge=1)
    cost_budget: float | None = Field(default=None, ge=0)
    books: list[BookInput]


class NodeCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=120)
    kind: str
    label: str = Field(min_length=1, max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)
    approved: bool = True


class NodeUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)
    approved: bool = True


class EdgeCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=160)
    source_node_id: str
    target_node_id: str
    kind: str
    label: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    approved: bool = True


class EdgeUpdate(BaseModel):
    label: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    approved: bool = True


class ArtifactSave(BaseModel):
    stable_key: str = Field(min_length=1, max_length=180)
    kind: str
    title: str
    document: dict[str, Any] = Field(default_factory=dict)
    markdown: str = ""
    book_id: str | None = None
    order: int = 0
    status: Literal["draft", "approved", "rejected"] = "draft"
    dependencies: list[tuple[str, str]] = Field(default_factory=list)


class ProviderProfileInput(BaseModel):
    key: str
    provider: str
    model: str
    base_url: str = ""
    secret_ref: str = ""
    secret_value: str | None = Field(default=None, repr=False)
    headers: dict[str, str] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class RouteInput(BaseModel):
    primary_profile_id: str
    fallback_profile_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class DecisionInput(BaseModel):
    approve: bool
    note: str = ""


class RollbackInput(BaseModel):
    revision_id: str


class PromptSave(BaseModel):
    key: str
    system_prompt: str
    user_prompt: str
    status: Literal["draft", "approved"] = "approved"


class BatchWriteInput(BaseModel):
    event_keys: list[str] = Field(min_length=1)


def _default_formats() -> list[Literal["md", "docx"]]:
    return ["md", "docx"]


class ExportInput(BaseModel):
    formats: list[Literal["md", "docx"]] = Field(default_factory=_default_formats)
    allow_stale: bool = False
