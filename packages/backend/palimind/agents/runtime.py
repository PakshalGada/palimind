from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any, cast

from palimind.agents import activity, approvals, questions
from palimind.agents.catalog import AgentDefinition
from palimind.agents.chat import append_chat
from palimind.agents.memory import append_memory, recall_memory
from palimind.agents.pricing import normalize_usage, usage_payload
from palimind.agents.skills import skill_instructions, skill_tools
from palimind.llm.mixture_of_expert.agents import run_agent
from palimind.llm.mixture_of_expert.tools import set_tool_context
from palimind.settings import (
    AGENT_AUTO_MEMORY_EXTRACT,
    AGENT_ESCALATION_MAX_USD,
    AGENT_ESCALATION_MODEL,
    AGENT_ESCALATION_MODELS,
    AGENT_FOLLOWUPS,
    AGENT_FRONTIER_BASE_URL,
    AGENT_MEMORY_RECALL_LIMIT,
    AGENT_RUN_HISTORY_LIMIT,
    PLAN_REVIEW_TIMEOUT,
    REASONING_CLASSIFIER_MODEL,
    SELF_CRITIQUE_MAX_RETRIES,
)

# ── RunningAgents registry ────────────────────────────────────────────────


class AgentBusyError(RuntimeError):
    """Raised when an agent has reached its concurrent-run limit."""


class _RunCancelled(BaseException):
    """Raised inside a run's worker thread once the run was cancelled.

    A BaseException so the agent loop's ``except Exception`` guards do not
    swallow it: the orphaned thread must stop calling the LLM and tools.
    """


