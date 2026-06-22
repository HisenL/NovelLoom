from __future__ import annotations

from pathlib import Path

from .base import ExportChapter, Exporter


class MarkdownExporter(Exporter):
    format = "md"

    def export(self, *, title: str, chapters: list[ExportChapter], output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        parts = [f"# {title}\n"]
        for chapter in sorted(chapters, key=lambda item: item.order):
            parts.append(f"\n## {chapter.title}\n\n{chapter.markdown.strip()}\n")
        output.write_text("\n".join(parts), encoding="utf-8")
        return output
