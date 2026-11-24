"""Chat pipeline for real Word and PowerPoint files.

The composer asks the model for one fenced artifact, then posts the settled
artifact here. Generation runs on the server through two staged pipelines:
Markdown → styled DOCX (``docx_document``) and outline → planned → rendered →
validated PPTX (``deck``). The result is a valid OOXML file even when the
desktop webview has no client-side DOCX/PPTX library available. Files are also
kept under ``~/.palimind/artifacts/exports`` for later download.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from functools import lru_cache
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


@lru_cache(maxsize=64)
def _plan_cached(title: str, content: str, subtitle: str, slides_json: str) -> dict:
    from palimind.artifacts.deck import parse_outline, plan_deck

    slides = json.loads(slides_json) if slides_json else None
    specs = parse_outline(title, content, slides)
    plan = plan_deck(title, specs, subtitle=subtitle)
    return plan.to_dict()


@router.post("/deck-plan")
async def deck_plan(req: Request):
    """Plan a deck without rendering bytes, for the in-app slide preview."""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    title = str(body.get("title") or "Presentation").strip() or "Presentation"
    content = str(body.get("content") or "")
    subtitle = str(body.get("subtitle") or "")
    slides = body.get("slides")
    if not content.strip() and not slides:
        raise HTTPException(status_code=400, detail="content is required")

    try:
        slides_json = json.dumps(slides, sort_keys=True) if slides is not None else ""
        plan = _plan_cached(title, content, subtitle, slides_json)
    except Exception as exc:  # noqa: BLE001 - surface a clear planning error
        raise HTTPException(status_code=500, detail=f"Could not plan deck: {exc}") from exc

    warnings: list[str] = []
    if not plan.get("slides"):
        warnings.append("The outline produced no content slides.")
    return {"plan": plan, "warnings": warnings}


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
