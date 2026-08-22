from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.config import load_config
from core.exceptions import NoContextError, ResponseError
from core.generative.responder import generate_response, generate_response_stream
from core.models import QueryResult, QueryStream, RetrievedContext


def _default_system_prompt() -> str:
    return "You are a helpful assistant. Use your knowledge to answer the question."


def _fetch_chat_episodes(
    root: Path,
    query: str,
    config: dict,
    session_id: str,
) -> str:
    try:
        from core.storage.chat_store import search_chat_episodes
        from core.embedder import generate_embeddings_batch

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
    limit: int = 5,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    files_filter: list[str] | None = None,
    mid_term_summary: str | None = None,
    long_term_episodes: list[dict] | None = None,
    session_id: str | None = None,
    web_search: bool = False,
) -> QueryStream:
    from core.memory import format_hierarchical_memory_context

    config = load_config(root)
    prompt = system_prompt if system_prompt is not None else _default_system_prompt()

    memory_ctx = format_hierarchical_memory_context(mid_term_summary, long_term_episodes or [])
    if memory_ctx:
        prompt = f"{prompt}\n\n{memory_ctx}"

    stream = generate_response_stream(
        query=query,
        context="",
        image_paths=[],
        ollama_url=config["ollama_base_url"],
        chat_model=config["chat_model"],
        system_prompt=prompt,
        history=history,
    )
    return RetrievedContext(text_contexts=(), image_paths=(), sources=()), stream


def query(
    root: Path,
    query_text: str,
    *,
    limit: int = 5,
    system_prompt: str | None = None,
) -> QueryResult:
    context, stream = query_stream(
        root, query_text, limit=limit, system_prompt=system_prompt
    )
    try:
        answer = generate_response(stream)
    except ResponseError:
        raise
    return QueryResult(answer=answer, context=context, query=query_text)


def retrieve(
    root: Path,
    query: str,
    *,
    limit: int = 5,
    files_filter: list[str] | None = None,
) -> RetrievedContext:
    return RetrievedContext(text_contexts=(), image_paths=(), sources=())


def document_query_stream(
    root: Path,
    query: str,
    *,
    limit: int = 10,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    mid_term_summary: str | None = None,
    long_term_episodes: list[dict] | None = None,
    files_filter: list[str] | None = None,
) -> QueryStream:
    """Strict document-mode query with hybrid retrieval and knowledge graph."""
    from core.document.engine import DocumentEngine

    engine = DocumentEngine(root)
    context = engine.retrieve_context(
        query, limit=limit,
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
        query, context,
        system_prompt=system_prompt,
        history=history,
        mid_term_summary=mid_term_summary,
        long_term_episodes=long_term_episodes,
    )
    return ctx, stream
