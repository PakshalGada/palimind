from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi.responses import StreamingResponse

from palimind.agents.catalog import AgentDefinition
from palimind.agents.runtime import run_with_definition


def agent_sse(etype: str, payload: dict[str, Any]) -> str:
    """Serialize an agent reasoning-chain event as an SSE frame."""
    event = {"type": etype, **payload}
    return f"data: {json.dumps(event)}\n\n"


async def agent_event_stream(
    defn: AgentDefinition,
    input: str,
    session_id: str = "",
    working_root: Path | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run an agent and stream reasoning-chain events as dicts.

    Yields ``{"type": ...}`` dicts: agent:thought / agent:tool_call /
    agent:tool_result / agent:waiting_for_human / agent:completed / error.
    The underlying run is registered in RunningAgents so it can be
    cancelled via POST /api/agents/{id}/cancel.

    ``working_root`` is the calling knowledge base the agent's tools are
    sandboxed to (defaults to the active field).
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def emit_event(etype: str, payload: dict[str, Any]) -> None:
        await queue.put({"type": etype, **payload})

    task = asyncio.create_task(
        run_with_definition(defn, input, session_id, emit=emit_event, calling_root=working_root)
    )
    try:
        while True:
            if task.done():
                while not queue.empty():
                    yield queue.get_nowait()
                break
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=0.2)
                yield ev
            except TimeoutError:
                continue
        try:
            await task
        except asyncio.CancelledError:
            yield {
                "type": "agent:completed",
                "output": "[Agent run cancelled]",
                "status": "cancelled",
            }
        except Exception as e:
            yield {"type": "error", "text": f"Agent run error: {e}"}
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


async def agent_mode_stream(
    field_root: Path,
    agent_name: str,
    agent_input: str,
    session_id: str | None,
    ollama_url: str,
    chat_model: str,
    working_root: Path | None = None,
) -> StreamingResponse:
    """Route an @agent-name chat invocation to run_with_definition.

    ``field_root`` is used for chat session storage; ``working_root`` is the
    knowledge base the agent's tools are sandboxed to (defaults to the active
    field when None).

    Streams the agent reasoning chain (agent:thought / tool_call /
    tool_result / waiting_for_human / completed) as SSE, appends the user
    message and final output to the chat session, and ends with 'done'.
    """
    from palimind.agents.registry import get_registry

    defn = get_registry().get(agent_name)
    if defn is None:

        async def err_stream():
            yield agent_sse(
                "error",
                {"text": f"Agent '{agent_name}' not found. Create it in the Agents panel."},
            )
            yield agent_sse("done", {})

        return StreamingResponse(err_stream(), media_type="text/event-stream")

    if not defn.enabled:

        async def err_stream():
            yield agent_sse("error", {"text": f"Agent '{agent_name}' is disabled."})
            yield agent_sse("done", {})

        return StreamingResponse(err_stream(), media_type="text/event-stream")

    mode_params = {"agent_name": agent_name}

    async def gen():
        from palimind.memory.session_store import append_message_to_session

        if session_id:
            await asyncio.to_thread(
                append_message_to_session,
                field_root,
                session_id,
                "user",
                f"@{agent_name} {agent_input}".strip(),
                mode="agent",
                mode_params=mode_params,
            )

        yield agent_sse("reasoning", {"text": f"🤖 Running agent '{agent_name}'..."})

        full_text = ""
        async for ev in agent_event_stream(defn, agent_input or "Run your task.", session_id or "", working_root=working_root):
            etype = ev.get("type", "")
            payload = {k: v for k, v in ev.items() if k != "type"}
            yield agent_sse(etype, payload)
            if etype == "agent:completed":
                full_text = str(payload.get("output", ""))
            elif etype == "error":
                full_text = str(payload.get("text", ""))

        if session_id and full_text:
            await asyncio.to_thread(
                append_message_to_session,
                field_root,
                session_id,
                "system",
                full_text,
                mode="agent",
                mode_params=mode_params,
            )

        yield agent_sse("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")
