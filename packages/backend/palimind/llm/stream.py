from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from fastapi.responses import StreamingResponse

from palimind.memory.session_store import (
    append_message_to_session,
    background_update_memory,
)

_LLM_SYSTEM_PROMPT = """You are a helpful, knowledgeable AI assistant. Answer the user's questions clearly, accurately, and freshly using your general knowledge.

You do NOT have access to the user's documents, the internet, or any tools. Answer based entirely on your training.

CRITICAL INSTRUCTIONS:
1. Always generate a direct, original response to the user's current question.
2. Do NOT copy, repeat, or output verbatim text from past conversation history or memory summaries.
3. If you don't know something, say so clearly rather than guessing."""

_LLM_WEB_SYSTEM_PROMPT = """You are a helpful, knowledgeable AI assistant with live web access. Use the web research
provided below to answer accurately and freshly.

CRITICAL INSTRUCTIONS:
1. Prefer the supplied web results for facts that can change (news, prices, releases, dates, people, statistics).
2. Cite the sources you rely on with bracketed markers that match their numbers, for example [1] or [2].
3. Never invent facts, numbers, dates, names or quotes that are not supported by the results.
4. If the results are incomplete or disagree, say so explicitly and explain the uncertainty.
5. Do NOT copy, repeat, or output verbatim text from past conversation history or memory summaries.
6. Write a direct, original answer in Markdown; do not dump the raw search results."""


def _truthy(value: object) -> bool:
    """Parse a query/config flag the way the chat API passes it."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


_TRIVIAL_QUERY_RE = re.compile(
    r"^(hi|hello|hey|thanks|thank you|ok|okay|great|cool|good morning|"
    r"good night|bye|see you)[\s!.?]*$",
    re.IGNORECASE,
)


def _web_worth_searching(query: str) -> bool:
    """Don't pay web-search latency for a greeting or a one-word pleasantry."""
    value = (query or "").strip()
    if not value:
        return False
    if _TRIVIAL_QUERY_RE.match(value):
        return False
    return len(value) > 3


def _web_sources(search_text: str) -> list:
    """Parse formatted web-search output into citable ``Source`` objects."""
    if not search_text:
        return []
    try:
        from palimind.generative.citation import parse_web_sources

        return parse_web_sources(search_text)
    except Exception:
        return []


def _citation_sse(answer: str, sources: list) -> tuple[str, str | None]:
    """Attach inline citations to a final answer; returns (text, SSE payload)."""
    if not answer or not sources:
        return answer, None
    try:
        from palimind.generative.citation import finalize_citations

        result = finalize_citations(answer, sources)
        return result.text, json.dumps({"type": "citation_map", **result.to_dict()})
    except Exception:
        return answer, None


