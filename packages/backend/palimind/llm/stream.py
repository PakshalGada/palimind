from __future__ import annotations

import asyncio
import json
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
) -> StreamingResponse:
    """PLAIN LLM MODE: Chat directly with the LLM using general knowledge only.
    No document context, no internet access, no code execution, no tools."""

    async def plain_stream():
        from palimind.generative.responder import generate_response_stream
        from palimind.memory.hierarchical import format_hierarchical_memory_context

        if active_sess_id:
            await asyncio.to_thread(
                append_message_to_session,
                active_field,
                active_sess_id,
                "user",
                q,
            )

        yield (
            f"data: {json.dumps({'type': 'reasoning', 'text': '💬 LLM Mode — general knowledge only (no document context)'})}\n\n"
        )

        system_prompt = _LLM_SYSTEM_PROMPT
        if persona:
            system_prompt = f"{persona}\n\n{system_prompt}"
        memory_ctx = format_hierarchical_memory_context(mid_term_summary, [])
        if memory_ctx:
            system_prompt = f"{system_prompt}\n\n{memory_ctx}"

        full_text = ""
        try:
            stream = generate_response_stream(
                query=q,
                context="",
                image_paths=[],
                ollama_url=ollama_url,
                chat_model=chat_model,
                system_prompt=system_prompt,
                history=history_to_send,
                is_chat_only=True,
            )
            for token in stream:
                full_text += token
                yield (f"data: {json.dumps({'type': 'token', 'text': token})}\n\n")
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
                )
                asyncio.create_task(
                    background_update_memory(active_field, active_sess_id, q, full_text)
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
    elif etype == "synthesizing":
        return [f"data: {json.dumps({'type': 'reasoning', 'text': event.get('text', '')})}\n\n"]
    elif etype == "verifying":
        return [f"data: {json.dumps({'type': 'reasoning', 'text': event.get('text', '')})}\n\n"]
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
) -> StreamingResponse:
    """MOE MODE: Uses an orchestrator LLM to create a plan, dispatches to 4 smaller
    agent LLMs that run in parallel with tool access, then synthesizes the results."""

    async def moe_stream():
        from palimind.llm.mixture_of_expert import run_moe_pipeline

        if active_sess_id:
            await asyncio.to_thread(
                append_message_to_session,
                active_field,
                active_sess_id,
                "user",
                q,
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
            )
        )

        full_text = ""
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

                if synthesis:
                    full_text += synthesis
                    yield f"data: {json.dumps({'type': 'token', 'text': synthesis})}\n\n"

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
            if active_sess_id and full_text:
                await asyncio.to_thread(
                    append_message_to_session,
                    active_field,
                    active_sess_id,
                    "system",
                    full_text,
                )
                asyncio.create_task(
                    background_update_memory(active_field, active_sess_id, q, full_text)
                )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(moe_stream(), media_type="text/event-stream")
