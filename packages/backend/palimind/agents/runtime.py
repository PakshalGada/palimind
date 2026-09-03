from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from palimind.agents.catalog import AgentDefinition
from palimind.agents.chat import append_chat
from palimind.agents.memory import append_memory, read_memory
from palimind.llm.mixture_of_expert.agents import run_agent
from palimind.llm.mixture_of_expert.tools import set_tool_context
from palimind.settings import AGENT_RUN_HISTORY_LIMIT

# ── RunningAgents registry ────────────────────────────────────────────────


class RunningAgent:
    def __init__(self, agent_id: str, run_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self.agent_id = agent_id
        self.run_id = run_id
        self.loop = loop
        self.task: asyncio.Task | None = None
        self.approval_event = asyncio.Event()
        self.approval_result: dict | None = None
        self.pending: dict | None = None


_running: dict[str, RunningAgent] = {}
_running_lock = asyncio.Lock()


async def register_running(agent_id: str, run_id: str) -> RunningAgent:
    loop = asyncio.get_running_loop()
    ra = RunningAgent(agent_id, run_id, loop)
    ra.task = asyncio.current_task()
    async with _running_lock:
        _running[agent_id] = ra
    return ra


async def unregister_running(agent_id: str) -> None:
    async with _running_lock:
        _running.pop(agent_id, None)


def get_running(agent_id: str) -> RunningAgent | None:
    return _running.get(agent_id)


def is_running(agent_id: str) -> bool:
    return agent_id in _running


def cancel_agent(agent_id: str) -> bool:
    ra = _running.get(agent_id)
    if ra is not None and ra.task is not None:
        ra.task.cancel()
        return True
    return False


async def resolve_approval(agent_id: str, approved: bool, correction: str = "") -> bool:
    """Called by the frontend approve/reject endpoint to unblock a waiting agent."""
    ra = _running.get(agent_id)
    if ra is None or ra.pending is None:
        return False
    ra.approval_result = {"approved": approved, "correction": correction}
    ra.approval_event.set()
    return True


# ── run history (per agent, persisted next to definitions) ────────────────


def clear_agent_memory(agent_id: str) -> None:
    """Clear an agent's memory file (resolved from its definition).

    Kept here (rather than in palimind.agents.memory) so that memory.py exposes
    only its two documented functions.
    """
    from palimind.agents.registry import get_registry

    defn = get_registry().get_by_id(agent_id)
    if defn is None or not defn.memory_file:
        return
    try:
        p = Path(defn.memory_file).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[]", "utf-8")
    except OSError as e:
        print(f"[agents] failed to clear memory for {agent_id}: {e}")


def delete_memory_entry(agent_id: str, index: int) -> None:
    """Remove a single memory entry by its (sorted) index."""
    from palimind.agents.memory import read_memory
    from palimind.agents.registry import get_registry

    defn = get_registry().get_by_id(agent_id)
    if defn is None or not defn.memory_file:
        return
    entries = read_memory(agent_id)
    if not (0 <= index < len(entries)):
        return
    entries.pop(index)
    try:
        p = Path(defn.memory_file).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(entries, indent=2), "utf-8")
    except OSError as e:
        print(f"[agents] failed to delete memory entry for {agent_id}: {e}")


def _runs_dir() -> Path:
    from palimind.agents.catalog import GLOBAL_AGENTS_DIR

    base = GLOBAL_AGENTS_DIR / "runs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def record_run(
    agent_id: str,
    run_id: str,
    input: str,
    output: str,
    status: str,
    duration: float,
) -> None:
    path = _runs_dir() / f"{agent_id}.json"
    try:
        data = []
        if path.exists():
            data = json.loads(path.read_text("utf-8"))
            if not isinstance(data, list):
                data = []
        data.append(
            {
                "run_id": run_id,
                "timestamp": time.time(),
                "input": input[:2000],
                "output": output[:100_000],
                "status": status,
                "duration": round(duration, 2),
            }
        )
        data = data[-AGENT_RUN_HISTORY_LIMIT:]
        path.write_text(json.dumps(data, indent=2), "utf-8")
    except Exception as e:
        print(f"[agents] failed to record run for {agent_id}: {e}")


def get_run_history(agent_id: str, limit: int = 50) -> list[dict]:
    path = _runs_dir() / f"{agent_id}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
        return (data if isinstance(data, list) else [])[-limit:]
    except Exception:
        return []


def get_last_run(agent_id: str) -> dict | None:
    history = get_run_history(agent_id, limit=1)
    return history[-1] if history else None


# ── human-in-the-loop bridge ──────────────────────────────────────────────


