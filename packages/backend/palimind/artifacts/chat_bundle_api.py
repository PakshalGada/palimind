"""HTTP endpoint for portable chat export bundles."""

from __future__ import annotations

import asyncio
import re
import time

from fastapi import APIRouter, HTTPException, Request, Response

from palimind.artifacts.chat_bundle import build_chat_bundle
from palimind.chat_audit import append_chat_audit
from palimind.security.tokens import palimind_home

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _filename(title: str) -> str:
    base = re.sub(r"[^\w.-]+", "_", title or "conversation", flags=re.ASCII).strip("._")
    return f"{base or 'conversation'}-bundle.zip"


@router.post("/export-bundle")
async def export_chat_bundle(req: Request):
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    if not body.get("messages") and not body.get("artifacts"):
        raise HTTPException(status_code=400, detail="messages or artifacts are required")

    try:
        data = await asyncio.to_thread(build_chat_bundle, body)
    except Exception as exc:  # noqa: BLE001 - surface a clear bundle failure
        raise HTTPException(status_code=500, detail=f"Could not build bundle: {exc}") from exc

    append_chat_audit(
        "chat.export_bundle",
        session_id=str(body.get("session_id") or ""),
        detail={
            "messages": len(body.get("messages") or []),
            "artifacts": len(body.get("artifacts") or []),
            "sources": len(body.get("sources") or []),
        },
    )
    name = _filename(str(body.get("title") or "Conversation"))
    stored = palimind_home() / "artifacts" / "exports" / f"{int(time.time())}-{name}"
    try:
        await asyncio.to_thread(stored.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(stored.write_bytes, data)
    except OSError:
        pass

    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Palimind-Filename": name,
            "X-Palimind-Path": str(stored),
            "Cache-Control": "no-store",
        },
    )
