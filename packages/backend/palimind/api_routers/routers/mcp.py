"""Local MCP server status and reload endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/servers")
async def list_mcp_servers():
    from palimind.agents.mcp import get_manager

    return {"servers": await asyncio.to_thread(lambda: get_manager().status())}


@router.post("/reload")
async def reload_mcp_servers():
    from palimind.agents.mcp import reload_manager

    try:
        manager = await asyncio.to_thread(reload_manager)
        from palimind.llm.mixture_of_expert.tools import _register_plugin_tools

        _register_plugin_tools(force=True)
        return {"status": "success", "servers": manager.status()}
    except Exception as exc:
        return {"error": f"Failed to reload MCP servers: {exc}"}
