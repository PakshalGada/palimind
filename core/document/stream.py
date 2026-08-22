from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.responses import StreamingResponse

from core.session_store import (
    append_message_to_session,
    background_update_memory,
)


async def document_mode_stream(
    q: str,
    active_sess_id: str | None,
    history_to_send: list[dict] | None,
    mid_term_summary: str | None,
    files_filter: list[str] | None,
    ollama_url: str,
    chat_model: str,
    active_field: Path,
    web_search: str,
    long_term_episodes: list[dict] | None = None,
    persona: str = "",
) -> StreamingResponse:
    """STRICT DOCUMENT RAG MODE: Answers only from indexed documents
    using hybrid search + knowledge graph.  No internet access, no code
    execution, no tool use — pure retrieval-augmented generation with
    source citation."""

    async def rag_stream():
        from core.document.engine import DocumentEngine, _DOC_SYSTEM_PROMPT

        system_prompt = None
        if persona:
            system_prompt = f"{persona}\n\n{_DOC_SYSTEM_PROMPT}"

        if active_sess_id:
            await asyncio.to_thread(
                append_message_to_session,
                active_field,
                active_sess_id,
                "user",
                q,
            )

        engine = DocumentEngine(active_field, ollama_url, chat_model)

        yield (
            f"data: {json.dumps({'type': 'reasoning', 'text': '📄 Document Mode — searching indexed documents only'})}\n\n"
        )

        yield (
            f"data: {json.dumps({'type': 'reasoning', 'text': 'Loading document knowledge graph...'})}\n\n"
        )
        try:
            graph = await asyncio.to_thread(engine.ensure_graph)
            if graph:
                yield (
                    f"data: {json.dumps({'type': 'reasoning', 'text': f'Graph ready: {len(graph.nodes)} nodes, {len(graph.edges)} connections'})}\n\n"
                )
        except Exception as e:
            print(f"Graph load error: {e}")

        yield (
            f"data: {json.dumps({'type': 'reasoning', 'text': 'Running multi-pass hybrid search (semantic + BM25 keyword + graph expansion)...'})}\n\n"
        )

        context = await asyncio.to_thread(
            engine.retrieve_context,
            q,
            limit=15,
            history=history_to_send,
            mid_term_summary=mid_term_summary,
            long_term_episodes=long_term_episodes,
            files_filter=files_filter,
        )

        sources = context.get("sources", [])
        total = context.get("total_results", 0)
        errors = context.get("errors", [])

        # Video/audio transcript chunks → clickable timestamp citations
        media_refs = []
        seen_media: set[str] = set()
        for r in context.get("results", []):
            start_ts = r.get("media_start_ts")
            if start_ts is None:
                continue
            fp = r.get("file_path", "")
            key = f"{fp}:{round(float(start_ts), 1)}"
            if key in seen_media:
                continue
            seen_media.add(key)
            media_refs.append(
                {
                    "file": fp,
                    "start": float(start_ts),
                    "end": float(r["media_end_ts"])
                    if r.get("media_end_ts") is not None
                    else None,
                    "snippet": (r.get("content", "") or "")[:160],
                }
            )
        if media_refs:
            yield (
                f"data: {json.dumps({'type': 'media_citations', 'citations': media_refs})}\n\n"
            )

        if errors:
            for err in errors:
                yield (
                    f"data: {json.dumps({'type': 'reasoning', 'text': f'[debug] {err}'})}\n\n"
                )

        if sources:
            source_list = "\n".join(f"  [{s}]" for s in sources[:8])
            yield (
                f"data: {json.dumps({'type': 'reasoning', 'text': f'Found {total} relevant passages from {len(sources)} source(s):\n{source_list}'})}\n\n"
            )
        elif errors:
            yield (
                f"data: {json.dumps({'type': 'reasoning', 'text': 'No indexed documents found — run Sync Active Field first.'})}\n\n"
            )
        else:
            yield (
                f"data: {json.dumps({'type': 'reasoning', 'text': 'No matching documents found for this query.'})}\n\n"
            )

        yield (
            f"data: {json.dumps({'text': 'Generating answer from document context with source citations...', 'type': 'reasoning'})}\n\n"
        )

        full_text = ""
        try:
            stream = engine.stream_answer(
                q,
                context,
                system_prompt=system_prompt,
                history=history_to_send,
                mid_term_summary=mid_term_summary,
                long_term_episodes=long_term_episodes,
            )
            for token in stream:
                full_text += token
                yield (
                    f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
                )
        except Exception as e:
            err_msg = f"Generation error: {str(e)}"
            if not full_text:
                full_text = f"**Error:** {err_msg}"
            yield (
                f"data: {json.dumps({'type': 'error', 'text': err_msg})}\n\n"
            )
        finally:
            if active_sess_id and full_text:
                await asyncio.to_thread(
                    append_message_to_session,
                    active_field,
                    active_sess_id,
                    "system",
                    full_text,
                    sources=sources if sources else None,
                )
                asyncio.create_task(
                    background_update_memory(
                        active_field, active_sess_id, q, full_text
                    )
                )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(rag_stream(), media_type="text/event-stream")
