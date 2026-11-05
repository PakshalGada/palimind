"""Local backup, verify and restore endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("")
async def list_backups():
    from palimind.backup import list_backups as _list

    return {"backups": await asyncio.to_thread(_list)}


@router.post("")
async def create_backup(req: Request):
    from palimind.backup import create_backup as _create

    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        meta = await asyncio.to_thread(
            _create,
            body.get("path") or None,
            include_workspaces=body.get("include_workspaces") or None,
            passphrase=str(body.get("passphrase") or ""),
            label=str(body.get("label") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {"backup": meta}


@router.post("/verify")
async def verify_backup(req: Request):
    from palimind.backup import verify_backup as _verify

    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    path = str(body.get("path") or "")
    if not path:
        return {"error": "path is required"}
    try:
        return await asyncio.to_thread(_verify, path, str(body.get("passphrase") or ""))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/restore")
async def restore_backup(req: Request):
    from palimind.backup import restore_backup as _restore

    try:
        body = await req.json()
    except Exception:
        return {"error": "invalid JSON body"}
    if body.get("confirm") is not True:
        return {"error": "restore requires confirm=true"}
    path = str(body.get("path") or "")
    if not path:
        return {"error": "path is required"}
    try:
        result = await asyncio.to_thread(
            _restore,
            path,
            passphrase=str(body.get("passphrase") or ""),
            target_home=body.get("target_home") or None,
            overwrite=bool(body.get("overwrite", True)),
            restore_workspaces=bool(body.get("restore_workspaces", False)),
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return result
