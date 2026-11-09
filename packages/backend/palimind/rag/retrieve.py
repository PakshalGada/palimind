"""Shared hybrid retrieval pipeline.

Extracted from :class:`palimind.document.engine.DocumentEngine` so document
chat, agents, MoE and CLI all go through the same retrieval code:

  query rewrite → batched embeddings → semantic + BM25 →
  reciprocal-rank fusion → graph expansion → rerank →
  diversity selection → window expansion → budgeted context assembly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from palimind.exceptions import EmbeddingError
from palimind.opencode.client import proxy_auth_headers
from palimind.storage.db import (
    fts_search,
    get_candidate_chunk_ids,
    get_chunk_neighbors,
    get_connection,
    get_file_summary,
    get_section_chunks,
    search_summary_files,
)
from palimind.storage.vector_store import (  # noqa: F401 - kept for callers/tests
    index_compatibility_error,
    index_dimension,
    read_stamp,
)
from palimind.storage.vector_store import search as vector_search

logger = logging.getLogger(__name__)

_rewrite_cache: dict[str, list[str]] = {}
_query_emb_cache: dict[str, list[float]] = {}
_query_emb_cache_max = 512
_semantic_result_cache: dict[str, dict] = {}
_SEMANTIC_CACHE_MAX = 256
_SEMANTIC_CACHE_TTL = 300  # 5 minutes


def fmt_ts(seconds: float) -> str:
    """Format seconds as M:SS (or H:MM:SS above one hour)."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def rrf_fuse(
    ranked_lists: list[list[dict]], k: int = 60, weights: list[float] | None = None
) -> list[dict]:
    """Reciprocal Rank Fusion across heterogeneous rankers.

    Each ranked list contributes ``weight / (k + rank)`` to a chunk's fused
    score. Weights let a high-precision lane (exact phrase / acronym) outrank
    noisy semantic lanes without discarding them.
    """
    fused: dict[int, dict] = {}
    for list_index, ranked in enumerate(ranked_lists):
        weight = 1.0
        if weights and list_index < len(weights):
            weight = float(weights[list_index])
        for rank, r in enumerate(ranked):
            cid = r.get("chunk_db_id")
            if cid is None:
                key = hash((r.get("file_path", ""), r.get("content", "")[:100]))
            else:
                key = int(cid)
            entry = fused.setdefault(key, {"result": r, "score": 0.0, "types": set()})
            entry["score"] += weight / (k + rank)
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
    results: list[dict],
    limit: int,
    similarity_threshold: float = 82.0,
    per_file_cap: int = 4,
) -> list[dict]:
    """Greedy selection with redundancy filtering (MMR-style, lexical).

    Skips candidates that are near-duplicates of already selected chunks
    (rapidfuzz token_set_ratio) and dampens source flooding.
    """
    fuzz: Any = None
    try:
        from rapidfuzz import fuzz as _rapidfuzz

        fuzz = _rapidfuzz
    except ImportError:
        pass

    selected: list[dict] = []
    selected_texts: list[str] = []
    path_counts: Counter = Counter()

    for r in results:
        if len(selected) >= limit:
            break
        content = r.get("content", "")
        fp = r.get("file_path", "")

        # Dampen over-representation of a single file
        if per_file_cap > 0 and path_counts[fp] >= per_file_cap:
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


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def _candidate_vectors(root: Path | None, pool: list[dict]) -> list[list[float] | None]:
    """Embeddings for the MMR pool, read from the FAISS index itself.

    This deliberately avoids :mod:`palimind.core.embedder`: re-embedding would
    either cost an HTTP call or load the whole JSON embedding cache, while the
    vectors are already persisted in the index.
    """
    ids = [r.get("chunk_db_id") for r in pool]
    wanted = {int(cid) for cid in ids if cid is not None}
    if not root or not wanted:
        return [None] * len(pool)
    try:
        from palimind.storage.vector_store import get_vectors

        mapping = get_vectors(root, wanted)
    except Exception as e:  # noqa: BLE001 - MMR is an optimization
        logger.debug(f"MMR vectors unavailable: {e}")
        return [None] * len(pool)
    return [mapping.get(int(cid)) if cid is not None else None for cid in ids]


