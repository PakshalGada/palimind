from __future__ import annotations

import hashlib
import os
from pathlib import Path

from core.config import load_config
from core.storage.db import get_connection


def compute_md5(file_path: Path) -> str:
    """Return hex MD5 of *file_path*, or empty string on error."""
    hasher = hashlib.md5(usedforsecurity=False)
    try:
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return ""


def crawl_directory(root: Path) -> tuple[list[Path], list[Path], list[str]]:
    """Scan *root* and return (new_or_modified, unchanged, deleted_paths)."""
    config = load_config(root)
    allowed_exts = set(
        config["extensions"] + config["doc_extensions"] + config["image_extensions"]
    )

    conn = get_connection(root)
    try:
        cur = conn.cursor()
        cur.execute("SELECT path, md5_hash FROM files")
        indexed_files = {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()

    current_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue
            file_path = Path(dirpath) / filename
            if file_path.suffix.lower() in allowed_exts:
                current_files.append(file_path)

    new_or_modified: list[Path] = []
    unchanged: list[Path] = []
    current_paths: set[str] = set()

    for file_path in current_files:
        path_str = str(file_path.relative_to(root))
        current_paths.add(path_str)

        current_hash = compute_md5(file_path)
        if not current_hash:
            continue

        if indexed_files.get(path_str) != current_hash:
            new_or_modified.append(file_path)
        else:
            unchanged.append(file_path)

    deleted_paths = [p for p in indexed_files if p not in current_paths]
    return new_or_modified, unchanged, deleted_paths
