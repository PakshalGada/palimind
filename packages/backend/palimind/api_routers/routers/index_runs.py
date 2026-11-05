"""Incremental indexing run endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/index/runs", tags=["index"])


@router.post("")
async def create_index_run(req: Request):
    """Plan and enqueue an incremental indexing run."""
    from palimind import api_server as server
    from palimind.rag import incremental

    try:
        body = await req.json()
    except Exception:
        body = {}
    root = str(body.get("root") or "")
    if not root and server.state.active_field:
        root = str(server.state.active_field)
    if not root:
        return {"error": "No active knowledge base"}
    source_root = str(body.get("source_root") or "") or None
    try:
        summary = await asyncio.to_thread(
            incremental.enqueue_run,
            Path(root),
            source_root=Path(source_root) if source_root else None,
            priority=int(body.get("priority") or 0),
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to start index run: {exc}"}
    return {"run": summary}


@router.get("")
async def list_index_runs(limit: int = 50):
    from palimind.rag import incremental

    return {"runs": await asyncio.to_thread(incremental.list_runs, max(1, min(limit, 200)))}


@router.get("/{run_id}")
async def get_index_run(run_id: str):
    from palimind.rag import incremental

    summary = await asyncio.to_thread(incremental.get_run, run_id)
    if summary is None:
        return {"error": "index run not found"}
    files = []
    try:
        files = await asyncio.to_thread(
            incremental.list_run_files, Path(str(summary.get("root") or "")), run_id
        )
    except Exception:
        pass
    return {"run": summary, "files": files}


@router.get("/{run_id}/events")
async def get_index_run_events(run_id: str, limit: int = 200):
    from palimind.rag import incremental

    summary = await asyncio.to_thread(incremental.get_run, run_id)
    if summary is None:
        return {"error": "index run not found"}
    events = await asyncio.to_thread(
        incremental.list_events,
        Path(str(summary.get("root") or "")),
        run_id,
        max(1, min(limit, 1000)),
    )
    return {"events": events}


@router.post("/{run_id}/cancel")
async def cancel_index_run(run_id: str):
    from palimind.rag import incremental

    summary = await asyncio.to_thread(incremental.cancel_run, run_id)
    return {"run": summary} if summary else {"error": "index run not found"}


@router.post("/{run_id}/resume")
async def resume_index_run(run_id: str):
    from palimind.rag import incremental

    summary = await asyncio.to_thread(incremental.resume_run, run_id)
    if summary is None:
        return {"error": "index run not found"}
    return {"run": summary}
