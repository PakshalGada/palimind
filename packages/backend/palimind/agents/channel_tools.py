"""Agent tools for shared channels.

The runtime installs ``channel_id`` and ``agent_id`` in the tool context; these
tools act only on the channel of the running turn.
"""

from __future__ import annotations

import json
from typing import Any

from palimind.agents import channels


def _ctx() -> dict[str, Any]:
    from palimind.llm.mixture_of_expert.tools import _get_context

    return _get_context()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _channel_id(channel_id: str = "") -> str:
    return str(channel_id or _ctx().get("channel_id") or "")


def _caller() -> str:
    return str(_ctx().get("agent_id") or "")


def channel_history(channel_id: str = "", limit: int = 50) -> str:
    channel_id = _channel_id(channel_id)
    if not channel_id:
        return "Error: no channel in this turn"
    return _json(
        {
            "channel": channels.get_channel(channel_id),
            "messages": channels.list_messages(channel_id, limit=max(1, min(int(limit or 50), 500))),
        }
    )


def channel_assign_task(
    request: str,
    agent_id: str = "",
    parent_task_id: str = "",
    channel_id: str = "",
) -> str:
    channel_id = _channel_id(channel_id)
    if not channel_id:
        return "Error: no channel in this turn"
    try:
        task = channels.create_task(
            channel_id,
            request,
            owner_agent_id=agent_id or _caller(),
            parent_task_id=parent_task_id,
        )
        return _json({"task": task})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def channel_transfer_task(task_id: str, agent_id: str, channel_id: str = "") -> str:
    channel_id = _channel_id(channel_id)
    task = channels.get_task(task_id)
    if task is None or (channel_id and str(task.get("channel_id")) != channel_id):
        return "Error: task not found"
    try:
        return _json({"task": channels.transfer_task(task_id, agent_id)})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def channel_report_result(task_id: str, result: str, channel_id: str = "") -> str:
    channel_id = _channel_id(channel_id)
    task = channels.get_task(task_id)
    if task is None or (channel_id and str(task.get("channel_id")) != channel_id):
        return "Error: task not found"
    if str(task.get("owner_agent_id")) not in ("", _caller()):
        return "Error: only the task owner can report a result"
    channel = channels.complete_task(task_id, result)
    channels.append_message(
        channel_id or str(task.get("channel_id") or ""),
        result,
        author_kind="agent",
        author_id=_caller(),
        task_id=task_id,
    )
    return _json({"task": channel})


def channel_add_member(agent_id: str, role: str = "", instructions: str = "", channel_id: str = "") -> str:
    channel_id = _channel_id(channel_id)
    if not channel_id:
        return "Error: no channel in this turn"
    try:
        return _json({"member": channels.add_member(channel_id, agent_id, role=role, instructions=instructions)})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def channel_remove_member(agent_id: str, channel_id: str = "") -> str:
    channel_id = _channel_id(channel_id)
    if agent_id == _caller():
        return "Error: an agent cannot remove itself"
    return _json({"removed": channels.remove_member(channel_id, agent_id)})


def channel_set_instructions(agent_id: str, instructions: str, channel_id: str = "") -> str:
    channel_id = _channel_id(channel_id)
    if agent_id != _caller():
        return "Error: an agent may change only its own channel instructions"
    return _json({"member": channels.set_member_instructions(channel_id, agent_id, instructions)})


def channel_list_routines(channel_id: str = "") -> str:
    channel_id = _channel_id(channel_id)
    from palimind.agents import routines

    items = [
        r
        for r in routines.list_routines(limit=500)
        if str(r.get("channel_id") or "") == channel_id
    ]
    return _json({"routines": items})


def channel_create_routine(
    name: str,
    instruction: str,
    schedule: str = "",
    channel_id: str = "",
) -> str:
    channel_id = _channel_id(channel_id)
    from palimind.agents import routines

    try:
        routine = routines.create_routine(
            {
                "name": name,
                "instruction": instruction,
                "schedule": schedule,
                "channel_id": channel_id,
                "agent_id": _caller(),
                "owner_kind": "channel",
            }
        )
        return _json({"routine": routine})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def channel_update_routine(routine_id: str, changes: str = "", channel_id: str = "") -> str:
    channel_id = _channel_id(channel_id)
    from palimind.agents import routines

    routine = routines.get_routine(routine_id)
    if routine is None or str(routine.get("channel_id") or "") != channel_id:
        return "Error: routine not found"
    try:
        payload = json.loads(changes) if isinstance(changes, str) and changes.strip() else {}
    except json.JSONDecodeError:
        return "Error: changes must be a JSON object"
    if not isinstance(payload, dict):
        return "Error: changes must be a JSON object"
    return _json({"routine": routines.update_routine(routine_id, payload)})


def channel_delete_routine(routine_id: str, channel_id: str = "") -> str:
    channel_id = _channel_id(channel_id)
    from palimind.agents import routines

    routine = routines.get_routine(routine_id)
    if routine is None or str(routine.get("channel_id") or "") != channel_id:
        return "Error: routine not found"
    return _json({"deleted": routines.delete_routine(routine_id)})


TOOLS: dict[str, dict[str, Any]] = {
    "channel_history": {
        "fn": channel_history,
        "description": "Read the current channel's metadata and recent messages.",
        "parameters": {
            "channel_id": {"type": "string", "required": False},
            "limit": {"type": "integer", "required": False},
        },
        "tier": 1,
        "requires_approval": False,
    },
    "channel_assign_task": {
        "fn": channel_assign_task,
        "description": "Assign a child task in the current channel.",
        "parameters": {
            "request": {"type": "string"},
            "agent_id": {"type": "string", "required": False},
            "parent_task_id": {"type": "string", "required": False},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "channel_transfer_task": {
        "fn": channel_transfer_task,
        "description": "Transfer a channel task to another member.",
        "parameters": {
            "task_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "channel_report_result": {
        "fn": channel_report_result,
        "description": "Report the owner's result for a channel task.",
        "parameters": {
            "task_id": {"type": "string"},
            "result": {"type": "string"},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": False,
    },
    "channel_add_member": {
        "fn": channel_add_member,
        "description": "Add an agent to the current channel.",
        "parameters": {
            "agent_id": {"type": "string"},
            "role": {"type": "string", "required": False},
            "instructions": {"type": "string", "required": False},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "channel_remove_member": {
        "fn": channel_remove_member,
        "description": "Remove another agent from the current channel.",
        "parameters": {
            "agent_id": {"type": "string"},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "channel_set_instructions": {
        "fn": channel_set_instructions,
        "description": "Set this agent's own instructions in the current channel.",
        "parameters": {
            "agent_id": {"type": "string"},
            "instructions": {"type": "string"},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "channel_list_routines": {
        "fn": channel_list_routines,
        "description": "List the current channel's routines.",
        "parameters": {"channel_id": {"type": "string", "required": False}},
        "tier": 1,
        "requires_approval": False,
    },
    "channel_create_routine": {
        "fn": channel_create_routine,
        "description": "Create a routine owned by the current channel.",
        "parameters": {
            "name": {"type": "string"},
            "instruction": {"type": "string"},
            "schedule": {"type": "string", "required": False},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "channel_update_routine": {
        "fn": channel_update_routine,
        "description": "Update a routine of the current channel with a JSON object.",
        "parameters": {
            "routine_id": {"type": "string"},
            "changes": {"type": "string", "required": False},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "channel_delete_routine": {
        "fn": channel_delete_routine,
        "description": "Delete a routine of the current channel.",
        "parameters": {
            "routine_id": {"type": "string"},
            "channel_id": {"type": "string", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
}
