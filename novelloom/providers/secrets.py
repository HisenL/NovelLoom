from __future__ import annotations

import os

import keyring


class SecretNotFound(RuntimeError):
    pass


class SecretStore:
    """Resolves environment and OS-keyring references without persisting secret values."""

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self.overrides = overrides or {}

    def resolve(self, reference: str) -> str:
        if reference in self.overrides:
            return self.overrides[reference]
        value: str | None
        if reference.startswith("env:"):
            value = os.getenv(reference.removeprefix("env:"), "")
        elif reference.startswith("keyring:"):
            service, _, username = reference.removeprefix("keyring:").partition("/")
            value = keyring.get_password(service, username) if service and username else None
        elif not reference:
            value = ""
        else:
            raise SecretNotFound("secret_ref 只允许 env: 或 keyring: 引用")
        if not value:
            raise SecretNotFound(f"未找到密钥引用: {reference}")
        return value

    def set_keyring(self, reference: str, value: str) -> None:
        if not reference.startswith("keyring:"):
            raise ValueError("只能写入 keyring: 引用")
        service, _, username = reference.removeprefix("keyring:").partition("/")
        if not service or not username:
            raise ValueError("keyring 引用格式应为 keyring:service/username")
        keyring.set_password(service, username, value)
