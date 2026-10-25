"""Project-scoped session persistence.

Sessions for a project are stored in the project's private folder by reusing
the shared SQLite session store. Passing the project root as the store root is
what keeps project conversations completely separate from global, field and
agent sessions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from palimind.memory import session_store as _sessions
from palimind.projects.store import ensure_project_dir, get_project


def _root(project_id: str) -> Path:
    if get_project(project_id) is None:
        raise FileNotFoundError(f"Project not found: {project_id}")
    return ensure_project_dir(project_id)


def project_root(project_id: str) -> Path:
    return _root(project_id)


def list_sessions(project_id: str, root: Path | None = None) -> dict[str, Any]:
    return _sessions.load_sessions(root or _root(project_id))


def new_session(project_id: str, name: str = "New Session", root: Path | None = None) -> dict[str, Any]:
    return _sessions.add_new_session(root or _root(project_id), name)


def set_active_session(
    project_id: str, session_id: str, root: Path | None = None
) -> dict[str, Any]:
    return _sessions.set_active_session_id(root or _root(project_id), session_id)


def delete_session(project_id: str, session_id: str, root: Path | None = None) -> dict[str, Any]:
    return _sessions.delete_session(root or _root(project_id), session_id)


def append_message(
    project_id: str,
    session_id: str,
    role: str,
    content: str,
    *,
    sources: list[str] | None = None,
    mode: str = "",
    mode_params: dict | None = None,
    citations: list[dict] | dict | None = None,
    root: Path | None = None,
) -> None:
    _sessions.append_message_to_session(
        root or _root(project_id),
        session_id,
        role,
        content,
        sources=sources,
        mode=mode,
        mode_params=mode_params,
        citations=citations,
    )


def get_session(project_id: str, session_id: str, root: Path | None = None) -> dict | None:
    return _sessions.load_session_by_id(root or _root(project_id), session_id)