async def llm_mode_stream(
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
    image_paths: list[str] | None = None,
    attachment_context: str = "",
    display_text: str | None = None,
) -> StreamingResponse:
    """PLAIN LLM MODE: Chat directly with the LLM using general knowledge.
    No document context, no code execution, no tools. Live web search is
    optionally prepended when the caller enables it.

    ``display_text`` is what the user actually typed when a hidden skill
    prompt is sent as ``q``. It is used for the stored transcript, web-search
    intent and memory, while the model still receives the full instructions.
    """

    visible_query = display_text or q

    async def plain_stream():
        from palimind.config import load_config
        from palimind.generative.responder import aiter_stream, generate_response_stream
        from palimind.memory.hierarchical import format_hierarchical_memory_context

        if active_sess_id:
            await asyncio.to_thread(
                append_message_to_session,
                active_field,
                active_sess_id,
                "user",
                visible_query,
            )

        web_enabled = _truthy(web_search) and _web_worth_searching(visible_query)
        yield (
            f"data: {json.dumps({'type': 'reasoning', 'text': 'LLM Mode — using general knowledge' + (' + live web search' if web_enabled else ' (no tools)')})}\n\n"
        )

        web_results = ""
        web_sources: list = []
        if web_enabled:
            yield (f"data: {json.dumps({'type': 'reasoning', 'text': 'Searching the web...'})}\n\n")
            yield (
                f"data: {json.dumps({'type': 'agent:tool_call', 'agent_id': 0, 'tool': 'web_search', 'args': {'query': visible_query}})}\n\n"
            )
            try:
                from palimind.core.web_search import perform_web_search

                web_results = await asyncio.to_thread(perform_web_search, visible_query, 6, True)
                web_sources = _web_sources(web_results)
                yield (
                    f"data: {json.dumps({'type': 'agent:tool_result', 'agent_id': 0, 'tool': 'web_search', 'result': [{'title': source.title, 'url': source.url, 'snippet': source.snippet} for source in web_sources]})}\n\n"
                )
                yield (
                    f"data: {json.dumps({'type': 'reasoning', 'text': f'Found {len(web_sources)} web source(s)'})}\n\n"
                )
            except Exception as exc:  # noqa: BLE001 - web search must not kill the answer
                yield (
                    f"data: {json.dumps({'type': 'agent:tool_result', 'agent_id': 0, 'tool': 'web_search', 'result': f'Search failed: {exc}'})}\n\n"
                )
                yield (
                    f"data: {json.dumps({'type': 'reasoning', 'text': f'Web search unavailable: {exc}'})}\n\n"
                )

        system_prompt = _LLM_WEB_SYSTEM_PROMPT if web_results else _LLM_SYSTEM_PROMPT
        if persona:
            system_prompt = f"{persona}\n\n{system_prompt}"
        memory_ctx = format_hierarchical_memory_context(mid_term_summary, [])
        if memory_ctx:
            system_prompt = f"{system_prompt}\n\n{memory_ctx}"

        full_text = ""
        reasoning_parts: list[str] = []

        def on_reasoning(chunk: str) -> None:
            reasoning_parts.append(chunk)

        query_for_model = q
        if web_results:
            query_for_model = (
                f"{q}\n\nWEB RESEARCH RESULTS (use these and cite them by number):\n{web_results}"
            )
        if attachment_context:
            query_for_model = f"{query_for_model}\n\n{attachment_context}"
        if image_paths or attachment_context:
            attached = len(image_paths or []) + (1 if attachment_context else 0)
            yield (
                f"data: {json.dumps({'type': 'reasoning', 'text': f'Using {attached} local attachment(s)'})}\n\n"
            )

        citation_payload: dict | None = None
        try:
            num_ctx = load_config(active_field).get("num_ctx")
            stream = generate_response_stream(
                query=query_for_model,
                context="",
                image_paths=list(image_paths or []),
                ollama_url=ollama_url,
                chat_model=chat_model,
                system_prompt=system_prompt,
                history=history_to_send,
                is_chat_only=True,
                num_ctx=num_ctx,
                on_reasoning=on_reasoning,
            )
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
                return f"data: {json.dumps({'type': 'thinking', 'text': text})}\n\n"

            async for token in aiter_stream(stream):
                if (sse := pending_thinking()) is not None:
                    yield sse
                full_text += token
                yield (f"data: {json.dumps({'type': 'token', 'text': token})}\n\n")
            if (sse := pending_thinking()) is not None:
                yield sse
            if web_sources and full_text and not full_text.startswith("**Error:**"):
                full_text, citation_sse = await asyncio.to_thread(
                    _citation_sse, full_text, web_sources
                )
                if citation_sse:
                    citation_payload = json.loads(citation_sse)
                    yield f"data: {citation_sse}\n\n"
        except Exception as e:
            err_msg = f"Generation error: {str(e)}"
            if not full_text:
                full_text = f"**Error:** {err_msg}"
            yield (f"data: {json.dumps({'type': 'error', 'text': err_msg})}\n\n")
        finally:
            if active_sess_id and full_text:
                await asyncio.to_thread(
                    append_message_to_session,
                    active_field,
                    active_sess_id,
                    "system",
                    full_text,
                    citations=citation_payload,
                )
                asyncio.create_task(
                    background_update_memory(active_field, active_sess_id, visible_query, full_text)
                )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(plain_stream(), media_type="text/event-stream")


