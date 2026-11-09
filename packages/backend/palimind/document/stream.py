from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.responses import StreamingResponse

from palimind.config import load_config
from palimind.memory.session_store import (
    append_message_to_session,
    background_update_memory,
)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _reasoning(text: str) -> str:
    return _sse({"type": "reasoning", "text": text})


def _media_refs(results: list[dict]) -> list[dict]:
    refs: list[dict] = []
    seen: set[str] = set()
    for r in results:
        start_ts = r.get("media_start_ts")
        if start_ts is None:
            continue
        fp = r.get("file_path", "")
        key = f"{fp}:{round(float(start_ts), 1)}"
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "file": fp,
                "start": float(start_ts),
                "end": float(r["media_end_ts"]) if r.get("media_end_ts") is not None else None,
                "snippet": (r.get("content", "") or "")[:160],
            }
        )
    return refs


def _text_refs(results: list[dict]) -> list[dict]:
    refs: list[dict] = []
    seen: set[str] = set()
    for r in results:
        if r.get("media_start_ts") is not None:
            continue
        fp = r.get("file_path", "")
        cid = r.get("chunk_db_id")
        key = f"{fp}:{cid}"
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "file": fp,
                "section": r.get("section_title") or r.get("main_section") or "",
                "page": r.get("page_number"),
                "snippet": (r.get("content", "") or "")[:160],
                "chunk_id": cid,
            }
        )
    return refs


