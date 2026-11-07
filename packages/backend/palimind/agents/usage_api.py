"""HTTP surface for local usage aggregates."""

from __future__ import annotations

from fastapi import APIRouter

from palimind.agents import usage

router = APIRouter(prefix="/api", tags=["usage"])


@router.get("/usage")
async def get_usage(agent_id: str = "", start: str = "", end: str = "", provider: str = ""):
    if not start or not end:
        start, end = usage.default_range(30)
    return usage.aggregate(agent_id, start=start, end=end, provider=provider)


@router.get("/agents/{agent_id}/usage")
async def get_agent_usage(agent_id: str, start: str = "", end: str = "", provider: str = ""):
    if not start or not end:
        start, end = usage.default_range(30)
    return usage.aggregate(agent_id, start=start, end=end, provider=provider)
