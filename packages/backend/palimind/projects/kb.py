"""Project-scoped retrieval-augmented knowledge base.

The working files stay in ``project.workspace_path``. This module indexes that
folder into the project's private store (``~/.palimind/projects/<id>/.palimind``)
so the FAISS index, SQLite chunk database and config can never leak into — or
be shared with — another project or the global knowledge bases.

It deliberately reuses the existing crawler, rich chunkers, embedder and
index/vector stores via :func:`palimind.rag.indexing.update_index`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from palimind.config import config_path, load_global_config, palimind_dir, save_config
from palimind.projects import store
from palimind.rag.indexing import update_index
from palimind.storage.db import get_connection, init_db

_INDEX_FILE = "faiss.index"
_DB_FILE = "index.db"


def ensure_project_storage(project_id: str) -> Path:
    """Create the project's private config + DB before first indexing."""
    project = store.get_project(project_id)
    if project is None:
        raise FileNotFoundError(f"Project not found: {project_id}")
    root = store.ensure_project_dir(project_id)
    palimind_dir(root).mkdir(parents=True, exist_ok=True)
    if not config_path(root).exists():
        # Inherit the user's global model choices so project chat behaves like
        # the rest of the app without a separate setup pass.
        save_config(root, load_global_config())
    init_db(root)
    return root


def sync_project_kb(project_id: str) -> dict[str, Any]:
    """Index ``workspace_path`` into the project's isolated FAISS index."""
    project = store.get_project(project_id)
    if project is None:
        raise FileNotFoundError(f"Project not found: {project_id}")

    workspace = Path(str(project.get("workspace_path") or "")).expanduser()
    if not workspace.is_dir():
        store.record_kb_sync(
            project_id,
            status="error",
            error=f"Workspace not found: {workspace}",
        )
        raise ValueError(f"Workspace not found: {workspace}")

    root = ensure_project_storage(project_id)
    try:
        result = update_index(root, source_root=workspace)
    except Exception as exc:
        store.record_kb_sync(project_id, status="error", error=str(exc))
        raise

    stats = {
        "indexed_files": result.indexed_files,
        "deleted_files": result.deleted_files,
        "unchanged_files": result.unchanged_files,
        "chunks_indexed": result.chunks_indexed,
        "file_errors": len(result.file_errors),
    }
    store.record_kb_sync(project_id, status="idle", **stats)
    return {
        "status": "success",
        "project_id": project_id,
        "workspace_path": str(workspace),
        "scope": store.project_scope(project_id),
        **stats,
        "errors": [{"path": e.path, "error": e.error} for e in result.file_errors],
    }


def kb_status(project_id: str) -> dict[str, Any]:
    """Return index availability and size for a project, without side effects."""
    project = store.get_project(project_id)
    if project is None:
        raise FileNotFoundError(f"Project not found: {project_id}")

    root = store.project_dir(project_id)
    index_dir = palimind_dir(root)
    workspace = str(project.get("workspace_path") or "")
    kb_meta = project.get("kb") or {}

    indexed_files = 0
    chunks = 0
    last_indexed_at = kb_meta.get("last_synced_at")
    if (index_dir / _DB_FILE).exists():
        try:
            conn = get_connection(root)
            try:
                row = conn.execute("SELECT COUNT(*) FROM files").fetchone()
                indexed_files = int(row[0]) if row else 0
                row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
                chunks = int(row[0]) if row else 0
                row = conn.execute("SELECT MAX(last_indexed) FROM files").fetchone()
                if row and row[0] is not None:
                    last_indexed_at = float(row[0])
            finally:
                conn.close()
        except Exception:
            pass

    return {
        "project_id": project_id,
        "workspace_path": workspace,
        "has_index": (index_dir / _INDEX_FILE).exists(),
        "indexed_files": indexed_files,
        "chunks": chunks,
        "last_indexed_at": last_indexed_at,
        "status": kb_meta.get("status", "idle"),
        "error": kb_meta.get("error", ""),
        "file_errors": int(kb_meta.get("file_errors") or 0),
    }
