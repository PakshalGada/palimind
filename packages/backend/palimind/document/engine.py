from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from concurrent.futures import ThreadPoolExecutor

from palimind.config import load_config
from palimind.document.graph import DocGraph, load_doc_graph
from palimind.document.tools import DocumentToolSet
from palimind.exceptions import EmbeddingError
from palimind.generative.responder import generate_response_stream
from palimind.storage.db import fts_search, get_connection, get_file_summary
from palimind.storage.vector_store import search as vector_search

logger = logging.getLogger(__name__)

_DOC_SYSTEM_PROMPT = """You are a precise document analysis assistant. Your answers MUST be based **strictly** on the provided document context.

CRITICAL RULES:
1. ANSWER ONLY FROM CONTEXT: Use **only** the retrieved document chunks below. Do not use your pre-training knowledge.
2. CITE EVERY CLAIM: Append **[Source: filename]** after every factual claim. If the source has a section, use **[Source: filename → Section Name]**.
3. QUOTE EXACTLY: Use "quotation marks" for direct quotes from the source.
4. NO HALLUCINATION: If the context lacks sufficient information, say exactly: *"The provided documents do not contain information about [topic]."*
5. BE COMPLETE: Include every relevant detail from the matching documents.
6. YEAR AWARENESS: If the query asks about specific years and context for some years is missing, note: *"No information found for [year] in the retrieved documents."*
7. COMPARISONS: When comparing, present each item separately with clear labels.
8. SECTION AWARENESS: Note which section of a document the information comes from (e.g., "Item 1A. Risk Factors", "Management's Discussion").

If you cannot answer from the context, say so clearly. Never fabricate numbers, dates, or statements."""


