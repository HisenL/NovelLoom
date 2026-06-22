from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from novelloom.config import AppConfig, NovelLoomConfig, ServerConfig
from novelloom.engine import NovelLoomEngine


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[NovelLoomEngine]:
    config = NovelLoomConfig(
        app=AppConfig(
            database_url=f"sqlite:///{tmp_path / 'novelloom.db'}",
            checkpoint_path=str(tmp_path / "checkpoints.db"),
            output_dir=str(tmp_path / "exports"),
        ),
        server=ServerConfig(open_browser=False),
    )
    instance = NovelLoomEngine(config)
    yield instance
    instance.close()


@pytest.fixture
def project(engine: NovelLoomEngine) -> dict[str, object]:
    return engine.projects.create_project(
        name="雾港纪事",
        premise="退役领航员调查一座会遗忘人的港口。",
        books=[
            {"key": "main", "type": "main", "title": "雾港纪事"},
            {
                "key": "bio",
                "type": "biography",
                "title": "伊澜传",
                "source_book": "main",
            },
        ],
    )
