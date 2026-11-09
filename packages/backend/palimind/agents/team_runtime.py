"""Team run coordinator.

Three modes:

* ``manager``  — one manager delegates to teammates via ``ask_agent`` and
  writes the final synthesis. Weak local models that never delegate fall back
  to a deterministic roundtable.
* ``roundtable`` — members work in parallel, then a synthesis pass combines
  their results.
* ``chain`` — members run in order, each receiving the previous result.

All modes append durable messages to the team thread and a run record under
``team:<team_id>`` so the UI can show history after a restart.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from palimind.agents import activity, blackboard, teams
from palimind.agents.catalog import AgentDefinition
from palimind.agents.runtime import (
    AgentBusyError,
    record_run,
    register_running,
    unregister_running,
)
from palimind.agents.team_chat import append_message
from palimind.agents.team_tools import delegation_count, reset_delegations

TEAM_TOOLS = ["ask_agent", "post_to_team", "read_team_notes"]

TEAM_PROMPT_V2 = """You are working as part of a team.
Plan -> act -> verify -> deliver. Use tools instead of guessing.
When another teammate is better suited, delegate with ask_agent(agent, task, context).
Write deliverables to your workspace when the task asks for a file.
Finish with FINAL_ANSWER containing the complete result."""


class TeamRunHandle:
    def __init__(self, team_id: str, run_id: str) -> None:
        self.team_id = team_id
        self.run_id = run_id
        self.tasks: set[asyncio.Task] = set()
        self.cancelled = False

    def add(self, task: asyncio.Task | None) -> None:
        if task is not None:
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    def cancel(self) -> int:
        self.cancelled = True
        count = 0
        for task in list(self.tasks):
            task.cancel()
            count += 1
        return count


_handles: dict[str, TeamRunHandle] = {}


def cancel_team(team_id: str) -> int:
    handle = _handles.get(team_id)
    if handle is None:
        return 0
    count = handle.cancel()
    append_message(
        team_id,
        "system",
        "[Team run cancelled]",
        author="system",
        run_id=handle.run_id,
        meta={"status": "cancelled"},
    )
    return count


def is_team_running(team_id: str) -> bool:
    return team_id in _handles


def _resolve_model(definition: AgentDefinition, working_root: Path | None) -> tuple[str, str]:
    from palimind.agents.runtime import _field_models

    chat_model, ollama_url, _light = _field_models(working_root)
    model = definition.model or chat_model or "llama3"
    try:
        from palimind.opencode.router import resolve_model_url

        ollama_url = resolve_model_url(model, ollama_url)
    except Exception:
        pass
    return model, ollama_url


def _synthesis_prompt(team: dict[str, Any], input: str, results: list[dict[str, Any]]) -> str:
    chunks = []
    for result in results:
        name = result.get("name") or "Teammate"
        role = result.get("role") or ""
        chunks.append(f"--- {name} ({role}) ---\n{result.get('output', '')}")
    return (
        f"Team task:\n{input}\n\n"
        "Combine the teammates' work below into one complete, well-organised "
        "final answer. Resolve overlap, keep the strongest evidence, and do not "
        "mention the internal handoffs.\n\n" + "\n\n".join(chunks)
    )


async def _synthesize(
    team: dict[str, Any],
    input: str,
    results: list[dict[str, Any]],
    working_root: Path | None,
) -> str:
    manager = teams.manager_of(team)
    defn = manager.get("agent") if manager else None
    if defn is None or not results:
        return "\n\n".join(str(r.get("output", "")) for r in results).strip()

    model, ollama_url = _resolve_model(defn, working_root)
    from palimind.llm.mixture_of_expert.llm import llm_chat_safe

    prompt = _synthesis_prompt(team, input, results)
    try:
        response = await asyncio.to_thread(
            llm_chat_safe,
            [
                {
                    "role": "system",
                    "content": "You are the team manager. Produce the final combined answer.",
                },
                {"role": "user", "content": prompt},
            ],
            model,
            ollama_url,
            temperature=0.2,
            error_prefix="[team synthesis",
        )
        text = str(response.get("content") or "").strip()
        if text and not text.startswith("[team synthesis"):
            return text
    except Exception as exc:  # noqa: BLE001 - fall back to concatenation
        print(f"[teams] synthesis failed: {exc}")
    return "\n\n".join(str(r.get("output", "")) for r in results).strip()


def _team_prompt(team: dict[str, Any], manager: bool) -> str:
    registry = _registry()
    lines = [f"[TEAM: {team.get('display_name') or team.get('name')}]"]
    if manager:
        lines.append(
            "You are the manager. Delegate work to your teammates instead of "
            "doing everything yourself."
        )
    lines.append("Teammates:")
    for member in team.get("members") or []:
        defn = registry.get_by_id(str(member.get("agent_id")))
        if defn is None:
            continue
        tools = ", ".join(defn.tools[:6]) or "no extra tools"
        role = member.get("role") or defn.title or "Specialist"
        lines.append(f"- {defn.label} ({role}) — tools: {tools}")
    charter = str(team.get("charter") or "").strip()
    if charter:
        lines.append(f"Charter: {charter}")
    notes = blackboard.render(str(team.get("id")))
    if notes:
        lines.append(notes.strip())
    if manager:
        lines.append(
            "Use ask_agent(agent, task, context) to delegate. Post short updates "
            "with post_to_team. Finish with FINAL_ANSWER containing the combined result."
        )
    lines.append(TEAM_PROMPT_V2)
    return "\n".join(lines)


def _registry():
    from palimind.agents.registry import get_registry

    return get_registry()


async def _run_member(
    team: dict[str, Any],
    member: dict[str, Any],
    task: str,
    *,
    run_id: str,
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    working_root: Path | None,
    previous: str = "",
    interactive: bool = True,
) -> dict[str, Any]:
    defn: AgentDefinition | None = member.get("agent")
    if defn is None:
        defn = _registry().get_by_id(str(member.get("agent_id")))
    if defn is None:
        return {
            "agent_id": member.get("agent_id"),
            "name": "Unknown",
            "output": "",
            "status": "error",
        }

    name = defn.label
    role = str(member.get("role") or defn.title or "")
    await emit(
        {
            "type": "team:member_started",
            "agent_id": defn.id,
            "name": name,
            "task": task[:500],
        }
    )
    handoff = append_message(
        team["id"],
        "handoff",
        task,
        author="system",
        run_id=run_id,
        meta={"to": f"agent:{defn.id}", "status": "working"},
    )
    await emit({"type": "team:message", "message": handoff})

    async def member_emit(etype: str, payload: dict[str, Any]) -> None:
        if etype == "agent:tool_call":
            blackboard.post(
                team["id"],
                author=name,
                label=f"Tool: {payload.get('tool')}",
                content=str(payload.get("args") or ""),
                kind="tool",
            )
        await emit({"type": etype, "agent_id": defn.id, "name": name, **payload})

    prompt = f"{_team_prompt(team, manager=False)}\n\nYour role: {role or 'Specialist'}"
    if previous:
        prompt += f"\n\n[PREVIOUS STEP]\n{previous[:8000]}"

    started = time.time()
    try:
        from palimind.agents.runtime import run_with_definition

        output = await run_with_definition(
            defn,
            task,
            session_id=f"team:{team['id']}:{run_id}",
            emit=member_emit,
            calling_root=working_root,
            interactive=interactive,
            team_context={
                "team_id": team["id"],
                "team_run_id": run_id,
                "team_emit": emit,
                "team_loop": asyncio.get_running_loop(),
                "delegate_depth": 1,
            },
            extra_tools=TEAM_TOOLS,
            extra_prompt=prompt,
        )
        status = "ok"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        output = f"[{name} failed] {exc}"
        status = "error"

    result_message = append_message(
        team["id"],
        "result",
        output,
        author=f"agent:{defn.id}",
        run_id=run_id,
        meta={
            "from": f"agent:{defn.id}",
            "status": status,
            "duration": round(time.time() - started, 2),
        },
    )
    await emit({"type": "team:message", "message": result_message})
    entry = blackboard.post(
        team["id"], author=name, label=f"Result ({status})", content=output[:4000], kind="result"
    )
    await emit({"type": "team:notes", "entry": entry})
    await emit(
        {
            "type": "team:member_result",
            "agent_id": defn.id,
            "name": name,
            "output": output,
            "status": status,
        }
    )
    return {"agent_id": defn.id, "name": name, "role": role, "output": output, "status": status}


async def _roundtable(
    team: dict[str, Any],
    input_text: str,
    *,
    run_id: str,
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    working_root: Path | None,
    interactive: bool = True,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(max(1, min(int(team.get("max_concurrency", 3) or 3), 4)))

    async def one(member: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            role = str(member.get("role") or "")
            task = (
                f"Team task:\n{input_text}\n\nYour role: {role or 'Specialist'}.\n"
                "Work on the part you can do best and produce a concrete result."
            )
            return await _run_member(
                team,
                member,
                task,
                run_id=run_id,
                emit=emit,
                working_root=working_root,
                interactive=interactive,
            )

    return list(await asyncio.gather(*(one(m) for m in team.get("members") or [])))


async def _chain(
    team: dict[str, Any],
    input_text: str,
    *,
    run_id: str,
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    working_root: Path | None,
    interactive: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    previous = ""
    for member in team.get("members") or []:
        role = str(member.get("role") or "")
        task = (
            f"Team task:\n{input_text}\n\nYour role: {role or 'Specialist'}.\n"
            "Continue from the previous step and improve the result."
        )
        result = await _run_member(
            team,
            member,
            task,
            run_id=run_id,
            emit=emit,
            working_root=working_root,
            previous=previous,
            interactive=interactive,
        )
        results.append(result)
        previous = str(result.get("output") or "")
    return results


async def _manager_run(
    team: dict[str, Any],
    input_text: str,
    *,
    run_id: str,
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    working_root: Path | None,
    interactive: bool = True,
) -> tuple[str, int]:
    manager = teams.manager_of(team)
    if manager is None or manager.get("agent") is None:
        return "", 0
    defn: AgentDefinition = manager["agent"]
    role = str(manager.get("role") or defn.title or "Manager")
    mgr_defn = replace(
        defn,
        tools=list(dict.fromkeys([*defn.tools, *TEAM_TOOLS])),
        tool_pack=defn.tool_pack,
    )
    await emit(
        {
            "type": "team:member_started",
            "agent_id": defn.id,
            "name": defn.label,
            "task": input_text[:500],
            "manager": True,
        }
    )

    async def manager_emit(etype: str, payload: dict[str, Any]) -> None:
        await emit(
            {"type": etype, "agent_id": defn.id, "name": defn.label, "manager": True, **payload}
        )

    prompt = _team_prompt(team, manager=True) + f"\n\nYour role: {role}"
    from palimind.agents.runtime import run_with_definition

    output = await run_with_definition(
        mgr_defn,
        input_text,
        session_id=f"team:{team['id']}:{run_id}",
        emit=manager_emit,
        calling_root=working_root,
        interactive=interactive,
        team_context={
            "team_id": team["id"],
            "team_run_id": run_id,
            "team_emit": emit,
            "team_loop": asyncio.get_running_loop(),
            "delegate_depth": 0,
        },
        extra_prompt=prompt,
    )
    return output, delegation_count(run_id)


async def run_team(
    team: dict[str, Any],
    input: str,
    *,
    mode: str | None = None,
    emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    interactive: bool = True,
    working_root: Path | None = None,
    post_user_message: bool = True,
) -> dict[str, Any]:
    """Run a team and return the persisted run payload."""
    team_id = str(team.get("id"))
    members = team.get("members") or []
    if not members:
        return {"run_id": "", "status": "error", "error": "Team has no members", "output": ""}

    run_mode = mode or str(team.get("mode") or "manager")
    if run_mode not in ("manager", "roundtable", "chain"):
        run_mode = "manager"

    run_id = str(uuid.uuid4())
    try:
        await register_running(f"team:{team_id}", run_id, 1)
    except AgentBusyError:
        # A second concurrent run would overwrite the first run's handle (so
        # Stop no longer reaches it) and clear the live state of the other.
        error = "Team is already running. Wait for it to finish or cancel it."
        if emit is not None:
            try:
                await emit({"type": "team:error", "text": error})
            except Exception:  # noqa: BLE001
                pass
        return {"run_id": "", "status": "error", "error": error, "output": ""}
    handle = TeamRunHandle(team_id, run_id)
    _handles[team_id] = handle
    handle.add(asyncio.current_task())

    emitted: list[dict[str, Any]] = []

    async def send(payload: dict[str, Any]) -> None:
        emitted.append(payload)
        if emit is not None:
            try:
                await emit(payload)
            except Exception as exc:  # noqa: BLE001
                print(f"[teams] stream emit failed: {exc}")

    async def send_message(
        role: str, content: str, author: str = "system", meta: dict | None = None
    ) -> None:
        message = append_message(
            team_id, role, content, author=author, run_id=run_id, meta=meta or {}
        )
        await send({"type": "team:message", "message": message})

    status = "success"
    output = ""
    error = ""
    started = time.time()

    activity.start(
        f"team:{team_id}",
        str(team.get("display_name") or team.get("name") or "Team"),
        run_id,
        f"team:{run_id}",
    )
    reset_delegations(run_id)

    try:
        await send(
            {
                "type": "team:started",
                "team_id": team_id,
                "run_id": run_id,
                "mode": run_mode,
                "members": [
                    {
                        "id": str(m.get("agent_id")),
                        "name": _member_name(m),
                        "role": str(m.get("role") or ""),
                        "manager": bool(m.get("manager")),
                    }
                    for m in members
                ],
            }
        )
        if post_user_message:
            await send_message("user", input, author="user")

        results: list[dict[str, Any]] = []
        if run_mode == "manager":
            output, delegations = await _manager_run(
                team,
                input,
                run_id=run_id,
                emit=send,
                working_root=working_root,
                interactive=interactive,
            )
            if delegations == 0:
                # Weak local model never delegated — fall back so the team still
                # produces a real multi-agent result.
                await send_message(
                    "system",
                    "The manager did not delegate; running a roundtable fallback.",
                    author="system",
                )
                results = await _roundtable(
                    team,
                    input,
                    run_id=run_id,
                    emit=send,
                    working_root=working_root,
                    interactive=interactive,
                )
                output = await _synthesize(team, input, results, working_root)
        elif run_mode == "roundtable":
            results = await _roundtable(
                team,
                input,
                run_id=run_id,
                emit=send,
                working_root=working_root,
                interactive=interactive,
            )
            output = await _synthesize(team, input, results, working_root)
        else:
            results = await _chain(
                team,
                input,
                run_id=run_id,
                emit=send,
                working_root=working_root,
                interactive=interactive,
            )
            output = str(results[-1].get("output") or "") if results else ""

        if not str(output or "").strip():
            output = (
                "\n\n".join(str(r.get("output", "")) for r in results).strip()
                or "[Team run finished without output]"
            )

        await send_message(
            "synthesis",
            output,
            author="system",
            meta={"manager": team.get("manager_agent_id"), "mode": run_mode},
        )
        await send({"type": "team:synthesis", "text": output})
    except asyncio.CancelledError:
        status = "cancelled"
        output = "[Team run cancelled]"
        if not handle.cancelled:
            handle.cancelled = True
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = str(exc)
        output = f"[Team run error] {exc}"
        try:
            await send({"type": "team:error", "text": error})
        except Exception:
            pass
    finally:
        try:
            await unregister_running(f"team:{team_id}", run_id)
        except Exception:
            pass
        activity.finish(f"team:{team_id}", status, output, run_id=run_id)
        if _handles.get(team_id) is handle:
            _handles.pop(team_id, None)
        try:
            await asyncio.to_thread(
                record_run,
                f"team:{team_id}",
                run_id,
                input,
                output,
                status,
                time.time() - started,
                usage={},
                trace=[],
            )
        except Exception as exc:
            print(f"[teams] failed to record team run: {exc}")
        try:
            from palimind.agents import goals

            goals.notify(
                "team_run",
                f"{team.get('display_name') or team.get('name')} finished with status {status}.",
                {"team_id": team_id, "run_id": run_id, "status": status},
            )
        except Exception:
            pass

    await send(
        {
            "type": "team:completed",
            "run_id": run_id,
            "output": output,
            "status": status,
            "error": error,
            "usage": {},
        }
    )
    reset_delegations(run_id)
    return {
        "run_id": run_id,
        "team_id": team_id,
        "mode": run_mode,
        "input": input,
        "output": output,
        "status": status,
        "error": error,
        "started_at": started,
        "finished_at": time.time(),
    }


def _member_name(member: dict[str, Any]) -> str:
    defn = member.get("agent")
    if defn is not None:
        return str(getattr(defn, "label", getattr(defn, "name", "Agent")))
    found = _registry().get_by_id(str(member.get("agent_id")))
    return str(found.label) if found else "Agent"
