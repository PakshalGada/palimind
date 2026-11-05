"""Task board endpoints."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request

from palimind.storage import task_store as board_store

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def get_tasks():
    return {"tasks": await asyncio.to_thread(board_store.list_tasks)}


@router.post("")
async def create_task_endpoint(req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    return {"task": await asyncio.to_thread(board_store.create_task, data)}


@router.patch("/{task_id}")
async def update_task_endpoint(task_id: str, req: Request):
    try:
        changes = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    task = await asyncio.to_thread(board_store.update_task, task_id, changes)
    return {"task": task} if task is not None else {"error": "Task not found"}


@router.delete("/{task_id}")
async def delete_task_endpoint(task_id: str):
    ok = await asyncio.to_thread(board_store.delete_task, task_id)
    return {"status": "success" if ok else "not_found"}


@router.post("/{task_id}/run")
async def run_task_endpoint(task_id: str):
    """Assign the task to its agent, run it, and store the result."""
    from palimind import api_server as server
    from palimind.agents.registry import get_registry

    task = await asyncio.to_thread(board_store.get_task, task_id)
    if task is None:
        return {"error": "Task not found"}
    agent_id = str(task.get("agent_id") or "")
    if not agent_id:
        return {"error": "Task has no agent assigned"}
    defn = await asyncio.to_thread(get_registry().get_by_id, agent_id)
    if defn is None:
        return {"error": "Assigned agent not found"}
    prompt = str(
        task.get("prompt") or task.get("description") or task.get("title") or "Run your task."
    )
    started = time.time()
    await asyncio.to_thread(
        board_store.update_task,
        task_id,
        {
            "status": "in_progress",
            "started_at": started,
            "agent_name": defn.name,
            "_actor": "system",
        },
    )
    try:
        output = await server._run_agent_and_record(agent_id, prompt, f"_task:{task_id}")
    except Exception as exc:
        failed = await asyncio.to_thread(
            board_store.update_task,
            task_id,
            {
                "status": "failed",
                "output": str(exc),
                "completed_at": time.time(),
                "_actor": "system",
            },
        )
        return {"task": failed, "error": str(exc)}
    completed = time.time()
    updated = await asyncio.to_thread(
        board_store.update_task,
        task_id,
        {
            "status": "completed",
            "output": output,
            "completed_at": completed,
            "duration": int(completed - started),
            "progress": 100,
            "agent_name": defn.name,
            "_actor": "system",
        },
    )
    return {"task": updated, "output": output}
