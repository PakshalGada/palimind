"""HTTP API for the global artifact library and export fallback."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from palimind.artifacts import export as export_mod
from palimind.artifacts import registry

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


def _body(data: Any) -> dict[str, Any]:
    return data if isinstance(data, dict) else {}


@router.get("")
async def list_artifacts(q: str = "", project_id: str = "", include_content: bool = False):
    items = await asyncio.to_thread(
        registry.list_artifacts, q or None, project_id or None, include_content
    )
    return {"artifacts": items}


@router.post("", status_code=201)
async def save_artifact(req: Request):
    try:
        body = _body(await req.json())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    if not str(body.get("content") or "").strip():
        raise HTTPException(status_code=400, detail="content is required")
    artifact = await asyncio.to_thread(
        registry.save_artifact, body, body.get("id") if isinstance(body.get("id"), str) else None
    )
    return artifact


@router.post("/save-to-knowledge")
async def save_to_knowledge(req: Request):
    """Write an artifact as a Markdown document and re-index its knowledge base."""
    body = _body(await req.json())
    title = str(body.get("title") or "Artifact")
    content = str(body.get("content") or "")
    project_id = str(body.get("project_id") or "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="content is required")

    from palimind.projects import kb as project_kb
    from palimind.projects.store import get_project

    target: Path | None = None
    if project_id:
        project = await asyncio.to_thread(get_project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        target = Path(str(project.get("workspace_path") or "")).expanduser()
    else:
        try:
            import palimind.api_server as server

            target = server.state.active_field
        except Exception:
            target = None
    if target is None:
        artifact = await asyncio.to_thread(registry.save_artifact, body, None)
        return {
            "status": "library",
            "artifact_id": artifact["id"],
            "message": "Saved to the artifact library. Select a knowledge base to index it.",
        }

    target = target.resolve()
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Knowledge base folder not found")
    safe_title = re.sub(r"[^\w.-]+", "-", title).strip("-") or "artifact"
    output_dir = target / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{safe_title}.md"
    path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")

    try:
        if project_id:
            result = await asyncio.to_thread(project_kb.sync_project_kb, project_id)
        else:
            from palimind.rag.indexing import update_index

            result = await asyncio.to_thread(update_index, target)
        indexed = getattr(result, "indexed_files", None)
        if isinstance(result, dict):
            indexed = result.get("indexed_files")
        return {"status": "success", "path": str(path), "indexed_files": indexed}
    except Exception as exc:
        return {"status": "saved", "path": str(path), "error": str(exc)}


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str):
    artifact = await asyncio.to_thread(registry.get_artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str):
    removed = await asyncio.to_thread(registry.delete_artifact, artifact_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"status": "success", "deleted": True}


@router.post("/{artifact_id}/export")
async def export_artifact(artifact_id: str, req: Request):
    body = _body(await req.json())
    fmt = str(body.get("format") or "md").lower().lstrip(".")
    artifact = await asyncio.to_thread(registry.get_artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        data, extension, media_type = await asyncio.to_thread(
            export_mod.export_bytes, artifact, fmt
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    project_id = str(artifact.get("project_id") or "")
    try:
        await asyncio.to_thread(
            export_mod.store_export,
            artifact_id=artifact_id,
            fmt=fmt,
            data=data,
            project_id=project_id,
        )
    except Exception:
        pass
    filename = export_mod.export_filename(str(artifact.get("title") or "artifact"), extension)
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
