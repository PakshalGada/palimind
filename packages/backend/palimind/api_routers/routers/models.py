"""Model listing, capabilities and pull-progress endpoints."""

from __future__ import annotations

import asyncio
import json

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from palimind.opencode.client import proxy_auth_headers

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
async def get_models():
    from palimind import api_server as server
    from palimind.config import load_config

    if server.state.active_field:
        config = load_config(server.state.active_field)
    else:
        config = server._global_chat_config()
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    current_model = config.get("chat_model", "gemma4:e2b")
    try:
        models = await asyncio.to_thread(server._fetch_ollama_models_blocking, ollama_url)
        from palimind.opencode.router import list_opencode_models

        oc_models = await asyncio.to_thread(list_opencode_models)
        seen = {m["model_id"] for m in models}
        for oc in oc_models:
            if oc["model_id"] not in seen:
                models.append(oc)
                seen.add(oc["model_id"])
        return {
            "models": models,
            "current_model": current_model,
            "ollama_url": ollama_url,
            "status": "ok" if models else "empty",
        }
    except Exception:
        return {
            "error": "Failed to fetch models",
            "models": [],
            "current_model": current_model,
            "status": "offline",
        }


@router.get("/capabilities")
async def get_model_capabilities(model: str | None = None):
    from palimind import api_server as server
    from palimind.config import load_config
    from palimind.model_capabilities import capabilities_for_models, get_capabilities

    if server.state.active_field:
        config = load_config(server.state.active_field)
    else:
        config = server._global_chat_config()
    ollama_url = config.get("ollama_base_url", "http://localhost:11434")
    if model:
        caps = await asyncio.to_thread(get_capabilities, model, ollama_url)
        return {"model": caps.to_dict()}
    models = await asyncio.to_thread(server._fetch_ollama_models_blocking, ollama_url)
    ids = [str(m.get("model_id") or "") for m in models if m.get("model_id")]
    if not ids:
        ids = [str(config.get("chat_model") or "")]
    payload = await asyncio.to_thread(capabilities_for_models, ids, ollama_url, use_ollama=False)
    return {"models": payload, "ollama_url": ollama_url}


@router.get("/pull")
async def pull_model(model: str):
    from palimind import api_server as server
    from palimind.config import load_config

    if not model or not model.strip():

        async def err_stream():
            yield f"data: {json.dumps({'error': 'model is required'})}\n\n"

        return StreamingResponse(err_stream(), media_type="text/event-stream")
    if server.state.active_field:
        config = load_config(server.state.active_field)
    else:
        config = server._global_chat_config()
    ollama_url = config.get("ollama_base_url", "http://localhost:11434").rstrip("/")

    async def gen():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{ollama_url}/api/pull",
                    json={"model": model.strip(), "stream": True},
                    headers=proxy_auth_headers(ollama_url),
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        detail = body[:200].decode("utf-8", errors="replace")
                        yield f"data: {json.dumps({'error': f'Ollama HTTP {resp.status_code}: {detail}'})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        total = obj.get("total")
                        completed = obj.get("completed")
                        percent = (
                            int(completed * 100 / total)
                            if (total and completed is not None)
                            else None
                        )
                        payload = {
                            "status": obj.get("status", ""),
                            "completed": completed,
                            "total": total,
                            "percent": percent,
                            "done": obj.get("status") == "success",
                        }
                        if obj.get("error"):
                            payload["error"] = obj["error"]
                        yield f"data: {json.dumps(payload)}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'error': 'Model pull failed'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
