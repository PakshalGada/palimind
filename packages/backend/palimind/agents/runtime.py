from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from palimind.agents import activity, approvals
from palimind.agents.catalog import AgentDefinition
from palimind.agents.chat import append_chat
from palimind.agents.memory import append_memory, recall_memory
from palimind.agents.skills import skill_instructions, skill_tools
from palimind.llm.mixture_of_expert.agents import run_agent
from palimind.llm.mixture_of_expert.tools import set_tool_context
from palimind.settings import (
    AGENT_AUTO_MEMORY_EXTRACT,
    AGENT_MEMORY_RECALL_LIMIT,
    AGENT_RUN_HISTORY_LIMIT,
    PLAN_REVIEW_TIMEOUT,
    REASONING_CLASSIFIER_MODEL,
    SELF_CRITIQUE_MAX_RETRIES,
)

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
    usage: dict | None = None,
    trace: list[dict] | None = None,
    verification: dict | None = None,
    effort: dict | None = None,
) -> None:
    path = _runs_dir() / f"{agent_id}.json"
    try:
        data = []
        if path.exists():
            data = json.loads(path.read_text("utf-8"))
            if not isinstance(data, list):
                data = []
        entry: dict = {
            "run_id": run_id,
            "timestamp": time.time(),
            "input": input[:2000],
            "output": output[:100_000],
            "status": status,
            "duration": round(duration, 2),
        }
        if usage:
            entry["usage"] = {
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
            }
        if trace:
            entry["trace"] = trace[-_RUN_TRACE_LIMIT:]
        if verification:
            entry["verification"] = verification
        if effort:
            entry["effort"] = effort
        data.append(entry)
        data = data[-AGENT_RUN_HISTORY_LIMIT:]
        path.write_text(json.dumps(data, indent=2), "utf-8")
    except Exception as e:
        print(f"[agents] failed to record run for {agent_id}: {e}")


# Cap the stored reasoning trace per run so a long agent loop cannot bloat the
# run-history file.
_RUN_TRACE_LIMIT = 400


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


def get_run(agent_id: str, run_id: str) -> dict | None:
    """Fetch a single run record (including its reasoning trace)."""
    for record in get_run_history(agent_id, limit=10**6):
        if str(record.get("run_id")) == str(run_id):
            return record
    return None


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
            approvals.add(
                ra.agent_id,
                ra.run_id,
                str(pending.get("tool", "")),
                pending.get("args"),
                float(pending.get("confidence", 0.0) or 0.0),
                str(pending.get("reasoning", "")),
            )
            await ra.approval_event.wait()
            result = ra.approval_result or {"approved": False}
            approvals.remove(ra.agent_id)
            ra.pending = None
            return result

        fut = asyncio.run_coroutine_threadsafe(_inner(), ra.loop)
        return fut.result()

    return provider


# ── automatic memory extraction ───────────────────────────────────────────

_FACT_EXTRACT_PROMPT = (
    "Extract at most 3 durable facts about the user or the task from the "
    "exchange below. Each must be a short, standalone statement (a stable "
    "preference, constraint, or fact). Return one per line starting with '- '. "
    "If there is nothing durable worth remembering, return 'NONE'."
)


def _extract_facts(
    definition: AgentDefinition,
    input_text: str,
    output_text: str,
    model: str,
    ollama_url: str,
) -> None:
    """Background pass that turns a run into a few durable memory facts."""
    try:
        from palimind.llm.mixture_of_expert.llm import llm_chat_safe

        result = llm_chat_safe(
            [
                {
                    "role": "user",
                    "content": (
                        f"{_FACT_EXTRACT_PROMPT}\n\nUSER:\n{input_text[:1500]}"
                        f"\n\nASSISTANT:\n{output_text[:2000]}"
                    ),
                }
            ],
            model,
            ollama_url,
            temperature=0.1,
            num_predict=200,
            error_prefix="[memory extract",
        )
        content = result.get("content", "") or ""
        for line in content.splitlines():
            text = line.strip().lstrip("-*• ").strip()
            if not text or text.upper() == "NONE" or text.startswith("["):
                continue
            append_memory(definition.id, "fact", text[:500])
    except Exception as e:  # noqa: BLE001 - extraction is best-effort
        print(f"[agents] fact extraction failed: {e}")


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


