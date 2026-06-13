"""
Context retrieval with intent-based routing and metadata-aware search.

Retrieval strategies available:

  FILE_TARGETED  → fetch stored summary + all chunks for the named file
                   directly from SQLite — no vector search needed.

  CORPUS_WIDE    → build a manifest of all indexed files and their summaries,
                   injected as context so the LLM can answer "what's indexed?".

  SEMANTIC       → hybrid BM25+vector with RRF and CrossEncoder reranking.

  METADATA       → SQL pre-filter by doc_year/doc_type/section + hybrid search
                   on the candidate subset (used by comparison/risk pipelines).

  COMPARISON     → parallel per-document METADATA retrieval, one per year/doc.

All retrieval functions return plain ``list[dict]`` chunk records that include
the full metadata fields added in the enhanced schema.
"""
from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

from core.config import load_config
from core.retrieval.embedder import generate_embedding
from core.retrieval.router import IntentKind, classify_query as legacy_classify
from core.storage.db import (
    fts_search,
    fts_search_filtered,
    get_all_files,
    get_candidate_chunk_ids,
    get_chunks_for_file,
    get_connection,
    get_file_summary,
    get_rich_chunks_for_file,
)
from core.storage.vector_store import search


# ── Helpers ────────────────────────────────────────────────────────────────────

def _normalize_path(p: str) -> str:
    return p.replace("\\", "/").lower().strip()


def _all_indexed_paths(root: Path) -> list[str]:
    conn = get_connection(root)
    try:
        rows = conn.execute("SELECT path FROM files ORDER BY path").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def _all_indexed_docs(root: Path) -> list[dict]:
    conn = get_connection(root)
    try:
        return get_all_files(conn)
    finally:
        conn.close()


