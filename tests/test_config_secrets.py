from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from novelloom.config import ServerConfig, generate_default_config, load_config
from novelloom.providers.secrets import SecretNotFound, SecretStore


def test_config_generation_and_environment_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_path = tmp_path / "default.yaml"
    generate_default_config(default_path)
    assert load_config(default_path).server.host == "127.0.0.1"
    custom = tmp_path / "custom.yaml"
    custom.write_text("app:\n  output_dir: ${OUTPUT_DIR}\n", encoding="utf-8")
    monkeypatch.setenv("OUTPUT_DIR", "./custom-output")
    assert load_config(custom).app.output_dir == "./custom-output"
    assert load_config(tmp_path / "missing.yaml").app.language == "zh-CN"
    with pytest.raises(ValidationError, match="localhost"):
        ServerConfig(host="0.0.0.0")


def test_secret_store_only_resolves_references(monkeypatch: pytest.MonkeyPatch) -> None:
    store = SecretStore({"env:OVERRIDE": "override"})
    assert store.resolve("env:OVERRIDE") == "override"
    monkeypatch.setenv("REAL_KEY", "secret")
    assert store.resolve("env:REAL_KEY") == "secret"
    with pytest.raises(SecretNotFound):
        store.resolve("env:MISSING_KEY")
    with pytest.raises(SecretNotFound, match="只允许"):
        store.resolve("plaintext")
    with pytest.raises(ValueError):
        store.set_keyring("env:BAD", "secret")
