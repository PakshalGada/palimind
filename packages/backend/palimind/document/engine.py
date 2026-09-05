from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from palimind.config import load_config
from palimind.document.graph import DocGraph, load_doc_graph
from palimind.document.tools import DocumentToolSet
from palimind.generative.responder import generate_response_stream
from palimind.rag.retrieve import hybrid_search

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
    """Strict RAG engine for document mode — retrieval is shared via
    :func:`palimind.rag.retrieve.hybrid_search`."""

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
        self.context_token_budget = config.get("context_token_budget")
        self.num_ctx = config.get("num_ctx")
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

    def retrieve_context(
        self,
        query: str,
        limit: int = 15,
        history: list[dict] | None = None,
        mid_term_summary: str | None = None,
        long_term_episodes: list[dict] | None = None,
        files_filter: list[str] | None = None,
    ) -> dict[str, Any]:
        """Hybrid retrieval — delegates to the shared pipeline."""
        graph = self.ensure_graph()
        return hybrid_search(
            self.root,
            query,
            limit=limit,
            files_filter=files_filter,
            history=history,
            ollama_url=self.ollama_url,
            embed_model=self.embed_model,
            light_model=self.light_model,
            rerank_enabled=self.rerank_enabled,
            rerank_model=self.rerank_model,
            query_rewrite_enabled=self.query_rewrite_enabled,
            context_token_budget=self.context_token_budget,
            graph=graph,
        )

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
            num_ctx=self.num_ctx,
            on_reasoning=on_reasoning,
        )
        yield from stream


def document_query_stream(
    root: Path,
    query: str,
    *,
    limit: int | None = None,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    mid_term_summary: str | None = None,
    files_filter: list[str] | None = None,
    on_reasoning: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], Iterator[str]]:
    """Run a strict document-mode query. Returns (context_info, token_stream)."""
    engine = DocumentEngine(root)
    if limit is None:
        limit = int(load_config(root).get("retrieval_limit", 10))
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
