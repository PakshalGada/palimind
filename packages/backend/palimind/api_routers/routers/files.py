"""Open a workspace document from a chat citation."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

router = APIRouter(prefix="/api/files", tags=["files"])


def _resolve_file_path(path_str: str) -> Path:
    from palimind import api_server as server

    if not server.state.active_field:
        raise StarletteHTTPException(status_code=404, detail="No active field")
    root = server.state.active_field.resolve()
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if root != resolved and root not in resolved.parents:
        raise StarletteHTTPException(status_code=403, detail="Path outside workspace")
    return resolved


@router.get("/open")
async def open_file(path: str, section: str | None = None):
    """Serve a workspace file inline so citations can link to their source.

    ``section`` is accepted for forward compatibility with section-aware
    viewers, but the raw file is always returned so the browser can decide how
    to present it.
    """
    try:
        resolved = _resolve_file_path(path)
    except StarletteHTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    headers = {}
    if section:
        headers["X-Source-Section"] = section
    return FileResponse(
        resolved,
        media_type=mime,
        filename=resolved.name,
        content_disposition_type="inline",
        headers=headers,
    )