def _make_approval_provider(
    ra: RunningAgent,
    emit_async: Callable[[str, dict], Awaitable[None]] | None,
) -> Callable[[dict], dict]:
    """Return a blocking approval callback suitable for the sync tool layer.

    Runs the suspension + SSE emission on the event loop and blocks the
    worker thread until the frontend resolves the pending approval.

    ``emit_async`` must be the raw async emitter (not a thread bridge):
    it is awaited from within a coroutine already running on the loop.
    """

    def provider(pending: dict) -> dict:
        async def _inner() -> dict:
            ra.pending = pending
            ra.approval_event.clear()
            ra.approval_result = None
            if emit_async is not None:
                await emit_async(
                    "agent:waiting_for_human",
                    {
                        "agent_id": ra.agent_id,
                        "run_id": ra.run_id,
                        "tool": pending.get("tool"),
                        "args": pending.get("args"),
                        "confidence": pending.get("confidence"),
                        "threshold": pending.get("threshold"),
                        "reasoning": pending.get("reasoning"),
                    },
                )
            await ra.approval_event.wait()
            result = ra.approval_result or {"approved": False}
            ra.pending = None
            return result

        fut = asyncio.run_coroutine_threadsafe(_inner(), ra.loop)
        return fut.result()

    return provider


# ── entry point ───────────────────────────────────────────────────────────


def _field_models(field_root: Path | None = None) -> tuple[str, str, str]:
    """Return (chat_model, ollama_url, light_model) for the given working root.

    Falls back to the active field, then to the global (user-level) config.
    """
    from palimind.agents.registry import get_registry
    from palimind.config import load_config, load_global_config

    root = field_root if field_root is not None else get_registry().field_root
    if root is None:
        config = load_global_config()
    else:
        try:
            config = load_config(root)
        except Exception:
            config = {}
    chat = config.get("chat_model", "llama3")
    ollama = config.get("ollama_base_url", "http://localhost:11434")
    light = config.get("light_model", "") or chat

    from palimind.opencode.router import resolve_model_url

    ollama = resolve_model_url(chat, ollama)
    return chat, ollama, light


def _resolve_available_model(
    requested: str, field_default: str, ollama_url: str
) -> tuple[str, str]:
    """Return ``(model, fallback_note)``.

    When *requested* is not served by Ollama or the OpenCode proxy, fall back
    to the field default (if available) or the first available model, and
    return a human-readable note explaining the switch. If availability can't
    be determined, return the requested model unchanged with an empty note so
    the run proceeds exactly as before.
    """
    from palimind.opencode.router import available_model_ids

    requested = requested or "llama3"
    try:
        available = available_model_ids(ollama_url)
    except Exception as e:
        print(f"[agents] model availability check failed: {e}")
        return requested, ""

    if not available or requested in available:
        return requested, ""

    if field_default and field_default in available and field_default != requested:
        return field_default, (
            f"Model '{requested}' is not installed; using field default '{field_default}'."
        )

    first = sorted(available)[0]
    return first, f"Model '{requested}' is not installed; using '{first}' instead."


def _stable_agent_int(agent_id: str) -> int:
    try:
        return int(uuid.UUID(agent_id).int % (10**9))
    except (ValueError, AttributeError):
        return sum(ord(c) for c in str(agent_id)) % (10**9)


_CONTEXT_SCAN_BUDGET = 4000
_CONTEXT_FILE_LIMIT = 250


def _workspace_context_block(context_fields: list[str]) -> str:
    """Summarise the contents of the knowledge bases attached to an agent.

    Returns a [WORKSPACE CONTEXT] block listing each knowledge base and a
    sample of its file paths so the agent knows what material it can draw on.
    """
    from itertools import islice

    lines: list[str] = []
    for raw in context_fields[:5]:
        root = Path(str(raw)).expanduser()
        if not root.is_dir():
            continue
        lines.append(f"Workspace '{root.name}': {root}")
        count = 0
        for entry in islice(root.rglob("*"), _CONTEXT_SCAN_BUDGET):
            if entry.is_dir():
                continue
            name = entry.name
            if (
                ".palimind" in entry.parts
                or "node_modules" in entry.parts
                or "__pycache__" in entry.parts
                or name.startswith(".")
            ):
                continue
            try:
                rel = entry.relative_to(root)
            except ValueError:
                continue
            lines.append(f"  - {rel}")
            count += 1
            if count >= _CONTEXT_FILE_LIMIT:
                lines.append("  - ... (more files exist)")
                break
        lines.append("")
    if not lines:
        return ""
    return "[WORKSPACE CONTEXT]\n" + "\n".join(lines).rstrip() + "\n"


