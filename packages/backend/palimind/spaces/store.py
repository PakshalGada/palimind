"""Knowledge spaces: user-visible containers for indexed knowledge.

A space is a logical container backed by a real folder on disk. Two kinds are
supported:

* ``managed`` — PaliMind created the folder (the user only picked a parent).
* ``linked``  — the user pointed at an existing folder.

The folder remains the indexing root, so the crawler, vector store, graph and
config continue to work exactly as before. This module only owns the registry
and the lifecycle (create / rename / delete / activate).
"""

from __future__ import annotations

import logging
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from palimind.storage import state_store

logger = logging.getLogger(__name__)

NAMESPACE = "knowledge_spaces"
ACTIVE_KEY = "active"
KINDS = ("managed", "linked")

_NAME_RE = re.compile(r"[^\w .,'()&+\-]+", re.UNICODE)


class SpaceError(ValueError):
    """A user-actionable space validation error."""


# ── helpers ──────────────────────────────────────────────────────────────────


def _now() -> float:
    return time.time()


def normalise_name(name: str) -> str:
    cleaned = _NAME_RE.sub(" ", (name or "").strip())
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        raise SpaceError("Give the knowledge space a name.")
    if len(cleaned) > 80:
        raise SpaceError("The name is too long (max 80 characters).")
    return cleaned


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:60] or "knowledge"


def _validate_root(root: Path) -> Path:
    root = root.expanduser()
    try:
        resolved = root.resolve()
    except OSError as exc:
        raise SpaceError(f"Could not resolve that folder: {exc}") from exc
    if resolved == Path(resolved.anchor):
        raise SpaceError("Choose a folder, not the filesystem root.")
    if resolved == Path.home().resolve():
        raise SpaceError("Choose a folder inside your home directory.")
    if ".palimind" in resolved.parts:
        raise SpaceError("That folder is inside PaliMind's private state.")
    return resolved


def default_parent() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


def _record(space_id: str) -> dict[str, Any] | None:
    value = state_store.get_json(NAMESPACE, space_id, default=None)
    return value if isinstance(value, dict) else None


def _save(record: dict[str, Any]) -> dict[str, Any]:
    record["updated_at"] = _now()
    state_store.set_json(NAMESPACE, str(record["id"]), record)
    return record


def _all() -> list[dict[str, Any]]:
    records = [
        item
        for item in state_store.list_json(NAMESPACE, limit=1000)
        if isinstance(item, dict) and item.get("id")
    ]
    records.sort(key=lambda item: str(item.get("name") or "").casefold())
    return records


def list_spaces() -> list[dict[str, Any]]:
    return [public(record) for record in _all()]


def public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "name": record.get("name") or "Knowledge",
        "slug": record.get("slug") or "",
        "root": record.get("root") or "",
        "kind": record.get("kind") or "linked",
        "source_dir": record.get("source_dir") or "sources",
        "icon": record.get("icon") or "book",
        "note": record.get("note") or "",
        "digest_enabled": bool(record.get("digest_enabled")),
        "domain_mode": record.get("domain_mode") or "off",
        "domains": list(record.get("domains") or []),
        "quota_bytes": int(record.get("quota_bytes") or 0),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def get_space(space_id: str) -> dict[str, Any] | None:
    if not space_id:
        return None
    record = _record(str(space_id))
    return public(record) if record else None


def get_record(space_id: str) -> dict[str, Any] | None:
    return _record(str(space_id or ""))


def find_by_root(root: str | Path) -> dict[str, Any] | None:
    try:
        key = Path(root).expanduser().resolve()
    except OSError:
        return None
    for record in _all():
        try:
            if Path(str(record.get("root") or "")).expanduser().resolve() == key:
                return public(record)
        except OSError:
            continue
    return None


def active_space_id() -> str:
    value = state_store.get_json(NAMESPACE, ACTIVE_KEY, default="")
    return str(value or "")


