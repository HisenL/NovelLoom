from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), match.group(0)), value)
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    return value


class AppConfig(BaseModel):
    database_url: str = "sqlite:///./data/novelloom.db"
    checkpoint_path: str = "./data/checkpoints.db"
    output_dir: str = "./exports"
    language: str = "zh-CN"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8123, ge=1, le=65535)
    open_browser: bool = True

    @field_validator("host")
    @classmethod
    def localhost_only(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("v0.1 只允许监听 localhost")
        return value


class RuntimeConfig(BaseModel):
    max_concurrent_projects: int = Field(default=1, ge=1, le=16)
    default_token_budget: int = Field(default=1_000_000, ge=1)
    default_cost_budget: float | None = Field(default=None, ge=0)


class NovelLoomConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    providers: list[dict[str, Any]] = Field(default_factory=list)


def load_config(path: str | Path | None = None) -> NovelLoomConfig:
    configured_path = path if path is not None else os.getenv("NOVELLOOM_CONFIG")
    target = Path(configured_path or "novelloom.config.yaml")
    if not target.exists():
        return NovelLoomConfig()
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return NovelLoomConfig.model_validate(_expand(raw))


def generate_default_config(path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(
            NovelLoomConfig().model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
