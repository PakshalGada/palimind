"""Knowledge workspace services.

The Knowledge view needs more than raw chat: index health, an index-backed file
library, retrieval diagnostics and workspace-scoped settings.  The functions in
this module are deliberately plain (no FastAPI imports) so they can be used by
the HTTP layer, the CLI and tests.

All file paths stored in the index are relative to the knowledge root.  A root
is either the active field or a project's private storage directory; callers
resolve that scope before calling these helpers.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from palimind.config import load_config, palimind_dir, save_config
from palimind.storage.db import get_connection

logger = logging.getLogger(__name__)

# Settings exposed by the Knowledge view. Keeping the allow-list here means the
# UI can never write arbitrary config keys (model paths, secrets, …).
SETTING_SPECS: dict[str, tuple[type, Any, Any]] = {
    "retrieval_limit": (int, 1, 100),
    "retrieval_candidate_depth": (int, 5, 500),
    "context_token_budget": (int, 500, 20000),
    "parent_max_tokens": (int, 200, 8000),
    "mmr_per_file_cap": (int, 1, 20),
    "mmr_lambda": (float, 0.0, 1.0),
    "rerank": (bool, None, None),
    "query_rewrite": (bool, None, None),
    "parent_retrieval": (bool, None, None),
    "mmr": (bool, None, None),
    "summary_search": (bool, None, None),
    "build_graph": (bool, None, None),
    "summarise": (bool, None, None),
    "auto_reindex": (bool, None, None),
}

SETTING_ENUMS: dict[str, tuple[str, ...]] = {
    "agentic_rag": ("auto", "off", "always"),
}

SORT_ORDERS = {
    "recent": "f.last_indexed DESC, f.path ASC",
    "path": "f.path ASC",
    "type": "f.doc_type ASC, f.path ASC",
    "chunks": "chunk_count DESC, f.path ASC",
    "year": "f.doc_year IS NULL, f.doc_year DESC, f.path ASC",
}


# ── scope / root helpers ─────────────────────────────────────────────────────


def resolve_root(scope: str = "field") -> Path | None:
    """Resolve ``field`` or ``project:<id>`` to its knowledge storage root."""
    from palimind import api_server as server

    scope = (scope or "field").strip()
    if scope in ("", "field"):
        return server.state.active_field
    if scope.startswith("project:"):
        try:
            return server._chat_root(scope)
        except Exception:  # noqa: BLE001 - a bad project id must not crash the API
            logger.exception("Could not resolve project knowledge root")
            return None
    return None


def resolve_content_root(scope: str = "field") -> Path | None:
    """Resolve the folder that contains the source files.

    For a field this is the same as the index root. A project keeps its index
    in ``~/.palimind/projects/<id>`` while the indexed files live in the
    project's ``workspace_path``; citations, reindex and diagnostics must
    resolve against the workspace, not the private index folder.
    """
    from palimind import api_server as server

    scope = (scope or "field").strip()
    if scope in ("", "field"):
        return server.state.active_field
    if not scope.startswith("project:"):
        return None
    project_id = scope.split(":", 1)[1].strip()
    if not project_id:
        return None
    try:
        from palimind.projects import store

        project = store.get_project(project_id)
        if project is None:
            return None
        workspace = str(project.get("workspace_path") or "").strip()
        if not workspace:
            return None
        path = Path(workspace).expanduser()
        return path if path.is_dir() else None
    except Exception:  # noqa: BLE001
        logger.exception("Could not resolve project content root")
        return None


# ── small DB helpers ─────────────────────────────────────────────────────────


def _scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _has_db(root: Path) -> bool:
    return (palimind_dir(root) / "index.db").exists()


def _latest_run(root: Path) -> dict[str, Any] | None:
    try:
        from palimind.rag import incremental

        for run in incremental.list_runs(limit=200):
            if str(run.get("root") or "") == str(root):
                return run
    except Exception:  # noqa: BLE001 - state store is optional for read paths
        logger.debug("Could not read index runs", exc_info=True)
    return None


def run_index(
    root: Path,
    *,
    source_root: Path | None = None,
    wait: bool = True,
    timeout: float = 600.0,
    priority: int = 0,
) -> dict[str, Any]:
    """Plan/execute a durable index run and optionally wait for completion.

    This is the compatibility bridge used by ``POST /api/update`` and project
    KB sync. When a durable job worker is running (the normal server path) the
    run goes through ``incremental.enqueue_run``. In a process without a worker
    (CLI, some tests) the already-planned run is executed inline so synchronous
    callers still receive a finished summary instead of hanging forever.
    """
    from palimind.jobs import runner_running
    from palimind.rag import incremental

    root = Path(root)
    source = Path(source_root) if source_root is not None else root
    if runner_running():
        run = incremental.enqueue_run(root, source_root=source, priority=priority)
        if not wait or str(run.get("status") or "") in incremental.TERMINAL_STATUSES:
            return run
        return incremental.wait_for_run(str(run["run_id"]), timeout=timeout) or run

    run = incremental.plan_run(root, source_root=source, priority=priority)
    if not wait or str(run.get("status") or "") in incremental.TERMINAL_STATUSES:
        return run
    return incremental.process_run(str(run["run_id"]))


def _dir_size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


# ── stats ────────────────────────────────────────────────────────────────────


def collect_stats(root: Path) -> dict[str, Any]:
    """Return everything the Knowledge overview needs, without side effects."""
    root = Path(root)
    config = load_config(root)
    files = chunks = summaries = tokens = pages = 0
    last_indexed: float | None = None
    types: list[dict[str, Any]] = []
    years: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []

    if _has_db(root):
        conn = get_connection(root)
        try:
            files = int(_scalar(conn, "SELECT COUNT(*) FROM files") or 0)
            chunks = int(_scalar(conn, "SELECT COUNT(*) FROM chunks") or 0)
            summaries = int(
                _scalar(
                    conn,
                    "SELECT COUNT(*) FROM files WHERE COALESCE(summary, '') <> ''",
                )
                or 0
            )
            tokens = int(_scalar(conn, "SELECT COALESCE(SUM(token_estimate), 0) FROM chunks") or 0)
            pages = int(_scalar(conn, "SELECT COALESCE(MAX(page_number), 0) FROM chunks") or 0)
            last_indexed = _scalar(conn, "SELECT MAX(last_indexed) FROM files")

            types = [
                {"type": row[0] or "other", "files": int(row[1]), "chunks": int(row[2])}
                for row in conn.execute(
                    """
                    SELECT f.doc_type, COUNT(DISTINCT f.id), COUNT(c.id)
                    FROM files f LEFT JOIN chunks c ON c.file_id = f.id
                    GROUP BY f.doc_type ORDER BY COUNT(DISTINCT f.id) DESC
                    """
                ).fetchall()
            ]
            years = [
                {"year": int(row[0]), "files": int(row[1])}
                for row in conn.execute(
                    """
                    SELECT doc_year, COUNT(*) FROM files
                    WHERE doc_year IS NOT NULL GROUP BY doc_year ORDER BY doc_year DESC
                    """
                ).fetchall()
            ]
            entities = [
                {"entity": row[0], "files": int(row[1])}
                for row in conn.execute(
                    """
                    SELECT entity_name, COUNT(*) FROM files
                    WHERE COALESCE(entity_name, '') <> ''
                    GROUP BY entity_name ORDER BY COUNT(*) DESC LIMIT 8
                    """
                ).fetchall()
            ]
        except Exception:  # noqa: BLE001 - stats must never take the UI down
            logger.exception("Could not read knowledge stats for %s", root)
        finally:
            conn.close()

    from palimind.storage.vector_store import _index_path, index_dimension, read_stamp

    index_file = _index_path(root)
    stamp = read_stamp(root) or {}
    dim = index_dimension(root)
    configured_model = str(config.get("embed_model") or "")
    stamped_model = str(stamp.get("model") or "")
    stale = bool(stamped_model and configured_model and stamped_model != configured_model)
    chunker_stale = bool(
        stamp and int(stamp.get("chunker") or 1) != int(config.get("chunker_version") or 1)
    )
    last_run = _latest_run(root)
    failed = int((last_run or {}).get("failed") or 0) if last_run else 0

    # Keep the historical ``retrieval`` keys (limit/candidate_depth) alongside
    # the canonical setting names so older clients and tests keep working.
    retrieval = read_settings(root)
    retrieval.setdefault("limit", retrieval.get("retrieval_limit"))
    retrieval.setdefault("candidate_depth", retrieval.get("retrieval_candidate_depth"))

    p_dir = palimind_dir(root)
    index_size = _dir_size(
        [
            index_file,
            p_dir / "faiss_meta.json",
            p_dir / "faiss_removed.json",
            p_dir / "index.db",
        ]
    )

    return {
        "root": str(root),
        "files": files,
        "chunks": chunks,
        "summaries": summaries,
        "tokens": tokens,
        "pages": pages,
        "last_indexed": float(last_indexed) if last_indexed else None,
        "index_ready": index_file.exists() and dim is not None,
        "index_model": stamped_model or configured_model,
        "configured_model": configured_model,
        "index_dim": dim,
        "stamp_dim": int(stamp.get("dim") or 0) or None,
        "chunker": int(stamp.get("chunker") or 0) or None,
        "configured_chunker": int(config.get("chunker_version") or 1),
        "stale": stale or chunker_stale,
        "stale_reason": (
            "Embedding model changed; reindex to restore semantic search."
            if stale
            else "Chunker changed; reindex to rebuild chunks."
            if chunker_stale
            else ""
        ),
        "index_size": index_size,
        "types": types,
        "years": years,
        "entities": entities,
        "failed": failed,
        "last_run": last_run,
        "retrieval": retrieval,
    }


# ── file library ─────────────────────────────────────────────────────────────


def _like(value: str) -> str:
    # Escape LIKE wildcards so a path search for "100%" behaves literally.
    return f"%{value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"


def list_files(
    root: Path,
    *,
    q: str = "",
    doc_type: str = "",
    doc_year: int | None = None,
    entity: str = "",
    status: str = "all",
    sort: str = "recent",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Index-backed file list with pagination and filters."""
    root = Path(root)
    if not _has_db(root):
        return {"files": [], "total": 0, "limit": limit, "offset": offset}

    where: list[str] = []
    params: list[Any] = []
    if q:
        where.append("f.path LIKE ? ESCAPE '\\'")
        params.append(_like(q))
    if doc_type:
        where.append("f.doc_type = ?")
        params.append(doc_type)
    if doc_year is not None:
        where.append("f.doc_year = ?")
        params.append(int(doc_year))
    if entity:
        where.append("f.entity_name LIKE ? ESCAPE '\\'")
        params.append(_like(entity))

    latest = _latest_run(root)
    failed_paths: list[str] = []
    if latest and latest.get("errors"):
        failed_paths = [str(item.get("path") or "") for item in latest["errors"] if item.get("path")]

    if status == "summary":
        where.append("COALESCE(f.summary, '') <> ''")
    elif status == "no-summary":
        where.append("COALESCE(f.summary, '') = ''")
    elif status == "failed":
        if not failed_paths:
            return {"files": [], "total": 0, "limit": limit, "offset": offset}
        where.append(f"f.path IN ({','.join('?' * len(failed_paths))})")
        params.extend(failed_paths)
    elif status == "ready":
        if failed_paths:
            where.append(f"f.path NOT IN ({','.join('?' * len(failed_paths))})")
            params.extend(failed_paths)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    order = SORT_ORDERS.get(sort, SORT_ORDERS["recent"])
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    failed_set = set(failed_paths)

    conn = get_connection(root)
    try:
        total = int(
            _scalar(conn, f"SELECT COUNT(DISTINCT f.id) FROM files f {clause}", tuple(params)) or 0
        )
        rows = conn.execute(
            f"""
            SELECT f.path, f.md5_hash, f.last_indexed, f.doc_year, f.doc_type,
                   f.entity_name, COALESCE(f.summary, ''),
                   COUNT(c.id) AS chunk_count,
                   COALESCE(SUM(c.token_estimate), 0) AS token_count,
                   COALESCE(MAX(c.page_number), 0) AS page_count
            FROM files f LEFT JOIN chunks c ON c.file_id = f.id
            {clause}
            GROUP BY f.id
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    finally:
        conn.close()

    files = []
    for row in rows:
        path = str(row[0])
        files.append(
            {
                "path": path,
                "name": Path(path).name,
                "extension": Path(path).suffix.lower().lstrip("."),
                "md5": row[1] or "",
                "last_indexed": float(row[2]) if row[2] else None,
                "doc_year": row[3],
                "doc_type": row[4] or "other",
                "entity": row[5] or "",
                "summary": row[6] or "",
                "has_summary": bool(row[6]),
                "chunks": int(row[7] or 0),
                "tokens": int(row[8] or 0),
                "pages": int(row[9] or 0),
                "failed": path in failed_set,
            }
        )
    return {"files": files, "total": total, "limit": limit, "offset": offset}


def get_file_detail(
    root: Path,
    file_path: str,
    *,
    include_content: bool = False,
    content_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return metadata, summary, section outline and chunk previews for a file."""
    root = Path(root)
    content_root = Path(content_root) if content_root is not None else root
    if not _has_db(root):
        return None
    from palimind.storage.db import get_rich_chunks_for_file

    conn = get_connection(root)
    try:
        row = conn.execute(
            """
            SELECT path, md5_hash, last_indexed, doc_year, doc_type, entity_name,
                   COALESCE(summary, ''), total_pages
            FROM files WHERE path = ?
            """,
            (file_path,),
        ).fetchone()
        if row is None:
            return None

        chunks = get_rich_chunks_for_file(conn, file_path)
        entities = [
            {"text": r[0], "type": r[1] or "organization", "mentions": int(r[2])}
            for r in conn.execute(
                """
                SELECT em.entity_text, em.entity_type, COUNT(*)
                FROM entity_mentions em
                JOIN chunks c ON c.id = em.chunk_id
                JOIN files f ON f.id = c.file_id
                WHERE f.path = ?
                GROUP BY em.entity_text, em.entity_type
                ORDER BY COUNT(*) DESC LIMIT 50
                """,
                (file_path,),
            ).fetchall()
        ]
    finally:
        conn.close()

    sections: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in chunks:
        key = (chunk.get("main_section") or "", chunk.get("section_title") or "")
        entry = sections.setdefault(
            key,
            {
                "main_section": key[0],
                "title": key[1],
                "chunks": 0,
                "page_start": None,
                "page_end": None,
            },
        )
        entry["chunks"] += 1
        page = chunk.get("page_number")
        if page is not None:
            entry["page_start"] = page if entry["page_start"] is None else min(entry["page_start"], page)
            entry["page_end"] = page if entry["page_end"] is None else max(entry["page_end"], page)

    previews = []
    for chunk in chunks[:80]:
        content = chunk.get("content") or ""
        previews.append(
            {
                "id": chunk.get("chunk_db_id"),
                "index": chunk.get("chunk_index"),
                "type": chunk.get("chunk_type"),
                "section": chunk.get("section_title") or chunk.get("main_section") or "",
                "subsection": chunk.get("subsection") or "",
                "page": chunk.get("page_number"),
                "words": chunk.get("word_count"),
                "tokens": chunk.get("token_estimate"),
                "content": content if include_content else content[:700],
                "truncated": (not include_content) and len(content) > 700,
            }
        )

    return {
        "path": row[0],
        "name": Path(row[0]).name,
        "md5": row[1] or "",
        "last_indexed": float(row[2]) if row[2] else None,
        "doc_year": row[3],
        "doc_type": row[4] or "other",
        "entity": row[5] or "",
        "summary": row[6] or "",
        "total_pages": row[7],
        "exists_on_disk": (content_root / row[0]).is_file(),
        "chunks": len(chunks),
        "sections": sorted(
            sections.values(),
            key=lambda s: (s["main_section"], s["title"]),
        ),
        "entities": entities,
        "previews": previews,
    }


def reindex_file(
    root: Path,
    file_path: str,
    *,
    content_root: Path | None = None,
) -> dict[str, Any]:
    """Re-parse and embed one indexed file (or record its deletion)."""
    from palimind.rag.indexing import update_index
    from palimind.rag.retrieve import clear_search_cache

    root = Path(root)
    content_root = Path(content_root) if content_root is not None else root
    # Clear the cached hash so the crawler treats an otherwise-unchanged file
    # as modified. Without this, "Reindex" would be a no-op.
    if _has_db(root):
        conn = get_connection(root)
        try:
            conn.execute("UPDATE files SET md5_hash = '' WHERE path = ?", (file_path,))
            conn.commit()
        finally:
            conn.close()

    try:
        result = update_index(root, source_root=content_root, paths={file_path})
    finally:
        clear_search_cache(root)
    return {
        "status": "success",
        "file": file_path,
        "indexed": result.indexed_files,
        "deleted": result.deleted_files,
        "unchanged": result.unchanged_files,
        "chunks": result.chunks_indexed,
        "errors": [{"path": e.path, "error": e.error} for e in result.file_errors],
    }


def remove_file(root: Path, file_path: str) -> bool:
    """Remove a file's vectors, chunks and graph node, leaving disk untouched."""
    from palimind.document.graph import DocGraph
    from palimind.rag.retrieve import clear_search_cache
    from palimind.storage.db import INDEX_WRITE_LOCK, delete_file
    from palimind.storage.vector_store import VectorStore

    root = Path(root)
    removed = False
    with INDEX_WRITE_LOCK:
        if _has_db(root):
            conn = get_connection(root)
            try:
                exists = conn.execute("SELECT 1 FROM files WHERE path = ?", (file_path,)).fetchone()
                if exists is not None:
                    with VectorStore(root) as store:
                        store.delete_file(file_path)
                    delete_file(conn, file_path)
                    conn.commit()
                    removed = True
            finally:
                conn.close()

        graph = DocGraph.load(root)
        if graph is not None:
            graph.remove_file(file_path)
            graph.save()

    clear_search_cache(root)
    return removed


# ── retrieval preview ────────────────────────────────────────────────────────


def search(
    root: Path,
    query: str,
    *,
    limit: int = 8,
    doc_type: str = "",
    doc_year: int | None = None,
    entity: str = "",
    section: str = "",
) -> dict[str, Any]:
    """Run the real hybrid retrieval pipeline and return a compact preview."""
    from palimind.rag.retrieve import hybrid_search

    root = Path(root)
    config = load_config(root)
    result = hybrid_search(
        root,
        query,
        limit=max(1, min(int(limit or 8), 50)),
        ollama_url=str(config.get("ollama_base_url") or ""),
        embed_model=str(config.get("embed_model") or ""),
        query_rewrite_enabled=False,
        doc_type=doc_type or None,
        doc_year=doc_year,
        entity_name=entity or None,
        section_title=section or None,
    )
    hits = []
    for item in result.get("results") or []:
        content = str(item.get("content") or "")
        hits.append(
            {
                "file_path": item.get("file_path") or "",
                "section": item.get("section_title") or item.get("main_section") or "",
                "page": item.get("page_number"),
                "page_end": item.get("page_end"),
                "score": item.get("relevance_score"),
                "lane": item.get("search_type") or "",
                "doc_year": item.get("doc_year"),
                "doc_type": item.get("doc_type"),
                "content": content[:900],
                "truncated": len(content) > 900,
            }
        )
    return {
        "query": query,
        "results": hits,
        "total": len(hits),
        "sources": result.get("sources") or [],
        "errors": result.get("errors") or [],
        "timings": result.get("timings") or {},
        "diagnostics": result.get("diagnostics") or {},
    }


# ── settings ─────────────────────────────────────────────────────────────────


def read_settings(root: Path) -> dict[str, Any]:
    config = load_config(Path(root))
    settings: dict[str, Any] = {
        key: config.get(key) for key in (*SETTING_SPECS.keys(), *SETTING_ENUMS.keys())
    }
    settings["context_token_budget"] = config.get("context_token_budget")
    return settings


def _coerce(key: str, raw: Any) -> Any:
    if key in SETTING_ENUMS:
        value = str(raw or "").strip().lower()
        if value not in SETTING_ENUMS[key]:
            raise ValueError(f"{key} must be one of {SETTING_ENUMS[key]}")
        return value
    kind, low, high = SETTING_SPECS[key]
    if kind is bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            value = raw.strip().lower()
            if value in ("1", "true", "yes", "on"):
                return True
            if value in ("0", "false", "no", "off"):
                return False
        raise ValueError(f"{key} must be a boolean")
    if raw is None or raw == "":
        if key == "context_token_budget":
            return None
        raise ValueError(f"{key} is required")
    value = kind(raw)
    if low is not None and value < low:
        raise ValueError(f"{key} must be >= {low}")
    if high is not None and value > high:
        raise ValueError(f"{key} must be <= {high}")
    return value


def update_settings(root: Path, changes: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist a partial knowledge settings update."""
    root = Path(root)
    config = load_config(root)
    applied: dict[str, Any] = {}
    for key, raw in changes.items():
        if key not in SETTING_SPECS and key not in SETTING_ENUMS:
            continue
        applied[key] = _coerce(key, raw)
    if not applied:
        raise ValueError("No supported settings supplied")
    # ``rerank`` is only honoured when the opt-in marker is set; otherwise
    # load_config deliberately disables it for backwards compatibility.
    if "rerank" in applied:
        applied["rerank_opt_in"] = bool(applied["rerank"])
    config.update(applied)
    save_config(root, config)
    return read_settings(root)


# ── diagnostics ──────────────────────────────────────────────────────────────


def diagnostics(root: Path, *, content_root: Path | None = None) -> dict[str, Any]:
    """Return index integrity signals for the Knowledge diagnostics panel."""
    root = Path(root)
    content_root = Path(content_root) if content_root is not None else root
    from palimind.storage.vector_store import _index_path, index_dimension, read_stamp

    config = load_config(root)
    p_dir = palimind_dir(root)
    index_file = _index_path(root)
    stamp = read_stamp(root) or {}
    dim = index_dimension(root)
    issues: list[dict[str, str]] = []

    files = chunks = summaries = 0
    missing_files: list[str] = []
    if _has_db(root):
        conn = get_connection(root)
        try:
            files = int(_scalar(conn, "SELECT COUNT(*) FROM files") or 0)
            chunks = int(_scalar(conn, "SELECT COUNT(*) FROM chunks") or 0)
            summaries = int(
                _scalar(
                    conn,
                    "SELECT COUNT(*) FROM files WHERE COALESCE(summary, '') <> ''",
                )
                or 0
            )
            for (path,) in conn.execute("SELECT path FROM files ORDER BY path").fetchall():
                if not (content_root / path).is_file():
                    missing_files.append(str(path))
        except Exception:  # noqa: BLE001
            logger.exception("Could not read diagnostics for %s", root)
            issues.append(
                {
                    "code": "db_unreadable",
                    "severity": "error",
                    "message": "The index database could not be read.",
                }
            )
        finally:
            conn.close()
    else:
        issues.append(
            {
                "code": "no_database",
                "severity": "warn",
                "message": "No index database yet. Run a sync to build one.",
            }
        )

    if not index_file.exists():
        issues.append(
            {
                "code": "no_vector_index",
                "severity": "warn" if files == 0 else "error",
                "message": "No vector index yet."
                if files == 0
                else "The vector index is missing but indexed files exist. Reindex.",
            }
        )
    if dim is None and index_file.exists():
        issues.append(
            {
                "code": "unreadable_vector_index",
                "severity": "error",
                "message": "The vector index exists but could not be loaded. Rebuild it.",
            }
        )
    configured_model = str(config.get("embed_model") or "")
    stamped_model = str(stamp.get("model") or "")
    if stamped_model and configured_model and stamped_model != configured_model:
        issues.append(
            {
                "code": "model_mismatch",
                "severity": "warn",
                "message": f"Index uses {stamped_model}; config uses {configured_model}.",
            }
        )
    chunker = int(stamp.get("chunker") or 1)
    configured_chunker = int(config.get("chunker_version") or 1)
    if stamp and chunker != configured_chunker:
        issues.append(
            {
                "code": "chunker_mismatch",
                "severity": "warn",
                "message": f"Index chunker v{chunker}; config expects v{configured_chunker}.",
            }
        )
    if files and summaries < files:
        issues.append(
            {
                "code": "missing_summaries",
                "severity": "info",
                "message": f"{files - summaries} of {files} files have no summary.",
            }
        )
    if missing_files:
        issues.append(
            {
                "code": "missing_source_files",
                "severity": "warn",
                "message": f"{len(missing_files)} indexed files no longer exist on disk.",
            }
        )

    meta_count = 0
    meta_path = p_dir / "faiss_meta.json"
    if meta_path.exists():
        try:
            meta_count = len(json.loads(meta_path.read_text()))
        except Exception:  # noqa: BLE001
            logger.debug("Could not read FAISS metadata", exc_info=True)
    if chunks and meta_count and chunks != meta_count:
        issues.append(
            {
                "code": "chunk_vector_mismatch",
                "severity": "warn",
                "message": f"{chunks} chunks in SQLite but {meta_count} vector records.",
            }
        )

    last_run = _latest_run(root)
    if last_run and last_run.get("errors"):
        issues.append(
            {
                "code": "last_run_errors",
                "severity": "error",
                "message": f"{len(last_run['errors'])} file(s) failed in the last run.",
            }
        )

    return {
        "root": str(root),
        "healthy": not any(i["severity"] == "error" for i in issues),
        "files": files,
        "chunks": chunks,
        "vectors": meta_count,
        "summaries": summaries,
        "index_ready": index_file.exists() and dim is not None,
        "index_model": stamped_model or configured_model,
        "index_dim": dim,
        "stamp_dim": int(stamp.get("dim") or 0) or None,
        "chunker": chunker if stamp else None,
        "configured_chunker": configured_chunker,
        "index_size": _dir_size([index_file, meta_path, p_dir / "index.db"]),
        "missing_files": missing_files[:50],
        "issues": issues,
        "last_run": last_run,
        "checked_at": time.time(),
    }


# ── graph payload ────────────────────────────────────────────────────────────


def graph_payload(
    root: Path,
    *,
    types: list[str] | None = None,
    q: str = "",
    doc_year: int | None = None,
    doc_type: str = "",
    relation: str = "",
    min_degree: int = 0,
    max_nodes: int = 400,
    max_edges: int = 1200,
) -> dict[str, Any]:
    """Load and filter the document graph without sending every node to the UI."""
    from palimind.document.graph import load_doc_graph
    from palimind.storage.db import get_connection

    root = Path(root)
    requested = {t for t in (types or []) if t}
    if not requested:
        requested = {"file", "entity", "section"}

    graph = load_doc_graph(root)
    all_nodes = dict(getattr(graph, "nodes", {}) or {})
    all_edges = list(getattr(graph, "edges", []) or [])

    needs_rebuild = False
    db_files = 0
    if _has_db(root):
        conn = get_connection(root)
        try:
            db_files = int(_scalar(conn, "SELECT COUNT(*) FROM files") or 0)
            last_indexed = _scalar(conn, "SELECT MAX(last_indexed) FROM files")
        finally:
            conn.close()
        graph_file = palimind_dir(root) / "doc_graph.json"
        graph_mtime = graph_file.stat().st_mtime if graph_file.exists() else 0.0
        needs_rebuild = bool(db_files and not all_nodes) or bool(
            last_indexed and float(last_indexed) > graph_mtime
        )

    degree: dict[str, int] = {}
    for edge in all_edges:
        degree[edge.get("source", "")] = degree.get(edge.get("source", ""), 0) + 1
        degree[edge.get("target", "")] = degree.get(edge.get("target", ""), 0) + 1

    query = (q or "").strip().lower()

    def node_matches(node_id: str, meta: dict[str, Any]) -> bool:
        node_type = str(meta.get("type") or "unknown")
        if node_type not in requested:
            return False
        if query:
            haystack = f"{meta.get('label', '')} {meta.get('file_path', '')}".lower()
            if query not in haystack:
                return False
        if doc_year is not None and node_type == "file" and meta.get("doc_year") != doc_year:
            return False
        if doc_type and node_type == "file" and str(meta.get("doc_type") or "") != doc_type:
            return False
        if min_degree and degree.get(node_id, 0) < min_degree:
            return False
        return True

    kept: dict[str, dict[str, Any]] = {}
    for node_id, meta in all_nodes.items():
        if node_matches(node_id, meta):
            kept[node_id] = meta

    # A year/type filter is about files; keep sections/entities attached to the
    # matching files so the graph still tells a coherent story.
    if (doc_year is not None or doc_type) and kept:
        allowed_files = {
            nid for nid, meta in kept.items() if str(meta.get("type")) == "file"
        }
        for edge in all_edges:
            src, tgt = edge.get("source", ""), edge.get("target", "")
            for anchor, neighbor in ((src, tgt), (tgt, src)):
                if anchor not in allowed_files:
                    continue
                meta = all_nodes.get(neighbor)
                if meta is None:
                    continue
                # Keep the matching file's sections/entities, but never pull
                # in unrelated files that merely share an edge with it.
                if str(meta.get("type")) == "file":
                    continue
                if str(meta.get("type")) in requested:
                    kept.setdefault(neighbor, meta)

    total_nodes = len(kept)
    # Prioritise files, then highly-connected entities, then sections.
    priority = {"file": 0, "entity": 1, "section": 2}
    ordered = sorted(
        kept.items(),
        key=lambda item: (
            priority.get(str(item[1].get("type")), 3),
            -degree.get(item[0], 0),
            str(item[1].get("label") or ""),
        ),
    )
    if max_nodes > 0:
        ordered = ordered[: max(1, int(max_nodes))]
    visible = dict(ordered)

    edges = [
        edge
        for edge in all_edges
        if edge.get("source") in visible
        and edge.get("target") in visible
        and (not relation or edge.get("relation") == relation)
    ]
    if max_edges > 0:
        edges = edges[: max(1, int(max_edges))]

    nodes = [
        {
            "id": nid,
            "type": meta.get("type", "unknown"),
            "label": meta.get("label", nid),
            "file_path": meta.get("file_path", ""),
            "doc_year": meta.get("doc_year"),
            "doc_type": meta.get("doc_type"),
            "entity_type": meta.get("entity_type"),
            "degree": degree.get(nid, 0),
        }
        for nid, meta in ordered
    ]

    return {
        "nodes": nodes,
        "edges": [
            {
                "source": edge.get("source", ""),
                "target": edge.get("target", ""),
                "relation": edge.get("relation", ""),
                "weight": edge.get("weight", 1.0),
            }
            for edge in edges
        ],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "total_nodes": total_nodes,
        "total_edges": len(all_edges),
        "indexed_files": len(getattr(graph, "file_nodes", {}) or {}),
        "db_files": db_files,
        "needs_rebuild": needs_rebuild,
        "truncated": len(nodes) < total_nodes,
        "relations": sorted(
            {str(e.get("relation") or "") for e in all_edges if e.get("relation")}
        ),
        "types": sorted({str(m.get("type") or "unknown") for m in all_nodes.values()}),
    }