def set_active_space(space_id: str) -> dict[str, Any] | None:
    """Point the app at a space and return its record."""
    from palimind import api_server as server

    record = _record(space_id)
    if record is None:
        return None
    root = Path(str(record.get("root") or ""))
    if not root.is_dir():
        raise SpaceError("The space folder no longer exists.")
    state_store.set_json(NAMESPACE, ACTIVE_KEY, str(space_id))
    server.state.active_field = root
    server.state.active_space_id = str(space_id)
    if str(root) not in server.state.fields:
        server.state.fields.append(str(root))
    server.state.save()
    try:
        server._on_field_changed(root)
    except Exception:  # noqa: BLE001 - activation must not fail on a watcher hiccup
        logger.debug("Watcher refresh failed after space activation", exc_info=True)
    return public(record)


# ── lifecycle ────────────────────────────────────────────────────────────────


def create_space(
    name: str,
    *,
    parent_dir: str | None = None,
    root: str | None = None,
    mode: str = "create",
    folder_name: str | None = None,
    icon: str = "book",
    usernote: str = "",
) -> dict[str, Any]:
    """Create a managed space or link an existing folder.

    ``mode="create"`` creates ``<parent_dir>/<folder_name or name>``.
    ``mode="link"`` indexes ``root`` in place and never writes a new folder.
    """
    raw_name = (name or "").strip()
    if any(sep in raw_name for sep in ("/", "\\", "\x00")) or raw_name in (".", ".."):
        raise SpaceError("The name cannot contain path separators.")
    name = normalise_name(raw_name)
    mode = (mode or "create").strip().lower()
    if mode not in ("create", "link"):
        raise SpaceError("mode must be 'create' or 'link'.")

    if mode == "link":
        if not root:
            raise SpaceError("Choose an existing folder to link.")
        target = _validate_root(Path(root))
        if not target.is_dir():
            raise SpaceError("That folder does not exist.")
        kind = "linked"
    else:
        parent = _validate_root(Path(parent_dir) if parent_dir else default_parent())
        if not parent.is_dir():
            raise SpaceError("The parent folder does not exist.")
        raw_folder = (folder_name or name).strip()
        if not raw_folder or raw_folder in (".", ".."):
            raise SpaceError("Invalid folder name.")
        if any(sep in raw_folder for sep in ("/", "\\", "\x00")):
            raise SpaceError("The folder name cannot contain path separators.")
        target = _validate_root(parent / raw_folder)
        if target.exists() and any(target.iterdir()):
            existing = find_by_root(target)
            if existing:
                set_active_space(str(existing["id"]))
                return existing
            raise SpaceError(f"That folder already exists: {target}")
        target.mkdir(parents=True, exist_ok=True)
        kind = "managed"

    existing = find_by_root(target)
    if existing:
        set_active_space(str(existing["id"]))
        return existing

    _ensure_index(target)

    record = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "slug": slugify(name),
        "root": str(target),
        "kind": kind,
        "source_dir": "sources",
        "icon": icon or "book",
        "note": usernote or "",
        "digest_enabled": False,
        "domain_mode": "off",
        "domains": [],
        "quota_bytes": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _save(record)
    set_active_space(str(record["id"]))
    return public(record)


def _ensure_index(root: Path) -> None:
    from palimind.config import config_path, write_default_config
    from palimind.rag.indexing import initialize_index
    from palimind.storage.db import init_db

    p_dir = root / ".palimind"
    if not p_dir.exists():
        initialize_index(root)
        return
    if not config_path(root).exists():
        write_default_config(root)
    init_db(root)


