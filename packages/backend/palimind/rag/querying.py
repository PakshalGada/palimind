from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from palimind.config import load_config
from palimind.exceptions import ResponseError
from palimind.generative.responder import generate_response, generate_response_stream
from palimind.models import QueryResult, QueryStream, RetrievedContext


def _default_system_prompt() -> str:
    return "You are a helpful assistant. Use your knowledge to answer the question."


def _fetch_chat_episodes(
    root: Path,
    query: str,
    config: dict,
    session_id: str,
) -> str:
    try:
        from palimind.core.embedder import generate_embeddings_batch
        from palimind.storage.chat_store import search_chat_episodes

        emb_res = generate_embeddings_batch(
            [query], config["ollama_base_url"], config["embed_model"]
        )
        if not emb_res or not emb_res[0]:
            return ""
        episodes = search_chat_episodes(root, emb_res[0], limit=3)
        if not episodes:
            return ""
        parts = [f"Past Turn: {ep['content']}" for ep in episodes]
        return "\n\n".join(parts)
    except Exception:
        return ""


def query_stream(
    root: Path,
    query: str,
    *,
    limit: int | None = None,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    files_filter: list[str] | None = None,
    mid_term_summary: str | None = None,
    long_term_episodes: list[dict] | None = None,
    session_id: str | None = None,
    web_search: bool = False,
    on_reasoning: Callable[[str], None] | None = None,
) -> QueryStream:
    from palimind.config import load_config
    from palimind.memory.hierarchical import format_hierarchical_memory_context
    from palimind.rag.retrieve import hybrid_search

    config = load_config(root)
    if limit is None:
        limit = int(config.get("retrieval_limit", 10))
    prompt = system_prompt if system_prompt is not None else _default_system_prompt()

    memory_ctx = format_hierarchical_memory_context(mid_term_summary, long_term_episodes or [])
    if memory_ctx:
        prompt = f"{prompt}\n\n{memory_ctx}"

    context = hybrid_search(
        root,
        query,
        limit=limit,
        files_filter=files_filter,
        history=history,
        ollama_url=config["ollama_base_url"],
        embed_model=config["embed_model"],
        light_model=config.get("light_model", "") or config["chat_model"],
        rerank_enabled=bool(config.get("rerank", True)),
        rerank_model=config.get("rerank_model") or "BAAI/bge-reranker-base",
        query_rewrite_enabled=bool(config.get("query_rewrite", True)),
        context_token_budget=config.get("context_token_budget"),
    )
    ctx_text = context.get("content", "")
    sources = context.get("sources", [])

    stream = generate_response_stream(
        query=query,
        context=ctx_text,
        image_paths=[],
        ollama_url=config["ollama_base_url"],
        chat_model=config["chat_model"],
        system_prompt=prompt,
        history=history,
        is_chat_only=not bool(ctx_text),
        num_ctx=config.get("num_ctx"),
        on_reasoning=on_reasoning,
    )
    return RetrievedContext(
        text_contexts=(ctx_text,) if ctx_text else (),
        image_paths=(),
        sources=tuple(sources),
    ), stream


def query(
    root: Path,
    query_text: str,
    *,
    limit: int | None = None,
    system_prompt: str | None = None,
) -> QueryResult:
    context, stream = query_stream(root, query_text, limit=limit, system_prompt=system_prompt)
    try:
        answer = generate_response(stream)
    except ResponseError:
        raise
    return QueryResult(answer=answer, context=context, query=query_text)


def retrieve(
    root: Path,
    query: str,
    *,
    limit: int | None = None,
    files_filter: list[str] | None = None,
) -> RetrievedContext:
    from palimind.config import load_config
    from palimind.rag.retrieve import hybrid_search

    config = load_config(root)
    if limit is None:
        limit = int(config.get("retrieval_limit", 10))

    context = hybrid_search(
        root,
        query,
        limit=limit,
        files_filter=files_filter,
        ollama_url=config["ollama_base_url"],
        embed_model=config["embed_model"],
        light_model=config.get("light_model", "") or config["chat_model"],
        rerank_enabled=bool(config.get("rerank", True)),
        rerank_model=config.get("rerank_model") or "BAAI/bge-reranker-base",
        query_rewrite_enabled=bool(config.get("query_rewrite", True)),
        context_token_budget=config.get("context_token_budget"),
    )
    ctx_text = context.get("content", "")
    return RetrievedContext(
        text_contexts=(ctx_text,) if ctx_text else (),
        image_paths=(),
        sources=tuple(context.get("sources", [])),
    )


def document_query_stream(
    root: Path,
    query: str,
    *,
    limit: int | None = None,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    mid_term_summary: str | None = None,
    long_term_episodes: list[dict] | None = None,
    files_filter: list[str] | None = None,
    on_reasoning: Callable[[str], None] | None = None,
) -> QueryStream:
    """Strict document-mode query with hybrid retrieval and knowledge graph."""
    from palimind.document.engine import DocumentEngine

    engine = DocumentEngine(root)
    if limit is None:
        limit = int(load_config(root).get("retrieval_limit", 10))
    context = engine.retrieve_context(
        query,
        limit=limit,
        history=history,
        mid_term_summary=mid_term_summary,
        long_term_episodes=long_term_episodes,
        files_filter=files_filter,
    )
    ctx = RetrievedContext(
        text_contexts=(context.get("content", ""),),
        image_paths=(),
        sources=tuple(context.get("sources", [])),
    )
    stream = engine.stream_answer(
        query,
        context,
        system_prompt=system_prompt,
        history=history,
        mid_term_summary=mid_term_summary,
        long_term_episodes=long_term_episodes,
        on_reasoning=on_reasoning,
    )
    return ctx, stream
