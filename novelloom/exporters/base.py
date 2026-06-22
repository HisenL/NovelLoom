from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class ExportChapter(BaseModel):
    order: int
    title: str
    markdown: str


class Exporter(ABC):
    format: str

    @abstractmethod
    def export(self, *, title: str, chapters: list[ExportChapter], output: Path) -> Path: ...