class RunningAgent:
    def __init__(self, agent_id: str, run_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self.agent_id = agent_id
        self.run_id = run_id
        self.loop = loop
        self.task: asyncio.Task | None = None
        self.approval_event = asyncio.Event()
        self.approval_result: dict | None = None
        self.pending: dict | None = None
        self.paused = threading.Event()
        # Set when the run is cancelled/finished; the worker thread checks it.
        self.cancelled = threading.Event()
        # One pending approval at a time per run: parallel workers (fan-out)
        # share this RunningAgent and must not overwrite each other's request.
        self.approval_lock = asyncio.Lock()
        self._steer: list[str] = []
        self._steer_lock = threading.Lock()
        # A user-edited checklist is applied before the next loop step.
        self._plan: list[dict[str, Any]] | None = None
        self._plan_lock = threading.Lock()

    def release(self) -> None:
        """Stop a worker thread that may outlive its task (loop thread only).

        Clears pause, rejects any pending/queued approval and flags the run
        cancelled so the thread exits at its next event instead of spinning
        or blocking forever.
        """
        self.cancelled.set()
        self.paused.clear()
        if self.pending is not None:
            self.approval_result = {"approved": False, "correction": ""}
        self.approval_event.set()

    def push_steer(self, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        with self._steer_lock:
            self._steer.append(text)

    def drain_steer(self) -> list[str]:
        with self._steer_lock:
            items, self._steer = self._steer, []
        return items

    def set_plan(self, items: list[dict[str, Any]]) -> None:
        with self._plan_lock:
            self._plan = list(items)

    def drain_plan(self) -> list[dict[str, Any]] | None:
        with self._plan_lock:
            items, self._plan = self._plan, None
        return items


# agent_id -> run_id -> RunningAgent (true N concurrent runs)
_running: dict[str, dict[str, RunningAgent]] = {}
_running_lock = asyncio.Lock()
_background_tasks: set[asyncio.Task] = set()


async def register_running(agent_id: str, run_id: str, max_concurrent: int = 1) -> RunningAgent:
    loop = asyncio.get_running_loop()
    ra = RunningAgent(agent_id, run_id, loop)
    ra.task = asyncio.current_task()
    async with _running_lock:
        runs = _running.setdefault(agent_id, {})
        limit = max(1, int(max_concurrent or 1))
        if len(runs) >= limit:
            raise AgentBusyError(
                f"Agent is already running ({len(runs)}/{limit}). "
                "Wait for a run to finish or raise the concurrency limit."
            )
        runs[run_id] = ra
    return ra


async def unregister_running(agent_id: str, run_id: str | None = None) -> None:
    async with _running_lock:
        runs = _running.get(agent_id)
        if not runs:
            return
        if run_id is None:
            runs.clear()
        else:
            runs.pop(run_id, None)
        if not runs:
            _running.pop(agent_id, None)


def running_runs(agent_id: str) -> list[RunningAgent]:
    return list((_running.get(agent_id) or {}).values())


def running_count(agent_id: str) -> int:
    return len(_running.get(agent_id) or {})


def get_running(agent_id: str) -> RunningAgent | None:
    runs = _running.get(agent_id)
    if not runs:
        return None
    return next(reversed(list(runs.values())))


def is_running(agent_id: str) -> bool:
    return bool(_running.get(agent_id))


def cancel_agent(agent_id: str, run_id: str | None = None) -> int:
    runs = _running.get(agent_id) or {}
    if run_id:
        # An unknown/finished run id must not cancel the agent's other runs.
        targets = [runs[run_id]] if run_id in runs else []
    else:
        targets = list(runs.values())
    cancelled = 0
    for ra in targets:
        if ra.task is not None:
            ra.task.cancel()
            ra.release()
            cancelled += 1
    return cancelled


def steer_agent(agent_id: str, text: str, run_id: str | None = None) -> bool:
    """Queue guidance for a running agent. It is injected on the next step."""
    runs = _running.get(agent_id) or {}
    if not runs:
        return False
    ra = runs.get(run_id) if run_id else next(reversed(list(runs.values())))
    if ra is None:
        return False
    ra.push_steer(text)
    return True


def set_agent_plan(agent_id: str, items: list[dict[str, Any]], run_id: str | None = None) -> bool:
    """Replace a live run's checklist with a user-edited one."""
    runs = _running.get(agent_id) or {}
    if not runs:
        return False
    ra = runs.get(run_id) if run_id else next(reversed(list(runs.values())))
    if ra is None:
        return False
    ra.set_plan(items)
    return True


def pause_agent(agent_id: str, run_id: str | None = None) -> bool:
    runs = _running.get(agent_id) or {}
    if not runs:
        return False
    ra = runs.get(run_id) if run_id else next(reversed(list(runs.values())))
    if ra is None:
        return False
    ra.paused.set()
    return True


def resume_agent(agent_id: str, run_id: str | None = None) -> bool:
    runs = _running.get(agent_id) or {}
    if not runs:
        return False
    ra = runs.get(run_id) if run_id else next(reversed(list(runs.values())))
    if ra is None:
        return False
    ra.paused.clear()
    return True


def is_paused(agent_id: str) -> bool:
    ra = get_running(agent_id)
    return bool(ra and ra.paused.is_set())


def _waiting_run(agent_id: str, run_id: str | None = None) -> RunningAgent | None:
    runs = _running.get(agent_id) or {}
    if not runs:
        return None
    if run_id:
        return runs.get(run_id)
    # Resolve the run that is actually waiting, not just the newest one.
    waiting = [r for r in runs.values() if r.pending is not None]
    return waiting[-1] if waiting else None


def validate_approval_args(
    agent_id: str, args: dict[str, Any], run_id: str | None = None
) -> str | None:
    """Validate an args override against the pending tool's schema.

    Returns a human-readable error, or None when the override is usable. The
    override replaces the complete argument object, not a patch.
    """
    if not isinstance(args, dict):
        return "args must be an object"
    ra = _waiting_run(agent_id, run_id)
    if ra is None or ra.pending is None:
        return "no pending approval"
    tool_name = str(ra.pending.get("tool") or "")
    if not tool_name:
        return "no pending tool"
    from palimind.agents.tools.base import coerce_tool_args
    from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY

    _, error = coerce_tool_args(
        tool_name,
        (TOOL_REGISTRY.get(tool_name) or {}).get("parameters"),
        args,
    )
    return error


async def resolve_approval(
    agent_id: str,
    approved: bool,
    correction: str = "",
    run_id: str | None = None,
    args: dict[str, Any] | None = None,
) -> bool:
    """Called by the frontend approve/reject endpoint to unblock a waiting agent.

    ``args`` may carry a user-edited replacement for the pending tool call. The
    API validates it first; the agent loop re-validates through call_tool.
    """
    ra = _waiting_run(agent_id, run_id)
    if ra is None or ra.pending is None:
        return False
    result: dict[str, Any] = {"approved": approved, "correction": correction}
    if approved and isinstance(args, dict):
        result["args"] = dict(args)
    ra.approval_result = result
    ra.approval_event.set()
    return True


# ── run history (per agent, persisted next to definitions) ────────────────


def clear_agent_memory(agent_id: str) -> None:
    """Clear the memory store resolved from the agent's memory mode."""
    from palimind.agents.memory import _memory_namespace
    from palimind.agents.registry import get_registry
    from palimind.agents.scope import memory_file_for
    from palimind.storage import state_store

    registry = get_registry()
    defn = registry.get_by_id(agent_id)
    if defn is None:
        return
    path = memory_file_for(defn, getattr(registry, "field_root", None))
    if path is None:
        return
    try:
        state_store.set_json(_memory_namespace(path), "entries", [])
    except Exception as e:
        print(f"[agents] failed to clear memory for {agent_id}: {e}")


def delete_memory_entry(agent_id: str, index: int) -> None:
    """Remove a single memory entry by its (sorted) index."""
    from palimind.agents.memory import _memory_namespace, read_memory
    from palimind.agents.registry import get_registry
    from palimind.agents.scope import memory_file_for
    from palimind.storage import state_store

    registry = get_registry()
    defn = registry.get_by_id(agent_id)
    if defn is None:
        return
    path = memory_file_for(defn, getattr(registry, "field_root", None))
    if path is None:
        return
    from palimind.agents.memory import write_lock

    with write_lock:
        entries = read_memory(agent_id)
        if not (0 <= index < len(entries)):
            return
        entries.pop(index)
        try:
            state_store.set_json(_memory_namespace(path), "entries", entries)
        except Exception as e:
            print(f"[agents] failed to delete memory entry for {agent_id}: {e}")


def _hosted_model_client(base_url: str) -> Callable[..., dict[str, Any]]:
    """Return an OpenAI-compatible model client for a hosted/frontier route."""

    def call(
        messages: list[dict[str, Any]],
        model_id: str,
        _url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from palimind.agents.openai_client import openai_chat_safe

        return openai_chat_safe(messages, model_id, base_url, **kwargs)

    return call


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
    citations: dict | None = None,
    suggestions: list[str] | None = None,
    usage_stages: dict | None = None,
    model_route: dict | None = None,
    plan: list[dict] | None = None,
) -> None:
    from palimind.storage import state_store

    try:
        entry: dict = {
            "run_id": run_id,
            "timestamp": time.time(),
            "input": input[:2000],
            # Keep each run bounded; retention is enforced by SQL.
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
        if citations:
            entry["citations"] = citations
        if suggestions:
            entry["suggestions"] = list(suggestions[:6])
        if usage_stages:
            entry["usage_stages"] = {
                str(stage): normalize_usage(value) for stage, value in usage_stages.items() if value
            }
        if model_route:
            entry["model_route"] = dict(model_route)
        if plan:
            entry["plan"] = [
                {
                    "label": str(item.get("label") or "")[:500],
                    "status": str(item.get("status") or "pending"),
                }
                for item in plan[:50]
                if str(item.get("label") or "").strip()
            ]
        state_store.append_run(agent_id, run_id, entry, AGENT_RUN_HISTORY_LIMIT)
        try:
            from palimind import metrics

            metrics.record_agent_run(status)
        except Exception:
            pass
    except Exception as e:
        print(f"[agents] failed to record run for {agent_id}: {e}")


# Cap the stored reasoning trace per run so a long agent loop cannot bloat the
# run-history file.
_RUN_TRACE_LIMIT = 400


def _migrate_legacy_runs(agent_id: str) -> None:
    """Import the old per-agent JSON run history exactly once."""
    from palimind.storage import state_store

    path = _runs_dir() / f"{agent_id}.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception as exc:
        print(f"[agents] could not migrate run history for {agent_id}: {exc}")
        return
    if isinstance(data, list):
        for entry in data[-AGENT_RUN_HISTORY_LIMIT:]:
            if isinstance(entry, dict):
                state_store.append_run(
                    agent_id,
                    str(entry.get("run_id") or uuid.uuid4()),
                    entry,
                    AGENT_RUN_HISTORY_LIMIT,
                )
    try:
        path.rename(path.with_suffix(".json.migrated"))
    except OSError:
        pass


def get_run_history(agent_id: str, limit: int = 50) -> list[dict]:
    from palimind.storage import state_store

    if not state_store.list_runs(agent_id, limit=1):
        _migrate_legacy_runs(agent_id)
    return state_store.list_runs(agent_id, limit=limit)


def get_last_run(agent_id: str) -> dict | None:
    history = get_run_history(agent_id, limit=1)
    return history[-1] if history else None


def get_run(agent_id: str, run_id: str) -> dict | None:
    """Fetch a single run record (including its reasoning trace)."""
    from palimind.storage import state_store

    record = state_store.get_run(agent_id, run_id)
    if record is not None:
        return record
    _migrate_legacy_runs(agent_id)
    return state_store.get_run(agent_id, run_id)


# ── human-in-the-loop bridge ──────────────────────────────────────────────


def _tool_tier(tool_name: str) -> int:
    try:
        from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, _register_plugin_tools

        _register_plugin_tools()
        return int((TOOL_REGISTRY.get(tool_name, {}).get("meta") or {}).get("tier", 0))
    except Exception:
        return 0


def _make_approval_provider(
    ra: RunningAgent,
    emit_async: Callable[[str, dict], Awaitable[None]] | None,
    definition: AgentDefinition | None = None,
    team_id: str = "",
) -> Callable[[dict], dict]:
    """Return a blocking approval callback suitable for the sync tool layer.

    Runs the suspension + SSE emission on the event loop and blocks the
    worker thread until the frontend resolves the pending approval.

    ``emit_async`` must be the raw async emitter (not a thread bridge):
    it is awaited from within a coroutine already running on the loop.
    """

    def provider(pending: dict) -> dict:
        async def _inner() -> dict:
            async with ra.approval_lock:
                if ra.cancelled.is_set():
                    return {"approved": False}
                return await _wait(pending)

        async def _wait(pending: dict) -> dict:
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
                agent_label=str(getattr(definition, "label", "") or ""),
                team_id=team_id,
                tier=_tool_tier(str(pending.get("tool", ""))),
            )
            if team_id:
                try:
                    from palimind.agents import team_chat

                    team_chat.append_message(
                        team_id,
                        "approval",
                        f"{pending.get('tool')} needs approval: {pending.get('args')}",
                        author=f"agent:{ra.agent_id}",
                        run_id=ra.run_id,
                        meta={"tool": pending.get("tool"), "status": "waiting"},
                    )
                except Exception:
                    pass
            await ra.approval_event.wait()
            result = ra.approval_result or {"approved": False}
            approvals.remove(ra.agent_id, ra.run_id)
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


_CHECKLIST_HINTS = (
    "then",
    "plan",
    "research",
    "compare",
    "investigate",
    "write",
    "create",
    "build",
    "fix",
    "debug",
    "analyse",
    "analyze",
    "review",
    "report",
    "implement",
)


def _task_words(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-zA-Z0-9_]{4,}", (text or "").lower())
        if word
        not in {
            "this",
            "that",
            "with",
            "from",
            "into",
            "what",
            "when",
            "where",
            "which",
            "should",
            "please",
            "using",
            "make",
            "need",
        }
    }


def _suggest_checklist(
    input_text: str,
    working_root: Path | None,
    *,
    limit: int = 3,
) -> list[str]:
    """Build a task-aware starting checklist, grounded in workspace files.

    The model still owns the list: this only seeds it so the UI shows a plan
    immediately and the agent starts from the material that actually exists
    instead of planning in the abstract.
    """
    text = (input_text or "").strip()
    if len(text) < 40 and not any(hint in text.lower() for hint in _CHECKLIST_HINTS):
        return []
    words = _task_words(text)
    files: list[str] = []
    if working_root is not None and Path(working_root).is_dir():
        from itertools import islice

        root = Path(working_root)
        try:
            for entry in islice(root.rglob("*"), 1000):
                if entry.is_dir() or ".palimind" in entry.parts:
                    continue
                if any(part in {"node_modules", "__pycache__", ".git"} for part in entry.parts):
                    continue
                try:
                    rel = str(entry.relative_to(root))
                except ValueError:
                    continue
                name_tokens = _task_words(rel.replace("/", " ").replace(".", " "))
                score = len(words & name_tokens)
                if score:
                    files.append(rel)
                if len(files) >= limit:
                    break
        except Exception:
            files = []
    first = (
        f"Review workspace material: {', '.join(files[:limit])}"
        if files
        else "Review the workspace context"
    )
    summary = " ".join(text.split())
    if len(summary) > 90:
        summary = summary[:87].rstrip() + "…"
    return [
        first,
        f"Complete the requested work: {summary}",
        "Verify the result, then cite any sources used",
    ]


def _checklist_prompt_block(items: list[str]) -> str:
    if not items:
        return ""
    lines = "\n".join(f"{index + 1}. [ ] {item}" for index, item in enumerate(items))
    return (
        "[CHECKLIST]\n"
        "This is your starting plan. Keep it accurate with todo_write: mark the "
        "current item in_progress, mark each item completed as you finish it, "
        "and add/remove items if the work changes.\n" + lines + "\n"
    )


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
            usage_cb=usage_cb,
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
    interactive: bool = True,
    *,
    team_context: dict[str, Any] | None = None,
    extra_tools: list[str] | None = None,
    extra_prompt: str = "",
    resume_state: dict[str, Any] | None = None,
    resume_from_run_id: str = "",
    channel_id: str = "",
    task_id: str = "",
) -> str:
    """Run an agent from its definition.

    Loads the agent's memory and prepends it to the system prompt as an
    [AGENT MEMORY] block, enforces the definition's tool allowlist, sets
    max iterations from the definition, runs the existing agent loop, and
    on completion appends a result entry to agent memory when
    memory mode is not "off".

    ``calling_root`` is the calling knowledge base — the agent's tools are
    sandboxed to it. When omitted it defaults to the active field, and when
    neither is set the agent runs unsandboxed (legacy behaviour).

    ``emit(event_type, payload)`` is an optional async callback for the
    SSE reasoning chain (agent:thought / tool_call / tool_result /
    waiting_for_human / completed).
    """
    run_id = str(uuid.uuid4())
    if resume_state:
        input = str(resume_state.get("input") or input)
        session_id = str(resume_state.get("session_id") or session_id)
    ra = await register_running(definition.id, run_id, definition.max_concurrent_runs)
    loop = asyncio.get_running_loop()
    if not resume_state:
        append_chat(definition.id, "user", input)
    activity.start(definition.id, definition.name, run_id, session_id)
    from palimind.agents import run_journal

    run_journal.start(run_id, definition.id, input, session_id)

    # Reasoning trace for the run-history detail view. Token frames are
    # excluded (they are just the answer streamed in chunks).
    trace: list[dict] = []
    trace_lock = threading.Lock()
    usage_holder: dict = {}
    usage_stages: dict[str, dict[str, int]] = {}
    suggestions_holder: list[str] = []
    plan_holder: list[dict] = []

    _live_kinds = {
        "agent:thought": "thought",
        "agent:tool_call": "tool",
        "agent:tool_result": "result",
    }

    def thread_emit(event_type: str, payload: dict) -> None:
        if ra.cancelled.is_set():
            # The task was cancelled but asyncio.to_thread cannot stop the
            # worker; abort it here so it stops running tools after Stop.
            raise _RunCancelled()
        if event_type == "agent:usage":
            # Enrich the live token counter with the configured cost estimate.
            payload = {**payload, **usage_payload(payload)}
        if event_type == "agent:todo":
            plan_holder[:] = list(payload.get("items") or [])
        if event_type not in ("agent:token", "agent:usage"):
            with trace_lock:
                trace.append({"type": event_type, **payload})
            # Checkpoint every meaningful step so a crash leaves an audit trail.
            run_journal.append(run_id, definition.id, event_type, payload)
        kind = _live_kinds.get(event_type)
        if kind is not None:
            label = payload.get("text") or payload.get("tool") or ""
            activity.step(definition.id, str(label), kind)
        if emit is None:
            return
        try:
            fut: Any = asyncio.run_coroutine_threadsafe(
                cast(Coroutine[Any, Any, None], emit(event_type, payload)), loop
            )
            fut.result(timeout=30)
        except Exception as e:
            print(f"[agents] emit failed: {e}")

    def _record_stage(stage: str, u: dict, *, add: bool = False) -> None:
        """Record token usage for one stage and keep the grand total."""
        normalized = normalize_usage(u)
        if add:
            previous = usage_stages.get(stage, {"prompt_tokens": 0, "completion_tokens": 0})
            usage_stages[stage] = {
                "prompt_tokens": previous["prompt_tokens"] + normalized["prompt_tokens"],
                "completion_tokens": previous["completion_tokens"]
                + normalized["completion_tokens"],
            }
            for key in ("prompt_tokens", "completion_tokens"):
                usage_holder[key] = int(usage_holder.get(key, 0)) + normalized[key]
        else:
            usage_stages[stage] = normalized
            for key in ("prompt_tokens", "completion_tokens"):
                usage_holder[key] = int(usage_holder.get(key, 0)) + normalized[key]

    def _usage_cb(u: dict) -> None:
        # The agent loop reports its cumulative total once, at the end.
        _record_stage("agent", u)

    def _add_usage(u: dict) -> None:
        """Accumulate auxiliary calls (e.g. follow-ups) into the run total."""
        _record_stage("followups", u, add=True)

    def _verification_usage(u: dict) -> None:
        _record_stage("verification", u, add=True)

    async def emit_completed(output: str, status: str) -> None:
        if emit is None:
            return
        payload: dict[str, Any] = {
            "output": output,
            "status": status,
            "usage": usage_payload(usage_holder) if usage_holder else {},
        }
        if suggestions_holder:
            payload["suggestions"] = list(suggestions_holder)
        if usage_stages:
            payload["usage_stages"] = {
                str(stage): normalize_usage(value) for stage, value in usage_stages.items() if value
            }
        await emit("agent:completed", payload)

    start = time.time()
    status = "success"
    output = ""
    cancelled = False
    verification_holder: dict[str, Any] = {}
    effort_info: dict[str, Any] = {}
    route_info: dict[str, Any] = {}
    route_model_client: Any | None = None
    collected_sources: list[dict[str, Any]] = []
    citation_holder: dict[str, Any] | None = None
    fallback_note = ""
    model = definition.model or "llama3"
    ollama_url = ""
    light_model = ""
    try:
        team_ctx = dict(team_context or {})
        approval_provider = (
            _make_approval_provider(
                ra,
                emit,
                definition,
                team_id=str(team_ctx.get("team_id") or ""),
            )
            if interactive
            else None
        )

        chat_model, ollama_url, light_model = _field_models(calling_root)
        from palimind.agents.providers.resolver import resolve_agent_model

        resolved = resolve_agent_model(
            definition, global_chat_model=chat_model, ollama_url=ollama_url
        )
        if not resolved.ok:
            raise RuntimeError(f"{resolved.message} [{resolved.action}]")
        model = resolved.model
        ollama_url = resolved.base_url
        fallback_note = ""
        from palimind.opencode.router import resolve_model_url

        if resolved.provider == "ollama" and resolved.source != "agent":
            model, fallback_note = _resolve_available_model(model, chat_model, ollama_url)
        from palimind.agents.registry import get_registry

        working_root = calling_root if calling_root is not None else get_registry().field_root
        from palimind.agents.scope import resolve_scope

        primary_root, extra_roots = resolve_scope(definition, working_root)
        set_tool_context(
            primary_root,
            ollama_url,
            model,
            light_model,
            extra_roots=extra_roots,
            read_only_roots=extra_roots,
            source_collector=collected_sources,
            agent_id=definition.id,
            session_id=session_id,
            run_id=run_id,
            write_access=bool(definition.write_access),
            desktop_access=bool(getattr(definition, "desktop_access", False)),
            desktop_control=bool(getattr(definition, "desktop_control", False)),
            desktop_allowed_apps=list(getattr(definition, "desktop_allowed_apps", []) or []),
            allow_network=False,
            team_id=str(team_ctx.get("team_id") or ""),
            team_run_id=str(team_ctx.get("team_run_id") or ""),
            team_emit=team_ctx.get("team_emit"),
            team_loop=team_ctx.get("team_loop"),
            delegate_depth=int(team_ctx.get("delegate_depth", 0) or 0),
            channel_id=channel_id,
            task_id=task_id,
            emit_event=thread_emit,
            run_control=ra,
        )

        # ── Phase 4.1: adaptive reasoning effort ─────────────────────────────
        from dataclasses import replace

        from palimind.agents import adaptive_reasoning as ar

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
                usage_cb=lambda u: _record_stage("classifier", u, add=True),
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
        if definition.memory_mode != "off":
            # Pre-run recall: surface the memory entries most relevant to this
            # input rather than just the most recent ones.
            mem = recall_memory(definition.id, input, k=AGENT_MEMORY_RECALL_LIMIT)
            if mem:
                lines = [
                    f"- [{e.get('type', 'fact')}] {str(e.get('content', ''))[:400]}" for e in mem
                ]
                memory_block = "[AGENT MEMORY]\n" + "\n".join(lines) + "\n"

        custom_prompt = definition.system_prompt or ""
        if memory_block:
            custom_prompt = (
                custom_prompt.rstrip() + "\n\n" if custom_prompt else ""
            ) + memory_block
        skill_prompt = skill_instructions(definition.skills)
        if skill_prompt:
            custom_prompt = (
                custom_prompt.rstrip() + "\n\n" if custom_prompt else ""
            ) + skill_prompt
        context_block = _workspace_context_block(working_root)
        if context_block:
            custom_prompt = (
                custom_prompt.rstrip() + "\n\n" if custom_prompt else ""
            ) + context_block

        from palimind.agents.workspace import workspace_context_block

        ws_block = workspace_context_block(definition)
        if ws_block:
            custom_prompt = (custom_prompt.rstrip() + "\n\n" if custom_prompt else "") + ws_block
        if extra_prompt:
            custom_prompt = (
                custom_prompt.rstrip() + "\n\n" if custom_prompt else ""
            ) + extra_prompt

        # Retrieval-aware checklist seed: ground the plan in files that exist,
        # then let the model own/update it. Emitted before the first turn so
        # the UI shows progress immediately.
        checklist_seed = (
            _suggest_checklist(input, working_root)
            if str(getattr(definition, "orchestration", "off")) in ("", "off")
            and str(getattr(definition, "planning_mode", "off")) != "review"
            else []
        )
        if checklist_seed:
            try:
                from palimind.llm.mixture_of_expert.tools import (
                    get_todo_items as _get_todo_items,
                )
                from palimind.llm.mixture_of_expert.tools import todo_write as _todo_write

                _todo_write([{"label": item, "status": "pending"} for item in checklist_seed])
                seeded = _get_todo_items()
                if seeded and emit is not None:
                    await emit("agent:todo", {"items": seeded})
                custom_prompt = (
                    custom_prompt.rstrip() + "\n\n" if custom_prompt else ""
                ) + _checklist_prompt_block(checklist_seed)
            except Exception as exc:  # noqa: BLE001 - seeding is best-effort
                print(f"[agents] checklist seeding failed: {exc}")

        custom_prompt = (
            (custom_prompt.rstrip() + "\n\n" if custom_prompt else "") + "[HOW TO WORK]\n"
            "Plan → act → verify → deliver. Use a tool instead of guessing. "
            "Before the first tool call in any multi-step task, create a short "
            "checklist with todo_write, then execute each item with a real tool; "
            "checklist updates are not progress. Mark every item completed before "
            "the final answer. Cite sources when you research. Write requested "
            "deliverables to your workspace with write_file. Read tool errors, adjust "
            "once, then continue. If a website needs a sign-in, password, OTP or "
            "CAPTCHA, call browser_request_takeover instead of guessing. Stop when the "
            "success criteria are met and always finish with FINAL_ANSWER."
        )

        # Attached skills can extend the agent's tool allowlist. A desktop
        # grant also contributes the desktop pack even when tool_pack is
        # "auto"; see resolve_effective_tools.
        from palimind.agents.catalog import (
            pinned_tools_for,
            resolve_effective_tools,
        )

        effective_tools = resolve_effective_tools(
            definition,
            extra_tools=extra_tools or [],
            skill_tools=skill_tools(definition.skills),
        )
        sub_task: dict[str, Any] = {
            "agent_id": _stable_agent_int(definition.id),
            "definition_id": definition.id,
            "label": definition.name,
            "task": input,
            "tools": effective_tools,
            "pinned_tools": pinned_tools_for(definition, input),
            "context": "",
        }

        # Capability-aware routing: keep the requested model unless the task
        # needs a capability it lacks, or a complex task on a small local model
        # has a configured hosted/frontier fallback.
        try:
            from palimind.agents.model_routing import route_model

            hosted: set[str] = set()
            try:
                from palimind.opencode.router import opencode_model_ids

                hosted = set(opencode_model_ids())
            except Exception:
                hosted = set()
            route = route_model(
                input,
                model,
                candidates=[chat_model, light_model, *AGENT_ESCALATION_MODELS],
                ollama_url=ollama_url,
                tools=effective_tools,
                complexity=str(effort_info.get("level") or "standard"),
                hosted_models=hosted,
            )
            route_info = route.to_dict()
            if route.model and route.model != model:
                previous = model
                model = route.model
                if route.provider != "hosted":
                    ollama_url = resolve_model_url(model, ollama_url)
                fallback_note = f"Model routed from '{previous}' to '{model}' ({route.reason})." + (
                    f" {fallback_note}" if fallback_note else ""
                )
                route_info["previous"] = previous
            if route.provider == "hosted":
                route_model_client = _hosted_model_client(AGENT_FRONTIER_BASE_URL)

            if emit is not None:
                await emit("agent:model_route", route_info)
        except Exception as exc:  # noqa: BLE001 - routing must never block a run
            print(f"[agents] model routing failed: {exc}")

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
                    usage_cb=lambda u: _record_stage("planning", u, add=True),
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
                    decision = await planner_mod.wait_for_plan_review(
                        plan["id"], PLAN_REVIEW_TIMEOUT
                    )
                    if not decision.get("approved") and not decision.get("timeout"):
                        plan_rejected = True
                    else:
                        refreshed = planner_mod.get_plan(plan["id"])
                        if refreshed:
                            plan = refreshed
                if not plan_rejected:
                    custom_prompt = _plan_prompt_block(custom_prompt, plan)

        # Automatic model escalation: when the agent's own model is smaller
        # than the knowledge base's chat model (or an explicit escalation model
        # is configured), keep it ready for the exhausted-budget synthesis.
        # Candidate order: explicit ordered list → single override → field
        # chat model. Only an installed model different from the current one
        # is eligible. A hosted route already uses the strongest configured
        # model, so it must not escalate into a local model.
        if route_info.get("provider") == "hosted":
            candidates: list[str] = []
        else:
            candidates = list(AGENT_ESCALATION_MODELS)
            if AGENT_ESCALATION_MODEL:
                candidates.append(AGENT_ESCALATION_MODEL)
            candidates.append(chat_model)
        try:
            from palimind.opencode.router import available_model_ids

            available = available_model_ids(ollama_url)
        except Exception:
            available = set()
        escalation_model = ""
        for candidate in candidates:
            candidate = str(candidate or "").strip()
            if not candidate or candidate == model:
                continue
            if available and candidate not in available:
                continue
            escalation_model = candidate
            break
        escalation_url = resolve_model_url(escalation_model, ollama_url) if escalation_model else ""

        start = time.time()
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
                        session_id=session_id,
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
                        run_control=ra,
                        run_id=run_id,
                        resume_state=resume_state,
                        resume_from_run_id=resume_from_run_id,
                        escalation_model=escalation_model,
                        escalation_url=escalation_url,
                        escalation_max_cost_usd=AGENT_ESCALATION_MAX_USD,
                        model_client=route_model_client,
                    )
            except asyncio.CancelledError:
                status = "cancelled"
                output = "[Agent run cancelled]"
                cancelled = True
                # Finalisation (run history, chat, journal) happens below so a
                # cancelled run is never lost. Re-raise only after persisting.
                try:
                    await emit_completed(output, status)
                except Exception:
                    pass
            except Exception as e:
                status = "error"
                output = f"[Agent run error] {e}"
                try:
                    await emit_completed(output, status)
                except Exception:
                    pass

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
                    usage_cb=_verification_usage,
                )
                verification_holder = report

            # ── Source ledger + citations ────────────────────────────────
            if status == "success" and output and collected_sources:
                try:
                    from palimind.agents.citations import finalize_agent_citations

                    output, citation_holder = finalize_agent_citations(output, collected_sources)
                    if citation_holder and emit is not None:
                        await emit("citation_map", citation_holder)
                except Exception as exc:  # noqa: BLE001 - never lose the answer
                    print(f"[agents] citation attachment failed: {exc}")

            # ── Follow-up suggestions ───────────────────────────────────
            if status == "success" and output and AGENT_FOLLOWUPS and emit is not None:
                try:
                    from palimind.agents.suggestions import generate_suggestions

                    with trace_lock:
                        trace_for_suggestions = list(trace)
                    tool_names = [
                        str(item.get("tool", ""))
                        for item in trace_for_suggestions
                        if item.get("type") == "agent:tool_call"
                    ]
                    suggestions_holder[:] = await asyncio.to_thread(
                        generate_suggestions,
                        input,
                        output,
                        light_model or model,
                        ollama_url,
                        tool_names=tool_names,
                        usage_cb=_add_usage,
                    )
                    if suggestions_holder:
                        await emit(
                            "agent:suggestions",
                            {"suggestions": list(suggestions_holder)},
                        )
                except Exception as exc:  # noqa: BLE001 - never lose the answer
                    print(f"[agents] follow-up suggestions failed: {exc}")
    except asyncio.CancelledError:
        # Cancelled outside the agent loop (plan review, setup, verification):
        # still finalise below so the run never stays "running".
        status = "cancelled"
        output = "[Agent run cancelled]"
        cancelled = True
        try:
            await emit_completed(output, status)
        except Exception:
            pass
    except Exception as e:
        status = "error"
        output = f"[Agent run error] {e}"
        try:
            await emit_completed(output, status)
        except Exception:
            pass
    finally:
        await unregister_running(definition.id, run_id)
        approvals.remove(definition.id, run_id)
        questions.clear(run_id=run_id)
        try:
            from palimind.llm.mixture_of_expert.tools import clear_todo

            clear_todo(run_id)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            pass
        # Unblock a worker thread that may outlive the run (cancelled while
        # paused or waiting for approval) so it stops instead of leaking.
        ra.release()

    if fallback_note and status == "success":
        output = f"**Note:** {fallback_note}\n\n{output}"

    if status in ("success", "rejected"):
        await emit_completed(output, status)

    duration = time.time() - start
    with trace_lock:
        trace_snapshot = list(trace)
    try:
        from palimind.agents import run_state as run_state_mod

        run_state_mod.finalize(run_id, status, output)
    except Exception as exc:  # noqa: BLE001 - never lose a completed run
        print(f"[agents] failed to finalize run state {run_id}: {exc}")
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
        citations=citation_holder,
        suggestions=suggestions_holder or None,
        usage_stages=usage_stages or None,
        model_route=route_info or None,
        plan=plan_holder or None,
    )
    append_chat(definition.id, "agent", output)
    activity.finish(definition.id, status, output, run_id=run_id)
    run_journal.finish(run_id, definition.id, status, output)

    if definition.memory_mode != "off":
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
            # Keep a reference so the task is not garbage-collected mid-run.
            extract = asyncio.create_task(
                asyncio.to_thread(
                    _extract_facts, definition, input, output, light_model, ollama_url
                )
            )
            _background_tasks.add(extract)
            extract.add_done_callback(_background_tasks.discard)

    if cancelled:
        raise asyncio.CancelledError()
    return output
