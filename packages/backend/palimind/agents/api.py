from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from palimind.agents.catalog import AgentDefinition
from palimind.agents.chat import clear_chat, read_chat
from palimind.agents.registry import get_registry
from palimind.agents.runtime import (
    cancel_agent,
    clear_agent_memory,
    delete_memory_entry,
    get_last_run,
    get_run_history,
    read_memory,
    resolve_approval,
)
from palimind.agents.stream import agent_event_stream
from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY

router = APIRouter(prefix="/api/agents", tags=["agents"])

# tier 1 = read-only / safe, tier 2 = write & execute, tier 3 = privileged
TOOL_META: dict[str, dict[str, Any]] = {
    "web_search": {"tier": 1, "requires_approval": False},
    "fetch_url": {"tier": 1, "requires_approval": False},
    "document_search": {"tier": 1, "requires_approval": False},
    "memory_search": {"tier": 1, "requires_approval": False},
    "read_file": {"tier": 1, "requires_approval": False},
    "list_files": {"tier": 1, "requires_approval": False},
    "summarize": {"tier": 1, "requires_approval": False},
    "write_file": {"tier": 2, "requires_approval": True},
    "run_python": {"tier": 2, "requires_approval": True},
}


def _agent_item(defn: AgentDefinition) -> dict[str, Any]:
    from palimind.agents.runtime import is_running

    item = defn.to_dict()
    last = get_last_run(defn.id)
    item["running"] = is_running(defn.id)
    item["last_run_status"] = last.get("status") if last else None
    item["last_run_at"] = last.get("timestamp") if last else None
    return item


@router.get("")
async def list_agents():
    agents = [_agent_item(d) for d in get_registry().all()]
    return {"agents": agents}


@router.post("/create")
async def create_agent(req: Request):
    body = await req.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return {"error": "name is required"}
    try:
        defn = AgentDefinition.from_dict(body)
        saved = get_registry().create(defn)
        return _agent_item(saved)
    except Exception as e:
        return {"error": str(e)}


@router.patch("/{agent_id}")
async def update_agent(agent_id: str, req: Request):
    changes = await req.json()
    try:
        saved = get_registry().update(agent_id, changes)
        return _agent_item(saved)
    except Exception as e:
        return {"error": str(e)}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    try:
        cancel_agent(agent_id)
        get_registry().delete(agent_id)
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/tools")
async def agent_tools():
    tools: dict[str, dict[str, Any]] = {}
    for name in sorted(TOOL_REGISTRY):
        info = TOOL_REGISTRY[name]
        meta = TOOL_META.get(name, {"tier": 3, "requires_approval": True})
        tools[name] = {
            "id": name,
            "description": info.get("description", ""),
            "parameters": info.get("parameters", {}),
            **meta,
        }
    return {"tools": tools}


@router.post("/validate-cron")
async def validate_cron(req: Request):
    from palimind.agents.catalog import validate_cron as vc

    body = await req.json()
    error = vc(str(body.get("schedule", "")))
    return {"valid": error is None, "error": error}


@router.get("/{agent_id}/memory")
async def agent_memory(agent_id: str, page: int = 1, per_page: int = 20):
    entries = list(reversed(read_memory(agent_id)))  # newest first
    total = len(entries)
    per_page = max(1, min(per_page, 100))
    page = max(1, page)
    start = (page - 1) * per_page
    return {
        "entries": entries[start : start + per_page],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.delete("/{agent_id}/memory")
async def delete_agent_memory_entry(agent_id: str, index: int):
    # The frontend paginates newest-first; convert to the stored oldest-first index.
    total = len(read_memory(agent_id))
    delete_memory_entry(agent_id, total - 1 - index)
    return {"status": "success"}


@router.post("/{agent_id}/memory/clear")
async def clear_memory(agent_id: str):
    clear_agent_memory(agent_id)
    return {"status": "success"}


@router.get("/{agent_id}/history")
async def agent_history(agent_id: str, limit: int = 50):
    return {"history": list(reversed(get_run_history(agent_id, limit=limit)))}


@router.post("/{agent_id}/run")
async def run_agent(agent_id: str, req: Request):
    body = await req.json()
    agent_input = str(body.get("input", "")).strip() or "Run your task."
    session_id = str(body.get("session_id", "") or "")

    defn = get_registry().get_by_id(agent_id)
    if defn is None:

        async def err_stream():
            yield 'data: {"type": "error", "text": "Agent not found"}\n\n'
            yield 'data: {"type": "done"}\n\n'

        return StreamingResponse(err_stream(), media_type="text/event-stream")

    async def gen():
        import json

        async for ev in agent_event_stream(defn, agent_input, session_id):
            yield f"data: {json.dumps(ev)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{agent_id}/chat")
async def agent_chat(agent_id: str):
    return {"messages": read_chat(agent_id)}


@router.delete("/{agent_id}/chat")
async def delete_agent_chat(agent_id: str):
    clear_chat(agent_id)
    return {"status": "success"}


@router.post("/{agent_id}/cancel")
async def cancel(agent_id: str):
    ok = cancel_agent(agent_id)
    return {"status": "cancelled" if ok else "not_running"}


@router.post("/{agent_id}/approve")
async def approve(agent_id: str, req: Request):
    body = await req.json()
    approved = bool(body.get("approved", False))
    correction = str(body.get("correction", ""))
    ok = await resolve_approval(agent_id, approved, correction)
    return {"status": "ok" if ok else "no_pending"}
