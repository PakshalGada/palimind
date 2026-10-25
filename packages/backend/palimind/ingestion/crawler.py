from __future__ import annotations

import hashlib
import os
from pathlib import Path

from palimind.config import load_config
from palimind.storage.db import get_connection


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


def crawl_directory(
    root: Path,
    *,
    index_root: Path | None = None,
    config: dict | None = None,
) -> tuple[list[Path], list[Path], list[str], dict[str, str]]:
    """Scan *root* and return (new_or_modified, unchanged, deleted_paths, hashes).

    ``hashes`` maps relative path → md5 for every new/modified file, so the
    indexer can reuse them instead of hashing the same bytes a second time.

    ``root`` is the directory that is scanned. ``index_root`` optionally points
    at a different directory holding the index database — used by projects,
    whose content lives in ``workspace_path`` while the index lives in the
    project's private store. ``config`` may be supplied to avoid re-reading it.
    """
    scan_root = root
    storage_root = index_root or root
    config = config if config is not None else load_config(storage_root)
    allowed_exts = set(
        config["extensions"]
        + config["doc_extensions"]
        + config["image_extensions"]
        + config.get("video_extensions", [])
    )
    ignore_dirs = {str(d).lower() for d in config.get("ignore_dirs", [])}

    conn = get_connection(storage_root)
    try:
        cur = conn.cursor()
        cur.execute("SELECT path, md5_hash FROM files")
        indexed_files = {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()

    current_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(scan_root):
        # Skip hidden directories and known noise (node_modules, venv, build…)
        # so selecting a project folder doesn't hash/parse thousands of files.
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d.lower() not in ignore_dirs
        ]
        for filename in filenames:
            if filename.startswith("."):
                continue
            file_path = Path(dirpath) / filename
            if file_path.suffix.lower() in allowed_exts:
                current_files.append(file_path)

    new_or_modified: list[Path] = []
    unchanged: list[Path] = []
    current_paths: set[str] = set()
    hashes: dict[str, str] = {}

    for file_path in current_files:
        path_str = str(file_path.relative_to(scan_root))
        current_paths.add(path_str)

        current_hash = compute_md5(file_path)
        if not current_hash:
            continue

        if indexed_files.get(path_str) != current_hash:
            new_or_modified.append(file_path)
            hashes[path_str] = current_hash
        else:
            unchanged.append(file_path)

    deleted_paths = [p for p in indexed_files if p not in current_paths]
    return new_or_modified, unchanged, deleted_paths, hashes
