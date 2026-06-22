from __future__ import annotations

from importlib.metadata import entry_points

from .anthropic import AnthropicProvider
from .base import ProviderAdapter
from .gemini import GeminiProvider
from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider


class ProviderRegistry:
    def __init__(self, *, discover_plugins: bool = True) -> None:
        self._providers: dict[str, ProviderAdapter] = {}
        self.register(OpenAICompatibleProvider())
        self.register(AnthropicProvider())
        self.register(GeminiProvider())
        self.register(MockProvider())
        if discover_plugins:
            self.discover()

    def register(self, provider: ProviderAdapter) -> None:
        self._providers[provider.name] = provider

    def discover(self) -> None:
        for point in entry_points(group="novelloom.providers"):
            if point.name in self._providers:
                continue
            loaded = point.load()
            provider = loaded() if isinstance(loaded, type) else loaded
            if isinstance(provider, ProviderAdapter):
                self.register(provider)

    def get(self, name: str) -> ProviderAdapter:
        try:
            return self._providers[name]
        except KeyError as error:
            raise KeyError(f"未知 Provider: {name}") from error

    def names(self) -> list[str]:
        return sorted(self._providers)
