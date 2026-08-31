from __future__ import annotations

import threading
from pathlib import Path

from palimind.agents.catalog import AgentCatalog

_registry: AgentCatalog | None = None
_registry_lock = threading.Lock()


def get_registry() -> AgentCatalog:
    """Return the process-wide AgentCatalog singleton.

    Initialized lazily on first access. Agents are global — they live in
    ``~/.palimind/agents`` and are shared across every knowledge base and the
    global chat.
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                from palimind.agents.presets import seed_preset_agents

                try:
                    seed_preset_agents()
                except Exception as e:
                    print(f"[agents] preset seeding failed: {e}")
                _registry = AgentCatalog()
                _registry.load()
    return _registry


def set_registry_field(field_root: Path | None) -> None:
    """Record the active field root on the singleton catalog.

    Agents themselves are global, but the active field root is kept so agent
    runs started outside a chat context (Agents panel, scheduler) default to
    that knowledge base as their working root.
    """
    reg = get_registry()
    with _registry_lock:
        reg.field_root = field_root


def reset_registry() -> None:
    """Replace the singleton (used mainly for tests / hot reloads)."""
    global _registry
    with _registry_lock:
        _registry = AgentCatalog()
        _registry.load()