def select_mmr(
    results: list[dict],
    limit: int,
    *,
    root: Path | None = None,
    query_vector: list[float] | None = None,
    lambda_: float = 0.7,
    per_file_cap: int = 4,
    candidate_pool: int = 0,
) -> list[dict]:
    """Maximal Marginal Relevance selection using stored chunk embeddings.

    Embeddings come straight from the FAISS index, so this adds no HTTP call.
    If they are unavailable it degrades to the lexical :func:`select_diverse`
    path rather than failing retrieval.
    """
    pool = results[:candidate_pool] if candidate_pool and candidate_pool > 0 else results
    if len(pool) <= 1:
        return pool[:limit]

    vectors = _candidate_vectors(root, pool)

    if sum(1 for v in vectors if v) < 2:
        return select_diverse(results, limit, per_file_cap=per_file_cap)

    # Relevance prior: cosine to the query when available, else the fused RRF
    # score normalized across the candidate pool.
    # Relevance prior: the fused RRF score is the primary signal (it already
    # includes semantic rank, BM25, all-terms and acronym lanes). A cosine
    # term breaks ties between semantically similar chunks but must not
    # override an exact identifier hit.
    raw = []
    for r in pool:
        value = r.get("_rerank_score")
        if value is None:
            value = r.get("rrf_score") or r.get("relevance_score") or 0.0
        raw.append(float(value or 0.0))
    hi = max(raw) if raw else 0.0
    lo = min(raw) if raw else 0.0
    span = hi - lo
    fused_rel = [((s - lo) / span) if span > 0 else 1.0 for s in raw]

    if query_vector and any(vectors):
        cosine_rel = [
            (max(-1.0, min(1.0, _cosine(v, query_vector))) + 1.0) / 2.0 if v else 0.0
            for v in vectors
        ]
        rel = [
            0.7 * fused + 0.3 * cosine for fused, cosine in zip(fused_rel, cosine_rel, strict=False)
        ]
    else:
        rel = fused_rel

    lam = max(0.0, min(1.0, float(lambda_)))
    selected: list[dict] = []
    selected_idx: set[int] = set()
    selected_vecs: list[list[float]] = []
    path_counts: Counter = Counter()
    seen_content: set[str] = set()

    while len(selected) < limit:
        best_i: int | None = None
        best_score = float("-inf")
        for i, r in enumerate(pool):
            if i in selected_idx:
                continue
            fp = r.get("file_path", "")
            if per_file_cap > 0 and path_counts[fp] >= per_file_cap:
                continue
            content_key = hashlib.sha1(
                str(r.get("content") or "").encode("utf-8", "replace")
            ).hexdigest()
            if content_key in seen_content:
                continue
            vec = vectors[i]
            redundancy = 0.0
            if vec and selected_vecs:
                redundancy = max(_cosine(vec, sv) for sv in selected_vecs)
                # Near-identical passages add no information; skip rather than
                # let a high relevance score keep a duplicate.
                if redundancy >= 0.98:
                    continue
            score = lam * rel[i] - (1.0 - lam) * redundancy
            if score > best_score:
                best_score = score
                best_i = i
        if best_i is None:
            break
        selected_idx.add(best_i)
        chosen = pool[best_i]
        selected.append(chosen)
        path_counts[chosen.get("file_path", "")] += 1
        seen_content.add(
            hashlib.sha1(str(chosen.get("content") or "").encode("utf-8", "replace")).hexdigest()
        )
        if vectors[best_i]:
            selected_vecs.append(vectors[best_i])  # type: ignore[arg-type]

    return selected


