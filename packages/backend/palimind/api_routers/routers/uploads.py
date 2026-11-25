"""Local attachment upload endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("")
async def create_upload(req: Request):
    """Store a local chat attachment (base64 JSON; no multipart dependency)."""
    from palimind.uploads import save_upload

    try:
        data = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    name = str(data.get("name") or "attachment")
    mime = str(data.get("mime") or "")
    payload = str(data.get("data") or "")
    try:
        upload = await asyncio.to_thread(save_upload, name, payload, mime)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception:
        return {"error": "failed to store attachment"}
    return {"upload": upload}


@router.get("")
async def list_uploads_endpoint(limit: int = 100):
    from palimind.uploads import list_uploads

    return {"uploads": await asyncio.to_thread(list_uploads, max(1, min(int(limit or 100), 500)))}


@router.get("/{upload_id}")
async def get_upload_endpoint(upload_id: str):
    from palimind.uploads import get_upload

    upload = await asyncio.to_thread(get_upload, upload_id)
    if upload is None:
        return {"error": "upload not found"}
    return {
        "upload": {
            key: upload.get(key)
            for key in ("id", "name", "mime", "size", "kind", "sha256", "created_at")
        }
    }


@router.get("/{upload_id}/file")
async def get_upload_file_endpoint(upload_id: str):
    """Serve an uploaded attachment inline for the right-side document viewer."""
    from palimind.uploads import get_upload

    upload = await asyncio.to_thread(get_upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="upload not found")
    path = Path(str(upload.get("path") or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file missing from local storage")
    return FileResponse(
        path,
        media_type=str(upload.get("mime") or "application/octet-stream"),
        filename=str(upload.get("name") or path.name),
        content_disposition_type="inline",
    )


@router.delete("/{upload_id}")
async def delete_upload_endpoint(upload_id: str):
    from palimind.uploads import delete_upload

    ok = await asyncio.to_thread(delete_upload, upload_id)
    return {"status": "success" if ok else "not_found"}
