"""Discovery and lookup for in-app agent tools.

Tools are folders under ``palimind/agents/tools/<name>/`` containing a
``tool.json`` manifest and an entrypoint module. Legacy plain-function
modules are wrapped with :class:`FunctionTool`.
"""

from __future__ import annotations

import importlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from palimind.agents.tools.base import PERMISSIONS, Tool

logger = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent
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
    module_name = f"palimind.agents.tools.{tool_dir.name}.{manifest.entrypoint.removesuffix('.py')}"
    return importlib.import_module(module_name)


def discover_tools() -> dict[str, Tool]:
    """Scan the tools directory and instantiate every declared tool."""
    tools: dict[str, Tool] = {}
    for folder in sorted(TOOLS_DIR.iterdir()):
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

                    tool = FunctionTool(
                        func,
                        name=manifest.name,
                        description=manifest.description,
                        permissions=tuple(manifest.permissions),
                        timeout_s=manifest.timeout_s,
                    )
                tools[tool.name] = tool
        except Exception as exc:  # noqa: BLE001 - one bad tool must not kill all
            logger.warning("Failed to load tool %s: %s", folder.name, exc)
    return tools


_registry: dict[str, Tool] | None = None


def get_registry() -> dict[str, Tool]:
    global _registry
    if _registry is None:
        _registry = discover_tools()
    return _registry


def get_tool(name: str) -> Tool | None:
    return get_registry().get(name)


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "permissions": list(t.permissions),
            "timeout_s": t.timeout_s,
        }
        for t in get_registry().values()
    ]
