"""HTTP surface for teams, routines, queue, overview, inbox and workspaces."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from palimind.agents import approvals, blackboard, overview, queue, routines, team_chat, teams
from palimind.agents import workspace as workspace_mod
from palimind.agents.registry import get_registry
from palimind.agents.runtime import (
    get_run,
    get_run_history,
    pause_agent,
    resume_agent,
    steer_agent,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _team_detail(team: dict[str, Any]) -> dict[str, Any]:
    registry = get_registry()
    members = []
    for member in team.get("members") or []:
        defn = registry.get_by_id(str(member.get("agent_id")))
        members.append(
            {
                **member,
                "agent": defn.to_dict() if defn else None,
                "name": defn.label if defn else "Unknown",
                "enabled": bool(defn.enabled) if defn else False,
            }
        )
    from palimind.agents import team_runtime

    return {
        **team,
        "members": members,
        "running": team_runtime.is_team_running(str(team.get("id"))),
        "pending_approvals": sum(
            1
            for p in approvals.list_pending()
            if str(p.get("agent_id")) in {str(m.get("agent_id")) for m in team.get("members") or []}
        ),
    }


# ── overview / inbox ─────────────────────────────────────────────────────


@router.get("/overview")
async def agents_overview():
    return overview.overview()


@router.get("/inbox")
async def agents_inbox():
    pending = approvals.list_pending()
    groups: dict[str, list[dict[str, Any]]] = {}
    registry = get_registry()
    for entry in pending:
        item = dict(entry)
        defn = registry.get_by_id(str(entry.get("agent_id")))
        if defn is not None:
            item["agent_name"] = defn.label
            item["agent_avatar"] = {
                "type": defn.avatar_type,
                "upload": defn.avatar_upload,
                "config": defn.avatar_config,
            }
        groups.setdefault(str(entry.get("agent_id")), []).append(item)
    return {"approvals": pending, "groups": groups}


# ── teams ────────────────────────────────────────────────────────────────


@router.get("/teams")
async def list_teams():
    items = []
    for team in teams.list_teams():
        items.append(_team_detail(team))
    return {"teams": items}


@router.post("/teams")
async def create_team(req: Request):
    body = await req.json()
    try:
        return {"team": _team_detail(teams.create_team(body))}
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to create team: {exc}"}


@router.get("/teams/{team_id}")
async def get_team(team_id: str):
    team = teams.get_team(team_id)
    if team is None:
        return {"error": "Team not found"}
    return {"team": _team_detail(team)}


@router.patch("/teams/{team_id}")
async def update_team(team_id: str, req: Request):
    body = await req.json()
    try:
        return {"team": _team_detail(teams.update_team(team_id, body))}
    except KeyError:
        return {"error": "Team not found"}
    except ValueError as exc:
        return {"error": str(exc)}


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str):
    from palimind.agents.team_runtime import cancel_team

    cancel_team(team_id)
    return {"status": "success" if teams.delete_team(team_id) else "not_found"}


@router.post("/teams/{team_id}/members")
async def add_team_member(team_id: str, req: Request):
    body = await req.json()
    try:
        team = teams.add_member(
            team_id,
            str(body.get("agent_id") or ""),
            str(body.get("role") or ""),
            bool(body.get("manager", False)),
        )
        return {"team": _team_detail(team)}
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}


@router.delete("/teams/{team_id}/members/{agent_id}")
async def remove_team_member(team_id: str, agent_id: str):
    try:
        return {"team": _team_detail(teams.remove_member(team_id, agent_id))}
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}


@router.post("/teams/{team_id}/manager")
async def set_team_manager(team_id: str, req: Request):
    body = await req.json()
    try:
        return {"team": _team_detail(teams.set_manager(team_id, str(body.get("agent_id") or "")))}
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}


@router.get("/teams/{team_id}/messages")
async def team_messages(team_id: str, limit: int = 100, before_seq: int | None = None):
    return {
        "messages": team_chat.list_messages(
            team_id, limit=max(1, min(int(limit or 100), 500)), before_seq=before_seq
        )
    }


@router.post("/teams/{team_id}/messages")
async def post_team_message(team_id: str, req: Request):
    body = await req.json()
    message = team_chat.append_message(
        team_id, "user", str(body.get("content") or ""), author="user"
    )
    return {"message": message}


@router.delete("/teams/{team_id}/messages")
async def clear_team_messages(team_id: str):
    team_chat.clear_messages(team_id)
    return {"status": "success"}


@router.post("/teams/{team_id}/run")
async def run_team_endpoint(team_id: str, req: Request):
    body = await req.json()
    input_text = str(body.get("input") or "").strip() or "Work as a team on the current task."
    mode = body.get("mode") or None
    interactive = bool(body.get("interactive", True))
    team = teams.get_team(team_id)
    if team is None:
        async def err():
            yield f"data: {json.dumps({'type': 'team:error', 'text': 'Team not found'})}\n\n"

        return StreamingResponse(err(), media_type="text/event-stream")

    from palimind.agents.team_runtime import run_team

    async def gen():
        q: asyncio.Queue = asyncio.Queue()

        async def emit(ev: dict[str, Any]) -> None:
            await q.put(ev)

        task = asyncio.create_task(
            run_team(
                team,
                input_text,
                mode=str(mode) if mode else None,
                emit=emit,
                interactive=interactive,
            )
        )
        try:
            while True:
                if task.done():
                    while not q.empty():
                        yield f"data: {json.dumps(q.get_nowait(), default=str)}\n\n"
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=0.2)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except TimeoutError:
                    continue
            try:
                await task
            except asyncio.CancelledError:
                yield f"data: {json.dumps({'type': 'team:completed', 'status': 'cancelled', 'output': '[Team run cancelled]'})}\n\n"
            except Exception as exc:  # noqa: BLE001
                yield f"data: {json.dumps({'type': 'team:error', 'text': str(exc)})}\n\n"
        finally:
            if not task.done():
                task.cancel()
            yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/teams/{team_id}/cancel")
async def cancel_team_endpoint(team_id: str):
    from palimind.agents.team_runtime import cancel_team

    return {"status": "cancelled", "cancelled": cancel_team(team_id)}


@router.post("/teams/{team_id}/pause")
async def pause_team(team_id: str):
    team = teams.get_team(team_id) or {}
    count = 0
    for member in team.get("members") or []:
        if pause_agent(str(member.get("agent_id"))):
            count += 1
    return {"status": "paused", "paused": count}


@router.post("/teams/{team_id}/resume")
async def resume_team(team_id: str):
    team = teams.get_team(team_id) or {}
    count = 0
    for member in team.get("members") or []:
        if resume_agent(str(member.get("agent_id"))):
            count += 1
    return {"status": "resumed", "resumed": count}


@router.post("/teams/{team_id}/steer")
async def steer_team(team_id: str, req: Request):
    body = await req.json()
    team = teams.get_team(team_id)
    if team is None:
        return {"error": "Team not found"}
    target = str(body.get("agent_id") or "")
    if not target:
        manager = teams.manager_of(team)
        target = str((manager or {}).get("agent_id") or "")
    ok = steer_agent(target, str(body.get("text") or ""), body.get("run_id"))
    return {"status": "ok" if ok else "not_running"}


@router.get("/teams/{team_id}/runs")
async def team_runs(team_id: str, limit: int = 30):
    history = list(reversed(get_run_history(f"team:{team_id}", limit=limit)))
    for record in history:
        record.pop("trace", None)
    return {"runs": history}


@router.get("/teams/{team_id}/runs/{run_id}")
async def team_run_detail(team_id: str, run_id: str):
    record = get_run(f"team:{team_id}", run_id)
    if record is None:
        return {"error": "run not found"}
    return record


@router.get("/teams/{team_id}/notes")
async def team_notes(team_id: str):
    return {"notes": blackboard.entries(team_id)}


@router.post("/teams/{team_id}/notes")
async def add_team_note(team_id: str, req: Request):
    body = await req.json()
    entry = blackboard.post(
        team_id,
        author=str(body.get("author") or "user"),
        label=str(body.get("label") or "Note"),
        content=str(body.get("content") or ""),
        kind=str(body.get("kind") or "note"),
    )
    return {"entry": entry}


@router.delete("/teams/{team_id}/notes")
async def clear_team_notes(team_id: str):
    blackboard.clear(team_id)
    return {"status": "success"}


# ── routines ─────────────────────────────────────────────────────────────


@router.get("/routines")
async def list_routines():
    return {"routines": routines.list_routines()}


@router.post("/routines")
async def create_routine(req: Request):
    body = await req.json()
    try:
        return {"routine": routines.create_routine(body)}
    except ValueError as exc:
        return {"error": str(exc)}


@router.patch("/routines/{routine_id}")
async def update_routine(routine_id: str, req: Request):
    body = await req.json()
    try:
        return {"routine": routines.update_routine(routine_id, body)}
    except KeyError:
        return {"error": "Routine not found"}
    except ValueError as exc:
        return {"error": str(exc)}


@router.delete("/routines/{routine_id}")
async def delete_routine(routine_id: str):
    return {"status": "success" if routines.delete_routine(routine_id) else "not_found"}


@router.post("/routines/{routine_id}/run")
async def run_routine(routine_id: str):
    """Start a routine in the background and return at once.

    The run can take minutes, so the request no longer waits for it; the
    outcome is reported through the routine's last_status and a notification
    (same as scheduled routine runs). Missing routine/target is still
    reported synchronously as ``{"error": ...}``.
    """
    routine = routines.get_routine(routine_id)
    if routine is None:
        return {"error": "Routine not found"}
    target_type = str(routine.get("target_type") or "agent")
    target_id = str(routine.get("target_id") or "")
    if target_type == "team":
        if teams.get_team(target_id) is None:
            return {"error": "Team not found"}
    elif get_registry().get_by_id(target_id) is None:
        return {"error": "Agent not found"}

    from palimind.agents.scheduler import _spawn, post_routine_notification

    async def _run() -> None:
        try:
            await routines.run_routine(routine_id)
            await post_routine_notification(routine, "success")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[agents] routine {routine_id} failed: {exc}")
            await post_routine_notification(routine, "error", str(exc))

    _spawn(_run())
    return {"status": "started"}


@router.post("/runs/{run_id}/save-as-routine")
async def save_run_as_routine(run_id: str, req: Request):
    body = await req.json()
    try:
        routine = routines.save_run_as_routine(
            run_id,
            str(body.get("target_type") or "agent"),
            str(body.get("target_id") or ""),
            str(body.get("name") or "Routine"),
            schedule=body.get("schedule"),
            run_mode=str(body.get("run_mode") or "manual"),
            tool_pack=str(body.get("tool_pack") or "auto"),
            working_root=str(body.get("working_root") or ""),
        )
        return {"routine": routine}
    except ValueError as exc:
        return {"error": str(exc)}


# ── queue ────────────────────────────────────────────────────────────────


@router.get("/queue")
async def list_queue(target_type: str | None = None, target_id: str | None = None):
    return {"items": queue.list_queue(target_type, target_id)}


@router.post("/queue")
async def enqueue(req: Request):
    body = await req.json()
    try:
        return {
            "item": queue.enqueue(
                str(body.get("target_type") or "agent"),
                str(body.get("target_id") or ""),
                str(body.get("input") or ""),
                int(body.get("priority", 0) or 0),
            )
        }
    except ValueError as exc:
        return {"error": str(exc)}


@router.patch("/queue/{item_id}")
async def update_queue_item(item_id: str, req: Request):
    body = await req.json()
    try:
        return {"item": queue.update_item(item_id, status=body.get("status"))}
    except KeyError:
        return {"error": "Queue item not found"}


@router.post("/queue/{item_id}/cancel")
async def cancel_queue_item(item_id: str):
    try:
        return {"item": queue.cancel_item(item_id)}
    except KeyError:
        return {"error": "Queue item not found"}


# ── agent workspace / controls ───────────────────────────────────────────


@router.get("/{agent_id}/workspace")
async def agent_workspace(agent_id: str, path: str = ""):
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    try:
        return {
            "files": workspace_mod.list_files(agent_id, path, str(defn.workspace_dir or "")),
            "path": path,
            "root": str(
                workspace_mod.ensure_workspace(agent_id, str(defn.workspace_dir or ""))
            ),
        }
    except ValueError as exc:
        return {"error": str(exc)}


@router.get("/{agent_id}/workspace/file")
async def agent_workspace_file(agent_id: str, path: str):
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    try:
        return workspace_mod.read_file(agent_id, path, str(defn.workspace_dir or ""))
    except (FileNotFoundError, ValueError) as exc:
        return {"error": str(exc)}


@router.delete("/{agent_id}/workspace/file")
async def delete_agent_workspace_file(agent_id: str, path: str):
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    try:
        return {"deleted": workspace_mod.delete_file(agent_id, path, str(defn.workspace_dir or ""))}
    except ValueError as exc:
        return {"error": str(exc)}


@router.post("/{agent_id}/approvals/always-allow")
async def always_allow(agent_id: str, req: Request):
    body = await req.json()
    tool = str(body.get("tool") or "")
    if not tool:
        return {"error": "tool is required"}
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    tools = list(dict.fromkeys([*defn.always_allow_tools, tool]))
    try:
        saved = get_registry().update(agent_id, {"always_allow_tools": tools})
        return {"agent": saved.to_dict()}
    except ValueError as exc:
        return {"error": str(exc)}


@router.delete("/{agent_id}/approvals/always-allow/{tool}")
async def revoke_always_allow(agent_id: str, tool: str):
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    tools = [t for t in defn.always_allow_tools if t != tool]
    try:
        saved = get_registry().update(agent_id, {"always_allow_tools": tools})
        return {"agent": saved.to_dict()}
    except ValueError as exc:
        return {"error": str(exc)}


@router.post("/{agent_id}/steer")
async def steer(agent_id: str, req: Request):
    body = await req.json()
    ok = steer_agent(agent_id, str(body.get("text") or ""), body.get("run_id"))
    return {"status": "ok" if ok else "not_running"}


@router.post("/{agent_id}/pause")
async def pause(agent_id: str):
    return {"status": "paused" if pause_agent(agent_id) else "not_running"}


@router.post("/{agent_id}/resume")
async def resume(agent_id: str):
    return {"status": "resumed" if resume_agent(agent_id) else "not_running"}
