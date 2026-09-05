"""Shared hybrid retrieval pipeline.

Extracted from :class:`palimind.document.engine.DocumentEngine` so document
chat, agents, MoE and CLI all go through the same retrieval code:

  query rewrite → batched embeddings → semantic + BM25 →
  reciprocal-rank fusion → graph expansion → rerank →
  diversity selection → window expansion → budgeted context assembly.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from palimind.exceptions import EmbeddingError
from palimind.storage.db import (
    fts_search,
    get_chunk_neighbors,
    get_connection,
    get_file_summary,
)
from palimind.storage.vector_store import search as vector_search

logger = logging.getLogger(__name__)

_rewrite_cache: dict[str, list[str]] = {}


def fmt_ts(seconds: float) -> str:
    """Format seconds as M:SS (or H:MM:SS above one hour)."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def rrf_fuse(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion across heterogeneous rankers.

    Each ranked list contributes 1 / (k + rank) to a chunk's fused score.
    """
    fused: dict[int, dict] = {}
    for ranked in ranked_lists:
        for rank, r in enumerate(ranked):
            cid = r.get("chunk_db_id")
            if cid is None:
                key = hash((r.get("file_path", ""), r.get("content", "")[:100]))
            else:
                key = int(cid)
            entry = fused.setdefault(key, {"result": r, "score": 0.0, "types": set()})
            entry["score"] += 1.0 / (k + rank)
            st = r.get("search_type", "")
            if st:
                entry["types"].add(st)

    for entry in fused.values():
        entry["result"]["relevance_score"] = round(entry["score"], 6)
        entry["result"]["rrf_score"] = round(entry["score"], 6)
        entry["result"]["search_type"] = (
            "+".join(t for t in ("semantic", "keyword") if t in entry["types"]) or "graph"
        )
    return sorted(fused.values(), key=lambda e: -e["score"])


def select_diverse(
    results: list[dict], limit: int, similarity_threshold: float = 82.0
) -> list[dict]:
    """Greedy selection with redundancy filtering (MMR-style, lexical).

    Skips candidates that are near-duplicates of already selected chunks
    (rapidfuzz token_set_ratio) and dampens source flooding.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:
        fuzz = None

    selected: list[dict] = []
    selected_texts: list[str] = []
    path_counts: Counter = Counter()

    for r in results:
        if len(selected) >= limit:
            break
        content = r.get("content", "")
        fp = r.get("file_path", "")

        # Dampen over-representation of a single file
        if path_counts[fp] >= 4:
            continue

        if fuzz is not None and content:
            if any(
                fuzz.token_set_ratio(content[:600], sel[:600]) >= similarity_threshold
                for sel in selected_texts
            ):
                continue

        path_counts[fp] += 1
        selected.append(r)
        if content:
            selected_texts.append(content)
    return selected


def expand_window(
    conn: Any, results: list[dict], window: int = 1, max_expansions: int = 8
) -> list[dict]:
    """Attach neighboring chunk content to top results for richer context."""
    expanded: list[dict] = []
    expansions = 0
    for r in results:
        item = dict(r)
        idx = r.get("chunk_index")
        fp = r.get("file_path", "")
        if (
            window > 0
            and idx is not None
            and fp
            and r.get("search_type") != "graph"
            and expansions < max_expansions
        ):
            try:
                neighbors = get_chunk_neighbors(conn, fp, int(idx), window, window)
                extra = [
                    n["content"]
                    for n in neighbors
                    if n["chunk_db_id"] != r.get("chunk_db_id") and n.get("content")
                ]
                if extra:
                    item["content"] = "\n\n".join([r.get("content", "")] + extra)
                    # Extend media timestamp range across expanded neighbors
                    last_end = None
                    for n in neighbors:
                        if n.get("media_end_ts") is not None:
                            last_end = n["media_end_ts"]
                    if r.get("media_start_ts") is not None and last_end is not None:
                        item["media_end_ts"] = max(
                            float(r.get("media_end_ts") or 0), float(last_end)
                        )
                    expansions += 1
            except Exception as e:
                logger.debug(f"Window expansion failed for {fp}#{idx}: {e}")
        expanded.append(item)
    return expanded


def base_query_variants(query: str) -> list[str]:
    """Cheap, zero-latency query variants (no LLM involved)."""
    variants = [query]
    stripped = query.strip().rstrip("?.!")
    if stripped.lower() != query.strip().lower() and len(stripped.split()) >= 4:
        variants.append(stripped)
    return variants