_LLM_MOE_SYSTEM_PROMPT = """You are a helpful, knowledgeable AI assistant in Mixture-of-Experts mode.
Your response will be synthesized from multiple expert agents. Answer clearly and concisely."""


def _progress_event_to_sse(event: dict) -> list[str]:
    etype = event.get("type", "")
    if etype == "planning":
        return [f"data: {json.dumps({'type': 'reasoning', 'text': event.get('text', '')})}\n\n"]
    elif etype == "agent_start":
        return [
            f"data: {
                json.dumps(
                    {
                        'type': 'agent_progress',
                        'agent_id': event.get('agent_id', 0),
                        'label': event.get('label', ''),
                        'task': event.get('task', ''),
                        'status': 'working',
                    }
                )
            }\n\n"
        ]
    elif etype == "agent_complete":
        return [
            f"data: {
                json.dumps(
                    {
                        'type': 'agent_progress',
                        'agent_id': event.get('agent_id', 0),
                        'label': event.get('label', ''),
                        'status': 'complete',
                    }
                )
            }\n\n"
        ]
    elif etype == "agent_step":
        return [
            f"data: {
                json.dumps(
                    {
                        'type': 'agent_thinking',
                        'agent_id': event.get('agent_id', 0),
                        'text': event.get('text', ''),
                    }
                )
            }\n\n"
        ]
    elif etype == "agent:thought":
        # Raw model reasoning from an expert. Keep it short enough for the
        # activity surface but expose it live rather than only at the end.
        text = str(event.get("text") or "").strip()
        if not text:
            return []
        return [
            f"data: {
                json.dumps(
                    {
                        'type': 'agent_thinking',
                        'agent_id': event.get('agent_id', 0),
                        'text': text[:1200],
                    }
                )
            }\n\n"
        ]
    elif etype == "agent:tool_call":
        return [
            f"data: {
                json.dumps(
                    {
                        'type': 'agent:tool_call',
                        'agent_id': event.get('agent_id', 0),
                        'tool': event.get('tool', 'tool'),
                        'args': event.get('args') or {},
                    }
                )
            }\n\n"
        ]
    elif etype == "agent:tool_result":
        return [
            f"data: {
                json.dumps(
                    {
                        'type': 'agent:tool_result',
                        'agent_id': event.get('agent_id', 0),
                        'tool': event.get('tool', 'tool'),
                        'result': event.get('result'),
                    }
                )
            }\n\n"
        ]
    elif etype == "synthesizing":
        return [f"data: {json.dumps({'type': 'reasoning', 'text': event.get('text', '')})}\n\n"]
    elif etype == "verifying":
        return [f"data: {json.dumps({'type': 'reasoning', 'text': event.get('text', '')})}\n\n"]
    elif etype == "plan_review":
        return [f"data: {json.dumps({'type': 'reasoning', 'text': event.get('text', '')})}\n\n"]
    elif etype == "cancelled":
        return [f"data: {json.dumps({'type': 'reasoning', 'text': event.get('text', '')})}\n\n"]
    elif etype == "moe_plan":
        steps = event.get("plan") or []
        return [
            f"data: {json.dumps({'type': 'agent:plan', 'steps': steps, 'mode': 'moe', 'status': 'ready'})}\n\n"
        ]
    elif etype in ("research_plan", "citation_map"):
        # Pass structured events through untouched.
        return [f"data: {json.dumps(event)}\n\n"]
    return []


