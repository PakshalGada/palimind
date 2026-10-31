"""FastAPI router for first-class projects.

Mounted at ``/api/projects`` by :mod:`palimind.api_server`. Authentication,
loopback enforcement and CORS are handled by the existing app middleware, so
this module only implements project behaviour.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from palimind.artifacts import export as artifact_export
from palimind.projects import artifacts, kb, session_store, store

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_project_or_404(project_id: str) -> dict[str, Any]:
    try:
        project = store.get_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _json_body(body: Any) -> dict[str, Any]:
    return body if isinstance(body, dict) else {}


# ── project CRUD ──────────────────────────────────────────────────────────


@router.get("")
async def list_projects(q: str = ""):
    return {"projects": await asyncio.to_thread(store.list_projects, q or None)}


@router.post("", status_code=201)
async def create_project(req: Request):
    try:
        body = _json_body(await req.json())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    name = str(body.get("name") or body.get("title") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        project = await asyncio.to_thread(
            store.create_project,
            name,
            str(body.get("description") or ""),
            body.get("workspace_path"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Prepare the private config/DB eagerly so the first chat or session call
    # works without an indexing pass.
    try:
        await asyncio.to_thread(kb.ensure_project_storage, project["id"])
    except Exception:
        pass
    return project


@router.get("/{project_id}")
async def get_project(project_id: str):
    project = await asyncio.to_thread(_get_project_or_404, project_id)
    try:
        project["kb_status"] = await asyncio.to_thread(kb.kb_status, project_id)
    except Exception:
        project["kb_status"] = {}
    return project


@router.patch("/{project_id}")
async def update_project(project_id: str, req: Request):
    await asyncio.to_thread(_get_project_or_404, project_id)
    body = _json_body(await req.json())
    try:
        project = await asyncio.to_thread(store.update_project, project_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    await asyncio.to_thread(_get_project_or_404, project_id)
    removed = await asyncio.to_thread(store.delete_project, project_id)
    return {"status": "success" if removed else "not_found", "deleted": removed}


@router.post("/{project_id}/open")
async def open_project(project_id: str):
    project = await asyncio.to_thread(store.touch_project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    sessions = await asyncio.to_thread(session_store.list_sessions, project_id)
    return {"project": project, "scope": store.project_scope(project_id), "sessions": sessions}


# ── project-scoped sessions ───────────────────────────────────────────────


@router.get("/{project_id}/sessions")
async def list_project_sessions(project_id: str):
    await asyncio.to_thread(_get_project_or_404, project_id)
    return await asyncio.to_thread(session_store.list_sessions, project_id)


@router.post("/{project_id}/sessions")
async def create_project_session(project_id: str, req: Request):
    await asyncio.to_thread(_get_project_or_404, project_id)
    body = _json_body(await req.json())
    name = str(body.get("name") or "New Session")
    return await asyncio.to_thread(session_store.new_session, project_id, name)


# ── project knowledge base ────────────────────────────────────────────────


@router.get("/{project_id}/kb/status")
async def project_kb_status(project_id: str):
    await asyncio.to_thread(_get_project_or_404, project_id)
    return await asyncio.to_thread(kb.kb_status, project_id)


@router.post("/{project_id}/kb/sync")
async def sync_project_kb(project_id: str):
    await asyncio.to_thread(_get_project_or_404, project_id)
    try:
        return await asyncio.to_thread(kb.sync_project_kb, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── project artifacts ─────────────────────────────────────────────────────


@router.get("/{project_id}/artifacts")
async def list_project_artifacts(project_id: str, include_content: bool = False):
    await asyncio.to_thread(_get_project_or_404, project_id)
    return {
        "artifacts": await asyncio.to_thread(
            artifacts.list_artifacts, project_id, include_content
        )
    }


@router.post("/{project_id}/artifacts", status_code=201)
async def save_project_artifact(project_id: str, req: Request):
    await asyncio.to_thread(_get_project_or_404, project_id)
    body = _json_body(await req.json())
    try:
        return await asyncio.to_thread(artifacts.save_artifact, project_id, body)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}/artifacts/{artifact_id}")
async def get_project_artifact(project_id: str, artifact_id: str, version: int | None = None):
    await asyncio.to_thread(_get_project_or_404, project_id)
    try:
        return await asyncio.to_thread(
            artifacts.get_artifact, project_id, artifact_id, version=version
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{project_id}/artifacts/{artifact_id}/versions", status_code=201)
async def add_project_artifact_version(project_id: str, artifact_id: str, req: Request):
    await asyncio.to_thread(_get_project_or_404, project_id)
    body = _json_body(await req.json())
    try:
        return await asyncio.to_thread(
            artifacts.add_version, project_id, artifact_id, body
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{project_id}/artifacts/{artifact_id}")
async def delete_project_artifact(project_id: str, artifact_id: str):
    await asyncio.to_thread(_get_project_or_404, project_id)
    removed = await asyncio.to_thread(
        artifacts.delete_artifact, project_id, artifact_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"status": "success", "deleted": True}


@router.post("/{project_id}/artifacts/{artifact_id}/export")
async def export_project_artifact_format(project_id: str, artifact_id: str, req: Request):
    """Export a project artifact to a downloadable binary format."""
    await asyncio.to_thread(_get_project_or_404, project_id)
    body = _json_body(await req.json())
    fmt = str(body.get("format") or "md").lower().lstrip(".")
    try:
        artifact = await asyncio.to_thread(artifacts.get_artifact, project_id, artifact_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        data, extension, media_type = await asyncio.to_thread(
            artifact_export.export_bytes, artifact, fmt
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        await asyncio.to_thread(
            artifact_export.store_export,
            artifact_id=artifact_id,
            fmt=fmt,
            data=data,
            project_id=project_id,
        )
    except Exception:
        pass
    filename = artifact_export.export_filename(
        str(artifact.get("title") or "artifact"), extension
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/artifacts/{artifact_id}/export")
async def export_project_artifact(
    project_id: str,
    artifact_id: str,
    version: int | None = None,
):
    await asyncio.to_thread(_get_project_or_404, project_id)
    try:
        path, filename, mime_type = await asyncio.to_thread(
            artifacts.export_artifact, project_id, artifact_id, version
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type=mime_type, filename=filename)
