from __future__ import annotations

from pathlib import Path

from core.config import load_config
from core.exceptions import NoContextError, ResponseError
from core.generative.responder import generate_response, generate_response_stream
from core.indexing import require_index
from core.models import QueryResult, QueryStream, RetrievedContext
from core.prompts.loader import load_prompt
from core.retrieval.searcher import retrieve_context


def _default_system_prompt() -> str:
    try:
        return load_prompt("system")
    except FileNotFoundError:
        return (
            "You are a helpful assistant. Use the provided context to answer "
            "the question."
        )


def _to_retrieved(raw: dict) -> RetrievedContext:
    text_contexts = tuple(raw.get("text_contexts", []))
    image_paths = tuple(raw.get("image_paths", []))
    sources: list[str] = []
    for block in text_contexts:
        if block.startswith("Source (") and "):" in block:
            path = block[len("Source (") : block.index("):")]
            if path not in sources:
                sources.append(path)
    for path in image_paths:
        if path not in sources:
            sources.append(path)
    return RetrievedContext(
        text_contexts=text_contexts,
        image_paths=image_paths,
        sources=tuple(sources),
    )


def retrieve(root: Path, query: str, *, limit: int = 5, files_filter: list[str] | None = None) -> RetrievedContext:
    root = require_index(root)
    raw = retrieve_context(query, root, limit=limit, files_filter=files_filter)
    return _to_retrieved(raw)


def _fetch_chat_episodes(
    root: Path,
    query: str,
    config: dict,
    session_id: str,
) -> str:
    """Fetch relevant past conversation episodes for the given query.
    Designed to run concurrently with document retrieval.
    """
    try:
        from core.storage.chat_store import search_chat_episodes
        from core.retrieval.embedder import generate_embeddings_batch

        emb_res = generate_embeddings_batch(
            [query], config["ollama_base_url"], config["embed_model"]
        )
        if not emb_res or not emb_res[0]:
            return ""
        episodes = search_chat_episodes(root, emb_res[0], limit=3)
        if not episodes:
            return ""
        parts = [
            f"Past Turn: {ep['content']}"
            for ep in episodes
            if ep.get("session_id") == session_id
        ]
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
    session_id: str | None = None,
) -> QueryStream:
    import concurrent.futures

    root = require_index(root)
    config = load_config(root)

    # Run document retrieval and (optionally) chat memory lookup concurrently
    # so neither blocks the other.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_docs = executor.submit(
            retrieve, root, query, limit=limit, files_filter=files_filter
        )
        future_episodes: concurrent.futures.Future[str] | None = None
        if session_id:
            future_episodes = executor.submit(
                _fetch_chat_episodes, root, query, config, session_id
            )

        context = future_docs.result()
        chat_context = future_episodes.result() if future_episodes else ""

    joined_context = "\n\n".join(context.text_contexts) if context.text_contexts else ""
    if chat_context:
        if joined_context:
            joined_context = f"{joined_context}\n\nPast Conversation Context:\n{chat_context}"
        else:
            joined_context = f"Past Conversation Context:\n{chat_context}"

    prompt = system_prompt if system_prompt is not None else _default_system_prompt()
    if mid_term_summary:
        prompt = f"{prompt}\n\nConversation Summary so far:\n{mid_term_summary}"

    stream = generate_response_stream(
        query=query,
        context=joined_context,
        image_paths=list(context.image_paths),
        ollama_url=config["ollama_base_url"],
        chat_model=config["chat_model"],
        system_prompt=prompt,
        history=history,
    )
    return context, stream


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