class DocumentEngine:
    """Strict RAG engine for document mode with hybrid search, graph, and tools."""

    def __init__(
        self,
        root: Path,
        ollama_url: str = "",
        chat_model: str = "",
        embed_model: str = "",
        light_model: str = "",
    ) -> None:
        self.root = root
        config = load_config(root)
        self.ollama_url = ollama_url or config.get("ollama_base_url", "http://localhost:11434")
        self.chat_model = chat_model or config.get("chat_model", "gemma4:e2b")
        self.embed_model = embed_model or config.get("embed_model", "nomic-embed-text")
        self.light_model = light_model or config.get("light_model", "") or self.chat_model
        self.rerank_enabled = bool(config.get("rerank", True))
        self.rerank_model = config.get("rerank_model") or "BAAI/bge-reranker-base"
        self.query_rewrite_enabled = bool(config.get("query_rewrite", True))
        self.graph: DocGraph | None = None
        self.tools: DocumentToolSet = DocumentToolSet(
            root,
            self.ollama_url,
            self.embed_model,
        )

    def ensure_graph(self) -> DocGraph | None:
        """Load the existing doc graph if present. Never rebuilds on the
        query path — building happens at index time or via explicit rebuild."""
        if self.graph is None:
            try:
                self.graph = load_doc_graph(
                    self.root, self.ollama_url, self.light_model, force_rebuild=False
                )
            except Exception as e:
                logger.debug(f"Graph load failed (continuing without): {e}")
                return None
            if len(self.graph.nodes) > 0:
                self.tools = DocumentToolSet(
                    self.root,
                    self.ollama_url,
                    self.embed_model,
                    graph=self.graph,
                )
        return self.graph

    def _index_exists(self) -> bool:
        from palimind.storage.vector_store import _index_path as _vec_index_path

        return _vec_index_path(self.root).exists()

    # ── query understanding ─────────────────────────────────────────────

    _rewrite_cache: dict[str, list[str]] = {}

    def _rewrite_queries(self, query: str) -> list[str]:
        """Use the light model to generate extra search query variants.

        Fails safe: returns [] on any error. Results are cached per query.
        """
        if not query.strip() or not self.light_model or not self.query_rewrite_enabled:
            return []
        cached = DocumentEngine._rewrite_cache.get(query)
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

            url = f"{self.ollama_url.rstrip('/')}/api/chat"
            payload = {
                "model": self.light_model,
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

        if len(DocumentEngine._rewrite_cache) > 256:
            DocumentEngine._rewrite_cache.clear()
        DocumentEngine._rewrite_cache[query] = variants
        return variants

    def _base_query_variants(self, query: str) -> list[str]:
        """Cheap, zero-latency query variants (no LLM involved)."""
        variants = [query]
        stripped = query.strip().rstrip("?.!")
        if stripped.lower() != query.strip().lower() and len(stripped.split()) >= 4:
            variants.append(stripped)
        return variants

    # ── fusion & selection ──────────────────────────────────────────────

    @staticmethod
    def _rrf_fuse(ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
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

    @staticmethod
    def _select_diverse(
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

    def _expand_window(
        self, conn, results: list[dict], window: int = 1, max_expansions: int = 8
    ) -> list[dict]:
        """Attach neighboring chunk content to top results for richer context."""
        from palimind.storage.db import get_chunk_neighbors

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

    def retrieve_context(
        self,
        query: str,
        limit: int = 15,
        history: list[dict] | None = None,
        mid_term_summary: str | None = None,
        long_term_episodes: list[dict] | None = None,
        files_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        """Hybrid retrieval with multi-query expansion, RRF fusion, reranking,
        and graph.

        Pipeline (parallelised): background LLM query rewriting → batched
        embedding of variants → concurrent semantic + BM25 searches →
        reciprocal rank fusion → cross-encoder reranking → diversity
        selection → chunk window expansion → graph-based related summaries.

        Returns dict with keys: content (str), sources (list[str]), results (list[dict]).
        """
        from concurrent.futures import ThreadPoolExecutor  # noqa: UP035

        sources: list[str] = []
        errors: list[str] = []
        executor = ThreadPoolExecutor(max_workers=6)
        try:
            return self._retrieve_context_impl(
                query,
                limit,
                history,
                files_filter,
                errors,
                sources,
                executor,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _retrieve_context_impl(
        self,
        query: str,
        limit: int,
        history: list[dict] | None,
        files_filter: list[str] | None,
        errors: list[str],
        sources: list[str],
        executor: ThreadPoolExecutor,
    ) -> dict[str, Any]:
        from palimind.core.embedder import generate_embeddings_batch

        # ── Kick off LLM query rewrite in the background ────────────────
        # It overlaps with embedding + search below; we only wait for it at
        # fusion time with a small budget, so it never dominates latency.
        rewrite_future = executor.submit(self._rewrite_queries, query)

        base_variants = self._base_query_variants(query)

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

        index_ok = self._index_exists()
        if not index_ok:
            errors.append("No vector index found — run 'pm add' to index files first")

        # ── Batch-embed ALL base variants in a single Ollama call ───────
        variant_vectors: dict[str, list[float]] = {}
        if index_ok and base_variants:
            try:
                vecs = generate_embeddings_batch(
                    base_variants, self.ollama_url, self.embed_model, root=self.root
                )
                variant_vectors = {
                    qv: vec for qv, vec in zip(base_variants, vecs, strict=False) if vec
                }
            except EmbeddingError as e:
                errors.append(f"Embedding failed: {e}")
            except Exception as e:
                errors.append(f"Embedding error: {e}")

        def _semantic(qv: str, vec: list[float]) -> list[dict]:
            res = vector_search(self.root, vec, limit=limit)
            for r in res:
                r["search_type"] = "semantic"
            return res

        def _keyword(qv: str, lim: int) -> list[dict]:
            conn = get_connection(self.root)
            try:
                res = fts_search(conn, qv, limit=lim)
                for r in res:
                    r["search_type"] = "keyword"
                return res
            finally:
                conn.close()

        # ── Run semantic + keyword searches concurrently ────────────────
        pending: list[tuple[str, Any]] = []  # (kind, future)
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
            # One batched embedding call + parallel searches for rewrites too
            try:
                rvecs = generate_embeddings_batch(
                    fresh_rewrites, self.ollama_url, self.embed_model, root=self.root
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
        fused = self._rrf_fuse(ranked_lists)
        all_results = [entry["result"] for entry in fused]

        # ── Graph-based expansion of fused results ──────────────────────
        try:
            graph = self.ensure_graph()
            if graph:
                conn2 = get_connection(self.root)
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
        if self.rerank_enabled and non_graph and query.strip():
            try:
                from palimind.core.reranker import rerank

                candidates = non_graph[:30]
                reranked = rerank(
                    query,
                    candidates,
                    root=self.root,
                    top_k=limit,
                    model_name=self.rerank_model,
                )
                if reranked:
                    non_graph = reranked + non_graph[30:]
            except Exception as e:
                errors.append(f"Rerank error: {e}")

        # ── Diversity selection (keeps graph summaries as supplements) ──
        selected = self._select_diverse(non_graph, limit)
        selected_results = selected + graph_results

        # ── Chunk window expansion for richer per-result context ────────
        try:
            conn3 = get_connection(self.root)
            try:
                selected_results = self._expand_window(conn3, selected_results)
            finally:
                conn3.close()
        except Exception as e:
            errors.append(f"Window expansion error: {e}")

        context_parts: list[str] = []
        for r in selected_results:
            fp = r.get("file_path", "unknown")
            if fp not in sources:
                sources.append(fp)
            sec = r.get("section_title", "") or r.get("main_section", "")
            sec_str = f" → {sec}" if sec else ""
            start_ts = r.get("media_start_ts")
            end_ts = r.get("media_end_ts")
            ts_str = ""
            if start_ts is not None:
                end_part = f"–{self._fmt_ts(float(end_ts))}" if end_ts is not None else ""
                ts_str = f" @ {self._fmt_ts(float(start_ts))}{end_part}"
            doc_year = r.get("doc_year")
            doc_type = r.get("doc_type", "")
            meta_parts = []
            if doc_year:
                meta_parts.append(f"Year: {doc_year}")
            if doc_type and doc_type != "other":
                meta_parts.append(f"Type: {doc_type}")
            meta_str = f" ({'; '.join(meta_parts)})" if meta_parts else ""
            header = f"--- Document: {fp}{sec_str}{ts_str}{meta_str} ---"
            context_parts.append(f"{header}\n{r.get('content', '')}")

        has_media = any(r.get("media_start_ts") is not None for r in selected_results)

        context_text = "\n\n".join(context_parts)
        deduped_errors = list(dict.fromkeys(errors))
        return {
            "content": context_text,
            "sources": sources,
            "results": selected_results,
            "total_results": len(selected_results),
            "has_media": has_media,
            "errors": deduped_errors,
        }

    @staticmethod
    def _fmt_ts(seconds: float) -> str:
        """Format seconds as M:SS (or H:MM:SS above one hour)."""
        s = int(round(seconds))
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"

    def stream_answer(
        self,
        query: str,
        context: dict[str, Any],
        system_prompt: str | None = None,
        history: list[dict] | None = None,
        mid_term_summary: str | None = None,
        long_term_episodes: list[dict] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
    ) -> Iterator[str]:
        """Stream the answer from the LLM using retrieved context."""
        from palimind.memory.hierarchical import format_hierarchical_memory_context

        ctx_text = context.get("content", "")
        sources = context.get("sources", [])
        errors = context.get("errors", [])

        sys = system_prompt or _DOC_SYSTEM_PROMPT

        memory_ctx = format_hierarchical_memory_context(mid_term_summary, long_term_episodes or [])
        if memory_ctx:
            sys = f"{sys}\n\n{memory_ctx}"

        if sources:
            source_list = "\n".join(f"  [{s}]" for s in sources[:8])
            sys = (
                f"{sys}\n\nRetrieved from these documents:\n{source_list}\n\n"
                "You MUST cite the relevant source for each claim using [Source: filename]."
            )
            if context.get("has_media"):
                sys += (
                    " For video/audio sources, ALWAYS include the timestamp from the "
                    "context header, e.g. [Source: video.mp4 @ 12:34]."
                )

        if not ctx_text:
            error_hint = ""
            if errors:
                err_list = "\n".join(f"  - {e}" for e in errors)
                error_hint = f"\n\nRetrieval diagnostics:\n{err_list}"
            query = (
                f"Query: {query}\n\n"
                "No relevant documents were found in the indexed workspace for this query."
                f"{error_hint}\n\n"
                "Inform the user that their documents do not contain information on this topic, "
                "and suggest they index more files or try a different query."
            )

        stream = generate_response_stream(
            query=query,
            context=ctx_text,
            image_paths=[],
            ollama_url=self.ollama_url,
            chat_model=self.chat_model,
            system_prompt=sys,
            history=history,
            is_chat_only=not bool(ctx_text),
            on_reasoning=on_reasoning,
        )
        yield from stream


def document_query_stream(
    root: Path,
    query: str,
    *,
    limit: int = 15,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    mid_term_summary: str | None = None,
    files_filter: list[str] | None = None,
    on_reasoning: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], Iterator[str]]:
    """Run a strict document-mode query. Returns (context_info, token_stream)."""
    engine = DocumentEngine(root)
    context = engine.retrieve_context(
        query,
        limit=limit,
        history=history,
        mid_term_summary=mid_term_summary,
        files_filter=files_filter,
    )
    stream = engine.stream_answer(
        query,
        context,
        system_prompt=system_prompt,
        history=history,
        mid_term_summary=mid_term_summary,
        on_reasoning=on_reasoning,
    )
    return context, stream
