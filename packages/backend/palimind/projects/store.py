"""Project persistence and lifecycle.

A project is a durable, global workspace concept. Its metadata lives in the
shared ``state.db`` under the ``projects`` namespace, while everything private
to it (sessions, index, artifacts, config) lives in an isolated folder:

    ~/.palimind/projects/<project_id>/

The user's actual files stay where they are; ``workspace_path`` points at the
folder that should be indexed for that project. Deleting a project removes the
private folder only — never the user's workspace.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from palimind.security.tokens import palimind_home
from palimind.storage import state_store

NAMESPACE = "projects"
_ID_RE = re.compile(r"^[\w-]{1,64}$")
_EDITABLE = ("name", "description", "workspace_path")


def projects_dir() -> Path:
    """Root folder holding every project's private store."""
    return palimind_home() / "projects"


def project_dir(project_id: str) -> Path:
    if not _ID_RE.match(str(project_id)):
        raise ValueError(f"Invalid project_id: {project_id!r}")
    return projects_dir() / str(project_id)


def project_scope(project_id: str) -> str:
    return f"project:{project_id}"


def _now() -> float:
    return time.time()


def _with_scope(project: dict[str, Any]) -> dict[str, Any]:
    out = dict(project)
    out["scope"] = project_scope(str(out.get("id", "")))
    out.setdefault("description", "")
    out.setdefault("workspace_path", "")
    out.setdefault("kb", {})
    return out


def _workspace_path(project_id: str, root: Path, raw: Any) -> Path:
    """Resolve a workspace path, creating it when it does not exist yet."""
    if raw in (None, ""):
        workspace = root / "workspace"
    else:
        workspace = Path(str(raw)).expanduser()
        if not workspace.is_absolute():
            workspace = (root / workspace).resolve()
    if workspace.exists() and not workspace.is_dir():
        raise ValueError(f"workspace_path is not a directory: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace.resolve()


def list_projects(query: str | None = None) -> list[dict[str, Any]]:
    """Return project summaries, newest activity first. Missing dirs are fine."""
    projects = [_with_scope(p) for p in state_store.list_json(NAMESPACE, limit=10_000)]
    if query and query.strip():
        needle = query.strip().lower()
        projects = [
            p
            for p in projects
            if needle in str(p.get("name", "")).lower()
            or needle in str(p.get("description", "")).lower()
            or needle in str(p.get("workspace_path", "")).lower()
        ]
    projects.sort(key=lambda p: float(p.get("updated_at") or 0), reverse=True)
    return projects


def get_project(project_id: str) -> dict[str, Any] | None:
    project = state_store.get_json(NAMESPACE, str(project_id), default=None)
    if not isinstance(project, dict):
        return None
    return _with_scope(project)


def create_project(
    name: str,
    description: str = "",
    workspace_path: str | Path | None = None,
) -> dict[str, Any]:
    """Create metadata + the isolated project folder. Never touches the workspace."""
    project_id = uuid.uuid4().hex
    root = project_dir(project_id)
    root.mkdir(parents=True, exist_ok=False)
    try:
        workspace = _workspace_path(project_id, root, workspace_path)
        now = _now()
        project = {
            "id": project_id,
            "name": name.strip() or "Untitled Project",
            "description": description or "",
            "workspace_path": str(workspace),
            "created_at": now,
            "updated_at": now,
            "last_opened_at": None,
            "kb": {},
        }
        state_store.set_json(NAMESPACE, project_id, project)
    except Exception:
        # Do not leave an orphan folder if the metadata write fails.
        shutil.rmtree(root, ignore_errors=True)
        raise
    return _with_scope(project)


def update_project(project_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    project = get_project(project_id)
    if project is None:
        return None
    changed = False
    for key in _EDITABLE:
        if key not in changes:
            continue
        if key == "workspace_path":
            root = project_dir(project_id)
            workspace = _workspace_path(project_id, root, changes[key])
            project[key] = str(workspace)
        elif key == "name":
            value = str(changes[key]).strip()
            if value:
                project[key] = value
        elif key == "description":
            project[key] = str(changes[key] or "")
        changed = True
    if changed:
        project["updated_at"] = _now()
        state_store.set_json(NAMESPACE, project_id, project)
    return _with_scope(project)


def delete_project(project_id: str) -> bool:
    """Delete the project row and its private folder (not the workspace)."""
    project = get_project(project_id)
    if project is None:
        return False
    state_store.delete_json(NAMESPACE, project_id)
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
    return True


def touch_project(project_id: str) -> dict[str, Any] | None:
    """Mark a project as opened/used without changing its content."""
    project = get_project(project_id)
    if project is None:
        return None
    now = _now()
    project["last_opened_at"] = now
    project["updated_at"] = now
    state_store.set_json(NAMESPACE, project_id, project)
    return _with_scope(project)


def record_kb_sync(
    project_id: str,
    *,
    indexed_files: int = 0,
    deleted_files: int = 0,
    unchanged_files: int = 0,
    chunks_indexed: int = 0,
    file_errors: int = 0,
    status: str = "idle",
    error: str = "",
) -> dict[str, Any] | None:
    """Persist the last KB sync summary on the project record."""
    project = get_project(project_id)
    if project is None:
        return None
    project["kb"] = {
        "last_synced_at": _now(),
        "indexed_files": int(indexed_files),
        "deleted_files": int(deleted_files),
        "unchanged_files": int(unchanged_files),
        "chunks_indexed": int(chunks_indexed),
        "file_errors": int(file_errors),
        "status": status,
        "error": error,
    }
    project["updated_at"] = _now()
    state_store.set_json(NAMESPACE, project_id, project)
    return _with_scope(project)


def ensure_project_dir(project_id: str) -> Path:
    """Return the private folder, recreating it if it was removed manually."""
    root = project_dir(project_id)
    root.mkdir(parents=True, exist_ok=True)
    return root
