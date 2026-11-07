"""Agent tools for event waits."""

from __future__ import annotations

import json
from typing import Any

from palimind.agents import waits


def _ctx() -> dict[str, Any]:
    from palimind.llm.mixture_of_expert.tools import _get_context

    return _get_context()


def _caller() -> str:
    return str(_ctx().get("agent_id") or "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def await_event(note: str, routine_id: str = "") -> str:
    caller = _caller()
    if not caller:
        return "Error: await_event needs a calling agent"
    try:
        wait = waits.create_wait(caller, note, routine_id=routine_id)
        return _json({"wait": wait})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def list_waits(agent_id: str = "") -> str:
    caller = _caller()
    target = agent_id or caller
    return _json({"waits": waits.list_waits(target, status="open", limit=100)})


def close_wait(wait_id: str, reason: str = "") -> str:
    wait = waits.get_wait(wait_id)
    if wait is None:
        return "Error: wait not found"
    if str(wait.get("agent_id")) != _caller():
        return "Error: an agent may close only its own waits"
    return _json({"wait": waits.close_wait(wait_id, reason=reason)})


TOOLS: dict[str, dict[str, Any]] = {
    "await_event": {
        "fn": await_event,
        "description": "Open a wait and end the turn until a routine or script wakes it.",
        "parameters": {
            "note": {"type": "string", "description": "What the agent waits for."},
            "routine_id": {"type": "string", "required": False},
        },
        "tier": 1,
        "requires_approval": False,
    },
    "list_waits": {
        "fn": list_waits,
        "description": "List open waits for this agent or another local agent.",
        "parameters": {"agent_id": {"type": "string", "required": False}},
        "tier": 1,
        "requires_approval": False,
    },
    "close_wait": {
        "fn": close_wait,
        "description": "Close one of this agent's waits.",
        "parameters": {
            "wait_id": {"type": "string"},
            "reason": {"type": "string", "required": False},
        },
        "tier": 1,
        "requires_approval": False,
    },
}
