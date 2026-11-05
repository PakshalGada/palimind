"""Hardware cookbook and recommendation endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

router = APIRouter(prefix="/api/cookbook", tags=["cookbook"])


@router.get("/hardware")
async def get_hardware():
    try:
        from palimind.hwfit.hardware import detect_hardware

        profile = await asyncio.to_thread(detect_hardware)
        return profile.to_dict()
    except Exception:
        return {"error": "Failed to get recommendations"}


@router.get("/recommendations")
async def get_recommendations(top: int = 20):
    try:
        from palimind.hwfit.catalog import MODEL_CATALOG
        from palimind.hwfit.fit import rank_models
        from palimind.hwfit.hardware import detect_hardware

        profile = await asyncio.to_thread(detect_hardware)
        ranked = rank_models(profile, MODEL_CATALOG, top=top)
        return {"recommendations": ranked, "hardware": profile.to_dict()}
    except Exception:
        return {"error": "Failed to get recommendations", "recommendations": []}