def expand_parent_sections(
    conn: Any,
    results: list[dict],
    *,
    max_tokens: int = 1500,
    enabled: bool = True,
) -> list[dict]:
    """Small-to-big expansion: replace each child hit with its parent section.

    The child chunk is what matched semantically; the whole section is what
    the LLM should read. Sections above *max_tokens* fall back to the child so
    one enormous section cannot crowd out every other source.
    """
    if not enabled:
        return results

    expanded: list[dict] = []
    seen_sections: set[tuple[str, str, str, str]] = set()

    for r in results:
        item = dict(r)
        if r.get("search_type") in ("graph", "summary"):
            expanded.append(item)
            continue

        fp = r.get("file_path", "")
        main_section = r.get("main_section", "")
        parent_section = r.get("parent_section", "") or main_section
        section_title = r.get("section_title", "")
        if not fp or not (parent_section or section_title):
            expanded.append(item)
            continue

        key = (fp, main_section, parent_section, section_title)
        if key in seen_sections:
            # The parent text is already in the context once; keep this child
            # as a compact extra hit instead of repeating the whole section.
            expanded.append(item)
            continue
        seen_sections.add(key)

        try:
            siblings = get_section_chunks(conn, fp, parent_section, section_title, main_section)
        except Exception as e:  # noqa: BLE001 - expansion is best-effort
            logger.debug(f"Parent expansion failed for {fp}: {e}")
            expanded.append(item)
            continue

        if len(siblings) <= 1:
            expanded.append(item)
            continue

        estimated = sum(
            int(s.get("token_estimate") or max(1, len(s.get("content", "")) // 4)) for s in siblings
        )
        if estimated > max_tokens:
            expanded.append(item)
            continue

        pages = [int(s["page_number"]) for s in siblings if s.get("page_number") is not None]
        item["child_content"] = r.get("content", "")
        item["content"] = "\n\n".join(s.get("content", "") for s in siblings if s.get("content"))
        item["parent_expanded"] = True
        item["token_estimate"] = estimated
        if pages:
            item["page_number"] = min(pages)
            item["page_end"] = max(pages)
        expanded.append(item)

    return expanded


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
            and r.get("search_type") not in ("graph", "summary", "exact")
            and not r.get("parent_expanded")
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
                    # Extend the page range too, so a block that spans pages is
                    # cited as "p. 6–7" rather than only its first page.
                    pages = [
                        int(n["page_number"]) for n in neighbors if n.get("page_number") is not None
                    ]
                    if r.get("page_number") is not None:
                        pages.append(int(r["page_number"]))
                    if pages:
                        item["page_number"] = min(pages)
                        item["page_end"] = max(pages)
                    expansions += 1
            except Exception as e:
                logger.debug(f"Window expansion failed for {fp}#{idx}: {e}")
        expanded.append(item)
    return expanded


_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}\b")
_MODEL_ID_RE = re.compile(r"\b[A-Za-z]{2,12}-\d{2,5}\b")
_QUOTED_TERM_RE = re.compile(r'"([^"\n]{3,60})"|\'([^\'\n]{3,60})\'')
_COMMON_ACRONYMS = {
    "AI",
    "API",
    "CPU",
    "CSV",
    "GPU",
    "HTML",
    "HTTP",
    "HTTPS",
    "ID",
    "JSON",
    "LLM",
    "OK",
    "PDF",
    "SQL",
    "UI",
    "URL",
    "USB",
    "XML",
    "YAML",
}


def _distinctive_terms(query: str, max_terms: int = 3) -> list[str]:
    """Extract rare, high-signal identifiers from a query.

    Acronyms ("SDDR"), product/model ids ("IRC-2027") and quoted phrases are
    effectively unique keys. Searching them as their own BM25 lane prevents a
    short acronym query from being swamped by thousands of documents that
    share a generic word like "video" or "limit".
    """
    terms: list[str] = []
    for match in _QUOTED_TERM_RE.finditer(query or ""):
        value = (match.group(1) or match.group(2) or "").strip()
        if value:
            terms.append(value)
    for match in _MODEL_ID_RE.finditer(query or ""):
        terms.append(match.group(0))
    for match in _ACRONYM_RE.finditer(query or ""):
        value = match.group(0)
        if value not in _COMMON_ACRONYMS and len(value) >= 2:
            terms.append(value)

    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= max_terms:
            break
    return out


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
            resp = client.post(url, json=payload, headers=proxy_auth_headers(url))
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


def _known_embedding_dim(model_id: str) -> int:
    """Known output dimension for an embedding model name (0 if unknown)."""
    try:
        from palimind.model_capabilities import infer_from_name

        return int(infer_from_name(model_id).embedding_dim or 0)
    except Exception:
        return 0


def _build_candidate_ids(
    root: Path,
    files_filter: list[str],
    *,
    doc_year: int | None = None,
    doc_type: str | None = None,
    entity_name: str | None = None,
    section_title: str | None = None,
) -> set[int] | None:
    """Resolve file/metadata filters to a set of chunk ids for vector search."""
    has_meta = any(v is not None for v in (doc_year, doc_type, entity_name, section_title))
    if not files_filter and not has_meta:
        return None
    try:
        conn = get_connection(root)
        try:
            file_ids: set[int] | None = None
            if files_filter:
                # Every filter counts — matching only the first one silently
                # excluded all other selected files from semantic/keyword search.
                where = " OR ".join("f.path LIKE ?" for _ in files_filter)
                rows = conn.execute(
                    f"""
                    SELECT c.id FROM chunks c JOIN files f ON c.file_id = f.id
                    WHERE {where}
                    """,
                    tuple(f"%{f}%" for f in files_filter),
                ).fetchall()
                file_ids = {row[0] for row in rows}

            if not has_meta:
                return file_ids

            meta_ids = get_candidate_chunk_ids(
                conn,
                doc_year=doc_year,
                doc_type=doc_type,
                entity_name=entity_name,
                section_title=section_title,
            )
            return meta_ids if file_ids is None else meta_ids & file_ids
        finally:
            conn.close()
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
        page = r.get("page_number")
        end_page = r.get("page_end")
        page_str = ""
        if page is not None:
            span_end = f"–{end_page}" if end_page is not None and end_page != page else ""
            page_str = f" (p. {page}{span_end})"
        doc_year = r.get("doc_year")
        doc_type = r.get("doc_type", "")
        meta_parts = []
        if doc_year:
            meta_parts.append(f"Year: {doc_year}")
        if doc_type and doc_type != "other":
            meta_parts.append(f"Type: {doc_type}")
        meta_str = f" ({'; '.join(meta_parts)})" if meta_parts else ""
        header = f"--- Document: {fp}{sec_str}{page_str}{ts_str}{meta_str} ---"
        block = f"{header}\n{r.get('content', '')}"

        if budget is not None:
            est = int(r.get("token_estimate") or 0) or max(1, len(block) // 4)
            if used + est > budget and kept:
                break
            used += est

        parts.append(block)
        kept.append(r)

    return parts, kept


def _entity_boost(
    all_results: list[dict], graph: Any | None, query: str, bonus: float = 0.1
) -> list[dict]:
    """Promote chunks from files matching entities named in *query*.

    This makes the knowledge graph change answers directly: a query that names
    an entity boosts that entity's documents' fused scores instead of merely
    appending unranked summaries.
    """
    if graph is None or not query.strip():
        return all_results
    try:
        matched = graph.match_entities(query)
        boosted_files: set[str] = set()
        for node_id in matched:
            boosted_files.update(graph.files_for_entity(node_id))
        if not boosted_files:
            return all_results
    except Exception as e:
        logger.debug(f"Entity boost failed: {e}")
        return all_results

    # RRF scores are tiny (≈1/61 per list); a flat bonus would swamp text
    # relevance. Scale the boost to the best fused score instead.
    top_score = max((float(r.get("rrf_score") or 0.0) for r in all_results), default=0.0) or 1.0
    for r in all_results:
        if r.get("file_path") in boosted_files:
            r["rrf_score"] = (r.get("rrf_score") or 0) + bonus * top_score
            r["entity_boosted"] = True
    return sorted(all_results, key=lambda r: -(r.get("rrf_score") or 0))


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
    rerank_enabled: bool = False,
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    query_rewrite_enabled: bool = True,
    context_token_budget: int | None = None,
    graph: Any | None = None,
    errors: list[str] | None = None,
    doc_year: int | None = None,
    doc_type: str | None = None,
    entity_name: str | None = None,
    section_title: str | None = None,
    candidate_depth: int | None = None,
    parent_retrieval: bool | None = None,
    parent_max_tokens: int | None = None,
    mmr_enabled: bool | None = None,
    mmr_lambda: float | None = None,
    mmr_per_file_cap: int | None = None,
    summary_search: bool | None = None,
) -> dict[str, Any]:
    """Hybrid retrieval with multi-query expansion, RRF fusion, reranking,
    graph/summary expansion, small-to-big parent assembly, MMR diversity, and
    budgeted context assembly.

    Metadata filters (``doc_year``, ``doc_type``, ``entity_name``,
    ``section_title``) are applied to both semantic and keyword search.

    Returns dict with keys: content, sources, results, total_results,
    has_media, errors.
    """
    from concurrent.futures import ThreadPoolExecutor  # noqa: UP035

    from palimind.config import load_config
    from palimind.core.embedder import generate_embeddings_batch

    sources: list[str] = []
    errors = errors if errors is not None else []
    timings: dict[str, float] = {}
    t_start = time.perf_counter()

    # Always read workspace config so retrieval options resolve even when the
    # caller supplies the model/URL explicitly (the common document-chat path).
    config: dict[str, Any] = load_config(root)
    ollama_url = ollama_url or config.get("ollama_base_url", "http://localhost:11434")
    embed_model = embed_model or config.get("embed_model", "bge-m3")
    if light_model == "":
        light_model = config.get("light_model", "") or config.get("chat_model", "")
    if rerank_model == "cross-encoder/ms-marco-MiniLM-L-6-v2":
        rerank_model = config.get("rerank_model") or rerank_model
    if context_token_budget is None:
        context_token_budget = config.get("context_token_budget")
    if limit is None or limit <= 0:
        limit = int(config.get("retrieval_limit", 10))
    if candidate_depth is None:
        candidate_depth = int(config.get("retrieval_candidate_depth", 50))
    candidate_depth = max(int(limit), int(candidate_depth))
    if parent_retrieval is None:
        parent_retrieval = bool(config.get("parent_retrieval", True))
    if parent_max_tokens is None:
        parent_max_tokens = int(config.get("parent_max_tokens", 1500))
    if mmr_enabled is None:
        mmr_enabled = bool(config.get("mmr", True))
    if mmr_lambda is None:
        mmr_lambda = float(config.get("mmr_lambda", 0.7))
    if mmr_per_file_cap is None:
        mmr_per_file_cap = int(config.get("mmr_per_file_cap", 4))
    if summary_search is None:
        summary_search = bool(config.get("summary_search", True))
    sparse_enabled = bool(config.get("sparse_retrieval", False))
    colbert_enabled = bool(config.get("colbert_rerank", False))

    executor = ThreadPoolExecutor(max_workers=6)
    try:
        # Semantic cache: key includes embed_model so switching models doesn't
        # serve results computed with the previous one.
        # The index root is part of the key: without it, the same query in a
        # different knowledge base / project returned the other index's hits.
        cache_key = (
            f"{Path(root).resolve()}:{query}:{limit}:{files_filter}:{embed_model}:"
            f"{graph is not None}:{rerank_enabled}:{context_token_budget}:"
            f"{doc_year}:{doc_type}:{entity_name}:{section_title}:{candidate_depth}:"
            f"{parent_retrieval}:{parent_max_tokens}:{mmr_enabled}:{mmr_lambda}:"
            f"{mmr_per_file_cap}:{summary_search}:"
            f"{json.dumps(history or [], sort_keys=True, default=str)[-500:]}"
        )
        cached = _semantic_result_cache.get(cache_key)
        if cached is not None:
            cached_ts = cached.get("_ts", 0)
            if time.time() - cached_ts < _SEMANTIC_CACHE_TTL:
                return cached
            else:
                del _semantic_result_cache[cache_key]
        # ── Kick off LLM query rewrite in the background ────────────────
        rewrite_future = executor.submit(
            rewrite_queries,
            query,
            ollama_url=ollama_url,
            light_model=light_model,
            enabled=query_rewrite_enabled,
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
        index_error = None
        index_dim: int | None = None
        query_embed_model = embed_model
        if not index_ok:
            errors.append("No vector index found — run 'pm add' to index files first")
        else:
            index_dim = index_dimension(root)
            stamp = read_stamp(root) or {}
            stamp_model = str(stamp.get("model") or "")
            stamp_dim = int(stamp.get("dim") or 0)

            if index_dim is None:
                index_error = "The vector index could not be loaded. Rebuild it with 'pm update'."
            elif stamp_dim and stamp_dim != index_dim:
                index_error = (
                    f"Vector index dimension ({index_dim}) does not match its stamp "
                    f"({stamp_dim}). Rebuild it with 'pm update'."
                )
            elif stamp_model and stamp_model != embed_model:
                # The config changed but the index was not rebuilt. Query with
                # the model that actually produced the vectors so retrieval
                # keeps working; the user is told a reindex is pending.
                query_embed_model = stamp_model
                note = (
                    f"Index was built with '{stamp_model}' but '{embed_model}' is "
                    f"configured; using '{stamp_model}' until the next reindex."
                )
                logger.warning(note)
                errors.append(note)

            if index_error is None:
                expected_dim = _known_embedding_dim(query_embed_model)
                if not expected_dim:
                    expected_dim = int(config.get("embed_dim") or 0)
                if expected_dim and index_dim and expected_dim != index_dim:
                    index_error = (
                        f"Embedding model '{query_embed_model}' produces {expected_dim}-dim "
                        f"vectors but the index has {index_dim}-dim. Restore the original "
                        "model or rebuild the index with 'pm update'."
                    )
            if index_error:
                logger.error("Vector index incompatible: %s", index_error)
                errors.append(f"Semantic search disabled: {index_error}")
                index_ok = False

        # Pre-filter candidates when a file or metadata filter is active
        has_metadata_filter = any(
            v is not None for v in (doc_year, doc_type, entity_name, section_title)
        )
        if has_metadata_filter:
            candidate_ids = _build_candidate_ids(
                root,
                files_filter or [],
                doc_year=doc_year,
                doc_type=doc_type,
                entity_name=entity_name,
                section_title=section_title,
            )
        else:
            candidate_ids = _build_candidate_ids(root, files_filter or [])

        # Deep candidate pool: the reranker/MMR needs more than the final
        # `limit` to choose from, and HNSW over-fetch is cheap.
        fetch_limit = max(1, int(candidate_depth))

        # NOTE: vector search intentionally runs over the *whole* index (true
        # hybrid). Previously it was restricted to the BM25/FTS5 candidate set,
        # which silently dropped semantically-relevant chunks that shared no
        # keywords with the query. HNSW makes the full search cheap.

        # ── Batch-embed ALL base variants with query embedding cache ────
        variant_vectors: dict[str, list[float]] = {}
        if index_ok and base_variants:
            try:
                # Check query embedding cache first, rejecting entries whose
                # dimension does not match the index (stale model tag/cache).
                uncached_variants: list[str] = []
                for qv in base_variants:
                    cached_vec = _query_emb_cache.get(qv)
                    if cached_vec is not None and (
                        index_dim is None or len(cached_vec) == index_dim
                    ):
                        variant_vectors[qv] = cached_vec
                    else:
                        _query_emb_cache.pop(qv, None)
                        uncached_variants.append(qv)

                if uncached_variants:
                    vecs = generate_embeddings_batch(
                        uncached_variants,
                        ollama_url,
                        query_embed_model,
                        root=root,
                        expected_dim=index_dim,
                    )
                    for qv, vec in zip(uncached_variants, vecs, strict=False):
                        if vec and (index_dim is None or len(vec) == index_dim):
                            variant_vectors[qv] = vec
                            _query_emb_cache[qv] = vec

                    if uncached_variants and not variant_vectors and vecs:
                        actual = len(vecs[0]) if vecs[0] else 0
                        dim_note = (
                            f"returned {actual}-dim vectors but the index expects {index_dim}-dim"
                            if index_dim is not None and actual
                            else "returned no usable vectors"
                        )
                        index_error = (
                            f"Embedding model '{query_embed_model}' {dim_note}. "
                            "Semantic search was skipped; restore the original model or "
                            "rebuild the index with 'pm update'."
                        )
                        errors.append(index_error)
                        index_ok = False

                # Trim cache if too large
                if len(_query_emb_cache) > _query_emb_cache_max:
                    # Remove oldest 25% of entries
                    keys = list(_query_emb_cache.keys())
                    for k in keys[: len(keys) // 4]:
                        _query_emb_cache.pop(k, None)
            except EmbeddingError as e:
                errors.append(f"Embedding failed: {e}")
                if index_dim is not None and "dimensions" in str(e):
                    # Keep keyword search available instead of failing the turn.
                    index_ok = False
                    index_error = str(e)
            except Exception as e:
                errors.append(f"Embedding error: {e}")

        timings["embed_ms"] = round((time.perf_counter() - t_start) * 1000, 1)

        def _semantic(qv: str, vec: list[float]) -> list[dict]:
            res = vector_search(root, vec, limit=fetch_limit, candidate_ids=candidate_ids)
            for r in res:
                r["search_type"] = "semantic"
            return res

        def _keyword(qv: str, lim: int, mode: str = "any") -> list[dict]:
            conn = get_connection(root)
            try:
                if candidate_ids is not None:
                    res = _fts_with_candidates(conn, qv, candidate_ids, lim, mode=mode)
                else:
                    res = fts_search(conn, qv, limit=lim, mode=mode)
                for r in res:
                    r["search_type"] = "keyword"
                return res
            finally:
                conn.close()

        # ── Run semantic + keyword searches concurrently ────────────────
        # Each lane carries a fusion weight. Exact/high-precision lanes
        # (all-terms BM25, acronym identifiers) outrank noisy semantic hits.
        pending: list[tuple[str, Any, float]] = []
        for qv, vec in variant_vectors.items():
            pending.append(("semantic", executor.submit(_semantic, qv, vec), 1.0))
        if base_variants:
            pending.append(("keyword", executor.submit(_keyword, query, fetch_limit), 1.0))
            # High-precision AND query: every term must occur. This is a strong
            # signal for short, specific asks ("sddr video limit") where an OR
            # query is dominated by documents that share only a common word.
            pending.append(("keyword", executor.submit(_keyword, query, fetch_limit, "all"), 1.4))
            for qv in base_variants[1:]:
                pending.append(
                    ("keyword", executor.submit(_keyword, qv, max(fetch_limit // 2, 1)), 0.9)
                )
            # Rare/distinctive terms (acronyms, quoted phrases, model numbers)
            # get their own ranked list so a document that matches the exact
            # identifier is not drowned out by common-word noise.
            for term in _distinctive_terms(query):
                pending.append(
                    (
                        "keyword",
                        executor.submit(_keyword, term, max(fetch_limit // 2, 8)),
                        1.6,
                    )
                )

        ranked_lists: list[list[dict]] = []
        ranked_weights: list[float] = []
        for kind, fut, weight in pending:
            try:
                res = fut.result(timeout=60.0)
                if res:
                    ranked_lists.append(res)
                    ranked_weights.append(weight)
            except EmbeddingError as e:
                errors.append(f"Embedding failed: {e}")
            except Exception as e:
                errors.append(f"{kind.capitalize()} search error: {e}")

        # ── Collect rewritten variants if they finished within budget ───
        # Only wait when the base pool is thin; a healthy hybrid search already
        # has enough candidates, and blocking on a slow local model just added
        # latency to every query.
        pool_size = sum(len(lst) for lst in ranked_lists)
        rewrite_timeout = float(config.get("query_rewrite_timeout", 0.6))
        if pool_size >= max(24, limit * 3):
            rewrite_future.cancel()
            rewrite_timeout = 0.0
        rewritten_variants: list[str] = []
        if rewrite_timeout > 0:
            try:
                rewritten_variants = rewrite_future.result(timeout=rewrite_timeout)
            except TimeoutError:
                logger.debug("Query rewrite exceeded budget — skipping extra variants")
            except Exception as e:
                logger.debug(f"Query rewrite failed: {e}")

        existing_lower = {v.lower() for v in base_variants}
        fresh_rewrites = [rv for rv in rewritten_variants if rv.lower() not in existing_lower]
        if index_ok and fresh_rewrites:
            try:
                rvecs = generate_embeddings_batch(
                    fresh_rewrites,
                    ollama_url,
                    query_embed_model,
                    root=root,
                    expected_dim=index_dim,
                )
                rw_pending: list[tuple[Any, float]] = []
                for qv, vec in zip(fresh_rewrites, rvecs, strict=False):
                    if vec:
                        rw_pending.append((executor.submit(_semantic, qv, vec), 0.8))
                for qv in fresh_rewrites:
                    rw_pending.append(
                        (executor.submit(_keyword, qv, max(fetch_limit // 2, 1)), 0.8)
                    )
                for fut, weight in rw_pending:
                    try:
                        res = fut.result(timeout=30.0)
                        if res:
                            ranked_lists.append(res)
                            ranked_weights.append(weight)
                    except Exception as e:
                        errors.append(f"Rewrite search error: {e}")
            except Exception as e:
                errors.append(f"Rewrite embedding error: {e}")

        # ── Fusion: RRF across all ranked lists ──────────────────────────
        timings["search_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
        fused = rrf_fuse(ranked_lists, weights=ranked_weights)
        all_results = [entry["result"] for entry in fused]

        # ── Entity boost: promote files whose graph entities match the query
        all_results = _entity_boost(all_results, graph, query)

        # ── Document-summary stage: match whole-document summaries ──────
        summary_results: list[dict] = []
        if summary_search:
            try:
                conn_s = get_connection(root)
                try:
                    summary_hits = search_summary_files(conn_s, query, limit=3)
                finally:
                    conn_s.close()
                if summary_hits:
                    summary_paths = {h["file_path"] for h in summary_hits}
                    top_score = (
                        max(
                            (float(r.get("rrf_score") or 0.0) for r in all_results),
                            default=0.0,
                        )
                        or 1.0
                    )
                    for r in all_results:
                        if r.get("file_path") in summary_paths:
                            r["rrf_score"] = (r.get("rrf_score") or 0) + 0.05 * top_score
                            r["summary_boosted"] = True
                    all_results.sort(key=lambda r: -(r.get("rrf_score") or 0))
                    for hit in summary_hits[:2]:
                        if files_filter and not any(f in hit["file_path"] for f in files_filter):
                            continue
                        summary_results.append(
                            {
                                "file_path": hit["file_path"],
                                "content": (
                                    f"[Document summary: {hit['file_path']}]\n"
                                    f"{hit.get('summary', '')[:1800]}"
                                ),
                                "section_title": "Document Summary",
                                "search_type": "summary",
                                "relevance_score": 0.5,
                                "doc_year": hit.get("doc_year"),
                                "doc_type": hit.get("doc_type", "other"),
                            }
                        )
            except Exception as e:
                errors.append(f"Summary search error: {e}")

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
        non_graph = [r for r in all_results if r.get("search_type") not in ("graph", "summary")]
        supplemental = [
            r for r in all_results if r.get("search_type") in ("graph", "summary")
        ] + summary_results
        if rerank_enabled and non_graph and query.strip():
            try:
                from palimind.core.reranker import rerank

                candidates = non_graph[:candidate_depth]
                reranked = rerank(
                    query,
                    candidates,
                    root=root,
                    top_k=min(candidate_depth, len(candidates)),
                    model_name=rerank_model,
                )
                if reranked:
                    non_graph = reranked + non_graph[candidate_depth:]
            except Exception as e:
                errors.append(f"Rerank error: {e}")

        # ── Optional bge-m3 learned-sparse / ColBERT rescoring ──────────
        if (sparse_enabled or colbert_enabled) and non_graph:
            try:
                from palimind.core.sparse import available as sparse_available
                from palimind.core.sparse import rerank as sparse_rerank

                sparse_model = str(config.get("sparse_model") or "BAAI/bge-m3")
                if sparse_available(sparse_model):
                    non_graph = sparse_rerank(
                        query,
                        non_graph,
                        model_name=sparse_model,
                        top_n=int(config.get("colbert_candidates", 50)),
                        use_sparse=sparse_enabled,
                        use_colbert=colbert_enabled,
                    )
            except Exception as e:  # noqa: BLE001 - optional signal
                errors.append(f"Sparse rerank error: {e}")

        # ── Diversity selection: embedding MMR, lexical fallback ────────
        query_vector = next(iter(variant_vectors.values()), None)
        # A single explicitly selected document may legitimately contribute
        # more than the default cap (e.g. "summarise this 100-page report").
        per_file_cap = mmr_per_file_cap
        if files_filter and len(files_filter) == 1:
            per_file_cap = max(per_file_cap, limit)
        if mmr_enabled:
            selected = select_mmr(
                non_graph,
                limit,
                root=root,
                query_vector=query_vector,
                lambda_=mmr_lambda,
                per_file_cap=per_file_cap,
                candidate_pool=max(limit * 4, 24),
            )
        else:
            selected = select_diverse(non_graph, limit, per_file_cap=per_file_cap)
        selected_results = selected + supplemental

        # ── Small-to-big expansion: children → parent sections ──────────
        try:
            conn3 = get_connection(root)
            try:
                selected_results = expand_parent_sections(
                    conn3,
                    selected_results,
                    max_tokens=parent_max_tokens,
                    enabled=bool(parent_retrieval),
                )
                # Neighbour expansion only for hits that could not be promoted
                # to a parent section (and never for synthesis blocks).
                selected_results = expand_window(conn3, selected_results)
            finally:
                conn3.close()
        except Exception as e:
            errors.append(f"Context expansion error: {e}")

        # ── Budgeted context assembly ────────────────────────────────────
        timings["select_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
        context_parts, kept_results = _assemble_context(selected_results, context_token_budget)
        for r in kept_results:
            fp = r.get("file_path", "unknown")
            if fp not in sources:
                sources.append(fp)

        has_media = any(r.get("media_start_ts") is not None for r in kept_results)

        deduped_errors = list(dict.fromkeys(errors))
        timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
        result = {
            "content": "\n\n".join(context_parts),
            "sources": sources,
            "results": kept_results,
            "total_results": len(kept_results),
            "has_media": has_media,
            "errors": deduped_errors,
            "index_error": index_error,
            "timings": timings,
        }

        # Semantic cache: store result for similar queries. Degraded results
        # (embedding/search failures) are not cached so recovery is immediate.
        if not deduped_errors:
            _semantic_result_cache[cache_key] = {**result, "_ts": time.time()}
        if len(_semantic_result_cache) > _SEMANTIC_CACHE_MAX:
            # Remove oldest entries
            sorted_keys = sorted(
                _semantic_result_cache.keys(),
                key=lambda k: _semantic_result_cache[k].get("_ts", 0),
            )
            for k in sorted_keys[: len(sorted_keys) // 4]:
                _semantic_result_cache.pop(k, None)

        return result
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _fts_with_candidates(
    conn: Any, query: str, candidate_ids: set[int], limit: int, *, mode: str = "any"
) -> list[dict]:
    """FTS search restricted to a candidate set of chunk ids."""
    try:
        from palimind.storage.db import build_fts_query

        if not candidate_ids:
            return []
        placeholders = ",".join("?" * len(candidate_ids))
        # Quote every term so FTS5 operators in user text ("-", AND/OR/NOT,
        # quotes, parens, "col:") can't cause a syntax error (which was
        # swallowed below, silently returning no keyword hits).
        fts_query = build_fts_query(query, mode=mode)
        if not fts_query:
            return []
        cur = conn.execute(
            f"""
            SELECT c.id, f.path, c.chunk_index, c.chunk_type, c.content,
                   chunks_fts.rank,
                   c.section_title, c.subsection, c.parent_section, c.main_section,
                   c.page_number, f.doc_year, f.doc_type, f.entity_name
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
                "main_section": row[9] or "",
                "page_number": row[10],
                "doc_year": row[11],
                "doc_type": row[12] or "other",
                "entity_name": row[13] or "",
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