async def _answer_stream(
    *,
    engine: Any,
    q: str,
    visible_query: str,
    context: dict[str, Any],
    active_sess_id: str | None,
    active_field: Path,
    history_to_send: list[dict] | None,
    mid_term_summary: str | None,
    long_term_episodes: list[dict] | None,
    system_prompt: str | None,
    image_paths: list[str] | None,
    attachment_context: str,
):
    """Emit citations, then stream a cited answer and persist the turn."""
    if attachment_context:
        context["content"] = (
            str(context.get("content") or "").rstrip() + "\n\n" + attachment_context
        ).strip()
        sources_list = context.setdefault("sources", [])
        if "attachment" not in sources_list:
            sources_list.append("attachment")
        yield _reasoning("Including attached document context")

    sources = context.get("sources", [])
    total = context.get("total_results", 0)
    errors = context.get("errors", [])

    media_refs = _media_refs(context.get("results", []))
    if media_refs:
        yield _sse({"type": "media_citations", "citations": media_refs})

    text_refs = _text_refs(context.get("results", []))
    if text_refs:
        yield _sse({"type": "citations", "citations": text_refs})

    for err in errors:
        yield _reasoning(f"[debug] {err}")

    if sources:
        source_list = "\n".join(f"  [{s}]" for s in sources[:8])
        yield _reasoning(
            f"Found {total} relevant passages from {len(sources)} source(s):\n{source_list}"
        )
    elif errors:
        yield _reasoning("No indexed documents found — run Sync Active Field first.")
    else:
        yield _reasoning("No matching documents found for this query.")

    yield _reasoning("Generating answer from document context with source citations...")
    if image_paths:
        yield _reasoning(f"Using {len(image_paths)} attached image(s)")

    full_text = ""
    final_text = ""
    citation_payload: dict | None = None
    reasoning_parts: list[str] = []

    def on_reasoning(chunk: str) -> None:
        reasoning_parts.append(chunk)

    try:
        stream = engine.stream_answer(
            q,
            context,
            system_prompt=system_prompt,
            history=history_to_send,
            mid_term_summary=mid_term_summary,
            long_term_episodes=long_term_episodes,
            on_reasoning=on_reasoning,
            image_paths=image_paths,
        )
        from palimind.generative.responder import aiter_stream

        # The frontend appends every ``thinking`` event, so only send the
        # reasoning that has not been sent yet (and flush any trailing
        # reasoning when the model produced no answer tokens after it).
        thinking_sent = 0

        def pending_thinking() -> str | None:
            nonlocal thinking_sent
            if len(reasoning_parts) <= thinking_sent:
                return None
            upto = len(reasoning_parts)
            text = "".join(reasoning_parts[thinking_sent:upto])
            thinking_sent = upto
            return _sse({"type": "thinking", "text": text})

        async for token in aiter_stream(stream):
            if (sse := pending_thinking()) is not None:
                yield sse
            full_text += token
            yield _sse({"type": "token", "text": token})
        if (sse := pending_thinking()) is not None:
            yield sse
    except Exception as e:
        err_msg = f"Generation error: {str(e)}"
        if not full_text:
            full_text = f"**Error:** {err_msg}"
        yield _sse({"type": "error", "text": err_msg})
    else:
        # ── Citation pass ─────────────────────────────────────────────────
        try:
            from palimind.generative.citation import (
                Source,
                finalize_citations,
                sources_from_text_refs,
            )

            citation_sources = sources_from_text_refs(text_refs)
            if not citation_sources and sources:
                citation_sources = [
                    Source(
                        marker=i + 1,
                        title=str(s).split("/")[-1],
                        kind="document",
                        file=str(s),
                    )
                    for i, s in enumerate(sources)
                ]
            if citation_sources and full_text.strip():
                result = finalize_citations(full_text, citation_sources)
                final_text = result.text
                citation_payload = result.to_dict()
                yield _sse({"type": "citation_map", **citation_payload})
                if final_text != full_text:
                    yield _sse({"type": "answer_final", "text": final_text})
        except Exception as e:
            print(f"Citation attachment failed: {e}")
    finally:
        persisted = final_text or full_text
        if active_sess_id and persisted:
            await asyncio.to_thread(
                append_message_to_session,
                active_field,
                active_sess_id,
                "system",
                persisted,
                sources=sources if sources else None,
                citations=citation_payload,
            )
            asyncio.create_task(
                background_update_memory(active_field, active_sess_id, visible_query, persisted)
            )

    yield _sse({"type": "done"})


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
    rerank: bool | None = None,
    image_paths: list[str] | None = None,
    attachment_context: str = "",
    display_text: str | None = None,
    rag_mode: str | None = None,
) -> StreamingResponse:
    """STRICT DOCUMENT RAG MODE: answers only from indexed documents.

    ``rag_mode`` selects the retrieval strategy:
    * ``auto``   — agentic only for complex/multi-hop questions (default),
    * ``off``    — the fast single-shot hybrid pipeline,
    * ``always`` — plan → parallel retrieve → verify on every question.
    """
    visible_query = display_text or q
    config = load_config(active_field)

    from palimind.document.agentic import (
        agentic_retrieve,
        resolve_mode,
        should_use_agentic,
    )

    mode = resolve_mode(rag_mode, config)
    use_agentic = mode == "always" or (mode == "auto" and should_use_agentic(visible_query, mode))

    async def rag_stream():
        from palimind.document.engine import _DOC_SYSTEM_PROMPT, DocumentEngine

        system_prompt = None
        if persona:
            system_prompt = f"{persona}\n\n{_DOC_SYSTEM_PROMPT}"

        if active_sess_id:
            await asyncio.to_thread(
                append_message_to_session,
                active_field,
                active_sess_id,
                "user",
                visible_query,
            )

        engine = DocumentEngine(active_field, ollama_url, chat_model, rerank=rerank)

        if use_agentic:
            yield _reasoning("Agentic RAG — planning document searches")
        else:
            yield _reasoning("Document Mode — searching indexed documents only")

        yield _reasoning("Loading document knowledge graph...")
        try:
            graph = await asyncio.to_thread(engine.ensure_graph)
            if graph:
                yield _reasoning(
                    f"Graph ready: {len(graph.nodes)} nodes, {len(graph.edges)} connections"
                )
        except Exception as e:
            print(f"Graph load error: {e}")

        retrieval_limit = int(config.get("retrieval_limit", 10))
        retrieval_limit = max(4, retrieval_limit)
        context: dict[str, Any]

        if use_agentic:
            yield _reasoning(
                "Planning sub-queries, then searching in parallel "
                f"(max {int(config.get('agentic_rag_max_subqueries', 6))} lanes)..."
            )
            try:
                context = await asyncio.to_thread(
                    agentic_retrieve,
                    engine,
                    visible_query,
                    limit=retrieval_limit,
                    files_filter=files_filter,
                    max_subqueries=int(config.get("agentic_rag_max_subqueries", 6)),
                    max_rounds=int(config.get("agentic_rag_max_rounds", 2)),
                    token_budget=config.get("context_token_budget"),
                    parent_retrieval=bool(config.get("parent_retrieval", True)),
                    parent_max_tokens=int(config.get("parent_max_tokens", 1500)),
                    planner_model=engine.light_model or chat_model,
                )
            except Exception as e:
                print(f"[agentic] retrieval failed, falling back to single-shot: {e}")
                yield _reasoning(f"Agentic retrieval failed ({e}) — using single-pass search")
                context = await asyncio.to_thread(
                    engine.retrieve_context,
                    visible_query,
                    limit=retrieval_limit,
                    history=history_to_send,
                    mid_term_summary=mid_term_summary,
                    long_term_episodes=long_term_episodes,
                    files_filter=files_filter,
                )
            else:
                subqueries = context.get("subqueries") or []
                yield _reasoning(
                    "Searched "
                    + str(len(subqueries))
                    + " sub-quer"
                    + ("y" if len(subqueries) == 1 else "ies")
                    + ":\n"
                    + "\n".join(f"  • {s}" for s in subqueries[:8])
                )
                for term in (context.get("lookup_terms") or [])[:4]:
                    yield _reasoning(f"Exact lookup: {term}")
                suff = context.get("sufficiency") or {}
                if suff.get("missing"):
                    yield _reasoning(f"Possible gap: {suff['missing']}")
                yield _reasoning(
                    f"Agentic retrieval complete after {context.get('rounds', 1)} round(s)"
                )
                yield _sse(
                    {
                        "type": "rag_plan",
                        **{
                            k: context.get(k)
                            for k in ("subqueries", "rounds", "plan_source", "lookup_terms")
                        },
                    }
                )
        else:
            yield _reasoning(
                "Running multi-pass hybrid search (semantic + BM25 keyword + graph expansion)..."
            )
            context = await asyncio.to_thread(
                engine.retrieve_context,
                visible_query,
                limit=retrieval_limit,
                history=history_to_send,
                mid_term_summary=mid_term_summary,
                long_term_episodes=long_term_episodes,
                files_filter=files_filter,
            )

        async for event in _answer_stream(
            engine=engine,
            q=q,
            visible_query=visible_query,
            context=context,
            active_sess_id=active_sess_id,
            active_field=active_field,
            history_to_send=history_to_send,
            mid_term_summary=mid_term_summary,
            long_term_episodes=long_term_episodes,
            system_prompt=system_prompt,
            image_paths=image_paths,
            attachment_context=attachment_context,
        ):
            yield event

    return StreamingResponse(rag_stream(), media_type="text/event-stream")