def _workspace_context_block(working_root: Path | None) -> str:
    """Summarise the contents of the selected knowledge base.

    Agents are global, but each run operates on the knowledge base the user
    currently has selected (the calling/active field). Returns a
    [WORKSPACE CONTEXT] block listing that knowledge base and a sample of its
    file paths so the agent knows what material it can draw on.
    """
    if working_root is None or not Path(working_root).is_dir():
        return ""
    from itertools import islice

    root = Path(working_root).expanduser()
    lines: list[str] = [f"Workspace '{root.name}': {root}"]
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
    if count == 0:
        return ""
    return "[WORKSPACE CONTEXT]\n" + "\n".join(lines).rstrip() + "\n"


def _plan_prompt_block(custom_prompt: str, plan: dict[str, Any]) -> str:
    """Inject an approved plan into the agent's system prompt."""
    steps = plan.get("steps", [])
    if not steps:
        return custom_prompt
    lines: list[str] = []
    for i, step in enumerate(steps):
        title = step.get("title") or f"Step {i + 1}"
        description = step.get("description", "")
        line = f"{i + 1}. {title}"
        if description:
            line += f" — {description}"
        if step.get("tool"):
            line += f" (tool: {step['tool']})"
        lines.append(line)
    block = (
        "[PLAN]\n"
        "Follow this approved plan step by step. Adapt if reality differs, but "
        "cover every step before finishing:\n" + "\n".join(lines) + "\n"
    )
    return (custom_prompt.rstrip() + "\n\n" if custom_prompt else "") + block