async def run_with_definition(
    definition: AgentDefinition,
    input: str,
    session_id: str = "",
    emit: Callable[[str, dict], Awaitable[None]] | None = None,
    calling_root: Path | None = None,
) -> str:
    """Run an agent from its definition.

    Loads the agent's memory and prepends it to the system prompt as an
    [AGENT MEMORY] block, enforces the definition's tool allowlist, sets
    max iterations from the definition, runs the existing agent loop, and
    on completion appends a result entry to agent memory when
    memory_scope is not "none".

    ``calling_root`` is the calling knowledge base — the agent's tools are
    sandboxed to it. When omitted it defaults to the active field, and when
    neither is set the agent runs unsandboxed (legacy behaviour).

    ``emit(event_type, payload)`` is an optional async callback for the
    SSE reasoning chain (agent:thought / tool_call / tool_result /
    waiting_for_human / completed).
    """
    run_id = str(uuid.uuid4())
    ra = await register_running(definition.id, run_id)
    loop = asyncio.get_running_loop()
    append_chat(definition.id, "user", input)

    def thread_emit(event_type: str, payload: dict) -> None:
        if emit is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(emit(event_type, payload), loop)
            fut.result(timeout=30)
        except Exception as e:
            print(f"[agents] emit failed: {e}")

    async def emit_completed(output: str, status: str) -> None:
        if emit is not None:
            await emit("agent:completed", {"output": output, "status": status})

    approval_provider = _make_approval_provider(ra, emit)

    chat_model, ollama_url, light_model = _field_models(calling_root)
    requested_model = definition.model or chat_model or "llama3"
    model, fallback_note = _resolve_available_model(requested_model, chat_model, ollama_url)
    from palimind.opencode.router import resolve_model_url

    # The agent may use a model different from the field's chat_model (e.g. an
    # OpenCode-proxy model); re-resolve the URL against the actual model so
    # proxy-served models are not called on the local Ollama instance.
    ollama_url = resolve_model_url(model, ollama_url)
    from palimind.agents.registry import get_registry

    working_root = calling_root if calling_root is not None else get_registry().field_root
    context_fields = [
        Path(str(cf)).expanduser() for cf in (getattr(definition, "context_fields", []) or [])
    ]
    extra_roots = [
        cf
        for cf in context_fields
        if cf.is_dir() and (working_root is None or cf.resolve() != working_root.resolve())
    ]
    set_tool_context(
        working_root,
        ollama_url,
        model,
        light_model,
        extra_roots=extra_roots,
    )

    memory_block = ""
    if definition.memory_scope != "none":
        mem = read_memory(definition.id)
        if mem:
            lines = [
                f"- [{e.get('type', 'fact')}] {str(e.get('content', ''))[:400]}" for e in mem[-20:]
            ]
            memory_block = "[AGENT MEMORY]\n" + "\n".join(lines) + "\n"

    custom_prompt = definition.system_prompt or ""
    if memory_block:
        custom_prompt = (custom_prompt.rstrip() + "\n\n" if custom_prompt else "") + memory_block
    context_block = _workspace_context_block(getattr(definition, "context_fields", []) or [])
    if context_block:
        custom_prompt = (custom_prompt.rstrip() + "\n\n" if custom_prompt else "") + context_block

    sub_task: dict[str, Any] = {
        "agent_id": _stable_agent_int(definition.id),
        "label": definition.name,
        "task": input,
        "tools": list(definition.tools),
        "context": "",
    }

    start = time.time()
    status = "success"
    try:
        output = await asyncio.to_thread(
            run_agent,
            sub_task["agent_id"],
            sub_task,
            model,
            ollama_url,
            definition.max_iterations,
            None,
            definition=definition,
            extra_system_prompt=custom_prompt,
            event_cb=thread_emit,
            approval_provider=approval_provider,
            session_id=session_id,
        )
    except asyncio.CancelledError:
        status = "cancelled"
        output = "[Agent run cancelled]"
        await emit_completed(output, status)
        raise
    except Exception as e:
        status = "error"
        output = f"[Agent run error] {e}"
        await emit_completed(output, status)
    finally:
        await unregister_running(definition.id)

    if fallback_note and status == "success":
        output = f"**Note:** {fallback_note}\n\n{output}"

    if status == "success":
        await emit_completed(output, status)

    duration = time.time() - start
    record_run(definition.id, run_id, input, output, status, duration)
    append_chat(definition.id, "agent", output)

    if definition.memory_scope != "none":
        try:
            append_memory(
                definition.id,
                "result" if status == "success" else "error",
                f"Run ({session_id or 'manual'}): {input[:300]} → {output[:1500]}",
            )
        except Exception as e:
            print(f"[agents] memory append failed: {e}")

    return output
