"""Project artifact collection with version metadata.

Artifacts are stored inside the project's private folder::

    ~/.palimind/projects/<id>/artifacts/
        index.json              # metadata + version list
        files/<artifact_id>/v1.html
        files/<artifact_id>/v2.html

The API never exposes private filesystem paths; it returns filenames, sizes,
checksums and a version number so the frontend can list, preview and export.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from palimind.projects import store

_EXTENSIONS = {
    "html": ".html",
    "svg": ".svg",
    "markdown": ".md",
    "md": ".md",
    "mermaid": ".mmd",
    "react": ".jsx",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "python": ".py",
    "json": ".json",
    "css": ".css",
    "code": ".txt",
    "text": ".txt",
}
_MIME_TYPES = {
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".md": "text/markdown",
    ".mmd": "text/plain",
    ".jsx": "text/plain",
    ".js": "text/javascript",
    ".ts": "text/plain",
    ".py": "text/plain",
    ".json": "application/json",
    ".css": "text/css",
    ".txt": "text/plain",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _now() -> float:
    return time.time()


def _artifacts_root(project_id: str) -> Path:
    if store.get_project(project_id) is None:
        raise FileNotFoundError(f"Project not found: {project_id}")
    root = store.ensure_project_dir(project_id) / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _index_path(project_id: str) -> Path:
    return _artifacts_root(project_id) / "index.json"


def _load_index(project_id: str) -> dict[str, Any]:
    path = _index_path(project_id)
    if not path.exists():
        return {"artifacts": []}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"artifacts": []}
    if not isinstance(data, dict) or not isinstance(data.get("artifacts"), list):
        return {"artifacts": []}
    return data


def _save_index(project_id: str, data: dict[str, Any]) -> None:
    path = _index_path(project_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(path)


def _safe_filename(name: str, fallback: str) -> str:
    candidate = Path(str(name or "")).name
    candidate = _SAFE_NAME.sub("-", candidate).strip(".-")
    return candidate or fallback


def _extension(artifact_type: str, language: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower() if filename else ""
    if suffix:
        return suffix
    language_ext = _EXTENSIONS.get(str(language or "").lower())
    if language_ext:
        return language_ext
    return _EXTENSIONS.get(str(artifact_type or "").lower(), ".txt")


def _mime_type(ext: str, provided: str = "") -> str:
    if provided:
        return provided
    mapped = _MIME_TYPES.get(ext.lower())
    if mapped:
        return mapped
    guessed, _ = mimetypes.guess_type(f"artifact{ext}")
    return guessed or "text/plain"


def _version_dir(project_id: str, artifact_id: str) -> Path:
    path = _artifacts_root(project_id) / "files" / artifact_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_payload_bytes(data: dict[str, Any]) -> bytes:
    content = data.get("content")
    if content is not None:
        if isinstance(content, bytes):
            return content
        return str(content).encode("utf-8")
    source_path = data.get("source_path") or data.get("path")
    if source_path:
        source = Path(str(source_path)).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f"Artifact source not found: {source}")
        return source.read_bytes()
    raise ValueError("content or source_path is required")


def _version_meta(
    *, version: int, created_at: float, size: int, checksum: str, filename: str, mime_type: str
) -> dict[str, Any]:
    return {
        "version": version,
        "created_at": created_at,
        "size": size,
        "checksum": checksum,
        "filename": filename,
        "mime_type": mime_type,
    }


def _write_version(
    project_id: str,
    artifact: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    payload = _read_payload_bytes(data)
    versions = artifact.get("versions") or []
    version = int(artifact.get("current_version") or 0) + 1
    supplied_name = str(data.get("filename") or "")
    ext = _extension(
        str(data.get("type") or data.get("artifact_type") or artifact.get("type") or "text"),
        str(data.get("language") or artifact.get("language") or ""),
        supplied_name,
    )
    filename = supplied_name or f"{artifact.get('id', 'artifact')[:8]}-v{version}{ext}"
    filename = _safe_filename(filename, f"artifact-v{version}{ext}")
    physical = f"v{version}{Path(filename).suffix or ext}"
    path = _version_dir(project_id, str(artifact["id"])) / physical
    path.write_bytes(payload)
    checksum = hashlib.sha256(payload).hexdigest()[:16]
    meta = _version_meta(
        version=version,
        created_at=_now(),
        size=len(payload),
        checksum=checksum,
        filename=filename,
        mime_type=_mime_type(Path(filename).suffix or ext, str(data.get("mime_type") or "")),
    )
    artifact["versions"] = [*versions, meta]
    artifact["current_version"] = version
    artifact["size"] = len(payload)
    artifact["updated_at"] = meta["created_at"]
    return meta


def _public(artifact: dict[str, Any], *, include_content: bool = False) -> dict[str, Any]:
    out = {
        key: value
        for key, value in artifact.items()
        if key in {
            "id",
            "project_id",
            "title",
            "type",
            "language",
            "description",
            "size",
            "current_version",
            "created_at",
            "updated_at",
            "versions",
            "metadata",
            "source",
            "session_id",
            "message_id",
        }
    }
    if include_content:
        out["content"] = artifact.get("_content", "")
    return out


def save_artifact(project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Create a new project artifact (version 1) from content or a copied file."""
    if store.get_project(project_id) is None:
        raise FileNotFoundError(f"Project not found: {project_id}")
    _read_payload_bytes(data)  # validate before writing metadata

    artifact_id = uuid.uuid4().hex
    now = _now()
    title = str(data.get("title") or "Untitled Artifact").strip() or "Untitled Artifact"
    artifact_type = str(data.get("type") or data.get("artifact_type") or "text")
    language = str(data.get("language") or "")
    artifact: dict[str, Any] = {
        "id": artifact_id,
        "project_id": project_id,
        "title": title,
        "type": artifact_type,
        "language": language,
        "description": str(data.get("description") or ""),
        "size": 0,
        "current_version": 0,
        "created_at": now,
        "updated_at": now,
        "versions": [],
        "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        "source": str(data.get("source") or data.get("origin") or ""),
        "session_id": str(data.get("session_id") or ""),
        "message_id": str(data.get("message_id") or ""),
    }
    _write_version(project_id, artifact, data)
    index = _load_index(project_id)
    index["artifacts"].append(artifact)
    _save_index(project_id, index)
    return _public(artifact)


