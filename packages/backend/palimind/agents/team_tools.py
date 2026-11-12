"""Team delegation tools: ``ask_agent``, ``post_to_team``, ``read_team_notes``.

Only meaningful inside a team run. Each call reads the run-scoped tool context
so parallel members cannot leak delegation state into each other.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from palimind.agents import blackboard, team_chat, teams
from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, _get_context

MAX_DELEGATIONS = 8
MAX_DEPTH = 2

_lock = threading.Lock()
_delegations: dict[str, int] = {}


def _meta(tier: int, requires_approval: bool = False) -> dict[str, Any]:
    return {"tier": tier, "requires_approval": requires_approval}


def _bump(run_id: str) -> int:
    with _lock:
        _delegations[run_id] = _delegations.get(run_id, 0) + 1
        return _delegations[run_id]


def delegation_count(run_id: str) -> int:
    with _lock:
        return _delegations.get(run_id, 0)


def reset_delegations(run_id: str) -> None:
    with _lock:
        _delegations.pop(run_id, None)


def _emit_sync(ctx: dict[str, Any], payload: dict[str, Any]) -> None:
    emit = ctx.get("team_emit")
    loop = ctx.get("team_loop")
    if emit is None or loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(emit(payload), loop).result(timeout=10)
    except Exception as exc:  # noqa: BLE001 - streaming is best-effort
        print(f"[teams] emit failed: {exc}")


def ask_agent(agent: str, task: str, context: str = "") -> str:
    """Delegate a self-contained task to a teammate and return their result."""
    ctx = _get_context()
    team_id = str(ctx.get("team_id") or "")
    run_id = str(ctx.get("team_run_id") or "")
    if not team_id or not run_id:
        return "Error: ask_agent is only available inside a team run."

    depth = int(ctx.get("delegate_depth", 0) or 0)
    if depth >= MAX_DEPTH:
        return "Error: delegation depth limit reached."

    team = teams.get_team(team_id)
    if team is None:
        return "Error: team not found."

    member = teams.resolve_member(team, agent)
    if member is None:
        return f"Error: '{agent}' is not a member of this team."

    caller = str(ctx.get("agent_id") or "")
    if str(member.get("agent_id")) == caller:
        return "Error: an agent cannot delegate to itself."

    count = _bump(run_id)
    if count > MAX_DELEGATIONS:
        return "Error: delegation budget exhausted for this team run."

    defn = member.get("agent")
    if defn is None:
        return "Error: teammate definition is unavailable."
    if not getattr(defn, "enabled", True):
        return f"Error: {defn.label} is disabled."

    task_text = str(task or "").strip()
    if not task_text:
        return "Error: task is required."
    if context:
        task_text = f"{task_text}\n\n[CONTEXT]\n{context}"

    handoff = team_chat.append_message(
        team_id,
        "handoff",
        task_text,
        author=f"agent:{caller}",
        run_id=run_id,
        meta={"from": f"agent:{caller}", "to": f"agent:{member['agent_id']}", "status": "working"},
    )
    _emit_sync(ctx, {"type": "team:message", "message": handoff})
    blackboard.post(
        team_id,
        author=str(getattr(defn, "label", defn.name)),
        label=f"Handoff: {task_text[:80]}",
        content=task_text,
        kind="handoff",
    )

    _emit_sync(
        ctx,
        {
            "type": "team:member_started",
            "agent_id": str(member["agent_id"]),
            "name": str(getattr(defn, "label", defn.name)),
            "task": task_text[:500],
        },
    )

    loop = ctx.get("team_loop")
    emit = ctx.get("team_emit")
    if loop is None:
        return "Error: team run loop is unavailable."

    async def member_emit(etype: str, payload: dict[str, Any]) -> None:
        if emit is None:
            return
        await emit(
            {
                "type": etype,
                "agent_id": str(member["agent_id"]),
                "name": str(getattr(defn, "label", defn.name)),
                **payload,
            }
        )

    from palimind.agents.runtime import run_with_definition

    working_root = None
    raw_root = str(team.get("working_root") or "")
    if raw_root:
        candidate = Path(raw_root).expanduser()
        if candidate.is_dir():
            working_root = candidate

    async def _run() -> str:
        # Track the delegate under the team run so Stop cancels it too;
        # otherwise it keeps running (up to 30 min) after the team is stopped.
        from palimind.agents.team_runtime import _handles

        handle = _handles.get(team_id)
        if handle is not None and handle.run_id == run_id:
            if handle.cancelled:
                raise asyncio.CancelledError()
            handle.add(asyncio.current_task())
        return await run_with_definition(
            defn,
            task_text,
            session_id=f"team:{team_id}:{run_id}",
            emit=member_emit,
            calling_root=working_root,
            interactive=True,
            team_context={
                "team_id": team_id,
                "team_run_id": run_id,
                "team_emit": emit,
                "team_loop": loop,
                "delegate_depth": depth + 1,
                "caller_agent_id": caller,
            },
        )

    started = time.time()
    future = asyncio.run_coroutine_threadsafe(_run(), loop)
    try:
        output = future.result(timeout=1800)
        status = "ok"
    except Exception as exc:  # noqa: BLE001 - surface failure to the manager
        # On timeout the delegate is still running; stop it.
        future.cancel()
        output = f"[{getattr(defn, 'label', defn.name)} failed] {exc}"
        status = "error"

    result_message = team_chat.append_message(
        team_id,
        "result",
        output,
        author=f"agent:{member['agent_id']}",
        run_id=run_id,
        meta={
            "from": f"agent:{member['agent_id']}",
            "status": status,
            "duration": round(time.time() - started, 2),
        },
    )
    _emit_sync(ctx, {"type": "team:message", "message": result_message})
    blackboard.post(
        team_id,
        author=str(getattr(defn, "label", defn.name)),
        label=f"Result ({status})",
        content=output[:4000],
        kind="result",
    )
    _emit_sync(
        ctx,
        {
            "type": "team:member_result",
            "agent_id": str(member["agent_id"]),
            "name": str(getattr(defn, "label", defn.name)),
            "output": output,
            "status": status,
        },
    )
    return output


def post_to_team(content: str, label: str = "Update") -> str:
    """Post a short update to the team thread and shared notes."""
    ctx = _get_context()
    team_id = str(ctx.get("team_id") or "")
    run_id = str(ctx.get("team_run_id") or "")
    if not team_id:
        return "Error: post_to_team is only available inside a team run."
    author = str(ctx.get("agent_id") or "system")
    message = team_chat.append_message(
        team_id,
        "manager",
        content,
        author=f"agent:{author}",
        run_id=run_id or None,
        meta={"label": label},
    )
    _emit_sync(ctx, {"type": "team:message", "message": message})
    entry = blackboard.post(team_id, author=author, label=label, content=content, kind="update")
    _emit_sync(ctx, {"type": "team:notes", "entry": entry})
    return "Posted."


def read_team_notes() -> str:
    """Read the team's shared notes (the blackboard)."""
    ctx = _get_context()
    team_id = str(ctx.get("team_id") or "")
    if not team_id:
        return "Error: read_team_notes is only available inside a team run."
    return blackboard.render(team_id) or "[TEAM NOTES] (empty)"


def register_team_tools() -> None:
    TOOL_REGISTRY.setdefault(
        "ask_agent",
        {
            "fn": ask_agent,
            "description": "Delegate a self-contained task to a teammate and return their result.",
            "parameters": {
                "agent": "Teammate name or id",
                "task": "Clear, self-contained task",
                "context": "Optional context the teammate needs",
            },
            "meta": _meta(1, False),
            "timeout_s": 1900,
        },
    )
    TOOL_REGISTRY.setdefault(
        "post_to_team",
        {
            "fn": post_to_team,
            "description": (
                "Post a short update (one or two sentences) to the team thread "
                "and shared notes. Not for your detailed result."
            ),
            "parameters": {"content": "Update text", "label": "Optional short label"},
            "meta": _meta(1, False),
        },
    )
    TOOL_REGISTRY.setdefault(
        "read_team_notes",
        {
            "fn": read_team_notes,
            "description": "Read the team's shared notes (blackboard).",
            "parameters": {},
            "meta": _meta(1, False),
        },
    )
