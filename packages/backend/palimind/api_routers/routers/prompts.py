"""Prompt library endpoints: reusable prompt templates with variables."""

from __future__ import annotations

from fastapi import APIRouter, Request

from palimind import prompts as prompt_store

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("")
async def get_prompts():
    """All saved prompt templates (user-global)."""
    return {"prompts": prompt_store.list_prompts()}


@router.post("")
async def create_prompt(req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    if not isinstance(data, dict):
        return {"error": "invalid body"}
    result = prompt_store.add_prompt(data)
    if isinstance(result, str):
        return {"error": result}
    return {"prompt": result, "prompts": prompt_store.list_prompts()}


@router.patch("/{prompt_id}")
async def patch_prompt(prompt_id: str, req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    if not isinstance(data, dict):
        return {"error": "invalid body"}
    result = prompt_store.update_prompt(prompt_id, data)
    if isinstance(result, str):
        return {"error": result}
    return {"prompt": result, "prompts": prompt_store.list_prompts()}


@router.delete("/{prompt_id}")
async def remove_prompt(prompt_id: str):
    if not prompt_store.delete_prompt(prompt_id):
        return {"error": "Prompt not found"}
    return {"status": "success", "prompts": prompt_store.list_prompts()}
