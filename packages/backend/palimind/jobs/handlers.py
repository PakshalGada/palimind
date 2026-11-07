"""Default handlers for durable jobs.

Each handler receives the job row and returns either a string or a dict with
``status``/``output``. Imports are lazy so the job service has no dependency on
the agent stack at import time.
"""

from __future__ import annotations

import asyncio
from typing import Any


async def run_agent_job(job: dict[str, Any]) -> dict[str, Any]:
    from palimind.agents.registry import get_registry
    from palimind.agents.scheduler import post_result, recorded_run_status
    from palimind.agents.service import run_agent

    payload = job.get("payload") or {}
    agent_id = str(job.get("target") or payload.get("agent_id") or "")
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"status": "error", "output": f"Agent not found: {agent_id}"}
    input_text = str(payload.get("input") or "Run your task.")
    source = str(payload.get("source") or "job")
    session_id = str(payload.get("session_id") or f"_{source}")
    output = await run_agent(defn, input_text, session_id=session_id, interactive=False)
    status = recorded_run_status(defn.id, input_text, output)
    await post_result(defn, output, status, source)
    return {"status": status, "output": output}


async def run_team_job(job: dict[str, Any]) -> dict[str, Any]:
    from palimind.agents import teams
    from palimind.agents.team_runtime import run_team

    payload = job.get("payload") or {}
    team_id = str(job.get("target") or payload.get("team_id") or "")
    team = teams.get_team(team_id)
    if team is None:
        return {"status": "error", "output": f"Team not found: {team_id}"}
    result = await run_team(team, str(payload.get("input") or ""), interactive=False)
    status = str(result.get("status") or "success")
    return {"status": status, "output": result.get("output") or result.get("error") or ""}


async def run_queue_item(job: dict[str, Any]) -> dict[str, Any]:
    from palimind.agents import queue

    payload = job.get("payload") or {}
    item_id = str(payload.get("queue_item_id") or "")
    item = queue.get_item(item_id)
    if item is None:
        return {"status": "error", "output": f"Queue item not found: {item_id}"}
    await queue._execute(item)
    updated = queue.get_item(item_id) or {}
    status = str(updated.get("status") or "")
    return {
        "status": "success" if status == "done" else "error",
        "output": updated.get("error") or status,
        "queue_status": status,
    }


async def run_background_task(job: dict[str, Any]) -> dict[str, Any]:
    from palimind.agents import goals

    payload = job.get("payload") or {}
    task_id = str(job.get("target") or payload.get("task_id") or "")
    task = goals.get_task(task_id)
    if task is None:
        return {"status": "error", "output": f"Background task not found: {task_id}"}
    await goals._run_one(task, goals._default_run)
    updated = goals.get_task(task_id) or {}
    status = str(updated.get("last_status") or "error")
    return {
        "status": status,
        "output": updated.get("last_output") or "",
        "task_status": updated.get("status") or "",
    }


async def run_routine_job(job: dict[str, Any]) -> dict[str, Any]:
    from palimind.agents import routines
    from palimind.agents.scheduler import post_routine_notification

    payload = job.get("payload") or {}
    routine_id = str(job.get("target") or payload.get("routine_id") or "")
    routine = routines.get_routine(routine_id)
    if routine is None:
        return {"status": "error", "output": f"Routine not found: {routine_id}"}
    try:
        run_id = await routines.run_routine(routine_id, str(payload.get("payload") or ""))
        await post_routine_notification(routine, "success")
        return {"status": "success", "output": run_id}
    except Exception as exc:  # noqa: BLE001 - notification still matters
        await post_routine_notification(routine, "error", str(exc))
        return {"status": "error", "output": str(exc)}


async def run_workflow_job(job: dict[str, Any]) -> dict[str, Any]:
    from palimind.workflows import runtime as workflow_runtime

    payload = job.get("payload") or {}
    workflow_id = str(payload.get("workflow_id") or job.get("target") or "")
    if not workflow_id:
        return {"status": "error", "output": "workflow job requires a workflow_id"}
    summary = await workflow_runtime.execute_workflow(
        workflow_id,
        input_text=str(payload.get("input") or ""),
        trigger=payload.get("trigger") if isinstance(payload.get("trigger"), dict) else None,
        workspace_root=payload.get("workspace_root") or None,
    )
    outcome = str(summary.get("status") or "failed")
    status = (
        "success"
        if outcome == "completed"
        else ("cancelled" if outcome == "cancelled" else "error")
    )
    return {
        "status": status,
        "output": summary.get("error") or outcome,
        "run_id": summary.get("run_id"),
    }


async def run_index_job(job: dict[str, Any]) -> dict[str, Any]:
    from palimind.rag import incremental

    payload = job.get("payload") or {}
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        return {"status": "error", "output": "index job requires a run_id"}

    loop = asyncio.get_running_loop()

    def _on_event(event: dict[str, Any]) -> None:
        # The indexer runs in a worker thread; forward progress to the API's
        # SSE subscribers without blocking the indexing path.
        try:
            from palimind.api_server import broadcast_event

            asyncio.run_coroutine_threadsafe(broadcast_event(event), loop)
        except Exception:
            pass

    summary = await asyncio.to_thread(incremental.process_run, run_id, on_event=_on_event)
    status = (
        "success"
        if summary.get("status") == "completed"
        else ("cancelled" if summary.get("status") == "cancelled" else "error")
    )
    return {
        "status": status,
        "output": summary.get("error") or summary.get("status") or "",
        "run_id": run_id,
    }


def default_handlers() -> dict[str, Any]:
    return {
        "agent_run": run_agent_job,
        "team_run": run_team_job,
        "queued_run": run_queue_item,
        "background_task": run_background_task,
        "routine_run": run_routine_job,
        "index": run_index_job,
        "workflow": run_workflow_job,
    }
