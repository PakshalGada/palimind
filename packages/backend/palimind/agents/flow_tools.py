"""Agent tools for routine flows."""

from __future__ import annotations

import json
from typing import Any

from palimind.agents import flows


def _ctx() -> dict[str, Any]:
    from palimind.llm.mixture_of_expert.tools import _get_context

    return _get_context()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def list_routine_flows(agent_id: str = "") -> str:
    caller = str(_ctx().get("agent_id") or "")
    return _json({"flows": flows.list_flows(agent_id or caller)})


def connect_routine_agents(routine_id: str, to_agent_id: str, canvas_agent_id: str = "") -> str:
    caller = str(_ctx().get("agent_id") or "")
    try:
        flow = flows.connect(canvas_agent_id or caller, routine_id, to_agent_id)
        return _json({"flow": flow})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def disconnect_routine_agents(routine_id: str, to_agent_id: str, canvas_agent_id: str = "") -> str:
    caller = str(_ctx().get("agent_id") or "")
    try:
        flow = flows.disconnect(canvas_agent_id or caller, routine_id, to_agent_id)
        return _json({"flow": flow})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


TOOLS: dict[str, dict[str, Any]] = {
    "list_routine_flows": {
        "fn": list_routine_flows,
        "description": "List the routine-flow canvases for an agent.",
        "parameters": {"agent_id": {"type": "string", "required": False}},
        "tier": 1,
        "requires_approval": False,
    },
    "connect_routine_agents": {
        "fn": connect_routine_agents,
        "description": "Hand a routine's result to another agent.",
        "parameters": {
            "routine_id": {"type": "string"},
            "to_agent_id": {"type": "string"},
            "canvas_agent_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "disconnect_routine_agents": {
        "fn": disconnect_routine_agents,
        "description": "Remove a routine-to-agent flow link.",
        "parameters": {
            "routine_id": {"type": "string"},
            "to_agent_id": {"type": "string"},
            "canvas_agent_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
}