async def moe_mode_stream(
    q: str,
    active_sess_id: str | None,
    history_to_send: list[dict] | None,
    mid_term_summary: str | None,
    files_filter: list[str] | None,
    ollama_url: str,
    chat_model: str,
    active_field: Path,
    web_search: str,
    orchestrator_model: str | None = None,
    worker_model: str | None = None,
    orchestrator_url: str | None = None,
    worker_url: str | None = None,
    long_term_episodes: list[dict] | None = None,
    display_text: str | None = None,
) -> StreamingResponse:
    """MOE MODE: Uses an orchestrator LLM to create a plan, dispatches to 4 smaller
    agent LLMs that run in parallel with tool access, then synthesizes the results."""

    visible_query = display_text or q

    async def moe_stream():
        from palimind.llm.mixture_of_expert import run_moe_pipeline

        if active_sess_id:
            await asyncio.to_thread(
                append_message_to_session,
                active_field,
                active_sess_id,
                "user",
                visible_query,
            )

        orch_model = orchestrator_model or chat_model
        work_model = worker_model or chat_model
        orch_url = orchestrator_url or ollama_url
        work_url = worker_url or ollama_url

        yield (
            f"data: {json.dumps({'type': 'reasoning', 'text': 'MoE Mode — orchestrator planning...'})}\n\n"
        )

        progress_queue: asyncio.Queue = asyncio.Queue()

        async def on_progress(event: dict):
            await progress_queue.put(event)

        pipeline_task = asyncio.create_task(
            run_moe_pipeline(
                user_query=q,
                ollama_url=orch_url,
                orchestrator_model=orch_model,
                worker_model=work_model,
                worker_url=work_url,
                num_workers=4,
                on_progress=on_progress,
                short_term=history_to_send,
                mid_term_summary=mid_term_summary,
                long_term_episodes=long_term_episodes,
                root=active_field,
                force_web=_truthy(web_search) and _web_worth_searching(visible_query),
            )
        )

        full_text = ""
        citation_payload: dict | None = None
        try:
            while True:
                if pipeline_task.done():
                    while not progress_queue.empty():
                        event = await progress_queue.get()
                        for sse in _progress_event_to_sse(event):
                            yield sse
                    break
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.15)
                    for sse in _progress_event_to_sse(event):
                        yield sse
                except TimeoutError:
                    continue

            result = pipeline_task.result()
            if "error" in result:
                err_text = result["error"]
                yield f"data: {json.dumps({'type': 'error', 'text': err_text})}\n\n"
                if "raw_plan" in result:
                    raw_plan_text = result.get("raw_plan", "")
                    yield f"data: {json.dumps({'type': 'token', 'text': f'Raw plan output:\\n{raw_plan_text}'})}\n\n"
                    full_text = f"**Error:** {err_text}\n\nRaw plan output:\n{raw_plan_text}"
                else:
                    full_text = f"**Error:** {err_text}"
            else:
                plan = result.get("plan", [])
                outputs = result.get("outputs", [])
                synthesis = result.get("synthesis", "")
                citation_payload = result.get("citations")

                if synthesis:
                    full_text += synthesis
                    yield f"data: {json.dumps({'type': 'token', 'text': synthesis})}\n\n"
                if citation_payload:
                    cited_text = citation_payload.get("text") or ""
                    if cited_text:
                        full_text = cited_text
                    yield f"data: {json.dumps(citation_payload)}\n\n"

                process_block = '\n\n<details class="moe-process-details">\n<summary class="moe-process-summary">View Agent Process</summary>\n<div class="moe-process-content">\n'
                if plan:
                    process_block += "#### Orchestrator Execution Plan\n\n"
                    for item in plan:
                        label = item.get("label") or f"Agent {item.get('agent_id', '?')}"
                        task = item.get("task", "")
                        process_block += f"- **{label}:** {task}\n"
                    process_block += "\n"

                if outputs:
                    process_block += "#### Agent Outputs\n\n"
                    for ao in outputs:
                        label = ao.get("label") or f"Agent {ao.get('agent_id', '?')}"
                        out_content = ao.get("output", "No output").strip()
                        process_block += f"**{label}:**\n{out_content}\n\n"

                usage = result.get("usage") or {}
                if usage:
                    prompt_tokens = sum(int(v.get("prompt_tokens", 0)) for v in usage.values())
                    completion_tokens = sum(
                        int(v.get("completion_tokens", 0)) for v in usage.values()
                    )
                    if prompt_tokens or completion_tokens:
                        process_block += (
                            f"\n**Tokens:** {prompt_tokens + completion_tokens} total "
                            f"({prompt_tokens} in / {completion_tokens} out)\n"
                        )

                timings = result.get("timings") or {}
                if timings.get("total"):
                    stage_parts = []
                    for stage in ("route", "briefing", "plan", "agents", "synthesis", "verify"):
                        if stage in timings:
                            stage_parts.append(f"{stage} {timings[stage]:.0f}s")
                    stage_str = f" ({', '.join(stage_parts)})" if stage_parts else ""
                    process_block += f"\n**Time:** {timings['total']:.0f}s{stage_str}\n"

                process_block += "</div>\n</details>\n"
                full_text += process_block
                yield f"data: {json.dumps({'type': 'token', 'text': process_block})}\n\n"
        except Exception as e:
            err_msg = f"MoE pipeline error: {str(e)}"
            if not full_text:
                full_text = f"**Error:** {err_msg}"
            yield f"data: {json.dumps({'type': 'error', 'text': err_msg})}\n\n"
        finally:
            # Client disconnected (or the stream errored) before the pipeline
            # finished: stop it instead of letting agents run to completion
            # for nobody.
            if not pipeline_task.done():
                pipeline_task.cancel()
            if active_sess_id and full_text:
                await asyncio.to_thread(
                    append_message_to_session,
                    active_field,
                    active_sess_id,
                    "system",
                    full_text,
                    citations=citation_payload,
                )
                asyncio.create_task(
                    background_update_memory(active_field, active_sess_id, visible_query, full_text)
                )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(moe_stream(), media_type="text/event-stream")


