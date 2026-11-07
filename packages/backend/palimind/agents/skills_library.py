"""Immutable local skill revisions and install/update.

A revision is written once and never edited.  Installing a revision copies it
into the normal skill store; changing the library does not silently change an
installed copy.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from palimind.agents import skills
from palimind.security.tokens import palimind_home

_ID_RE = re.compile(r"^[\w-]{1,64}$")


def library_root() -> Path:
    return palimind_home() / "local-skills"


def _skill_dir(skill_id: str) -> Path:
    safe = "".join(c for c in str(skill_id) if c.isalnum() or c in "-_")
    return library_root() / safe


def _revision_dir(skill_id: str, revision: int) -> Path:
    return _skill_dir(skill_id) / str(int(revision))


def _bundle_path(skill_id: str, revision: int) -> Path:
    return _revision_dir(skill_id, revision) / "bundle.json"


def _write_revision(skill_id: str, revision: int, data: dict[str, Any]) -> dict[str, Any]:
    path = _bundle_path(skill_id, revision)
    if path.exists():
        raise ValueError(f"revision {revision} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**data, "id": skill_id, "revision": int(revision), "created_at": time.time()}
    path.write_text(json.dumps(payload, indent=2), "utf-8")
    return payload


def create_skill(data: dict[str, Any]) -> dict[str, Any]:
    skill_id = str(data.get("id") or uuid.uuid4())
    if not _ID_RE.match(skill_id):
        raise ValueError("id must be 1-64 chars of letters, digits, underscore or dash")
    error = skills.validate_skill({**data, "id": skill_id})
    if error:
        raise ValueError(error)
    return _write_revision(skill_id, 1, data)


def revise_skill(skill_id: str, expected_revision: int, data: dict[str, Any]) -> dict[str, Any]:
    current = latest_revision(skill_id)
    if current is None:
        raise KeyError("skill not found in the local library")
    if int(current) != int(expected_revision):
        raise ValueError(f"revision conflict: expected {expected_revision}, current {current}")
    error = skills.validate_skill({**data, "id": skill_id})
    if error:
        raise ValueError(error)
    return _write_revision(skill_id, int(current) + 1, data)


def latest_revision(skill_id: str) -> int | None:
    folder = _skill_dir(skill_id)
    if not folder.is_dir():
        return None
    revisions = []
    for child in folder.iterdir():
        if child.is_dir() and child.name.isdigit():
            revisions.append(int(child.name))
    return max(revisions) if revisions else None


def read_skill(skill_id: str, revision: int | None = None) -> dict[str, Any] | None:
    rev = int(revision) if revision is not None else latest_revision(skill_id)
    if rev is None:
        return None
    path = _bundle_path(skill_id, rev)
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def list_revisions(skill_id: str) -> list[dict[str, Any]]:
    folder = _skill_dir(skill_id)
    if not folder.is_dir():
        return []
    out = []
    for child in sorted(folder.iterdir()):
        if not child.is_dir() or not child.name.isdigit():
            continue
        value = read_skill(skill_id, int(child.name))
        if value is not None:
            out.append(value)
    return out


def list_library() -> list[dict[str, Any]]:
    root = library_root()
    if not root.is_dir():
        return []
    out = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        value = read_skill(folder.name)
        if value is not None:
            out.append(value)
    return out


def install_local_skill(skill_id: str, *, revision: int | None = None, overwrite: bool = True) -> dict[str, Any]:
    data = read_skill(skill_id, revision)
    if data is None:
        raise KeyError("skill not found in the local library")
    return skills.install_skill(data, source="local", overwrite=overwrite)


def export_skill(skill_id: str, revision: int | None = None) -> dict[str, Any] | None:
    return read_skill(skill_id, revision)


def delete_skill(skill_id: str) -> bool:
    folder = _skill_dir(skill_id)
    if not folder.is_dir():
        return False
    for child in sorted(folder.rglob("*"), reverse=True):
        try:
            child.unlink() if child.is_file() else child.rmdir()
        except OSError:
            pass
    try:
        folder.rmdir()
        return True
    except OSError:
        return False
