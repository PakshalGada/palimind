"""Chat pipeline for real Word and PowerPoint files.

The composer asks the model for one fenced artifact, then posts the settled
artifact here. Generation happens on the server with python-docx/python-pptx,
so the result is a valid OOXML file even when the desktop webview has no
client-side DOCX/PPTX library available. Files are also kept under
``~/.palimind/artifacts/exports`` for later download.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from palimind.artifacts import export as export_mod
from palimind.security.tokens import palimind_home

router = APIRouter(prefix="/api/office", tags=["office"])

_FORMAT_EXT = {"docx": "docx", "pptx": "pptx"}
_FORMAT_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def exports_dir() -> Path:
    path = palimind_home() / "artifacts" / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(value: str, fallback: str = "document") -> str:
    base = re.sub(r"[^\w.-]+", "_", value or "", flags=re.ASCII).strip("._")
    return (base or fallback)[:80]


def _download_name(title: str, extension: str) -> str:
    return f"{_safe_name(title, 'document')}.{extension}"


@router.post("/generate")
async def generate_office_file(req: Request):
    """Create a DOCX/PPTX from the chat artifact and return it as a download."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    fmt = str(body.get("format") or "").lower().lstrip(".")
    if fmt not in _FORMAT_EXT:
        raise HTTPException(status_code=400, detail="format must be docx or pptx")
    title = str(body.get("title") or "Document").strip() or "Document"
    content = str(body.get("content") or "")
    slides = body.get("slides")
    if not content.strip() and not slides:
        raise HTTPException(status_code=400, detail="content is required")

    try:
        data, extension, media = await asyncio.to_thread(
            export_mod.office_bytes, fmt, title, content, slides
        )
    except Exception as exc:  # noqa: BLE001 - report generation failures clearly
        raise HTTPException(status_code=500, detail=f"Could not create {fmt}: {exc}") from exc

    filename = _download_name(title, extension)
    stored = exports_dir() / f"{int(time.time())}-{_safe_name(title, 'document')}.{extension}"
    try:
        await asyncio.to_thread(stored.write_bytes, data)
    except OSError:
        # The download still works even if the exports folder is read-only.
        pass

    return Response(
        content=data,
        media_type=_FORMAT_MEDIA[fmt],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Palimind-Filename": filename,
            "X-Palimind-Path": str(stored),
            "Cache-Control": "no-store",
        },
    )


@router.get("/file/{filename}")
async def download_office_file(filename: str):
    """Re-download a file the pipeline stored earlier."""
    candidate = (exports_dir() / filename).resolve()
    root = exports_dir().resolve()
    if root != candidate and root not in candidate.parents:
        raise HTTPException(status_code=403, detail="Path outside the export folder")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    extension = candidate.suffix.lower().lstrip(".")
    media = _FORMAT_MEDIA.get(extension, "application/octet-stream")
    return FileResponse(
        candidate,
        media_type=media,
        filename=candidate.name,
        content_disposition_type="attachment",
    )