def add_version(project_id: str, artifact_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Append a new version to an existing artifact."""
    index = _load_index(project_id)
    for artifact in index["artifacts"]:
        if artifact.get("id") == artifact_id:
            _write_version(project_id, artifact, data)
            if data.get("title"):
                artifact["title"] = str(data["title"]).strip()
            if data.get("description") is not None:
                artifact["description"] = str(data.get("description") or "")
            if data.get("metadata") and isinstance(data.get("metadata"), dict):
                artifact["metadata"] = {**(artifact.get("metadata") or {}), **data["metadata"]}
            _save_index(project_id, index)
            return _public(artifact)
    raise FileNotFoundError(f"Artifact not found: {artifact_id}")


def list_artifacts(project_id: str) -> list[dict[str, Any]]:
    index = _load_index(project_id)
    artifacts = [_public(a) for a in index["artifacts"] if isinstance(a, dict)]
    artifacts.sort(key=lambda a: float(a.get("updated_at") or 0), reverse=True)
    return artifacts


def _find(index: dict[str, Any], artifact_id: str) -> dict[str, Any]:
    for artifact in index["artifacts"]:
        if isinstance(artifact, dict) and artifact.get("id") == artifact_id:
            return artifact
    raise FileNotFoundError(f"Artifact not found: {artifact_id}")


def _version_file(project_id: str, artifact: dict[str, Any], version: int | None) -> tuple[Path, dict[str, Any]]:
    versions = [v for v in artifact.get("versions", []) if isinstance(v, dict)]
    if not versions:
        raise FileNotFoundError("Artifact has no stored versions")
    target_version = int(version or artifact.get("current_version") or versions[-1]["version"])
    meta = next((v for v in versions if int(v.get("version", -1)) == target_version), None)
    if meta is None:
        raise FileNotFoundError(f"Artifact version not found: {target_version}")
    ext = Path(str(meta.get("filename") or "")).suffix or ".txt"
    path = _version_dir(project_id, str(artifact["id"])) / f"v{target_version}{ext}"
    if not path.exists():
        raise FileNotFoundError(f"Artifact file missing: {path.name}")
    return path, meta


def get_artifact(
    project_id: str,
    artifact_id: str,
    *,
    version: int | None = None,
    include_content: bool = True,
) -> dict[str, Any]:
    artifact = _find(_load_index(project_id), artifact_id)
    result = _public(artifact)
    if include_content:
        path, meta = _version_file(project_id, artifact, version)
        result["content"] = path.read_text("utf-8", errors="replace")
        result["version"] = int(meta.get("version") or 0)
    return result


def delete_artifact(project_id: str, artifact_id: str) -> bool:
    index = _load_index(project_id)
    before = len(index["artifacts"])
    index["artifacts"] = [
        artifact
        for artifact in index["artifacts"]
        if not (isinstance(artifact, dict) and artifact.get("id") == artifact_id)
    ]
    if len(index["artifacts"]) == before:
        return False
    _save_index(project_id, index)
    shutil.rmtree(_artifacts_root(project_id) / "files" / artifact_id, ignore_errors=True)
    return True


def export_artifact(
    project_id: str, artifact_id: str, version: int | None = None
) -> tuple[Path, str, str]:
    """Return the physical file, download filename and MIME type."""
    artifact = _find(_load_index(project_id), artifact_id)
    path, meta = _version_file(project_id, artifact, version)
    filename = str(meta.get("filename") or path.name)
    mime_type = str(meta.get("mime_type") or "text/plain")
    return path, filename, mime_type
