"""Agent tools for tasks, mailbox, profiles and sections.

These tools are thin adapters over :mod:`palimind.agents.tasks`,
:mod:`palimind.agents.mailbox`, :mod:`palimind.agents.threads` and the agent
catalog.  They never run a model directly.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from palimind.agents import mailbox, sections, tasks, threads


def _ctx() -> dict[str, Any]:
    from palimind.llm.mixture_of_expert.tools import _get_context

    return _get_context()


def _caller_id() -> str:
    return str(_ctx().get("agent_id") or "")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _resolve_agent(ref: str) -> Any:
    from palimind.agents.registry import get_registry

    registry = get_registry()
    return registry.get_by_id(ref) or registry.get(ref)


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # The tool sandbox normally runs in its own thread; if a loop exists, run
    # the coroutine on a private loop so the tool stays synchronous.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def start_task(task: str, context: str = "") -> str:
    caller = _caller_id()
    if not caller:
        return "Error: start_task needs a calling agent"
    from palimind.agents.registry import get_registry

    defn = get_registry().get_by_id(caller)
    if defn is None:
        return f"Error: agent not found: {caller}"
    ok, reason = tasks.can_start_task(caller, defn)
    if not ok:
        return f"Error: {reason}"
    title = (task or "Task").strip().splitlines()[0][:120]
    task_input = task if not context else f"{task}\n\nContext:\n{context}"
    record = tasks.create_task(caller, title, input_text=task_input)
    delivery = mailbox.send(
        caller,
        task_input,
        sender_kind="agent",
        sender_id=caller,
        task_id=record["id"],
        target_thread_id=record.get("thread_id") or "",
        expects_reply=True,
    )
    from palimind.agents import queue

    try:
        queue.enqueue(
            "task",
            record["id"],
            task_input,
            lane=f"task:{record['id']}",
            task_id=record["id"],
            idempotency_key=f"task:{record['id']}",
            metadata={"delivery_id": delivery["id"]},
        )
    except Exception as exc:  # noqa: BLE001
        tasks.fail_task(record["id"], str(exc))
        mailbox.fail(delivery["id"], str(exc))
        return f"Error: could not queue task: {exc}"
    return _json({"task": record, "delivery_id": delivery["id"]})


def send_message(
    agent: str,
    text: str,
    task_id: str = "",
    expects_reply: bool = False,
) -> str:
    caller = _caller_id()
    target = _resolve_agent(str(agent or ""))
    if target is None:
        return f"Error: agent not found: {agent}"
    if task_id:
        task = tasks.get_task(task_id)
        if task is None:
            return f"Error: task not found: {task_id}"
        if str(task.get("agent_id")) != target.id:
            return "Error: task does not belong to that agent"
    delivery = mailbox.send(
        target.id,
        text,
        sender_kind="agent" if caller else "user",
        sender_id=caller,
        task_id=task_id,
        expects_reply=bool(expects_reply),
        idempotency_key=str((_ctx().get("run_id") or "") and f"{_ctx().get('run_id')}:{target.id}:{task_id}:{text[:32]}"),
    )
    from palimind.agents import queue

    try:
        if task_id:
            queue.enqueue(
                "task",
                task_id,
                text,
                lane=f"task:{task_id}",
                task_id=task_id,
                metadata={"delivery_id": delivery["id"]},
            )
        else:
            queue.enqueue(
                "agent",
                target.id,
                text,
                lane="chat",
                metadata={"delivery_id": delivery["id"]},
            )
    except Exception as exc:  # noqa: BLE001 - the delivery is still visible
        return _json({"delivery": delivery, "queued": False, "warning": str(exc)})
    return _json({"delivery": delivery, "queued": True})


def interrupt_agent(agent: str, reason: str = "") -> str:
    caller = _caller_id()
    target = _resolve_agent(str(agent or ""))
    if target is None:
        return f"Error: agent not found: {agent}"
    if caller and target.id == caller:
        return "Error: an agent cannot interrupt itself"
    if _ctx().get("team_id") or _ctx().get("team_run_id"):
        return "Error: an agent cannot interrupt work from a team turn"
    from palimind.agents.runtime import cancel_agent

    cancelled = cancel_agent(target.id)
    for delivery in mailbox.list_deliveries(target.id, status="queued", limit=100):
        if str((delivery.get("metadata") or {}).get("sender_id") or "") == caller:
            mailbox.cancel(delivery["id"])
    return _json({"agent_id": target.id, "cancelled_runs": cancelled, "reason": reason})


def list_agents() -> str:
    from palimind.agents import queue
    from palimind.agents.registry import get_registry
    from palimind.agents.runtime import running_count

    out = []
    for defn in get_registry().all():
        if getattr(defn, "hidden_at", ""):
            continue
        out.append(
            {
                "id": defn.id,
                "name": defn.label,
                "title": defn.title,
                "description": defn.description,
                "provider": defn.provider,
                "model": defn.model,
                "status": "working" if running_count(defn.id) else "idle",
                "running": running_count(defn.id),
                "open_tasks": tasks.open_task_count(defn.id),
                "queued_messages": len(queue.list_queue("agent", defn.id, limit=100)),
                "hidden": bool(defn.hidden_at),
                "enabled": defn.enabled,
            }
        )
    return _json({"agents": out})


def read_agent(agent: str = "") -> str:
    caller = _caller_id()
    target = _resolve_agent(str(agent or caller))
    if target is None:
        return f"Error: agent not found: {agent}"
    from palimind.agents import routines
    from palimind.agents.runtime import get_run_history

    data = target.to_dict()
    for secret in ("webhook_token",):
        data.pop(secret, None)
    data["tasks"] = tasks.list_tasks(target.id, limit=20)
    data["routines"] = [
        r for r in routines.list_routines(limit=200) if str(r.get("agent_id") or "") == target.id
    ]
    data["recent_runs"] = get_run_history(target.id, limit=5)
    return _json(data)


def list_models() -> str:
    from palimind.agents.providers import get_provider_registry

    registry = get_provider_registry()
    models = _run_async(registry.models())
    return _json(
        {
            "providers": registry.status(),
            "models": [model.as_dict() for model in models],
        }
    )


def create_agent(
    name: str,
    title: str = "",
    instructions: str = "",
    provider: str = "",
    model: str = "",
    effort: str = "auto",
) -> str:
    caller = _caller_id()
    from palimind.agents.catalog import AgentDefinition
    from palimind.agents.registry import get_registry

    caller_def = get_registry().get_by_id(caller) if caller else None
    try:
        defn = AgentDefinition.new(
            name,
            display_name=title or name,
            title=title,
            system_prompt=instructions or "",
            provider=provider or (caller_def.provider if caller_def else "ollama"),
            model=model or (caller_def.model if caller_def else ""),
            reasoning_effort=effort or "auto",
            autonomy_level=caller_def.autonomy_level if caller_def else "semi",
            memory_mode=caller_def.memory_mode if caller_def else "private",
            write_access=bool(caller_def.write_access) if caller_def else False,
            shell_access=bool(caller_def.shell_access) if caller_def else False,
            desktop_access=bool(caller_def.desktop_access) if caller_def else False,
            desktop_control=bool(caller_def.desktop_control) if caller_def else False,
            task_limit=caller_def.task_limit if caller_def else 2,
        )
        saved = get_registry().create(defn)
        threads.ensure_chat_thread(saved.id)
        return _json({"agent": saved.to_dict()})
    except Exception as exc:  # noqa: BLE001
        return f"Error: could not create agent: {exc}"


def update_profile(
    agent: str = "",
    display_name: str = "",
    title: str = "",
    description: str = "",
    system_prompt: str = "",
    provider: str = "",
    model: str = "",
    reasoning_effort: str = "",
    task_limit: int | None = None,
    busy_message_mode: str = "",
    browser_profile: str = "",
    section_id: str = "",
    write_access: bool | None = None,
    shell_access: bool | None = None,
    desktop_access: bool | None = None,
    desktop_control: bool | None = None,
) -> str:
    caller = _caller_id()
    target = _resolve_agent(str(agent or caller))
    if target is None:
        return f"Error: agent not found: {agent}"
    changes: dict[str, Any] = {}
    for key, value in (
        ("display_name", display_name),
        ("title", title),
        ("description", description),
        ("system_prompt", system_prompt),
        ("provider", provider),
        ("model", model),
        ("reasoning_effort", reasoning_effort),
        ("busy_message_mode", busy_message_mode),
        ("browser_profile", browser_profile),
        ("section_id", section_id),
    ):
        if value:
            changes[key] = value
    if task_limit is not None:
        changes["task_limit"] = max(1, min(int(task_limit), 8))
    for key, flag in (
        ("write_access", write_access),
        ("shell_access", shell_access),
        ("desktop_access", desktop_access),
        ("desktop_control", desktop_control),
    ):
        if flag is not None:
            # An agent may restrict itself or a teammate, never widen access.
            if flag and not bool(getattr(target, key, False)):
                return f"Error: an agent may not widen {key}; the user must do that"
            changes[key] = bool(flag)
    try:
        from palimind.agents.registry import get_registry

        saved = get_registry().update(target.id, changes)
        return _json({"agent": saved.to_dict()})
    except Exception as exc:  # noqa: BLE001
        return f"Error: could not update profile: {exc}"


def update_agents(
    agent_ids: str = "",
    provider: str = "",
    model: str = "",
    reasoning_effort: str = "",
    write_access: bool | None = None,
    shell_access: bool | None = None,
    desktop_access: bool | None = None,
    desktop_control: bool | None = None,
) -> str:
    ids = [part.strip() for part in str(agent_ids or "").split(",") if part.strip()]
    results = []
    for agent_id in ids:
        results.append(
            {
                "agent_id": agent_id,
                "result": update_profile(
                    agent=agent_id,
                    provider=provider,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    write_access=write_access,
                    shell_access=shell_access,
                    desktop_access=desktop_access,
                    desktop_control=desktop_control,
                ),
            }
        )
    return _json({"results": results})


def start_new_chat(agent: str = "") -> str:
    caller = _caller_id()
    target = _resolve_agent(str(agent or caller))
    if target is None:
        return f"Error: agent not found: {agent}"
    thread = threads.ensure_chat_thread(target.id)
    threads.reset_thread(thread["id"], reason=f"new-chat:{caller or 'user'}")
    return _json({"agent_id": target.id, "thread_id": thread["id"], "status": "reset"})


def react_to_user_message(message_id: str, emoji: str) -> str:
    caller = _caller_id()
    return _json(mailbox.react(message_id, emoji, actor_kind="agent", actor_id=caller))


def attach_files_to_response(paths: str) -> str:
    workspace = _ctx().get("root")
    attachments = []
    root = Path(workspace).resolve() if workspace else None
    for raw in str(paths or "").splitlines():
        candidate = Path(raw.strip()).expanduser()
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if root is not None and root not in resolved.parents and resolved != root:
            continue
        attachments.append({"name": resolved.name, "path": str(resolved), "size": resolved.stat().st_size})
    return _json({"attachments": attachments})


def list_sections() -> str:
    return _json({"sections": sections.list_sections()})


def create_section(name: str, sort_order: int = 0) -> str:
    try:
        return _json({"section": sections.create_section(name, sort_order=sort_order)})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def rename_section(section_id: str, name: str) -> str:
    try:
        return _json({"section": sections.rename_section(section_id, name)})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


def delete_section(section_id: str) -> str:
    return _json({"deleted": sections.delete_section(section_id)})


def assign_agent_section(agent: str, section_id: str = "") -> str:
    try:
        saved = sections.assign_agent_section(agent, section_id)
        return _json({"agent": saved.to_dict()})
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


_TOOL_ARGS: dict[str, dict[str, Any]] = {
    "task": {"type": "string", "description": "The task to run in a separate lane."},
    "context": {"type": "string", "description": "Optional background for the task."},
}


TOOLS: dict[str, dict[str, Any]] = {
    "start_task": {
        "fn": start_task,
        "description": "Start a separate task lane for this agent and return its id.",
        "parameters": _TOOL_ARGS,
        "tier": 1,
        "requires_approval": False,
    },
    "send_message": {
        "fn": send_message,
        "description": "Send a durable message to another agent, optionally inside one of its tasks.",
        "parameters": {
            "agent": {"type": "string", "description": "Agent name or id."},
            "text": {"type": "string", "description": "Message text."},
            "task_id": {"type": "string", "description": "Optional task id.", "required": False},
            "expects_reply": {"type": "boolean", "description": "Wait for a reply conceptually.", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "interrupt_agent": {
        "fn": interrupt_agent,
        "description": "Interrupt this caller's work on another agent.",
        "parameters": {
            "agent": {"type": "string", "description": "Agent name or id."},
            "reason": {"type": "string", "description": "Why the work stops.", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "list_agents_compact": {
        "fn": list_agents,
        "description": "List agents with status, task counts and queued messages.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
    },
    "read_agent": {
        "fn": read_agent,
        "description": "Read one agent's profile, tasks, routines and recent runs (never secrets).",
        "parameters": {"agent": {"type": "string", "description": "Agent name or id.", "required": False}},
        "tier": 1,
        "requires_approval": False,
    },
    "list_models": {
        "fn": list_models,
        "description": "List providers and models with their capabilities.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
    },
    "create_agent": {
        "fn": create_agent,
        "description": "Create a persistent teammate with a profile and instructions.",
        "parameters": {
            "name": {"type": "string", "description": "Handle (letters, digits, dash, underscore)."},
            "title": {"type": "string", "description": "Display title.", "required": False},
            "instructions": {"type": "string", "description": "System instructions.", "required": False},
            "provider": {"type": "string", "description": "Provider id.", "required": False},
            "model": {"type": "string", "description": "Model id.", "required": False},
            "effort": {"type": "string", "description": "Reasoning effort.", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "update_profile": {
        "fn": update_profile,
        "description": "Update an agent profile. An agent may restrict access, never widen it.",
        "parameters": {
            "agent": {"type": "string", "description": "Agent name or id.", "required": False},
            "display_name": {"type": "string", "required": False},
            "title": {"type": "string", "required": False},
            "description": {"type": "string", "required": False},
            "system_prompt": {"type": "string", "required": False},
            "provider": {"type": "string", "required": False},
            "model": {"type": "string", "required": False},
            "reasoning_effort": {"type": "string", "required": False},
            "task_limit": {"type": "integer", "required": False},
            "busy_message_mode": {"type": "string", "enum": ["queue", "steer"], "required": False},
            "browser_profile": {"type": "string", "required": False},
            "section_id": {"type": "string", "required": False},
            "write_access": {"type": "boolean", "required": False},
            "shell_access": {"type": "boolean", "required": False},
            "desktop_access": {"type": "boolean", "required": False},
            "desktop_control": {"type": "boolean", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "update_agents": {
        "fn": update_agents,
        "description": "Apply the same provider/model/access settings to several agents.",
        "parameters": {
            "agent_ids": {"type": "string", "description": "Comma-separated ids."},
            "provider": {"type": "string", "required": False},
            "model": {"type": "string", "required": False},
            "reasoning_effort": {"type": "string", "required": False},
            "write_access": {"type": "boolean", "required": False},
            "shell_access": {"type": "boolean", "required": False},
            "desktop_access": {"type": "boolean", "required": False},
            "desktop_control": {"type": "boolean", "required": False},
        },
        "tier": 2,
        "requires_approval": True,
    },
    "start_new_chat": {
        "fn": start_new_chat,
        "description": "Forget the current provider context while keeping messages visible.",
        "parameters": {"agent": {"type": "string", "required": False}},
        "tier": 2,
        "requires_approval": True,
    },
    "react_to_user_message": {
        "fn": react_to_user_message,
        "description": "React to a user message with one emoji.",
        "parameters": {
            "message_id": {"type": "string"},
            "emoji": {"type": "string"},
        },
        "tier": 1,
        "requires_approval": False,
    },
    "attach_files_to_response": {
        "fn": attach_files_to_response,
        "description": "Attach workspace files to the current answer.",
        "parameters": {"paths": {"type": "string", "description": "One path per line."}},
        "tier": 2,
        "requires_approval": True,
    },
    "list_sections": {
        "fn": list_sections,
        "description": "List agent sidebar sections.",
        "parameters": {},
        "tier": 1,
        "requires_approval": False,
    },
    "create_section": {
        "fn": create_section,
        "description": "Create a sidebar section.",
        "parameters": {"name": {"type": "string"}, "sort_order": {"type": "integer", "required": False}},
        "tier": 2,
        "requires_approval": True,
    },
    "rename_section": {
        "fn": rename_section,
        "description": "Rename a sidebar section.",
        "parameters": {"section_id": {"type": "string"}, "name": {"type": "string"}},
        "tier": 2,
        "requires_approval": True,
    },
    "delete_section": {
        "fn": delete_section,
        "description": "Delete a sidebar section without deleting its agents.",
        "parameters": {"section_id": {"type": "string"}},
        "tier": 2,
        "requires_approval": True,
    },
    "assign_agent_section": {
        "fn": assign_agent_section,
        "description": "Put an agent in a sidebar section, or ungroup it with an empty id.",
        "parameters": {"agent": {"type": "string"}, "section_id": {"type": "string", "required": False}},
        "tier": 2,
        "requires_approval": True,
    },
}
