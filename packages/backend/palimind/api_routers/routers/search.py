"""Search provider selection, configuration and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from palimind.config import load_global_config, save_global_config
from palimind.core.search_providers import SearchRouter

router = APIRouter(prefix="/api/search", tags=["search"])

_PROVIDERS = ("auto", "searxng", "ddg")


@router.get("/status")
async def search_status():
    return SearchRouter().status()


@router.get("/providers")
async def search_providers():
    status = SearchRouter().status()
    return {
        "providers": [
            {"name": "searxng", **status["providers"]["searxng"]},
            {"name": "ddg", **status["providers"]["ddg"]},
        ],
        "active": status["active"],
    }


@router.get("/config")
async def get_search_config():
    cfg = load_global_config()
    return {
        "provider": cfg.get("search_provider") or "auto",
        "searxng_url": cfg.get("searxng_url") or "",
        "status": SearchRouter(config=cfg).status(),
    }


@router.patch("/config")
async def update_search_config(req: Request):
    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    changes: dict[str, str] = {}
    if "provider" in body:
        provider = str(body.get("provider") or "").strip().lower()
        if provider not in _PROVIDERS:
            return {"error": f"provider must be one of {_PROVIDERS}"}
        changes["search_provider"] = provider
    if "searxng_url" in body:
        url = str(body.get("searxng_url") or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            return {"error": "searxng_url must be an http(s) URL"}
        changes["searxng_url"] = url
    if not changes:
        return {"error": "no supported fields supplied"}
    cfg = save_global_config(changes)
    return {
        "status": "success",
        "provider": cfg.get("search_provider") or "auto",
        "searxng_url": cfg.get("searxng_url") or "",
    }
