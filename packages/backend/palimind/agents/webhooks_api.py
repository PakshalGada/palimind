"""HTTP surface for signed routine webhooks."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request

from palimind.agents import webhooks

router = APIRouter(prefix="/api", tags=["webhooks"])


@router.get("/routines/{routine_id}/webhook")
async def list_webhooks(routine_id: str):
    return {"routes": webhooks.list_routes(routine_id)}


@router.post("/routines/{routine_id}/webhook")
async def create_webhook(routine_id: str, req: Request):
    body = await req.json()
    try:
        route = webhooks.create_route(
            routine_id,
            event_type=str(body.get("event_type") or ""),
            filters=body.get("filters") if isinstance(body.get("filters"), list) else [],
        )
        return {"route": {**route, "url": f"/api/hooks/{route['route_id']}"}}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.delete("/routines/{routine_id}/webhook/{route_id}")
async def revoke_webhook(routine_id: str, route_id: str):
    route = webhooks.get_route(route_id)
    if route is None or str(route.get("routine_id")) != routine_id:
        return {"error": "route not found"}
    return {"revoked": webhooks.revoke_route(route_id)}


@router.post("/webhooks/{route_id}/rotate")
async def rotate_secret(route_id: str):
    try:
        return {"route_id": route_id, "secret": webhooks.rotate_secret(route_id)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/hooks/{route_id}")
async def receive(route_id: str, req: Request):
    from fastapi.responses import JSONResponse

    route = webhooks.get_route(route_id)
    if route is None or route.get("revoked_at"):
        return JSONResponse({"error": "unknown route"}, status_code=404)
    body = await req.body()
    if len(body) > webhooks.MAX_BODY:
        return JSONResponse({"error": "body too large"}, status_code=413)
    timestamp = str(req.headers.get("X-PaliMind-Timestamp") or "")
    delivery_id = str(req.headers.get("X-PaliMind-Delivery") or "")
    provided = str(req.headers.get("X-PaliMind-Signature") or "")
    secret = webhooks.read_secret(route_id)
    if not webhooks.verify(
        secret,
        timestamp=timestamp,
        delivery_id=delivery_id,
        body=body,
        provided=provided,
    ):
        return JSONResponse({"error": "bad signature"}, status_code=401)
    try:
        event = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)
    if not isinstance(event, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    event_type = str(event.get("type") or "")
    data = event.get("data")
    matched, reason = webhooks.matches(route, event_type, data)
    status = "accepted" if matched else f"ignored:{reason}"
    is_new = webhooks.record_receipt(route_id, delivery_id, str(route.get("routine_id") or ""), status)
    if not is_new:
        return JSONResponse({"status": "duplicate"}, status_code=200)
    if not matched:
        return JSONResponse({"status": status}, status_code=202)
    from palimind.jobs import enqueue

    instruction = webhooks.run_instruction(route, event_type, data)
    job = enqueue(
        "routine_run",
        str(route.get("routine_id") or ""),
        {
            "routine_id": route.get("routine_id"),
            "payload": instruction,
            "source": "webhook",
        },
    )
    return JSONResponse({"status": "accepted", "run_id": job.get("id")}, status_code=202)
