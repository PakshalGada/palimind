"""HTTP surface for provider status and model catalogs."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from palimind.agents.providers import get_provider_registry

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _opencode_key_present() -> bool:
    try:
        from palimind.opencode.auth import get_key

        return bool(str(get_key("opencode") or "").strip())
    except Exception:
        return False


def _opencode_catalog() -> list[dict[str, Any]]:
    try:
        from palimind.model_capabilities import infer_from_name
        from palimind.opencode.router import list_opencode_models

        rows: list[dict[str, Any]] = []
        for item in list_opencode_models():
            model_id = str(item.get("model_id") or item.get("id") or "")
            if not model_id:
                continue
            caps = infer_from_name(model_id)
            rows.append(
                {
                    "id": model_id,
                    "provider": "opencode",
                    "name": str(item.get("display_name") or item.get("name") or model_id),
                    "capabilities": {
                        "tools": True,
                        "vision": bool(getattr(caps, "supports_vision", False)),
                        "reasoning": bool(getattr(caps, "supports_reasoning", False)),
                        "context_window": int(getattr(caps, "context_window", 0) or 0),
                    },
                    "free": bool(item.get("free")),
                }
            )
        return rows
    except Exception:
        return []


async def _payload() -> dict:
    registry = get_provider_registry()
    models = await registry.models()
    opencode_models = await asyncio.to_thread(_opencode_catalog)
    key_present = await asyncio.to_thread(_opencode_key_present)
    providers = registry.status()
    if not any(provider.get("id") == "opencode" for provider in providers):
        providers.append(
            {
                "id": "opencode",
                "available": key_present,
                "capabilities": {
                    "tools": True,
                    "vision": True,
                    "reasoning": True,
                    "streaming": True,
                    "usage": True,
                    "accounts": False,
                    "attachments": True,
                    "concurrent_turns": True,
                },
                "error": "" if key_present else "OpenCode API key is not saved",
                "key_present": key_present,
                "source": "key",
            }
        )
    return {
        "providers": providers,
        "models": [model.as_dict() for model in models],
        "opencode": {"key_present": key_present, "models": opencode_models},
    }


@router.get("")
async def list_providers():
    return await _payload()


@router.get("/models")
async def list_models():
    return await _payload()


@router.post("/opencode/check")
async def check_opencode():
    """Metadata-only readiness check: list models, never run a completion."""
    key_present = await asyncio.to_thread(_opencode_key_present)
    models = await asyncio.to_thread(_opencode_catalog) if key_present else []
    return {
        "provider": "opencode",
        "key_present": key_present,
        "models": models,
        "status": "ready" if key_present and models else ("no-key" if not key_present else "no-models"),
    }
