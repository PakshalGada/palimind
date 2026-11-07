"""HTTP surface for sandboxed visual replies."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

from palimind.agents import visuals

router = APIRouter(prefix="/api/visuals", tags=["visuals"])


@router.get("")
async def list_visuals(agent_id: str = ""):
    return {"visuals": visuals.list_visuals(agent_id)}


@router.get("/{visual_id}")
async def get_visual(visual_id: str, token: str = ""):
    html = visuals.read_visual(visual_id, token)
    if html is None:
        return PlainTextResponse("not found", status_code=404)
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": "sandbox allow-scripts allow-forms",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