def _rrf(list1: list[dict], list2: list[dict], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion of two ranked result lists."""
    rrf_scores: dict[int, dict[str, Any]] = {}
    for rank, doc in enumerate(list1):
        doc_id = doc.get("chunk_db_id")
        if doc_id is not None:
            rrf_scores[doc_id] = {"doc": doc, "score": 1.0 / (k + rank)}
    for rank, doc in enumerate(list2):
        doc_id = doc.get("chunk_db_id")
        if doc_id is not None:
            if doc_id in rrf_scores:
                rrf_scores[doc_id]["score"] += 1.0 / (k + rank)
            else:
                rrf_scores[doc_id] = {"doc": doc, "score": 1.0 / (k + rank)}
    return [item["doc"] for item in sorted(rrf_scores.values(), key=lambda x: x["score"], reverse=True)]


def _apply_file_filter(results: list[dict], files_filter: list[str] | None) -> list[dict]:
    if not files_filter:
        return results
    normalized = {_normalize_path(f) for f in files_filter}
    return [r for r in results if _normalize_path(r.get("file_path", "")) in normalized]


# ── Legacy routes ──────────────────────────────────────────────────────────────

def _file_targeted_context(root: Path, matched_paths: list[str]) -> dict:
    conn = get_connection(root)
    text_contexts: list[str] = []
    try:
        for path in matched_paths:
            summary = get_file_summary(conn, path) or ""
            chunks = get_chunks_for_file(conn, path)
            if summary:
                text_contexts.append(f"Source ({path}) — Summary:\n{summary}")
            if chunks:
                full_text = "\n\n".join(chunks)
                text_contexts.append(f"Source ({path}) — Full content:\n{full_text}")
    finally:
        conn.close()
    return {"text_contexts": text_contexts, "image_paths": []}


def _corpus_wide_context(root: Path, files_filter: list[str] | None = None) -> dict:
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
        year_tag = f" ({f['doc_year']})" if f.get("doc_year") else ""
        type_tag = f" [{f['doc_type'].upper()}]" if f.get("doc_type") and f["doc_type"] != "other" else ""
        summary = f["summary"].strip() if f["summary"] else "No summary available."
        lines.append(f"• {path}{year_tag}{type_tag}\n  {summary}")

    manifest_block = "\n".join(lines)
    return {"text_contexts": [f"File manifest:\n{manifest_block}"], "image_paths": []}


# ── Core hybrid search ─────────────────────────────────────────────────────────

def _hybrid_search(
    query: str,
    root: Path,
    config: dict,
    limit: int,
    *,
    candidate_ids: set[int] | None = None,
    files_filter: list[str] | None = None,
    doc_year: int | None = None,
    doc_type: str | None = None,
    entity_name: str | None = None,
    section_title: str | None = None,
) -> list[dict]:
    """
    Core hybrid (BM25 + vector) search with optional metadata filtering.

    When ``candidate_ids`` is provided, vector search results are restricted
    to those IDs (pre-filtered via SQL). BM25 uses fts_search_filtered.
    """
    from core.retrieval.reranker import rerank_chunks

    ollama_url = config.get("ollama_base_url", "https://mighty-eggs-move.loca.lt")
    embed_model = config.get("embed_model", "nomic-embed-text")
    search_limit = max(limit * 3, 15)

    has_filters = any([doc_year, doc_type, entity_name, section_title, files_filter, candidate_ids])

    def _do_vector():
        query_vector = generate_embedding(query, ollama_url, embed_model)
        results = search(root, query_vector, limit=search_limit)
        if candidate_ids is not None:
            results = [r for r in results if r.get("chunk_db_id") in candidate_ids]
        elif files_filter:
            results = _apply_file_filter(results, files_filter)
        elif doc_year is not None:
            results = [r for r in results if r.get("doc_year") == doc_year]
        return results

    def _do_fts():
        conn = get_connection(root)
        try:
            if has_filters and (doc_year or doc_type or entity_name or section_title):
                return fts_search_filtered(
                    conn, query,
                    doc_year=doc_year,
                    doc_type=doc_type,
                    entity_name=entity_name,
                    section_title=section_title,
                    limit=search_limit,
                )
            results = fts_search(conn, query, limit=search_limit)
            if candidate_ids is not None:
                results = [r for r in results if r.get("chunk_db_id") in candidate_ids]
            elif files_filter:
                results = _apply_file_filter(results, files_filter)
            return results
        finally:
            conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        fut_vec = ex.submit(_do_vector)
        fut_fts = ex.submit(_do_fts)
        vector_results = fut_vec.result()
        fts_results = fut_fts.result()

    fused = _rrf(vector_results, fts_results)
    reranked = rerank_chunks(query, fused, top_n=limit)

    # Filter out chunks below a neutral relevance score.
    # ms-marco-MiniLM scores range ~-10 to +10; -1.0 is a "below neutral"
    # cutoff that removes clearly irrelevant chunks while keeping marginal ones.
    RELEVANCE_THRESHOLD = -1.0
    has_scores = any("rerank_score" in r for r in reranked)
    if has_scores:
        filtered = [r for r in reranked if r.get("rerank_score", 0.0) >= RELEVANCE_THRESHOLD]
        # Always keep at least 1 result so we never return empty-handed
        reranked = filtered if filtered else reranked[:1]

    return reranked


def _chunks_to_context_dict(chunks: list[dict], limit: int, root: Path, config: dict) -> dict:
    """Convert flat chunk list to the legacy {text_contexts, image_paths} format."""
    text_contexts: list[str] = []
    image_paths: set[str] = set()

    for row in chunks[:limit]:
        chunk_type = row.get("chunk_type", "text")
        content = row.get("content", "")
        file_path = row.get("file_path", "")
        section = row.get("section_title", "")

        if chunk_type in ("text", "caption", "table"):
            label = f"Source ({file_path}" + (f" — {section}" if section else "") + f"):\n{content}"
            text_contexts.append(label)
            if chunk_type == "caption":
                image_paths.add(file_path)
        elif chunk_type == "image":
            image_paths.add(file_path)

    # Fallback: inject file summaries when search returned nothing
    if not text_contexts:
        conn = get_connection(root)
        try:
            files = get_all_files(conn)
        finally:
            conn.close()
        for f in files:
            if f["summary"]:
                text_contexts.append(f"Source ({f['path']}) — Summary:\n{f['summary']}")
        text_contexts = text_contexts[:limit]

    return {"text_contexts": text_contexts, "image_paths": list(image_paths)}


# ── Public retrieval functions ─────────────────────────────────────────────────

def retrieve_documents(
    query: str,
    root: Path,
    limit: int = 5,
    *,
    files_filter: list[str] | None = None,
    section_filter: str | None = None,
    rerank: bool = True,
) -> list[dict]:
    """
    Hybrid BM25+vector retrieval with optional section filtering.

    Parameters
    ----------
    query: Search query string.
    root: Project root Path.
    limit: Maximum number of chunks to return.
    files_filter: Restrict results to these relative file paths.
    section_filter: Keyword to match against section_title (LIKE search).
    rerank: Whether to apply CrossEncoder reranking (default True).
    """
    config = load_config(root)
    return _hybrid_search(
        query, root, config, limit,
        files_filter=files_filter,
        section_title=section_filter,
    )


def retrieve_by_metadata(
    query: str,
    root: Path,
    limit: int = 5,
    *,
    doc_year: int | None = None,
    doc_type: str | None = None,
    entity_name: str | None = None,
    section_title: str | None = None,
    files_filter: list[str] | None = None,
) -> list[dict]:
    """
    Metadata-filtered retrieval: SQL pre-filter then hybrid search.

    Applies year/type/entity/section filters BEFORE embedding search so
    only chunks from the target documents are considered.
    """
    config = load_config(root)

    # Build candidate set via SQL
    conn = get_connection(root)
    try:
        candidate_ids = get_candidate_chunk_ids(
            conn,
            doc_year=doc_year,
            doc_type=doc_type,
            entity_name=entity_name,
            section_title=section_title,
            file_paths=files_filter,
        )
    finally:
        conn.close()

    if not candidate_ids:
        # No candidates match the metadata filter — return empty
        return []

    return _hybrid_search(
        query, root, config, limit,
        candidate_ids=candidate_ids,
        doc_year=doc_year,
        doc_type=doc_type,
        entity_name=entity_name,
        section_title=section_title,
        files_filter=files_filter,
    )


def retrieve_risk_factors(
    query: str,
    root: Path,
    limit: int = 6,
    *,
    doc_year: int | None = None,
    entity_name: str | None = None,
) -> list[dict]:
    """
    Section-targeted retrieval for risk factor sections.

    Searches only chunks whose section_title contains "risk" (Item 1A etc.).
    Falls back to full corpus search if no risk section chunks found.
    """
    chunks = retrieve_by_metadata(
        query, root, limit,
        doc_year=doc_year,
        entity_name=entity_name,
        section_title="risk",
    )
    if not chunks:
        # Fallback: full semantic search
        chunks = retrieve_documents(query, root, limit)
    return chunks


def retrieve_for_comparison(
    query: str,
    root: Path,
    years: list[int],
    chunks_per_doc: int = 4,
    *,
    section_title: str | None = None,
) -> dict[int, list[dict]]:
    """
    Parallel per-year retrieval for comparison queries.

    Returns {year: [chunks]} where each year gets its own retrieval call
    running concurrently. Equal chunk budget per year ensures balanced coverage.
    """
    def _retrieve_year(year: int) -> tuple[int, list[dict]]:
        year_chunks = retrieve_by_metadata(
            query, root, chunks_per_doc,
            doc_year=year,
            section_title=section_title,
        )
        return year, year_chunks

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(years), 4)) as ex:
        futures = {ex.submit(_retrieve_year, yr): yr for yr in years}
        results: dict[int, list[dict]] = {}
        for fut in concurrent.futures.as_completed(futures):
            year, chunks = fut.result()
            results[year] = chunks

    return results


# ── Legacy entry point (used by existing querying.py) ─────────────────────────

def _semantic_context(
    query: str,
    root: Path,
    config: dict,
    limit: int,
    files_filter: list[str] | None = None,
) -> dict:
    """Legacy _semantic_context — wraps retrieve_documents for backward compat."""
    chunks = _hybrid_search(query, root, config, limit, files_filter=files_filter)
    return _chunks_to_context_dict(chunks, limit, root, config)


def retrieve_context(
    query: str,
    root: Path,
    limit: int = 5,
    files_filter: list[str] | None = None,
) -> dict:
    """
    Retrieve relevant context using intent-based routing.
    Legacy entry point used by querying.py.
    Returns {text_contexts: list[str], image_paths: list[str]}.
    """
    config = load_config(root)
    indexed_paths = _all_indexed_paths(root)

    intent = legacy_classify(query, indexed_paths)

    if intent.kind == IntentKind.FILE_TARGETED:
        matched = intent.matched_paths
        if files_filter:
            normalized_filter = {_normalize_path(f) for f in files_filter}
            matched = [p for p in matched if _normalize_path(p) in normalized_filter]
        return _file_targeted_context(root, matched)

    if intent.kind == IntentKind.CORPUS_WIDE:
        return _corpus_wide_context(root, files_filter=files_filter)

    return _semantic_context(query, root, config, limit, files_filter=files_filter)