_DEEP_RESEARCH_SYSTEM_PROMPT = """You are a deep research assistant. Your response is synthesized from
multiple research agents that investigate different aspects of the topic. Provide comprehensive,
well-structured reports with clear citations and sources."""


async def deep_research_mode_stream(
    q: str,
    active_sess_id: str | None,
    history_to_send: list[dict] | None,
    mid_term_summary: str | None,
    files_filter: list[str] | None,
    ollama_url: str,
    chat_model: str,
    active_field: Path,
    web_search: str,
    orchestrator_model: str | None = None,
    worker_model: str | None = None,
    orchestrator_url: str | None = None,
    worker_url: str | None = None,
    long_term_episodes: list[dict] | None = None,
    display_text: str | None = None,
) -> StreamingResponse:
    """DEEP RESEARCH MODE: Plans research sub-topics, dispatches parallel research
    agents with web access, then synthesizes a comprehensive research report."""

    visible_query = display_text or q

    async def deep_research_stream():
        from palimind.llm.deep_research import run_deep_research_pipeline

        if active_sess_id:
            await asyncio.to_thread(
                append_message_to_session,
                active_field,
                active_sess_id,
                "user",
                visible_query,
            )

        orch_model = orchestrator_model or chat_model
        work_model = worker_model or chat_model
        orch_url = orchestrator_url or ollama_url
        work_url = worker_url or ollama_url

        yield (
            f"data: {json.dumps({'type': 'reasoning', 'text': 'Deep Research Mode — planning research...'})}\n\n"
        )

        progress_queue: asyncio.Queue = asyncio.Queue()

        async def on_progress(event: dict):
            await progress_queue.put(event)

        # ── interactive plan review (3.1) ────────────────────────────────
        from palimind.research.plan_registry import (
            discard_plan,
            get_pending_plan,
            register_plan,
        )
        from palimind.settings import DR_PLAN_REVIEW_TIMEOUT

        plan_event = asyncio.Event()

        async def on_plan(plan: list[dict]):
            pending = register_plan(visible_query, plan, plan_event)
            await on_progress(
                {
                    "type": "research_plan",
                    "plan_id": pending.plan_id,
                    "query": visible_query,
                    "plan": plan,
                }
            )
            try:
                await asyncio.wait_for(plan_event.wait(), timeout=DR_PLAN_REVIEW_TIMEOUT)
            except TimeoutError:
                discard_plan(pending.plan_id)
                return plan
            except asyncio.CancelledError:
                discard_plan(pending.plan_id)
                raise
            current = get_pending_plan(pending.plan_id)
            discard_plan(pending.plan_id)
            if current is None or current.cancelled:
                return None
            return current.edited_plan or plan

        pipeline_task = asyncio.create_task(
            run_deep_research_pipeline(
                user_query=q,
                ollama_url=orch_url,
                orchestrator_model=orch_model,
                worker_model=work_model,
                num_subtopics=5,
                on_progress=on_progress,
                short_term=history_to_send,
                mid_term_summary=mid_term_summary,
                long_term_episodes=long_term_episodes,
                root=active_field,
                worker_url=work_url,
                on_plan=on_plan,
            )
        )

        full_text = ""
        citation_payload: dict | None = None
        try:
            while True:
                if pipeline_task.done():
                    while not progress_queue.empty():
                        event = await progress_queue.get()
                        for sse in _progress_event_to_sse(event):
                            yield sse
                    break
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.15)
                    for sse in _progress_event_to_sse(event):
                        yield sse
                except TimeoutError:
                    continue

            result = pipeline_task.result()
            if "error" in result:
                err_text = result["error"]
                yield f"data: {json.dumps({'type': 'error', 'text': err_text})}\n\n"
                full_text = f"**Error:** {err_text}"
            elif result.get("cancelled"):
                full_text = "_Research cancelled._"
                yield f"data: {json.dumps({'type': 'token', 'text': full_text})}\n\n"
            else:
                plan = result.get("plan", [])
                outputs = result.get("outputs", [])
                synthesis = result.get("synthesis", "")
                citation_payload = result.get("citations")

                if synthesis:
                    full_text += synthesis
                    yield f"data: {json.dumps({'type': 'token', 'text': synthesis})}\n\n"

                process_block = '\n\n<details class="moe-process-details">\n<summary class="moe-process-summary">View Research Process</summary>\n<div class="moe-process-content">\n'
                if plan:
                    process_block += "#### Research Plan\n\n"
                    for item in plan:
                        title = item.get("title") or f"Sub-topic {item.get('subtopic_id', '?')}"
                        rq = item.get("research_question", "")
                        process_block += f"- **{title}:** {rq}\n"
                    process_block += "\n"

                if outputs:
                    process_block += "#### Research Agent Outputs\n\n"
                    for ro in outputs:
                        title = ro.get("title") or f"Research {ro.get('subtopic_id', '?')}"
                        out_content = ro.get("output", "No output").strip()
                        process_block += f"**{title}:**\n{out_content}\n\n"

                usage = result.get("usage") or {}
                if usage:
                    prompt_tokens = sum(int(v.get("prompt_tokens", 0)) for v in usage.values())
                    completion_tokens = sum(
                        int(v.get("completion_tokens", 0)) for v in usage.values()
                    )
                    if prompt_tokens or completion_tokens:
                        process_block += (
                            f"\n**Tokens:** {prompt_tokens + completion_tokens} total "
                            f"({prompt_tokens} in / {completion_tokens} out)\n"
                        )

                timings = result.get("timings") or {}
                if timings.get("total"):
                    stage_parts = []
                    for stage in ("plan", "briefing", "agents", "synthesis", "verify"):
                        if stage in timings:
                            stage_parts.append(f"{stage} {timings[stage]:.0f}s")
                    stage_str = f" ({', '.join(stage_parts)})" if stage_parts else ""
                    process_block += f"\n**Time:** {timings['total']:.0f}s{stage_str}\n"

                process_block += "</div>\n</details>\n"
                full_text += process_block
                yield f"data: {json.dumps({'type': 'token', 'text': process_block})}\n\n"
        except Exception as e:
            err_msg = f"Deep research pipeline error: {str(e)}"
            if not full_text:
                full_text = f"**Error:** {err_msg}"
            yield f"data: {json.dumps({'type': 'error', 'text': err_msg})}\n\n"
        finally:
            # Client disconnected (e.g. while the plan awaited review): stop
            # the pipeline instead of running the whole research unattended.
            if not pipeline_task.done():
                pipeline_task.cancel()
            if active_sess_id and full_text:
                await asyncio.to_thread(
                    append_message_to_session,
                    active_field,
                    active_sess_id,
                    "system",
                    full_text,
                    citations=citation_payload,
                )
                asyncio.create_task(
                    background_update_memory(active_field, active_sess_id, visible_query, full_text)
                )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(deep_research_stream(), media_type="text/event-stream")
