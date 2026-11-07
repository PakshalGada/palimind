"""HTTP surface for provider status and model catalogs."""

from __future__ import annotations

from fastapi import APIRouter

from palimind.agents.providers import get_provider_registry

router = APIRouter(prefix="/api/providers", tags=["providers"])


async def _payload() -> dict:
    registry = get_provider_registry()
    models = await registry.models()
    return {
        "providers": registry.status(),
        "models": [model.as_dict() for model in models],
    }


@router.get("")
async def list_providers():
    return await _payload()


@router.get("/models")
async def list_models():
    return await _payload()
