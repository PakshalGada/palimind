"""HTTP surface for browser profiles, tabs and takeover requests."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from palimind.agents import browser_profiles

router = APIRouter(prefix="/api/browser", tags=["browser"])


@router.get("/profiles")
async def list_profiles():
    return {"profiles": browser_profiles.list_profiles()}


@router.post("/profiles")
async def create_profile(req: Request):
    body = await req.json()
    try:
        return {
            "profile": browser_profiles.create_profile(
                str(body.get("name") or ""), color=str(body.get("color") or "")
            )
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.patch("/profiles/{profile_id}")
async def update_profile(profile_id: str, req: Request):
    body = await req.json()
    profile = browser_profiles.update_profile(profile_id, **body)
    return {"profile": profile} if profile else {"error": "Profile not found"}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    return {"deleted": browser_profiles.delete_profile(profile_id)}


@router.get("/tabs")
async def list_tabs(profile_id: str = "", agent_id: str = ""):
    return {"tabs": browser_profiles.list_tabs(profile_id, agent_id)}


@router.post("/tabs")
async def save_tab(req: Request):
    body = await req.json()
    return {
        "tab": browser_profiles.save_tab(
            str(body.get("profile_id") or "shared"),
            agent_id=str(body.get("agent_id") or ""),
            url=str(body.get("url") or ""),
            title=str(body.get("title") or ""),
            opener_tab_id=str(body.get("opener_tab_id") or ""),
            tab_id=str(body.get("tab_id") or ""),
            state=body.get("state") if isinstance(body.get("state"), dict) else {},
        )
    }


@router.delete("/tabs/{tab_id}")
async def delete_tab(tab_id: str):
    return {"deleted": browser_profiles.delete_tab(tab_id)}


@router.get("/takeovers")
async def list_takeovers(agent_id: str = "", status: str = ""):
    return {"takeovers": browser_profiles.list_takeovers(agent_id, status=status)}


@router.get("/state")
async def browser_state(agent_id: str = ""):
    from palimind.agents.tools.browser.tool import live_state

    state = await asyncio.to_thread(live_state)
    agent_id = str(state.get("agent_id") or agent_id or "")
    pending = browser_profiles.list_takeovers(agent_id, status="pending") if agent_id else []
    active = browser_profiles.list_takeovers(agent_id, status="active") if agent_id else []
    state["takeover"] = (active or pending or [None])[0]
    return state


@router.post("/control/claim")
async def claim_browser_control(req: Request):
    from palimind.agents.tools.browser.tool import claim_control

    body = await req.json() if req.headers.get("content-length") not in (None, "0") else {}
    return {
        "control": claim_control(
            agent_id=str((body or {}).get("agent_id") or ""),
            takeover_id=str((body or {}).get("takeover_id") or ""),
        )
    }


@router.post("/control/release")
async def release_browser_control():
    from palimind.agents.tools.browser.tool import release_control

    return {"control": release_control()}


@router.get("/frame")
async def browser_frame(quality: int = 70):
    from palimind.agents.tools.browser.tool import live_frame_jpeg

    frame = await asyncio.to_thread(live_frame_jpeg, quality)
    if not frame:
        return JSONResponse({"error": "No active browser session"}, status_code=404)
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/action")
async def browser_action(req: Request):
    from palimind.agents.tools.browser.tool import human_action

    body = await req.json()
    action = str((body or {}).get("action") or "")
    payload = {k: v for k, v in (body or {}).items() if k != "action"}
    return await asyncio.to_thread(human_action, action, payload)


@router.post("/takeovers/{takeover_id}/accept")
async def accept_takeover(takeover_id: str):
    from palimind.agents.tools.browser.tool import claim_control

    existing = browser_profiles.get_takeover(takeover_id)
    if existing is None:
        return JSONResponse({"error": "Takeover not found"}, status_code=404)
    if str(existing.get("status")) not in ("pending", "active"):
        return JSONResponse({"error": "Takeover is no longer available"}, status_code=409)
    takeover = browser_profiles.accept_takeover(takeover_id)
    control = claim_control(
        agent_id=str(takeover.get("agent_id") or ""),
        takeover_id=takeover_id,
    )
    return {"takeover": takeover, "control": control}


@router.post("/takeovers")
async def request_takeover(req: Request):
    body = await req.json()
    return {
        "takeover": browser_profiles.request_takeover(
            str(body.get("agent_id") or ""),
            tab_id=str(body.get("tab_id") or ""),
            reason=str(body.get("reason") or ""),
        )
    }


@router.post("/takeovers/{takeover_id}/resolve")
async def resolve_takeover(takeover_id: str, req: Request):
    from palimind.agents.tools.browser.tool import claim_control, release_control

    body = await req.json()
    status = str(body.get("status") or "completed")
    try:
        takeover = browser_profiles.resolve_takeover(takeover_id, status=status)
        if takeover and status == "active":
            claim_control(
                agent_id=str(takeover.get("agent_id") or ""),
                takeover_id=takeover_id,
            )
        elif takeover and status in ("completed", "cancelled", "expired"):
            release_control()
        return {"takeover": takeover}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
