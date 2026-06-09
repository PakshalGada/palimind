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


def query_stream(
    root: Path,
    query: str,
    *,
    limit: int = 5,
    system_prompt: str | None = None,
    history: list[dict] | None = None,
    files_filter: list[str] | None = None,
) -> QueryStream:
    root = require_index(root)
    config = load_config(root)
    context = retrieve(root, query, limit=limit, files_filter=files_filter)
    joined_context = "\n\n".join(context.text_contexts) if context.text_contexts else ""
    prompt = system_prompt if system_prompt is not None else _default_system_prompt()

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
