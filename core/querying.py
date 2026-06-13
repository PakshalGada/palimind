from __future__ import annotations

import logging
import time
from pathlib import Path

from core.config import load_config
from core.exceptions import NoContextError, ResponseError
from core.generative.responder import generate_response, generate_response_stream
from core.indexing import require_index
from core.models import QueryResult, QueryStream, RetrievedContext
from core.prompts.loader import load_prompt
from core.retrieval.searcher import retrieve_context

logger = logging.getLogger(__name__)


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
            path = block[len("Source (") : block.index(")")]
            if "—" in path:
                path = path[:path.index(" —")].strip()
            if path not in sources:
                sources.append(path)
        elif block.startswith("━━━"):
            # Comparative context block header: "━━━ filename | 2023 | 10-K ━━━"
            parts = block.split("━━━")
            if len(parts) >= 2:
                label_parts = parts[1].strip().split("|")
                path = label_parts[0].strip()
                if path and path not in sources:
                    sources.append(path)
    for path in image_paths:
        if path not in sources:
            sources.append(path)
    return RetrievedContext(
        text_contexts=text_contexts,
        image_paths=image_paths,
        sources=tuple(sources),
    )


def retrieve(
    root: Path,
    query: str,
    *,
    limit: int = 5,
    files_filter: list[str] | None = None,
) -> RetrievedContext:
    root = require_index(root)
    raw = retrieve_context(query, root, limit=limit, files_filter=files_filter)
    return _to_retrieved(raw)


def _fetch_chat_episodes(
    root: Path,
    query: str,
    config: dict,
    session_id: str,
) -> str:
    """Fetch relevant past conversation episodes for the given query."""
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
        parts = [f"Past Turn: {ep['content']}" for ep in episodes]
        return "\n\n".join(parts)
    except Exception:
        return ""


def _agent_query_stream(
    root: Path,
    query: str,
    *,
    limit: int = 5,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    files_filter: list[str] | None = None,
    mid_term_summary: str | None = None,
    session_id: str | None = None,
    web_search: bool = False,
) -> tuple[RetrievedContext, object, object | None]:
    """
    Agentic query stream using AgentPlanner.

    Returns (RetrievedContext, token_stream_iterator, diagnostics_report_or_None).
    """
    import concurrent.futures
    from core.agent_planner.planner import AgentPlanner, get_task_system_prompt
    from core.diagnostics.reporter import compute_diagnostics

    config = load_config(root)
    ollama_url = config["ollama_base_url"]
    chat_model = config["chat_model"]

    start_time = time.monotonic()

    # 1. Run AgentPlanner
    planner = AgentPlanner(
        root=root,
        config=config,
        ollama_url=ollama_url,
        model=chat_model,
        token_budget=config.get("context_token_budget", 8000),
    )

    agent_result = planner.execute(query, files_filter=files_filter)
    elapsed_ms = (time.monotonic() - start_time) * 1000

    # 2. Optionally fetch chat episodes concurrently (no agent blocking)
    chat_context = ""
    if session_id:
        try:
            chat_context = _fetch_chat_episodes(root, query, config, session_id)
        except Exception:
            pass

    # 3. Assemble final context string
    context_text = agent_result.assembled_context
    if chat_context:
        if context_text:
            context_text = f"{context_text}\n\nPast Conversation Context:\n{chat_context}"
        else:
            context_text = f"Past Conversation Context:\n{chat_context}"

    if web_search:
        from core.web_search import perform_web_search
        web_context = perform_web_search(query)
        if context_text:
            context_text = f"{context_text}\n\n{web_context}"
        else:
            context_text = web_context

    # 4. Build task-specific system prompt
    task_prompt = get_task_system_prompt(
        agent_result.classification.task_type,
        base_prompt=system_prompt or _default_system_prompt(),
    )
    if mid_term_summary:
        task_prompt = f"{task_prompt}\n\nConversation Summary so far:\n{mid_term_summary}"

    # 5. Build sources list from all retrieved chunks
    sources_set: set[str] = set()
    image_paths: list[str] = agent_result.image_paths or []
    for chunk in agent_result.all_chunks:
        fp = chunk.get("file_path", "")
        if fp:
            sources_set.add(fp)

    context = RetrievedContext(
        text_contexts=tuple(context_text.split("\n\n")) if context_text else (),
        image_paths=tuple(image_paths),
        sources=tuple(sorted(sources_set)),
    )

    # 6. Compute diagnostics
    diagnostics = compute_diagnostics(
        query=query,
        agent_result=agent_result,
        elapsed_ms=elapsed_ms,
    )

    # 7. Generate streaming response
    stream = generate_response_stream(
        query=query,
        context=context_text,
        image_paths=image_paths,
        ollama_url=ollama_url,
        chat_model=chat_model,
        system_prompt=task_prompt,
        history=history,
    )

    return context, stream, diagnostics


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
    web_search: bool = False,
) -> QueryStream:
    """
    Public query stream interface.

    Uses the agentic planner when available, falls back to legacy retrieval.
    Returns (RetrievedContext, token_stream) for backward compatibility.
    """
    root = require_index(root)

    try:
        context, stream, _diagnostics = _agent_query_stream(
            root,
            query,
            limit=limit,
            system_prompt=system_prompt,
            history=history,
            files_filter=files_filter,
            mid_term_summary=mid_term_summary,
            session_id=session_id,
        )
        return context, stream
    except Exception as exc:
        logger.warning(
            "AgentPlanner failed for query %r — falling back to legacy retrieval: %s",
            query[:80],
            exc,
            exc_info=True,
        )
        # Fallback to legacy retrieval pipeline
        return _legacy_query_stream(
            root,
            query,
            limit=limit,
            system_prompt=system_prompt,
            history=history,
            files_filter=files_filter,
            mid_term_summary=mid_term_summary,
            session_id=session_id,
            web_search=web_search,
        )


