"""Research plan, project and comparison endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from palimind.llm.comparative_research import analyze_comparison, find_contradictions
from palimind.research.plan_registry import resolve_plan
from palimind.research.project_store import (
    add_finding,
    add_report,
    add_sources,
    create_project,
    delete_project,
    list_projects,
    load_project,
    update_project,
)

router = APIRouter(prefix="/api/research", tags=["research"])


@router.post("/approve")
async def approve_research_plan(req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    plan_id = data.get("plan_id")
    if not plan_id:
        return {"error": "plan_id is required"}
    plan = data.get("plan")
    if plan is not None and not isinstance(plan, list):
        return {"error": "plan must be a list"}
    ok = resolve_plan(str(plan_id), plan=plan)
    return {"status": "approved" if ok else "not_found"}


@router.post("/cancel")
async def cancel_research_plan(req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    plan_id = data.get("plan_id")
    if not plan_id:
        return {"error": "plan_id is required"}
    ok = resolve_plan(str(plan_id), cancelled=True)
    return {"status": "cancelled" if ok else "not_found"}


@router.get("/projects")
async def get_research_projects():
    return {"projects": await asyncio.to_thread(list_projects)}


@router.post("/projects")
async def create_research_project(req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    return await asyncio.to_thread(
        create_project,
        str(data.get("title") or "Untitled Research"),
        str(data.get("query") or ""),
    )


@router.get("/projects/{project_id}")
async def get_research_project(project_id: str):
    project = await asyncio.to_thread(load_project, project_id)
    return project if project is not None else {"error": "Project not found"}


@router.put("/projects/{project_id}")
async def put_research_project(project_id: str, req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    project = await asyncio.to_thread(update_project, project_id, data)
    return project if project is not None else {"error": "Project not found"}


@router.delete("/projects/{project_id}")
async def remove_research_project(project_id: str):
    try:
        removed = await asyncio.to_thread(delete_project, project_id)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"status": "success" if removed else "not_found"}


@router.post("/projects/{project_id}/findings")
async def add_research_finding(project_id: str, req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    finding = await asyncio.to_thread(
        add_finding,
        project_id,
        str(data.get("title") or "Finding"),
        str(data.get("content") or ""),
    )
    return {"finding": finding} if finding is not None else {"error": "Project not found"}


@router.post("/projects/{project_id}/sources")
async def add_research_sources(project_id: str, req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    sources = data.get("sources")
    if not isinstance(sources, list):
        return {"error": "sources must be a list"}
    project = await asyncio.to_thread(add_sources, project_id, sources)
    return project if project is not None else {"error": "Project not found"}


@router.post("/projects/{project_id}/reports")
async def add_research_report(project_id: str, req: Request):
    try:
        data = await req.json()
    except Exception:
        return {"error": "Invalid JSON body"}
    project = await asyncio.to_thread(
        add_report,
        project_id,
        str(data.get("query") or ""),
        str(data.get("report") or ""),
    )
    return project if project is not None else {"error": "Project not found"}


@router.get("/compare")
async def compare_research(q: str, models: str = "", scope: str = "chat"):
    """Stream the same question to up to 3 models, then compare their answers."""
    from palimind import api_server as server

    model_list = [m.strip() for m in models.split(",") if m.strip()][:3]
    if not q.strip():
        return {"error": "query is required"}
    if len(model_list) < 2:
        return {"error": "Select at least two models to compare"}

    config = server._global_chat_config()
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    num_ctx = config.get("num_ctx")

    async def stream():
        from palimind.llm.mixture_of_expert.llm import llm_chat_safe

        yield f"data: {json.dumps({'type': 'compare_start', 'models': model_list})}\n\n"
        system_prompt = (
            "You are a rigorous research assistant. Answer the question thoroughly and "
            "factually in a few well-structured paragraphs. State uncertainties explicitly."
        )

        async def answer_with(model: str) -> tuple[str, str]:
            try:
                result = await asyncio.to_thread(
                    llm_chat_safe,
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": q},
                    ],
                    model,
                    ollama_url,
                    read_timeout=300.0,
                    num_ctx=num_ctx,
                    error_prefix="[compare error",
                )
                return model, result.get("content", "") or ""
            except Exception as exc:
                return model, f"**Error:** {exc}"

        answers: dict[str, str] = {}
        results = await asyncio.gather(*(answer_with(m) for m in model_list))
        for model, answer in results:
            answers[model] = answer
            yield (
                f"data: {json.dumps({'type': 'compare_model', 'model': model, 'answer': answer})}\n\n"
            )
        analysis = analyze_comparison(answers)
        if len(model_list) >= 2:
            analysis["contradictions"] = await find_contradictions(
                q,
                answers,
                model=model_list[0],
                ollama_url=ollama_url,
                num_ctx=num_ctx or 8192,
            )
        yield f"data: {json.dumps({'type': 'compare_result', **analysis})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/x")
async def x_social_research(q: str, max_results: int = 8):
    if not q.strip():
        return {"error": "query is required"}
    from palimind.agents.tools.x_search import x_search as _x_search

    return await asyncio.to_thread(_x_search, q, max_results)
