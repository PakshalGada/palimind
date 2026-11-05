"""HTTP surface for the memory center (view, edit, forget, consolidate)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from palimind.agents import memory

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _agent_id(value: Any) -> str:
    return str(value or "").strip()


@router.get("")
async def list_memory(
    agent_id: str,
    q: str = "",
    limit: int = 50,
    include_superseded: bool = False,
):
    if not _agent_id(agent_id):
        return {"error": "agent_id is required"}
    cap = max(1, min(int(limit or 50), 500))
    if q.strip():
        entries = memory.recall_memory(agent_id, q, k=cap, include_superseded=include_superseded)
    else:
        entries = memory.read_memory(agent_id)
        if not include_superseded:
            entries = [e for e in entries if not e.get("superseded_by")]
        entries = list(reversed(entries))[:cap]
    return {"entries": entries, "stats": memory.memory_stats(agent_id)}


@router.get("/stats")
async def memory_stats(agent_id: str):
    if not _agent_id(agent_id):
        return {"error": "agent_id is required"}
    return memory.memory_stats(agent_id)


@router.post("")
async def add_memory(req: Request):
    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    agent_id = _agent_id(body.get("agent_id"))
    if not agent_id:
        return {"error": "agent_id is required"}
    content = str(body.get("content") or "").strip()
    if not content:
        return {"error": "content is required"}
    entry = memory.append_memory(
        agent_id,
        str(body.get("type") or "fact"),
        content,
        confidence=float(body.get("confidence", 1.0) or 1.0),
        supersedes=[str(x) for x in (body.get("supersedes") or [])],
        source_run_id=str(body.get("source_run_id") or ""),
    )
    if entry is None:
        return {"error": "agent has no writable memory store"}
    return {"entry": entry}


@router.patch("/{entry_id}")
async def update_memory(entry_id: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    agent_id = _agent_id(body.get("agent_id"))
    if not agent_id:
        return {"error": "agent_id is required"}
    entry = memory.update_memory_entry(
        agent_id,
        entry_id,
        content=body.get("content"),
        entry_type=body.get("type"),
        confidence=body.get("confidence"),
    )
    return {"entry": entry} if entry else {"error": "memory entry not found"}


@router.delete("/{entry_id}")
async def delete_memory(entry_id: str, agent_id: str):
    if not _agent_id(agent_id):
        return {"error": "agent_id is required"}
    ok = memory.delete_memory_entry_by_id(agent_id, entry_id)
    return {"status": "success" if ok else "not_found"}


@router.post("/consolidate")
async def consolidate_memory(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    agent_id = _agent_id(body.get("agent_id"))
    if not agent_id:
        return {"error": "agent_id is required"}
    threshold = float(body.get("threshold", 0.92) or 0.92)
    marked = memory.consolidate_memory(agent_id, threshold=max(0.1, min(threshold, 1.0)))
    return {"status": "success", "superseded": marked, "stats": memory.memory_stats(agent_id)}
