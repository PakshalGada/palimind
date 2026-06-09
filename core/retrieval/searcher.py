"""
Context retrieval with intent-based routing.

Before touching the vector index, the query is classified by the router:

  FILE_TARGETED  → fetch stored summary + all chunks for the named file
                   directly from SQLite — no vector search needed.

  CORPUS_WIDE    → build a manifest of all indexed files and their summaries,
                   injected as context so the LLM can answer "what's indexed?".

  SEMANTIC       → standard turbovec similarity search (original behaviour),
                   but with file summaries injected as fallback if no hits.
"""
from __future__ import annotations

from pathlib import Path

from core.config import load_config
from core.retrieval.embedder import generate_embedding
from core.retrieval.router import IntentKind, classify_query
from core.storage.db import (
    get_all_files,
    get_chunks_for_file,
    get_connection,
    get_file_summary,
)
from core.storage.vector_store import search


def _all_indexed_paths(root: Path) -> list[str]:
    """Return all file paths currently tracked in the index."""
    conn = get_connection(root)
    try:
        rows = conn.execute("SELECT path FROM files ORDER BY path").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def _file_targeted_context(root: Path, matched_paths: list[str]) -> dict:
    """
    For file-targeted queries, pull the stored summary and all chunk text
    for each matched file directly from SQLite.
    """
    conn = get_connection(root)
    text_contexts: list[str] = []
    try:
        for path in matched_paths:
            summary = get_file_summary(conn, path) or ""
            chunks = get_chunks_for_file(conn, path)

            if summary:
                text_contexts.append(
                    f"Source ({path}) — Summary:\n{summary}"
                )
            if chunks:
                full_text = "\n\n".join(chunks)
                text_contexts.append(
                    f"Source ({path}) — Full content:\n{full_text}"
                )
    finally:
        conn.close()

    return {"text_contexts": text_contexts, "image_paths": []}


def _normalize_path(p: str) -> str:
    return p.replace("\\", "/").lower().strip()


def _corpus_wide_context(root: Path, files_filter: list[str] | None = None) -> dict:
    """
    Build a structured file-manifest context block listing all indexed
    files and their summaries. Used to answer "what files are indexed?" etc.
    """
    conn = get_connection(root)
    try:
        files = get_all_files(conn)
    finally:
        conn.close()

    if not files:
        return {"text_contexts": [], "image_paths": []}

    normalized_filter = {_normalize_path(f) for f in files_filter} if files_filter else set()

    lines = ["Indexed files in this knowledge base:\n"]
    for f in files:
        path = f["path"]
        if normalized_filter and _normalize_path(path) not in normalized_filter:
            continue
        summary = f["summary"].strip() if f["summary"] else "No summary available."
        lines.append(f"• {path}\n  {summary}")

    manifest_block = "\n".join(lines)
    return {
        "text_contexts": [f"File manifest:\n{manifest_block}"],
        "image_paths": [],
    }


def _semantic_context(query: str, root: Path, config: dict, limit: int, files_filter: list[str] | None = None) -> dict:
    """Standard turbovec vector similarity search."""
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    embed_model = config.get("embed_model", "nomic-embed-text")

    query_vector = generate_embedding(query, ollama_url, embed_model)
    search_limit = max(limit * 5, 50) if files_filter else limit
    results = search(root, query_vector, limit=search_limit)

    text_contexts: list[str] = []
    image_paths: set[str] = set()
    normalized_filter = {_normalize_path(f) for f in files_filter} if files_filter else set()

    for row in results:
        chunk_type = row.get("chunk_type", "text")
        content = row.get("content", "")
        file_path = row.get("file_path", "")

        if normalized_filter and _normalize_path(file_path) not in normalized_filter:
            continue

        if len(text_contexts) >= limit:
            if chunk_type not in ["caption", "image"]:
                continue

        if chunk_type in ["text", "caption"]:
            text_contexts.append(f"Source ({file_path}):\n{content}")
            if chunk_type == "caption":
                image_paths.add(file_path)
        elif chunk_type == "image":
            image_paths.add(file_path)

    # Fallback: if vector search found nothing, inject file summaries so the
    # LLM at least knows what's in the index.
    if not text_contexts:
        conn = get_connection(root)
        try:
            files = get_all_files(conn)
        finally:
            conn.close()
        summaries = []
        for f in files:
            path = f["path"]
            if normalized_filter and _normalize_path(path) not in normalized_filter:
                continue
            if f["summary"]:
                summaries.append(f"Source ({path}) — Summary:\n{f['summary']}")
        text_contexts = summaries[:limit]

    return {"text_contexts": text_contexts[:limit], "image_paths": list(image_paths)}


def retrieve_context(query: str, root: Path, limit: int = 5, files_filter: list[str] | None = None) -> dict:
    """
    Retrieve relevant context for *query* using intent-based routing.

    Returns a dict with ``text_contexts`` (list[str]) and
    ``image_paths`` (list[str]).
    """
    config = load_config(root)
    indexed_paths = _all_indexed_paths(root)

    intent = classify_query(query, indexed_paths)

    if intent.kind == IntentKind.FILE_TARGETED:
        matched = intent.matched_paths
        if files_filter:
            normalized_filter = {_normalize_path(f) for f in files_filter}
            matched = [p for p in matched if _normalize_path(p) in normalized_filter]
        return _file_targeted_context(root, matched)

    if intent.kind == IntentKind.CORPUS_WIDE:
        return _corpus_wide_context(root, files_filter=files_filter)

    # Default: SEMANTIC
    return _semantic_context(query, root, config, limit, files_filter=files_filter)
