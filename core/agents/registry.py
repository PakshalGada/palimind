from __future__ import annotations

import threading
from pathlib import Path

from core.agents.catalog import AgentCatalog

_registry: AgentCatalog | None = None
_registry_lock = threading.Lock()


def get_registry() -> AgentCatalog:
    """Return the process-wide AgentCatalog singleton.

    Initialized lazily on first access and (re)loaded at FastAPI startup
    with the active field so field-scoped agents resolve correctly.
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = AgentCatalog()
                _registry.load()
    return _registry


def set_registry_field(field_root: Path | None) -> None:
    """Repoint the singleton catalog at a field root and reload.

    Called whenever the active field changes (e.g. at FastAPI startup and
    when the user switches fields) so field-scoped agents merge correctly.
    """
    reg = get_registry()
    with _registry_lock:
        reg.field_root = field_root
        reg.load()


def reset_registry() -> None:
    """Replace the singleton (used mainly for tests / hot reloads)."""
    global _registry
    with _registry_lock:
        _registry = AgentCatalog()
        _registry.load()
