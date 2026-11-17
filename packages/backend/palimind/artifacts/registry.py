"""Global artifact library registry.

Project artifacts live in their project folder (see ``palimind.projects``).
This registry is the global, searchable index for artifacts saved outside a
project, plus artifacts pinned from any conversation. Metadata and text
content are stored in the shared ``state.db`` so the library survives restarts.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from palimind.storage import state_store

NAMESPACE = "artifacts"
_MAX_RESULTS = 500
# Bounded history per artifact: the oldest snapshots fall off first.
_MAX_VERSIONS = 40


def _now() -> float:
    return time.time()


def _detect_type(content: str) -> str:
    text = content.lstrip()
    lower = text.lower()
    if lower.startswith("<svg") or "<svg" in lower[:400]:
        return "svg"
    if lower.startswith("<!doctype html") or lower.startswith("<html"):
        return "html"
    if (
        lower.startswith("graph ")
        or lower.startswith("flowchart ")
        or lower.startswith("sequencediagram")
    ):
        return "mermaid"
    if "# " in text[:200] or "| ---" in text:
        return "markdown"
    return "code"


def _detect_title(content: str, fallback: str = "Artifact") -> str:
    heading = re.search(r"^\s*#{1,6}\s+(.+)$", content, flags=re.MULTILINE)
    if heading:
        return heading.group(1).strip()[:72]
    title = re.search(r"<title[^>]*>([^<]+)</title>", content, flags=re.IGNORECASE)
    if title:
        return title.group(1).strip()[:72]
    return fallback


def _summary(artifact: dict[str, Any]) -> dict[str, Any]:
    versions = artifact.get("versions") or []
    return {
        "id": str(artifact.get("id", "")),
        "title": str(artifact.get("title", "Artifact")),
        "type": str(artifact.get("type", "code")),
        "language": str(artifact.get("language", "")),
        "description": str(artifact.get("description", "")),
        "project_id": str(artifact.get("project_id", "")),
        "source": str(artifact.get("source", "")),
        "size": len(str(artifact.get("content", ""))),
        "version_count": len(versions),
        "current_version": int(artifact.get("current_version", 0) or 0),
        "created_at": float(artifact.get("created_at", 0) or 0),
        "updated_at": float(artifact.get("updated_at", 0) or 0),
    }


def list_artifacts(
    query: str | None = None,
    project_id: str | None = None,
    include_content: bool = False,
) -> list[dict[str, Any]]:
    items = [
        item
        for item in state_store.list_json(NAMESPACE, limit=10_000)
        if isinstance(item, dict) and item.get("id")
    ]
    if project_id:
        items = [item for item in items if str(item.get("project_id", "")) == project_id]
    if query and query.strip():
        needle = query.strip().lower()
        items = [
            item
            for item in items
            if needle in str(item.get("title", "")).lower()
            or needle in str(item.get("content", "")).lower()
            or needle in str(item.get("type", "")).lower()
            or needle in str(item.get("language", "")).lower()
        ]
    items.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    out = []
    for item in items[:_MAX_RESULTS]:
        summary = _summary(item)
        if include_content:
            summary["content"] = str(item.get("content", ""))
        out.append(summary)
    return out


def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    item = state_store.get_json(NAMESPACE, str(artifact_id), default=None)
    return item if isinstance(item, dict) else None


def save_artifact(data: dict[str, Any], artifact_id: str | None = None) -> dict[str, Any]:
    now = _now()
    existing = get_artifact(artifact_id) if artifact_id else None
    content = data.get("content")
    if content is None:
        content = existing.get("content", "") if existing else ""
    new_content = str(content or "")

    # Version history: saving over an existing artifact snapshots the content
    # it replaces instead of silently discarding it ("the first draft was
    # better" must stay recoverable). Mirrors the project artifact store.
    versions = [v for v in (existing or {}).get("versions") or [] if isinstance(v, dict)]
    if existing is not None:
        old_content = str(existing.get("content", ""))
        if old_content and old_content != new_content:
            next_number = max((int(v.get("version", 0) or 0) for v in versions), default=0) + 1
            versions.append(
                {
                    "version": next_number,
                    "saved_at": float(existing.get("updated_at") or now),
                    "size": len(old_content),
                    "note": "Replaced by a newer save",
                    "content": old_content,
                }
            )
            versions = versions[-_MAX_VERSIONS:]

    artifact = {
        "id": artifact_id or str(uuid.uuid4().hex),
        "title": str(
            data.get("title") or (existing or {}).get("title") or _detect_title(str(content or ""))
        ),
        "type": str(
            data.get("type") or (existing or {}).get("type") or _detect_type(str(content or ""))
        ),
        "language": str(data.get("language") or (existing or {}).get("language", "")),
        "description": str(data.get("description") or (existing or {}).get("description", "")),
        "project_id": str(data.get("project_id") or (existing or {}).get("project_id", "")),
        "source": str(data.get("source") or (existing or {}).get("source", "")),
        "session_id": str(data.get("session_id") or (existing or {}).get("session_id", "")),
        "message_id": str(data.get("message_id") or (existing or {}).get("message_id", "")),
        "content": new_content,
        "versions": versions,
        "current_version": max((int(v.get("version", 0) or 0) for v in versions), default=0),
        "created_at": float((existing or {}).get("created_at") or now),
        "updated_at": now,
    }
    state_store.set_json(NAMESPACE, artifact["id"], artifact)
    return artifact


def list_versions(artifact_id: str) -> list[dict[str, Any]]:
    """Version summaries (no bodies) for a registry artifact, oldest first."""
    artifact = get_artifact(artifact_id)
    if artifact is None:
        return []
    return [
        {
            "version": int(v.get("version", 0) or 0),
            "saved_at": float(v.get("saved_at", 0) or 0),
            "size": int(v.get("size", 0) or 0),
            "note": str(v.get("note", "")),
        }
        for v in artifact.get("versions") or []
        if isinstance(v, dict)
    ]


def get_artifact_version(artifact_id: str, version: int) -> dict[str, Any] | None:
    """Read one historical version body, or None when it does not exist."""
    artifact = get_artifact(artifact_id)
    if artifact is None:
        return None
    for v in artifact.get("versions") or []:
        if isinstance(v, dict) and int(v.get("version", 0) or 0) == int(version):
            return {
                "version": int(v.get("version", 0) or 0),
                "saved_at": float(v.get("saved_at", 0) or 0),
                "note": str(v.get("note", "")),
                "content": str(v.get("content", "")),
            }
    return None


def delete_artifact(artifact_id: str) -> bool:
    existing = get_artifact(artifact_id)
    if existing is None:
        return False
    state_store.delete_json(NAMESPACE, artifact_id)
    return True


def migrate_canvas_documents() -> int:
    """Import legacy Canvas documents into the artifact library once.

    Canvas was removed as a feature; its files live under
    ``~/.palimind/canvases/*.json``. Importing them as global artifacts keeps
    existing work accessible from the new Artifacts page.
    """
    from palimind.security.tokens import palimind_home

    marker = state_store.get_json("migrations", "canvas-documents", default=None)
    if marker is not None:
        return 0

    directory = palimind_home() / "canvases"
    migrated = 0
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text("utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            canvas_id = str(data.get("id") or path.stem)
            artifact_id = f"canvas-{canvas_id}"
            if get_artifact(artifact_id) is not None:
                continue
            content = str(data.get("content") or "")
            now = _now()
            artifact = {
                "id": artifact_id,
                "title": str(data.get("title") or _detect_title(content)),
                "type": _detect_type(content),
                "language": "",
                "description": "Migrated from Canvas",
                "project_id": "",
                "source": "canvas-migration",
                "session_id": "",
                "message_id": "",
                "content": content,
                "created_at": float(data.get("created_at") or now),
                "updated_at": float(data.get("updated_at") or now),
            }
            state_store.set_json(NAMESPACE, artifact_id, artifact)
            migrated += 1

    state_store.set_json(
        "migrations",
        "canvas-documents",
        {"completed_at": _now(), "migrated": migrated},
    )
    return migrated
