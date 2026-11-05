"""HTTP surface for workflows and their triggers."""

from __future__ import annotations

from fastapi import APIRouter, Request

from palimind.workflows import runtime, store, triggers

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("")
async def list_workflows(limit: int = 200):
    return {"workflows": store.list_workflows(limit=max(1, min(int(limit or 200), 1000)))}


@router.post("")
async def create_workflow(req: Request):
    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    try:
        workflow = store.create_workflow(body)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"workflow": workflow}


@router.get("/runs")
async def list_all_runs(workflow_id: str | None = None, limit: int = 50):
    return {"runs": runtime.list_runs(workflow_id, limit=max(1, min(int(limit or 50), 500)))}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = runtime.get_run(run_id)
    return {"run": run} if run else {"error": "workflow run not found"}


@router.post("/hooks/{token}")
async def workflow_webhook(token: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    job = triggers.enqueue_webhook(token, body if isinstance(body, dict) else {})
    if job is None:
        return {"error": "unknown or disabled webhook token"}
    return {"status": "queued", "job": job}


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    workflow = store.get_workflow(workflow_id)
    return {"workflow": workflow} if workflow else {"error": "workflow not found"}


@router.patch("/{workflow_id}")
async def update_workflow(workflow_id: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    try:
        workflow = store.update_workflow(workflow_id, body)
    except KeyError:
        return {"error": "workflow not found"}
    except ValueError as exc:
        return {"error": str(exc)}
    return {"workflow": workflow}


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    return {"status": "success" if store.delete_workflow(workflow_id) else "not_found"}


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: str, req: Request):
    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        return {"error": "workflow not found"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        job = runtime.enqueue_workflow(
            workflow_id,
            input_text=str(body.get("input") or ""),
            trigger={"type": "manual"},
            priority=int(body.get("priority") or 0),
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {"status": "queued", "job": job}


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(workflow_id: str, limit: int = 50):
    return {"runs": runtime.list_runs(workflow_id, limit=max(1, min(int(limit or 50), 500)))}
