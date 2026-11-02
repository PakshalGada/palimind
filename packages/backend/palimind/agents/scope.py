"""Agent knowledge scope + memory store resolution.

A definition carries a JSON-safe ``knowledge_scope``:
    {"mode": "all" | "personal" | "project",
     "primary_field": "<path>",
     "extra_fields": ["<path>", ...]}

Reads may span the primary root plus the extra roots; writes only ever target
the primary root. "personal" gives the agent its own workspace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from palimind.agents.catalog import GLOBAL_AGENTS_DIR, AgentDefinition

GLOBAL_CONFIG_PATH = Path.home() / ".palimind_global.json"


def configured_fields() -> list[Path]:
    """Return every configured knowledge-base root (existing directories)."""
    try:
        data = json.loads(GLOBAL_CONFIG_PATH.read_text("utf-8"))
    except Exception:
        return []
    out: list[Path] = []
    for raw in data.get("fields", []) or []:
        try:
            path = Path(str(raw)).expanduser()
        except Exception:
            continue
        if path.is_dir():
            resolved = path.resolve()
            if resolved not in out:
                out.append(resolved)
    return out


def personal_workspace(defn: AgentDefinition) -> Path:
    path = GLOBAL_AGENTS_DIR / defn.id / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scope(defn: AgentDefinition) -> dict[str, Any]:
    scope = defn.knowledge_scope
    if not isinstance(scope, dict):
        return {"mode": "all", "primary_field": "", "extra_fields": []}
    return scope


def resolve_scope(
    defn: AgentDefinition,
    active_root: Path | None = None,
) -> tuple[Path | None, list[Path]]:
    """Resolve ``(primary_root, read_only_extra_roots)`` for a run."""
    scope = _scope(defn)
    mode = scope.get("mode") or "all"
    fields = configured_fields()

    if mode == "personal":
        return personal_workspace(defn), []

    primary: Path | None = None
    raw_primary = str(scope.get("primary_field") or "").strip()
    if raw_primary:
        candidate = Path(raw_primary).expanduser()
        if candidate.is_dir():
            primary = candidate.resolve()

    if primary is None and active_root is not None and active_root.is_dir():
        primary = active_root.resolve()
    if primary is None and fields:
        primary = fields[0]
    if primary is None:
        primary = personal_workspace(defn)

    extras: list[Path] = []
    if mode == "all":
        extras = [f for f in fields if f != primary]
    elif mode == "project":
        for raw in scope.get("extra_fields") or []:
            try:
                candidate = Path(str(raw)).expanduser().resolve()
            except Exception:
                continue
            if candidate.is_dir() and candidate != primary and candidate not in extras:
                extras.append(candidate)

    return primary, extras


def primary_root(defn: AgentDefinition, active_root: Path | None = None) -> Path | None:
    return resolve_scope(defn, active_root)[0]


def memory_file_for(defn: AgentDefinition, active_root: Path | None = None) -> Path | None:
    """Resolve the agent's memory store for its current ``memory_mode``."""
    mode = defn.memory_mode or "off"
    if mode == "off":
        return None
    if mode == "shared":
        return GLOBAL_AGENTS_DIR / "memory" / "_shared.json"
    if mode == "project":
        root = primary_root(defn, active_root)
        if root is None:
            return GLOBAL_AGENTS_DIR / "memory" / f"{defn.id}.json"
        return root / ".palimind" / "agents" / "memory" / f"{defn.id}.json"
    return GLOBAL_AGENTS_DIR / "memory" / f"{defn.id}.json"
