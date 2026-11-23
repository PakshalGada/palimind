"""Portable space backup and restore (Markdown + metadata)."""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path, PurePosixPath

from palimind.storage.db import SOURCE_COLUMNS, get_connection, upsert_source

_ALLOWED_PREFIXES = ("sources/", ".palimind/config.json", ".palimind/doc_graph.json")
_TOP_FILES = {"space.json", "sources.json"}


def create_backup(root: Path, space: dict | None = None) -> bytes:
    root = Path(root)
    buffer = io.BytesIO()
    conn = get_connection(root)
    try:
        rows = conn.execute(
            f"SELECT {', '.join(SOURCE_COLUMNS)} FROM sources ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    sources = [
        {name: row[index] for index, name in enumerate(SOURCE_COLUMNS)} for row in rows
    ]
    manifest = {
        "format": "palimind-space",
        "version": 1,
        "exported_at": time.time(),
        "space": space or {},
        "sources": len(sources),
    }
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("space.json", json.dumps(manifest, indent=2))
        archive.writestr("sources.json", json.dumps(sources, indent=2, default=str))
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if not rel.startswith(_ALLOWED_PREFIXES):
                continue
            archive.write(path, rel)
    return buffer.getvalue()


def _safe_name(name: str) -> bool:
    if name in _TOP_FILES:
        return True
    if not name.startswith(_ALLOWED_PREFIXES):
        return False
    parts = PurePosixPath(name).parts
    return bool(parts) and ".." not in parts and not name.startswith("/")


def restore_backup(data: bytes, root: Path) -> dict:
    """Restore a backup into an existing (usually empty) space root."""
    from palimind.config import config_path, write_default_config
    from palimind.storage.db import get_connection, init_db, upsert_source

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    restored = 0
    metadata: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.endswith("/") or not _safe_name(name):
                continue
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            restored += 1
            if name == "sources.json":
                try:
                    metadata = json.loads(target.read_text("utf-8"))
                except (OSError, json.JSONDecodeError):
                    metadata = []
    init_db(root)
    if not config_path(root).exists():
        write_default_config(root)
    if metadata:
        conn = get_connection(root)
        try:
            for item in metadata:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                values = {name: item.get(name) for name in SOURCE_COLUMNS}
                upsert_source(conn, values)
        finally:
            conn.close()
    return {"restored_files": restored, "sources": len(metadata), "root": str(root)}