def update_space(space_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    record = _record(space_id)
    if record is None:
        return None
    if "name" in changes:
        record["name"] = normalise_name(str(changes.get("name") or ""))
        record["slug"] = slugify(str(record["name"]))
    if "icon" in changes:
        record["icon"] = str(changes.get("icon") or "book")[:40]
    if "source_dir" in changes:
        value = str(changes.get("source_dir") or "sources").strip().strip("/\\")
        if not value or ".." in Path(value).parts:
            raise SpaceError("Invalid source folder.")
        record["source_dir"] = value
    if "note" in changes:
        record["note"] = str(changes.get("note") or "")[:2000]
    if "digest_enabled" in changes:
        record["digest_enabled"] = bool(changes.get("digest_enabled"))
    if "domain_mode" in changes:
        mode = str(changes.get("domain_mode") or "off").lower()
        if mode not in ("off", "allow", "deny"):
            raise SpaceError("domain_mode must be off, allow or deny.")
        record["domain_mode"] = mode
    if "domains" in changes:
        raw = changes.get("domains") or []
        if isinstance(raw, str):
            raw = [item.strip() for item in raw.split(",")]
        domains = []
        for item in raw:
            value = str(item or "").strip().lower()
            if value:
                domains.append(value.removeprefix("."))
        record["domains"] = sorted(set(domains))[:200]
    if "quota_bytes" in changes:
        try:
            quota = int(changes.get("quota_bytes") or 0)
        except (TypeError, ValueError) as exc:
            raise SpaceError("quota_bytes must be an integer.") from exc
        record["quota_bytes"] = max(0, quota)
    _save(record)
    return public(record)


def delete_space(space_id: str, *, delete_files: bool = False) -> bool:
    record = _record(space_id)
    if record is None:
        return False
    root = Path(str(record.get("root") or ""))
    kind = str(record.get("kind") or "linked")

    if delete_files and kind == "managed" and root.is_dir():
        from palimind.security.tokens import palimind_home

        trash = palimind_home() / "trash"
        trash.mkdir(parents=True, exist_ok=True)
        destination = trash / f"{slugify(str(record.get('name') or 'space'))}-{int(_now())}"
        try:
            shutil.move(str(root), str(destination))
        except OSError as exc:
            raise SpaceError(f"Could not move the folder to trash: {exc}") from exc

    state_store.delete_json(NAMESPACE, space_id)
    if active_space_id() == space_id:
        state_store.delete_json(NAMESPACE, ACTIVE_KEY)

    from palimind import api_server as server

    if str(root) in server.state.fields:
        server.state.fields.remove(str(root))
    if server.state.active_space_id == space_id or (
        server.state.active_field and str(server.state.active_field) == str(root)
    ):
        server.state.active_field = None
        server.state.active_space_id = None
        server.state.save()
        try:
            server._on_field_changed(None)
        except Exception:  # noqa: BLE001
            logger.debug("Watcher reset failed after space deletion", exc_info=True)
    else:
        server.state.save()
    return True


def resolve_space(space_id: str) -> Path | None:
    record = _record(space_id)
    if record is None:
        return None
    root = Path(str(record.get("root") or ""))
    return root if root.is_dir() else None


# ── migration ────────────────────────────────────────────────────────────────


def migrate_legacy_fields(fields: list[str] | None) -> int:
    """Adopt folder paths saved by the pre-space app as linked spaces."""
    created = 0
    for raw in fields or []:
        try:
            path = Path(str(raw)).expanduser().resolve()
        except OSError:
            continue
        if not path.is_dir() or find_by_root(path):
            continue
        record = {
            "id": uuid.uuid4().hex[:12],
            "name": path.name or "Knowledge",
            "slug": slugify(path.name or "knowledge"),
            "root": str(path),
            "kind": "linked",
            "source_dir": "sources",
            "icon": "book",
            "note": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        _save(record)
        created += 1
    return created


def ensure_active_space() -> dict[str, Any] | None:
    """Return the active space, adopting the active field or the first space."""
    from palimind import api_server as server

    current = get_space(active_space_id())
    if current and Path(str(current.get("root") or "")).is_dir():
        return current
    if server.state.active_field:
        match = find_by_root(server.state.active_field)
        if match:
            set_active_space(str(match["id"]))
            return match
    spaces = list_spaces()
    if spaces:
        set_active_space(str(spaces[0]["id"]))
        return spaces[0]
    return None
