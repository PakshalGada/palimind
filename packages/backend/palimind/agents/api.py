from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from palimind.agents import activity, approvals
from palimind.agents.catalog import AgentDefinition
from palimind.agents.chat import clear_chat, read_chat
from palimind.agents.memory import read_memory
from palimind.agents.registry import get_registry
from palimind.agents.runtime import (
    cancel_agent,
    clear_agent_memory,
    delete_memory_entry,
    get_last_run,
    get_run,
    get_run_history,
    resolve_approval,
)
from palimind.agents.service import stream_agent
from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, _register_plugin_tools

router = APIRouter(prefix="/api/agents", tags=["agents"])


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
    _register_plugin_tools()
    tools: dict[str, dict[str, Any]] = {}
    for name in sorted(TOOL_REGISTRY):
        info = TOOL_REGISTRY[name]
        meta = info.get("meta", {"tier": 3, "requires_approval": True})
        tools[name] = {
            "id": name,
            "description": info.get("description", ""),
            "parameters": info.get("parameters", {}),
            "tier": int(meta.get("tier", 3)),
            "requires_approval": bool(meta.get("requires_approval", True)),
        }
    return {"tools": tools}


@router.get("/skills")
async def agent_skills():
    """List the skills that can be attached to agents."""
    from palimind.agents.skills import list_skills

    return {"skills": list_skills()}


@router.get("/activity")
async def agent_activity():
    """Live activity for the Mission Control wall: what each agent is doing
    right now, plus a bounded wire of recent events."""
    return activity.snapshot()


@router.get("/approvals")
async def agent_approvals():
    """All pending human-in-the-loop approvals across agents (the Inbox)."""
    return {"approvals": approvals.list_pending()}


@router.get("/runs/recent")
async def recent_runs(limit: int = 30):
    """Recent runs across every agent, newest first (traces stripped)."""
    cap = max(1, min(int(limit or 30), 100))
    items: list[dict] = []
    for defn in get_registry().all():
        for record in get_run_history(defn.id, limit=cap):
            stripped = {k: v for k, v in record.items() if k != "trace"}
            items.append({"agent_id": defn.id, "agent_name": defn.name, **stripped})
    items.sort(key=lambda r: float(r.get("timestamp", 0) or 0), reverse=True)
    return {"runs": items[:cap]}


@router.post("/hooks/{token}")
async def agent_webhook(token: str, req: Request):
    """Run a webhook-mode agent. The token is the agent's webhook_token."""
    defn = get_registry().get_by_webhook_token(token)
    if defn is None:
        return {"error": "unknown webhook token"}
    if not defn.enabled:
        return {"error": "agent is disabled"}
    if defn.run_mode != "webhook":
        return {"error": "agent is not in webhook mode"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    payload = str(body.get("input") or body.get("q") or "").strip() or "Run your task."
    from palimind.agents.service import run_agent

    output = await run_agent(defn, payload, session_id="_webhook")
    return {"status": "success", "output": output}


@router.post("/validate-cron")
async def validate_cron(req: Request):
    from palimind.agents.catalog import validate_cron as vc

    body = await req.json()
    error = vc(str(body.get("schedule", "")))
    return {"valid": error is None, "error": error}


@router.post("/{agent_id}/recall-preview")
async def recall_preview(agent_id: str, req: Request):
    """Preview which memory entries would be recalled for a query."""
    body = await req.json()
    from palimind.agents.memory import recall_memory

    query = str(body.get("query", ""))
    k = int(body.get("k", 8) or 8)
    return {"entries": recall_memory(agent_id, query, k=k)}


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
    history = list(reversed(get_run_history(agent_id, limit=limit)))
    # The list view omits the (potentially large) reasoning trace; fetch a
    # single run via /runs/{run_id} when the user expands it.
    for record in history:
        record.pop("trace", None)
    return {"history": history}


@router.get("/{agent_id}/runs/{run_id}")
async def agent_run_detail(agent_id: str, run_id: str):
    record = get_run(agent_id, run_id)
    if record is None:
        return {"error": "run not found"}
    return record


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

        async for ev in stream_agent(defn, agent_input, session_id):
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