def query_stream_with_diagnostics(
    root: Path,
    query: str,
    *,
    limit: int = 5,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    files_filter: list[str] | None = None,
    mid_term_summary: str | None = None,
    session_id: str | None = None,
    web_search: bool = False,
) -> tuple[RetrievedContext, object, object | None]:
    """
    Extended query stream that also returns the DiagnosticsReport.
    Used by the updated /api/chat endpoint.

    Returns (RetrievedContext, token_stream, diagnostics_or_None).
    """
    root = require_index(root)

    try:
        return _agent_query_stream(
            root,
            query,
            limit=limit,
            system_prompt=system_prompt,
            history=history,
            files_filter=files_filter,
            mid_term_summary=mid_term_summary,
            session_id=session_id,
            web_search=web_search,
        )
    except Exception as exc:
        logger.warning(
            "AgentPlanner failed (with_diagnostics) for query %r — falling back: %s",
            query[:80],
            exc,
            exc_info=True,
        )
        context, stream = _legacy_query_stream(
            root,
            query,
            limit=limit,
            system_prompt=system_prompt,
            history=history,
            files_filter=files_filter,
            mid_term_summary=mid_term_summary,
            session_id=session_id,
            web_search=web_search,
        )
        return context, stream, None


def _legacy_query_stream(
    root: Path,
    query: str,
    *,
    limit: int = 5,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    files_filter: list[str] | None = None,
    mid_term_summary: str | None = None,
    session_id: str | None = None,
    web_search: bool = False,
) -> QueryStream:
    """Legacy retrieval fallback (original single-pass pipeline)."""
    import concurrent.futures

    config = load_config(root)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_docs = executor.submit(
            retrieve, root, query, limit=limit, files_filter=files_filter
        )
        future_episodes = None
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

    if web_search:
        from core.web_search import perform_web_search
        web_context = perform_web_search(query)
        if joined_context:
            joined_context = f"{joined_context}\n\n{web_context}"
        else:
            joined_context = web_context

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