def rewrite_queries(
    query: str,
    *,
    ollama_url: str,
    light_model: str,
    enabled: bool = True,
) -> list[str]:
    """Use the light model to generate extra search query variants.

    Fails safe: returns [] on any error. Results are cached per query.
    """
    if not query.strip() or not light_model or not enabled:
        return []
    cached = _rewrite_cache.get(query)
    if cached is not None:
        return cached

    prompt = (
        "Rewrite the user's question into 2 alternative search queries for a "
        "document retrieval system. Use different keywords, synonyms, and "
        "phrasing that might appear in the documents. Return ONLY a JSON array "
        f'of strings, e.g. ["query one", "query two"].\n\nQuestion: "{query}"'
    )
    variants: list[str] = []
    try:
        import httpx

        url = f"{ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": light_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_predict": 120},
        }
        with httpx.Client(timeout=httpx.Timeout(connect=5.0, read=30.0)) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            raw = resp.json().get("message", {}).get("content", "")
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            variants = [str(v).strip() for v in parsed if str(v).strip()][:2]
    except Exception as e:
        logger.debug(f"Query rewrite failed (continuing without): {e}")

    if len(_rewrite_cache) > 256:
        _rewrite_cache.clear()
    _rewrite_cache[query] = variants
    return variants


def _index_exists(root: Path) -> bool:
    from palimind.storage.vector_store import _index_path as _vec_index_path

    return _vec_index_path(root).exists()


def _build_candidate_ids(root: Path, files_filter: list[str]) -> set[int] | None:
    """Resolve a file-path filter to a set of chunk ids for vector search."""
    if not files_filter:
        return None
    try:
        conn = get_connection(root)
        try:
            rows = conn.execute(
                """
                SELECT c.id FROM chunks c JOIN files f ON c.file_id = f.id
                WHERE f.path LIKE ?
                """,
                (f"%{files_filter[0]}%",),
            ).fetchall()
        finally:
            conn.close()
        return {row[0] for row in rows}
    except Exception as e:
        logger.debug(f"candidate_ids build failed: {e}")
        return None


