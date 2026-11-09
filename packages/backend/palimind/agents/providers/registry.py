"""Provider registry and model catalog merging.

Adapters register a zero-argument factory.  The registry never imports optional
third-party packages at module import time; a provider that cannot load reports
itself as unavailable instead of breaking the agent API.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from palimind.agents.providers.base import ProviderClient, ProviderModel

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[], ProviderClient]


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}
        self._instances: dict[str, ProviderClient] = {}
        self._errors: dict[str, str] = {}

    def register(
        self, provider_id: str, factory: ProviderFactory, *, replace: bool = False
    ) -> None:
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise ValueError("provider id is required")
        if provider_id in self._factories and not replace:
            raise ValueError(f"provider already registered: {provider_id}")
        self._factories[provider_id] = factory
        self._instances.pop(provider_id, None)
        self._errors.pop(provider_id, None)

    def unregister(self, provider_id: str) -> None:
        self._factories.pop(provider_id, None)
        self._instances.pop(provider_id, None)
        self._errors.pop(provider_id, None)

    def ids(self) -> list[str]:
        return sorted(self._factories)

    def get(self, provider_id: str) -> ProviderClient | None:
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            return None
        if provider_id in self._instances:
            return self._instances[provider_id]
        factory = self._factories.get(provider_id)
        if factory is None:
            return None
        try:
            instance = factory()
            instance.id = provider_id
            self._instances[provider_id] = instance
            self._errors.pop(provider_id, None)
            return instance
        except Exception as exc:  # noqa: BLE001 - one bad adapter must not break all
            self._errors[provider_id] = str(exc)
            logger.warning("Provider %s failed to initialize: %s", provider_id, exc)
            return None

    def status(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for provider_id in self.ids():
            client = self.get(provider_id)
            if client is None:
                out.append(
                    {
                        "id": provider_id,
                        "available": False,
                        "error": self._errors.get(provider_id, "not available"),
                    }
                )
                continue
            out.append(
                {
                    "id": provider_id,
                    "available": True,
                    "capabilities": client.capabilities.as_dict(),
                    "error": "",
                }
            )
        return out

    async def models(self, provider_id: str = "") -> list[ProviderModel]:
        targets = [provider_id] if provider_id else self.ids()
        models: list[ProviderModel] = []
        for target in targets:
            client = self.get(target)
            if client is None:
                continue
            try:
                models.extend(await client.list_models())
            except Exception as exc:  # noqa: BLE001
                self._errors[target] = str(exc)
                logger.warning("Provider %s model list failed: %s", target, exc)
        return models

    async def close(self) -> None:
        for client in list(self._instances.values()):
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        self._instances.clear()


_registry = ProviderRegistry()


def get_provider_registry() -> ProviderRegistry:
    _ensure_defaults()
    return _registry


def _ensure_defaults() -> None:
    if _registry.ids():
        return
    from palimind.agents.providers.ollama import OllamaProvider

    _registry.register("ollama", OllamaProvider)
    try:
        from palimind.agents.providers.openai_compat import OpenAICompatibleProvider

        _registry.register("openai", OpenAICompatibleProvider)
    except Exception:  # noqa: BLE001 - optional adapter
        pass
    try:
        import os

        from palimind.agents.providers.acp import ACPProvider

        if os.environ.get("PALIMIND_ACP_COMMAND", "").strip():
            _registry.register("acp", ACPProvider)
    except Exception:  # noqa: BLE001 - optional adapter
        pass
    try:
        from palimind.agents.providers.presets import register_presets

        register_presets(_registry)
    except Exception:  # noqa: BLE001 - optional presets
        pass
    try:
        import shutil

        from palimind.agents.providers.claude import ClaudeProvider
        from palimind.agents.providers.codex import CodexProvider

        if os.environ.get("PALIMIND_CODEX_COMMAND") or shutil.which("codex"):
            _registry.register("codex", CodexProvider)
        if os.environ.get("PALIMIND_CLAUDE_COMMAND") or shutil.which("claude"):
            _registry.register("claude", ClaudeProvider)
    except Exception:  # noqa: BLE001 - optional adapters
        pass


def register_provider(provider_id: str, factory: ProviderFactory, *, replace: bool = False) -> None:
    _registry.register(provider_id, factory, replace=replace)


def reset_provider_registry() -> None:
    """Test hook: unregister everything so a test can install fakes."""
    for provider_id in _registry.ids():
        _registry.unregister(provider_id)
