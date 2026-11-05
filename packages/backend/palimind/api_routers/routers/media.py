"""Workspace media streaming with HTTP range support."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

router = APIRouter(prefix="/api/media", tags=["media"])

_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


def _resolve_media_path(path_str: str) -> Path:
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


@router.get("/info")
async def media_info(path: str):
    try:
        resolved = _resolve_media_path(path)
    except StarletteHTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    import mimetypes

    mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return {"size": resolved.stat().st_size, "mime": mime}


@router.get("/stream")
async def media_stream(request: Request, path: str):
    from urllib.parse import unquote

    try:
        resolved = _resolve_media_path(unquote(path))
    except StarletteHTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if not resolved.is_file() or resolved.suffix.lower() not in (_VIDEO_EXTS | _AUDIO_EXTS):
        raise HTTPException(status_code=404, detail="Media file not found")

    import mimetypes

    mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    file_size = resolved.stat().st_size
    range_header = request.headers.get("range")
    if range_header:
        range_val = range_header.strip().lower()
        if range_val.startswith("bytes="):
            parts = range_val[6:].split(",", 1)[0].strip().split("-", 1)
            if not parts[0].strip() and len(parts) > 1 and parts[1].strip().isdigit():
                start = max(0, file_size - int(parts[1].strip()))
                end = file_size - 1
            else:
                start = int(parts[0]) if parts[0].strip().isdigit() else 0
                end = (
                    int(parts[1])
                    if len(parts) > 1 and parts[1].strip().isdigit()
                    else min(start + 4 * 1024 * 1024 - 1, file_size - 1)
                )
            end = min(end, file_size - 1)
            if start >= file_size or end < start:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
            content_len = end - start + 1

            def _range_gen():
                with resolved.open("rb") as fh:
                    fh.seek(start)
                    remaining = content_len
                    while remaining > 0:
                        chunk = fh.read(min(1024 * 256, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return StreamingResponse(
                _range_gen(),
                status_code=206,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_len),
                    "Content-Type": mime,
                },
            )

    def _full_gen():
        with resolved.open("rb") as fh:
            while True:
                chunk = fh.read(512 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _full_gen(),
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": mime,
        },
    )