async def _verify_and_maybe_retry(
    *,
    definition: AgentDefinition,
    input_text: str,
    output: str,
    model: str,
    ollama_url: str,
    light_model: str,
    custom_prompt: str,
    sub_task: dict[str, Any],
    effective_iterations: int,
    approval_provider: Any,
    session_id: str,
    emit: Any,
    thread_emit: Any,
    usage_cb: Any,
) -> tuple[str, dict[str, Any]]:
    """Run structured verification, retrying a bounded number of times.

    Returns ``(final_output, report)``. Emits ``agent:verification`` after each
    attempt and ``agent:needs_review`` when the result should reach a human.
    """
    from palimind.agents import self_critique as sc

    verify_model = light_model or model
    threshold = definition.verify_confidence_threshold or None

    async def _run_verification(text: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            sc.verify_output,
            input_text,
            text,
            verify_model,
            ollama_url,
            definition=definition,
            success_criteria=definition.success_criteria,
        )

    report = await _run_verification(output)
    if emit is not None:
        await emit("agent:verification", {"report": report, "attempt": 0})

    retries = 0
    while sc.needs_retry(report, threshold) and retries < SELF_CRITIQUE_MAX_RETRIES:
        retries += 1
        retry_task = {**sub_task, "task": sc.build_retry_prompt(input_text, output, report)}
        try:
            output = await asyncio.to_thread(
                run_agent,
                sub_task["agent_id"],
                retry_task,
                model,
                ollama_url,
                effective_iterations,
                None,
                definition=definition,
                extra_system_prompt=custom_prompt,
                event_cb=thread_emit,
                approval_provider=approval_provider,
                session_id=session_id,
                token_stream=True,
                reflect=False,
                usage_cb=usage_cb,
            )
        except Exception as e:  # noqa: BLE001 - a failed retry keeps the draft
            print(f"[agents] verification retry failed: {e}")
            break
        report = await _run_verification(output)
        if emit is not None:
            await emit("agent:verification", {"report": report, "attempt": retries})

    if sc.needs_human_review(report, threshold) and emit is not None:
        await emit("agent:needs_review", {"report": report})
    return output, report


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
    activity.start(definition.id, definition.name, run_id, session_id)

    # Reasoning trace for the run-history detail view. Token frames are
    # excluded (they are just the answer streamed in chunks).
    trace: list[dict] = []
    trace_lock = threading.Lock()
    usage_holder: dict = {}

    _live_kinds = {
        "agent:thought": "thought",
        "agent:tool_call": "tool",
        "agent:tool_result": "result",
    }

    def thread_emit(event_type: str, payload: dict) -> None:
        if event_type != "agent:token":
            with trace_lock:
                trace.append({"type": event_type, **payload})
        kind = _live_kinds.get(event_type)
        if kind is not None:
            label = payload.get("text") or payload.get("tool") or ""
            activity.step(definition.id, str(label), kind)
        if emit is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(emit(event_type, payload), loop)
            fut.result(timeout=30)
        except Exception as e:
            print(f"[agents] emit failed: {e}")

    def _usage_cb(u: dict) -> None:
        usage_holder.update(u)

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
    set_tool_context(
        working_root,
        ollama_url,
        model,
        light_model,
        extra_roots=[],
    )

    # ── Phase 4.1: adaptive reasoning effort ─────────────────────────────
    from dataclasses import replace

    from palimind.agents import adaptive_reasoning as ar

    effort_info: dict[str, Any] = {}
    effective_iterations = definition.max_iterations
    effective_context = definition.context_budget
    if definition.reasoning_effort and definition.reasoning_effort != "off":
        classifier_model = REASONING_CLASSIFIER_MODEL or light_model or model
        effort_info = await asyncio.to_thread(
            ar.resolve_effort,
            input,
            definition.reasoning_effort,
            classifier_model,
            ollama_url,
        )
        applied = ar.apply_effort(
            effort_info["level"],
            max_iterations=definition.max_iterations,
            context_budget=definition.context_budget,
        )
        effective_iterations = applied["iterations"]
        effective_context = applied["context_budget"]
        if emit is not None:
            await emit(
                "agent:effort",
                {
                    "level": effort_info["level"],
                    "indicator": ar.effort_indicator(effort_info["level"]),
                    "source": effort_info.get("source", ""),
                    "score": effort_info.get("score"),
                    "reasoning": effort_info.get("reasoning", ""),
                    "max_iterations": effective_iterations,
                },
            )
    run_definition = replace(definition, context_budget=effective_context)

    memory_block = ""
    if definition.memory_scope != "none":
        # Pre-run recall: surface the memory entries most relevant to this
        # input rather than just the most recent ones.
        mem = recall_memory(definition.id, input, k=AGENT_MEMORY_RECALL_LIMIT)
        if mem:
            lines = [f"- [{e.get('type', 'fact')}] {str(e.get('content', ''))[:400]}" for e in mem]
            memory_block = "[AGENT MEMORY]\n" + "\n".join(lines) + "\n"

    custom_prompt = definition.system_prompt or ""
    if memory_block:
        custom_prompt = (custom_prompt.rstrip() + "\n\n" if custom_prompt else "") + memory_block
    skill_prompt = skill_instructions(definition.skills)
    if skill_prompt:
        custom_prompt = (custom_prompt.rstrip() + "\n\n" if custom_prompt else "") + skill_prompt
    context_block = _workspace_context_block(working_root)
    if context_block:
        custom_prompt = (custom_prompt.rstrip() + "\n\n" if custom_prompt else "") + context_block

    # Attached skills can extend the agent's tool allowlist.
    effective_tools = list(dict.fromkeys([*definition.tools, *skill_tools(definition.skills)]))
    sub_task: dict[str, Any] = {
        "agent_id": _stable_agent_int(definition.id),
        "label": definition.name,
        "task": input,
        "tools": effective_tools,
        "context": "",
    }

    # ── Phase 4.4: planning mode ─────────────────────────────────────────
    from palimind.agents import planner as planner_mod

    plan: dict[str, Any] | None = None
    plan_rejected = False
    if definition.planning_mode in ("review", "auto"):
        try:
            plan = await asyncio.to_thread(
                planner_mod.generate_plan,
                input,
                light_model or model,
                ollama_url,
                agent_id=definition.id,
                available_tools=effective_tools,
                success_criteria=definition.success_criteria,
            )
        except Exception as e:  # noqa: BLE001 - planning is best-effort
            print(f"[agents] plan generation failed: {e}")
            plan = None
        if plan is not None:
            planner_mod.save_plan(plan)
            if emit is not None:
                await emit(
                    "agent:plan",
                    {
                        "plan_id": plan["id"],
                        "mode": definition.planning_mode,
                        "status": "pending",
                        "steps": plan.get("steps", []),
                    },
                )
            if definition.planning_mode == "review" and emit is not None:
                decision = await planner_mod.wait_for_plan_review(plan["id"], PLAN_REVIEW_TIMEOUT)
                if not decision.get("approved") and not decision.get("timeout"):
                    plan_rejected = True
                else:
                    refreshed = planner_mod.get_plan(plan["id"])
                    if refreshed:
                        plan = refreshed
            if not plan_rejected:
                custom_prompt = _plan_prompt_block(custom_prompt, plan)

    start = time.time()
    status = "success"
    output = ""
    verification_holder: dict[str, Any] = {}
    orchestration_result: dict[str, Any] | None = None
    try:
        if plan_rejected:
            status = "rejected"
            output = "[Plan rejected by user]"
        else:
            try:
                if definition.orchestration in ("fan_out", "arena"):
                    from palimind.agents import orchestrator as orch_mod

                    async def orch_emit(etype: str, payload: dict) -> None:
                        with trace_lock:
                            trace.append({"type": etype, **payload})
                        if emit is not None:
                            await emit(etype, payload)

                    orchestration_result = await orch_mod.orchestrate(
                        input,
                        model=model,
                        ollama_url=ollama_url,
                        light_model=light_model,
                        definition=run_definition,
                        working_root=working_root,
                        num_agents=definition.orchestration_agents or None,
                        mode=definition.orchestration,
                        emit=orch_emit,
                        approval_provider=approval_provider,
                    )
                    output = orchestration_result.get("output", "")
                else:
                    output = await asyncio.to_thread(
                        run_agent,
                        sub_task["agent_id"],
                        sub_task,
                        model,
                        ollama_url,
                        effective_iterations,
                        None,
                        definition=run_definition,
                        extra_system_prompt=custom_prompt,
                        event_cb=thread_emit,
                        approval_provider=approval_provider,
                        session_id=session_id,
                        token_stream=True,
                        reflect=False,
                        usage_cb=_usage_cb,
                    )
            except asyncio.CancelledError:
                status = "cancelled"
                output = "[Agent run cancelled]"
                activity.finish(definition.id, status, output)
                await emit_completed(output, status)
                raise
            except Exception as e:
                status = "error"
                output = f"[Agent run error] {e}"
                await emit_completed(output, status)

            # ── Phase 4.6: structured self-critique / verification ───────
            if status == "success" and output and definition.self_critique:
                output, report = await _verify_and_maybe_retry(
                    definition=run_definition,
                    input_text=input,
                    output=output,
                    model=model,
                    ollama_url=ollama_url,
                    light_model=light_model,
                    custom_prompt=custom_prompt,
                    sub_task=sub_task,
                    effective_iterations=effective_iterations,
                    approval_provider=approval_provider,
                    session_id=session_id,
                    emit=emit,
                    thread_emit=thread_emit,
                    usage_cb=_usage_cb,
                )
                verification_holder = report
    finally:
        await unregister_running(definition.id)
        approvals.remove(definition.id)

    if fallback_note and status == "success":
        output = f"**Note:** {fallback_note}\n\n{output}"

    if status == "success":
        await emit_completed(output, status)

    duration = time.time() - start
    with trace_lock:
        trace_snapshot = list(trace)
    record_run(
        definition.id,
        run_id,
        input,
        output,
        status,
        duration,
        usage=usage_holder,
        trace=trace_snapshot,
        verification=verification_holder or None,
        effort=effort_info or None,
    )
    append_chat(definition.id, "agent", output)
    activity.finish(definition.id, status, output)

    if definition.memory_scope != "none":
        try:
            append_memory(
                definition.id,
                "result" if status == "success" else "error",
                f"Run ({session_id or 'manual'}): {input[:300]} → {output[:1500]}",
            )
        except Exception as e:
            print(f"[agents] memory append failed: {e}")
        if status == "success" and AGENT_AUTO_MEMORY_EXTRACT:
            # Fire-and-forget so extraction never delays the run's completion.
            asyncio.create_task(
                asyncio.to_thread(
                    _extract_facts, definition, input, output, light_model, ollama_url
                )
            )

    return output
