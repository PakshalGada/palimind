"""Discovery and lookup for in-app agent tools.

Tools are folders under ``palimind/agents/tools/<name>/`` containing a
``tool.json`` manifest and an entrypoint module. Legacy plain-function
modules are wrapped with :class:`FunctionTool`.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from palimind.agents.tools.base import PERMISSIONS, Tool

logger = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent
#: Drop-in user tools. A folder here needs the same ``tool.json`` + entrypoint
#: layout as a built-in tool. Built-ins always win on a name collision.
USER_TOOLS_DIR = Path.home() / ".palimind" / "tools"
MANIFEST_NAME = "tool.json"


@dataclass
class ToolManifest:
    name: str
    version: str
    description: str
    entrypoint: str
    permissions: list[str]
    timeout_s: int
    function: str  # dotted attribute inside the entrypoint module

    @classmethod
    def from_dict(cls, data: dict[str, Any], folder: str) -> ToolManifest:
        name = data.get("name") or folder
        return cls(
            name=name,
            version=str(data.get("version", "0.0.0")),
            description=data.get("description", ""),
            entrypoint=data.get("entrypoint", "tool.py"),
            permissions=list(data.get("permissions", [])),
            timeout_s=int(data.get("timeout_s", 30)),
            function=data.get("function", ""),
        )


def _manifest_path(folder: Path) -> Path | None:
    p = folder / MANIFEST_NAME
    return p if p.exists() else None


def _load_module(tool_dir: Path, manifest: ToolManifest):
    """Import a built-in or user tool module.

    Built-ins live inside the package and use normal imports. User tools live
    outside the package, so they are loaded from their file path with a unique
    synthetic module name (no ``sys.path`` pollution).
    """
    entry = (tool_dir / manifest.entrypoint).resolve()
    root = tool_dir.resolve()
    if entry != root and root not in entry.parents:
        raise ValueError("entrypoint escapes the tool folder")
    if not entry.is_file():
        raise FileNotFoundError(f"entrypoint not found: {manifest.entrypoint}")

    try:
        entry.relative_to(TOOLS_DIR)
        module_name = f"palimind.agents.tools.{tool_dir.name}.{entry.stem}"
        return importlib.import_module(module_name)
    except ValueError:
        module_name = f"_palimind_user_tool_{tool_dir.name}_{abs(hash(str(entry)))}"
        spec = importlib.util.spec_from_file_location(module_name, entry)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load user tool module {entry}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


def _scan_dir(tools: dict[str, Tool], base: Path, *, source: str) -> None:
    if not base.is_dir():
        return
    for folder in sorted(base.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        mpath = _manifest_path(folder)
        if mpath is None:
            continue
        try:
            data = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping tool %s: bad manifest (%s)", folder.name, exc)
            continue
        manifest = ToolManifest.from_dict(data, folder.name)
        if manifest.name in tools:
            logger.warning(
                "Skipping %s tool %s: a tool with that name is already loaded",
                source,
                manifest.name,
            )
            continue
        unknown = [p for p in manifest.permissions if p not in PERMISSIONS]
        if unknown:
            logger.warning("Tool %s requests unknown permissions: %s", manifest.name, unknown)
        try:
            module = _load_module(folder, manifest)
            func = getattr(module, manifest.function) if manifest.function else None
            if callable(func):
                tool_cls = getattr(module, "TOOL_CLASS", None)
                if tool_cls is not None:
                    tool = tool_cls()
                else:
                    from palimind.agents.tools.base import FunctionTool

                    definition = getattr(module, "TOOL_DEFINITION", {}) or {}
                    tool = FunctionTool(
                        func,
                        name=manifest.name,
                        description=manifest.description or definition.get("description", ""),
                        permissions=tuple(manifest.permissions),
                        timeout_s=manifest.timeout_s,
                        parameters=definition.get("parameters") or data.get("parameters"),
                        tier=int(definition.get("tier", data.get("tier", 1)) or 1),
                        requires_approval=bool(
                            definition.get(
                                "requires_approval", data.get("requires_approval", False)
                            )
                        ),
                        parallel_safe=bool(
                            definition.get("parallel_safe", data.get("parallel_safe", False))
                        ),
                        idempotent=bool(
                            definition.get("idempotent", data.get("idempotent", False))
                        ),
                    )
                tools[tool.name] = tool
                tool.source = source
        except Exception as exc:  # noqa: BLE001 - one bad tool must not kill all
            logger.warning("Failed to load %s tool %s: %s", source, folder.name, exc)


def discover_tools() -> dict[str, Tool]:
    """Scan built-in and user tool directories and instantiate every tool."""
    tools: dict[str, Tool] = {}
    _scan_dir(tools, TOOLS_DIR, source="builtin")
    _scan_dir(tools, USER_TOOLS_DIR, source="user")
    workspace_dir = os.environ.get("PALIMIND_WORKSPACE_TOOLS_DIR", "").strip()
    if workspace_dir:
        _scan_dir(tools, Path(workspace_dir).expanduser(), source="workspace")
    return tools


def discover_user_tools() -> dict[str, Tool]:
    """Scan only drop-in user (and optional workspace) tools."""
    tools: dict[str, Tool] = {}
    _scan_dir(tools, USER_TOOLS_DIR, source="user")
    workspace_dir = os.environ.get("PALIMIND_WORKSPACE_TOOLS_DIR", "").strip()
    if workspace_dir:
        _scan_dir(tools, Path(workspace_dir).expanduser(), source="workspace")
    return tools


_registry: dict[str, Tool] | None = None


def get_registry() -> dict[str, Tool]:
    global _registry
    if _registry is None:
        _registry = discover_tools()
    return _registry


def reload_tools() -> dict[str, Tool]:
    """Re-scan built-in/user tool folders (drop-in tools load without restart)."""
    global _registry
    _registry = discover_tools()
    return _registry


def get_tool(name: str) -> Tool | None:
    return get_registry().get(name)


def list_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in get_registry().values():
        try:
            spec = tool.spec().to_dict()
        except Exception:  # noqa: BLE001 - a bad tool must not hide the rest
            spec = {
                "name": tool.name,
                "description": tool.description,
                "parameters": {},
                "permissions": list(tool.permissions),
                "timeout_s": tool.timeout_s,
            }
        # Keep the historical bare "parameters" key as the JSON schema; the UI
        # and the model both consume it.
        tools.append(spec)
    return tools
