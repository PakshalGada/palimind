"""HTTP surface for agent export, import and templates."""

from __future__ import annotations

from fastapi import APIRouter, Request

from palimind.agents import sharing

router = APIRouter(prefix="/api", tags=["sharing"])


@router.post("/agents/export")
async def export_agents(req: Request):
    body = await req.json()
    ids = [str(item) for item in (body.get("agent_ids") or [])]
    return {
        "export": sharing.export_agents(
            ids, include_workspace=bool(body.get("include_workspace", False))
        )
    }


@router.post("/agents/import")
async def import_agents(req: Request):
    body = await req.json()
    try:
        return sharing.import_agents(
            body.get("export") if isinstance(body.get("export"), dict) else body
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/agents/export/archive")
async def export_archive(req: Request):
    body = await req.json()
    path = str(body.get("path") or "")
    if not path:
        return {"error": "path is required"}
    try:
        return {
            "path": sharing.export_archive(path, [str(i) for i in (body.get("agent_ids") or [])])
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/agents/import/archive")
async def import_archive(req: Request):
    body = await req.json()
    path = str(body.get("path") or "")
    if not path:
        return {"error": "path is required"}
    try:
        return sharing.import_archive(path)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/agents/{agent_id}/template")
async def template(agent_id: str):
    try:
        return {"template": sharing.template_from_agent(agent_id)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/agent-templates/install")
async def install_template(req: Request):
    body = await req.json()
    template = body.get("template") if isinstance(body.get("template"), dict) else body
    try:
        return sharing.install_template(template)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
