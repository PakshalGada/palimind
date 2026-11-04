"""Persistent per-agent workspace and artifact listing.

Every agent owns a folder that survives between runs and holds the files it
produces. The tools sandbox already exposes this folder via ``scope``; this
module adds the API-facing listing/preview helpers and a prompt block.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from palimind.agents.catalog import GLOBAL_AGENTS_DIR, AgentDefinition

MAX_FILES = 5000
MAX_BYTES = 200_000_000
_TEXT_SUFFIXES = {
    "",
    ".md",
    ".txt",
    ".json",
    ".csv",
    ".tsv",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".log",
    ".xml",
    ".sql",
}


def workspace_path(agent_id: str) -> Path:
    return GLOBAL_AGENTS_DIR / agent_id / "workspace"


def ensure_workspace(agent_id: str, override: str = "") -> Path:
    if override:
        path = Path(override).expanduser()
    else:
        path = workspace_path(agent_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe(base: Path, rel: str) -> Path:
    target = (base / str(rel or "")).resolve()
    root = base.resolve()
    if target != root and root not in target.parents:
        raise ValueError("path escapes the workspace")
    return target


def list_files(agent_id: str, rel: str = "", override: str = "") -> list[dict[str, Any]]:
    base = ensure_workspace(agent_id, override)
    target = _safe(base, rel)
    if not target.exists() or not target.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:MAX_FILES]:
        try:
            stat = entry.stat()
        except OSError:
            continue
        items.append(
            {
                "name": entry.name,
                "path": str(entry.relative_to(base)),
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size if entry.is_file() else 0,
                "modified": stat.st_mtime,
                "ext": entry.suffix.lower(),
            }
        )
    return items


def read_file(
    agent_id: str, rel: str, override: str = "", max_chars: int = 200_000
) -> dict[str, Any]:
    base = ensure_workspace(agent_id, override)
    target = _safe(base, rel)
    if not target.is_file():
        raise FileNotFoundError(rel)
    if target.stat().st_size > MAX_BYTES:
        raise ValueError("file is too large to preview")
    if target.suffix.lower() not in _TEXT_SUFFIXES:
        return {
            "path": rel,
            "binary": True,
            "size": target.stat().st_size,
            "content": "",
            "mime": "application/octet-stream",
        }
    content = target.read_text("utf-8", errors="replace")[:max_chars]
    return {"path": rel, "binary": False, "size": target.stat().st_size, "content": content}


def write_file(agent_id: str, rel: str, content: str, override: str = "") -> dict[str, Any]:
    base = ensure_workspace(agent_id, override)
    target = _safe(base, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, "utf-8")
    return {"path": rel, "size": target.stat().st_size}


def delete_file(agent_id: str, rel: str, override: str = "") -> bool:
    base = ensure_workspace(agent_id, override)
    target = _safe(base, rel)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
        return True
    if target.is_file():
        target.unlink(missing_ok=True)
        return True
    return False


def purge_workspace(agent_id: str) -> None:
    override = ""
    try:
        from palimind.agents.registry import get_registry

        defn = get_registry().get_by_id(agent_id)
        override = str(getattr(defn, "workspace_dir", "") or "") if defn else ""
    except Exception:
        pass
    shutil.rmtree(override or workspace_path(agent_id), ignore_errors=True)


def workspace_context_block(definition: AgentDefinition) -> str:
    try:
        base = ensure_workspace(definition.id, str(definition.workspace_dir or ""))
        files = list_files(definition.id, override=str(definition.workspace_dir or ""))
    except Exception:
        return ""
    lines = [f"Workspace: {base}"]
    for item in files[:12]:
        if item["type"] == "file":
            lines.append(f"  - {item['path']} ({item['size']} bytes)")
    if not files:
        lines.append("  (empty — write deliverables here with write_file)")
    return "[WORKSPACE]\n" + "\n".join(lines) + "\n"
