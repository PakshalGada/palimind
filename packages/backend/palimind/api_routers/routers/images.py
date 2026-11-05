"""Local image generation endpoints and image artifact serving."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/status")
async def image_status():
    from palimind.imagegen import availability

    return availability()


@router.get("")
async def list_images(limit: int = 100):
    from palimind.imagegen import list_images as _list

    return {"images": await asyncio.to_thread(_list, max(1, min(int(limit or 100), 500)))}


@router.post("/generate")
async def generate_image(req: Request):
    from palimind.imagegen import generate_and_save

    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    prompt = str(body.get("prompt") or "")
    try:
        image = await asyncio.to_thread(
            generate_and_save,
            prompt,
            negative_prompt=str(body.get("negative_prompt") or ""),
            width=int(body.get("width") or 512),
            height=int(body.get("height") or 512),
            steps=int(body.get("steps") or 20),
            seed=int(body["seed"]) if body.get("seed") is not None else None,
            backend=str(body.get("backend") or "") or None,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {"image": image}


@router.get("/{image_id}")
async def get_image(image_id: str):
    from palimind.imagegen import image_bytes

    try:
        data = await asyncio.to_thread(image_bytes, image_id)
    except Exception:
        data = None
    if not data:
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{image_id}/meta")
async def get_image_meta(image_id: str):
    from palimind.imagegen import get_image as _get

    record = await asyncio.to_thread(_get, image_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"image": _public(record)}


def _public(record: dict) -> dict:
    from palimind.imagegen import public_image

    return public_image(record)


@router.delete("/{image_id}")
async def delete_image(image_id: str):
    from palimind.imagegen import delete_image as _delete

    ok = await asyncio.to_thread(_delete, image_id)
    return {"status": "success" if ok else "not_found"}