def _assemble_context(
    selected_results: list[dict],
    token_budget: int | None,
) -> tuple[list[str], list[dict]]:
    """Build the context blocks, trimming to a token budget.

    Returns (context_parts, kept_results). A block's own token estimate is
    used for budgeting; window-expanded blocks fall back to a char/4 estimate.
    """
    parts: list[str] = []
    kept: list[dict] = []
    budget = token_budget
    used = 0

    for r in selected_results:
        fp = r.get("file_path", "unknown")
        sec = r.get("section_title", "") or r.get("main_section", "")
        sec_str = f" → {sec}" if sec else ""
        start_ts = r.get("media_start_ts")
        end_ts = r.get("media_end_ts")
        ts_str = ""
        if start_ts is not None:
            end_part = f"–{fmt_ts(float(end_ts))}" if end_ts is not None else ""
            ts_str = f" @ {fmt_ts(float(start_ts))}{end_part}"
        doc_year = r.get("doc_year")
        doc_type = r.get("doc_type", "")
        meta_parts = []
        if doc_year:
            meta_parts.append(f"Year: {doc_year}")
        if doc_type and doc_type != "other":
            meta_parts.append(f"Type: {doc_type}")
        meta_str = f" ({'; '.join(meta_parts)})" if meta_parts else ""
        header = f"--- Document: {fp}{sec_str}{ts_str}{meta_str} ---"
        block = f"{header}\n{r.get('content', '')}"

        if budget is not None:
            est = int(r.get("token_estimate") or 0) or max(1, len(block) // 4)
            if used + est > budget and kept:
                break
            used += est

        parts.append(block)
        kept.append(r)

    return parts, kept


def hybrid_search(
    root: Path,
    query: str,
    *,
    limit: int = 15,
    files_filter: list[str] | None = None,
    history: list[dict] | None = None,
    ollama_url: str = "",
    embed_model: str = "",
    light_model: str = "",
    rerank_enabled: bool = True,
    rerank_model: str = "BAAI/bge-reranker-base",
    query_rewrite_enabled: bool = True,
    context_token_budget: int | None = None,
    graph: Any | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Hybrid retrieval with multi-query expansion, RRF fusion, reranking,
    graph expansion, and budgeted context assembly.

    Returns dict with keys: content, sources, results, total_results,
    has_media, errors.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: UP035

    from palimind.core.embedder import generate_embeddings_batch

    sources: list[str] = []
    errors = errors if errors is not None else []

    # Resolve embedding model when not provided explicitly
    if not embed_model or not ollama_url:
        from palimind.config import load_config

        config = load_config(root)
        ollama_url = ollama_url or config.get("ollama_base_url", "http://localhost:11434")
        embed_model = embed_model or config.get("embed_model", "nomic-embed-text")
        if light_model == "":
            light_model = config.get("light_model", "") or config.get("chat_model", "")
        if rerank_model == "BAAI/bge-reranker-base":
            rerank_model = config.get("rerank_model") or rerank_model
        if context_token_budget is None:
            context_token_budget = config.get("context_token_budget")
        if limit is None or limit <= 0:
            limit = int(config.get("retrieval_limit", 10))

    executor = ThreadPoolExecutor(max_workers=6)
    try:
        # ── Kick off LLM query rewrite in the background ────────────────
        rewrite_future = executor.submit(
            rewrite_queries, query, ollama_url=ollama_url,
            light_model=light_model, enabled=query_rewrite_enabled,
        )

        base_variants = base_query_variants(query)

        # History context appended as an extra cheap variant
        if history:
            last_user_msg = ""
            for h in reversed(history):
                if h.get("role") == "user":
                    last_user_msg = h.get("content", "")
                    break
            combined = f"{query} {last_user_msg}"
            if (
                last_user_msg
                and len(last_user_msg.split()) >= 3
                and all(combined.lower() != v.lower() for v in base_variants)
            ):
                base_variants.append(combined)

        index_ok = _index_exists(root)
        if not index_ok:
            errors.append("No vector index found — run 'pm add' to index files first")

        # Pre-filter candidates when a file filter is active
        candidate_ids = _build_candidate_ids(root, files_filter or [])

        # ── Batch-embed ALL base variants in a single Ollama call ───────
        variant_vectors: dict[str, list[float]] = {}
        if index_ok and base_variants:
            try:
                vecs = generate_embeddings_batch(
                    base_variants, ollama_url, embed_model, root=root
                )
                variant_vectors = {
                    qv: vec for qv, vec in zip(base_variants, vecs, strict=False) if vec
                }
            except EmbeddingError as e:
                errors.append(f"Embedding failed: {e}")
            except Exception as e:
                errors.append(f"Embedding error: {e}")

        def _semantic(qv: str, vec: list[float]) -> list[dict]:
            res = vector_search(root, vec, limit=limit, candidate_ids=candidate_ids)
            for r in res:
                r["search_type"] = "semantic"
            return res

        def _keyword(qv: str, lim: int) -> list[dict]:
            conn = get_connection(root)
            try:
                if candidate_ids is not None:
                    res = _fts_with_candidates(conn, qv, candidate_ids, lim)
                else:
                    res = fts_search(conn, qv, limit=lim)
                for r in res:
                    r["search_type"] = "keyword"
                return res
            finally:
                conn.close()

        # ── Run semantic + keyword searches concurrently ────────────────
        pending: list[tuple[str, Any]] = []
        for qv, vec in variant_vectors.items():
            pending.append(("semantic", executor.submit(_semantic, qv, vec)))
        if base_variants:
            pending.append(("keyword", executor.submit(_keyword, query, limit)))
            for qv in base_variants[1:]:
                pending.append(("keyword", executor.submit(_keyword, qv, max(limit // 2, 1))))

        ranked_lists: list[list[dict]] = []
        for kind, fut in pending:
            try:
                res = fut.result(timeout=60.0)
                if res:
                    ranked_lists.append(res)
            except EmbeddingError as e:
                errors.append(f"Embedding failed: {e}")
            except Exception as e:
                errors.append(f"{kind.capitalize()} search error: {e}")

        # ── Collect rewritten variants if they finished within budget ───
        rewritten_variants: list[str] = []
        try:
            rewritten_variants = rewrite_future.result(timeout=1.5)
        except TimeoutError:
            logger.debug("Query rewrite exceeded budget — skipping extra variants")
        except Exception as e:
            logger.debug(f"Query rewrite failed: {e}")

        existing_lower = {v.lower() for v in base_variants}
        fresh_rewrites = [rv for rv in rewritten_variants if rv.lower() not in existing_lower]
        if index_ok and fresh_rewrites:
            try:
                rvecs = generate_embeddings_batch(
                    fresh_rewrites, ollama_url, embed_model, root=root
                )
                rw_pending = []
                for qv, vec in zip(fresh_rewrites, rvecs, strict=False):
                    if vec:
                        rw_pending.append(executor.submit(_semantic, qv, vec))
                for qv in fresh_rewrites:
                    rw_pending.append(executor.submit(_keyword, qv, max(limit // 2, 1)))
                for fut in rw_pending:
                    try:
                        res = fut.result(timeout=30.0)
                        if res:
                            ranked_lists.append(res)
                    except Exception as e:
                        errors.append(f"Rewrite search error: {e}")
            except Exception as e:
                errors.append(f"Rewrite embedding error: {e}")

        # ── Fusion: RRF across all ranked lists ──────────────────────────
        fused = rrf_fuse(ranked_lists)
        all_results = [entry["result"] for entry in fused]

        # ── Graph-based expansion of fused results ──────────────────────
        try:
            if graph is not None:
                conn2 = get_connection(root)
                try:
                    seen_keys: set[str] = set()
                    for r in list(all_results[:limit]):
                        fp = r.get("file_path", "")
                        if not fp:
                            continue
                        related = graph.get_related_files(fp)
                        for rel_fp in related[:3]:
                            if rel_fp not in sources:
                                sources.append(rel_fp)
                            summary = get_file_summary(conn2, rel_fp)
                            if summary:
                                key = f"graph:{rel_fp}"
                                if key not in seen_keys:
                                    seen_keys.add(key)
                                    all_results.append(
                                        {
                                            "file_path": rel_fp,
                                            "content": f"[Related: {rel_fp}]\n{summary[:2000]}",
                                            "section_title": "Related Document Summary",
                                            "search_type": "graph",
                                            "relevance_score": 0.5,
                                        }
                                    )
                finally:
                    conn2.close()
        except Exception as e:
            errors.append(f"Graph expansion error: {e}")

        if files_filter:
            all_results = [
                r for r in all_results if any(f in r.get("file_path", "") for f in files_filter)
            ]

        # ── Rerank fused candidates with local cross-encoder ─────────────
        non_graph = [r for r in all_results if r.get("search_type") != "graph"]
        graph_results = [r for r in all_results if r.get("search_type") == "graph"]
        if rerank_enabled and non_graph and query.strip():
            try:
                from palimind.core.reranker import rerank

                candidates = non_graph[:30]
                reranked = rerank(
                    query,
                    candidates,
                    root=root,
                    top_k=limit,
                    model_name=rerank_model,
                )
                if reranked:
                    non_graph = reranked + non_graph[30:]
            except Exception as e:
                errors.append(f"Rerank error: {e}")

        # ── Diversity selection (keeps graph summaries as supplements) ──
        selected = select_diverse(non_graph, limit)
        selected_results = selected + graph_results

        # ── Chunk window expansion for richer per-result context ────────
        try:
            conn3 = get_connection(root)
            try:
                selected_results = expand_window(conn3, selected_results)
            finally:
                conn3.close()
        except Exception as e:
            errors.append(f"Window expansion error: {e}")

        # ── Budgeted context assembly ────────────────────────────────────
        context_parts, kept_results = _assemble_context(selected_results, context_token_budget)
        for r in kept_results:
            fp = r.get("file_path", "unknown")
            if fp not in sources:
                sources.append(fp)

        has_media = any(r.get("media_start_ts") is not None for r in kept_results)

        deduped_errors = list(dict.fromkeys(errors))
        return {
            "content": "\n\n".join(context_parts),
            "sources": sources,
            "results": kept_results,
            "total_results": len(kept_results),
            "has_media": has_media,
            "errors": deduped_errors,
        }
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _fts_with_candidates(
    conn: Any, query: str, candidate_ids: set[int], limit: int
) -> list[dict]:
    """FTS search restricted to a candidate set of chunk ids."""
    try:
        placeholders = ",".join("?" * len(candidate_ids))
        import re as _re

        safe_query = _re.sub(r"[^\w\s\-]", " ", query, flags=_re.UNICODE).strip()
        terms = [f"{w}*" for w in safe_query.split() if len(w) >= 2]
        if not terms:
            return []
        fts_query = " OR ".join(terms)
        cur = conn.execute(
            f"""
            SELECT c.id, f.path, c.chunk_index, c.chunk_type, c.content,
                   chunks_fts.rank,
                   c.section_title, c.subsection, c.parent_section, c.page_number,
                   f.doc_year, f.doc_type, f.entity_name
            FROM chunks_fts
            JOIN chunks c ON chunks_fts.rowid = c.id
            JOIN files f ON c.file_id = f.id
            WHERE chunks_fts MATCH ? AND c.id IN ({placeholders})
            ORDER BY chunks_fts.rank
            LIMIT ?
            """,
            (fts_query, *sorted(candidate_ids), limit),
        )
    except Exception:
        return []

    results = []
    for row in cur.fetchall():
        results.append(
            {
                "chunk_db_id": row[0],
                "file_path": row[1],
                "chunk_index": row[2],
                "chunk_type": row[3],
                "content": row[4],
                "score": -row[5],
                "section_title": row[6] or "",
                "subsection": row[7] or "",
                "parent_section": row[8] or "",
                "page_number": row[9],
                "doc_year": row[10],
                "doc_type": row[11] or "other",
                "entity_name": row[12] or "",
            }
        )
    return results


def list_candidate_paths(root: Path, files_filter: Iterable[str]) -> list[str]:
    """Return indexed file paths matching any of the given substrings."""
    conn = get_connection(root)
    try:
        rows = conn.execute("SELECT path FROM files").fetchall()
    finally:
        conn.close()
    matches: set[str] = set()
    for (path,) in rows:
        if any(f in path for f in files_filter):
            matches.add(path)
    return sorted(matches)
