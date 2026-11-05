"""Model/config, MoE hardware and browser-view endpoints."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter(prefix="/api", tags=["config"])


def _server():
    from palimind import api_server as server

    return server


@router.patch("/config/model")
async def update_model(req: Request, scope: str = "field"):
    server = _server()
    data = await req.json()
    model_id = data.get("model_id")
    if not model_id:
        return {"error": "model_id is required"}
    if scope.startswith("agent:"):
        from palimind.agents.registry import get_registry

        agent_id = scope.split(":", 1)[1].strip()
        try:
            get_registry().update(agent_id, {"model": model_id})
        except Exception:
            return {"error": "Failed to update agent model"}
        return {"status": "success", "model": model_id}

    from palimind.config import config_path, load_config, palimind_dir, save_config

    if scope.startswith("project:"):
        root = server._chat_root(scope)
        if root is None:
            return {"error": "Project not found"}
        cfg = load_config(root)
        cfg["chat_model"] = model_id
        save_config(root, cfg)
        return {"status": "success", "model": model_id}
    if server.state.active_field:
        cfg = load_config(server.state.active_field)
        cfg["chat_model"] = model_id
        p_dir = palimind_dir(server.state.active_field)
        p_dir.mkdir(parents=True, exist_ok=True)
        config_path(server.state.active_field).write_text(json.dumps(cfg, indent=2), "utf-8")
    try:
        global_data = {}
        if server.GLOBAL_CONFIG_PATH.exists():
            global_data = json.loads(server.GLOBAL_CONFIG_PATH.read_text("utf-8"))
        global_data["chat_model"] = model_id
        server._write_global_config(global_data)
    except Exception:
        pass
    return {"status": "success", "model": model_id}


@router.get("/config")
async def get_config(scope: str = "field"):
    server = _server()
    from palimind.config import load_config

    if scope.startswith("agent:"):
        from palimind.agents.registry import get_registry

        base = server._global_chat_config()
        agent_id = scope.split(":", 1)[1].strip()
        defn = get_registry().get_by_id(agent_id)
        return {
            "chat_model": (defn.model if defn and defn.model else base.get("chat_model", "llama3")),
            "embed_model": base.get("embed_model", "bge-m3"),
            "ollama_base_url": base.get("ollama_base_url", "http://localhost:11434"),
            "moe_orchestrator_model": "",
            "moe_worker_model": "",
            "moe_sub_mode": "default",
            "persona_name": defn.name if defn else "",
            "persona_system_prompt": defn.system_prompt if defn else "",
        }
    if scope == "chat":
        config = server._global_chat_config()
    elif scope.startswith("project:"):
        root = server._chat_root(scope)
        config = load_config(root) if root else {}
    elif server.state.active_field:
        config = load_config(server.state.active_field)
    else:
        config = {}
    return {
        "chat_model": config.get("chat_model", "llama3"),
        "embed_model": config.get("embed_model", "bge-m3"),
        "ollama_base_url": config.get("ollama_base_url", "http://localhost:11434"),
        "moe_orchestrator_model": config.get("moe_orchestrator_model", ""),
        "moe_worker_model": config.get("moe_worker_model", ""),
        "moe_sub_mode": config.get("moe_sub_mode", "default"),
        "persona_name": config.get("persona_name", ""),
        "persona_system_prompt": config.get("persona_system_prompt", ""),
    }


def _patch_field_config(data: dict) -> None:
    server = _server()
    from palimind.config import config_path, load_config, palimind_dir

    if not server.state.active_field:
        return
    cfg = load_config(server.state.active_field)
    cfg.update(data)
    p_dir = palimind_dir(server.state.active_field)
    p_dir.mkdir(parents=True, exist_ok=True)
    config_path(server.state.active_field).write_text(json.dumps(cfg, indent=2), "utf-8")


@router.patch("/config/persona")
async def update_persona(req: Request, scope: str = "field"):
    server = _server()
    data = await req.json()
    patch = {}
    if "persona_name" in data:
        patch["persona_name"] = str(data["persona_name"]).strip()
    if "persona_system_prompt" in data:
        patch["persona_system_prompt"] = str(data["persona_system_prompt"])
    if scope.startswith("project:"):
        from palimind.config import load_config, save_config

        root = server._chat_root(scope)
        if root is None:
            return {"error": "Project not found"}
        cfg = load_config(root)
        cfg.update(patch)
        save_config(root, cfg)
        return {"status": "success", **patch}
    _patch_field_config(patch)
    return {"status": "success", **patch}


@router.patch("/config/moe")
async def update_moe_config(req: Request, scope: str = "field"):
    server = _server()
    data = await req.json()
    if scope.startswith("agent:"):
        return {"status": "success", "note": "MoE settings do not apply to an agent"}
    if scope == "chat":
        global_data = {}
        if server.GLOBAL_CONFIG_PATH.exists():
            try:
                global_data = json.loads(server.GLOBAL_CONFIG_PATH.read_text("utf-8"))
            except Exception:
                pass
        for key in ("moe_orchestrator_model", "moe_worker_model", "moe_sub_mode"):
            if key in data:
                global_data[key] = data[key]
        server._write_global_config(global_data)
        return {"status": "success"}
    from palimind.config import config_path, load_config, palimind_dir, save_config

    if scope.startswith("project:"):
        root = server._chat_root(scope)
        if root is None:
            return {"error": "Project not found"}
        cfg = load_config(root)
        for key in ("moe_orchestrator_model", "moe_worker_model", "moe_sub_mode"):
            if key in data:
                cfg[key] = data[key]
        save_config(root, cfg)
        return {"status": "success"}
    if server.state.active_field:
        cfg = load_config(server.state.active_field)
        for key in ("moe_orchestrator_model", "moe_worker_model", "moe_sub_mode"):
            if key in data:
                cfg[key] = data[key]
        p_dir = palimind_dir(server.state.active_field)
        p_dir.mkdir(parents=True, exist_ok=True)
        config_path(server.state.active_field).write_text(json.dumps(cfg, indent=2), "utf-8")
    return {"status": "success"}


@router.patch("/config/embed-model")
async def update_embed_model(req: Request, scope: str = "field"):
    server = _server()
    data = await req.json()
    model_id = str(data.get("embed_model", "")).strip()
    if not model_id:
        return {"error": "embed_model is required"}
    if scope.startswith("agent:"):
        return {"status": "success", "note": "Embed model does not apply to an agent"}
    if scope == "chat":
        global_data = {}
        if server.GLOBAL_CONFIG_PATH.exists():
            try:
                global_data = json.loads(server.GLOBAL_CONFIG_PATH.read_text("utf-8"))
            except Exception:
                pass
        global_data["embed_model"] = model_id
        server._write_global_config(global_data)
        return {"status": "success"}
    from palimind.config import config_path, load_config, palimind_dir, save_config

    if scope.startswith("project:"):
        root = server._chat_root(scope)
        if root is None:
            return {"error": "Project not found"}
        cfg = load_config(root)
        cfg["embed_model"] = model_id
        save_config(root, cfg)
        return {"status": "success"}
    if server.state.active_field:
        cfg = load_config(server.state.active_field)
        cfg["embed_model"] = model_id
        p_dir = palimind_dir(server.state.active_field)
        p_dir.mkdir(parents=True, exist_ok=True)
        config_path(server.state.active_field).write_text(json.dumps(cfg, indent=2), "utf-8")
    return {"status": "success"}


@router.get("/moe/hardware-check")
async def moe_hardware_check():
    server = _server()
    from palimind.config import load_config
    from palimind.hwfit.hardware import detect_hardware
    from palimind.llm.mixture_of_expert import estimate_hardware_requirements

    config = {}
    if server.state.active_field:
        config = load_config(server.state.active_field)
    orch = config.get("moe_orchestrator_model", "") or config.get("chat_model", "llama3")
    worker = config.get("moe_worker_model", "") or config.get("chat_model", "llama3")
    try:
        hw = await asyncio.to_thread(detect_hardware)
        gpu_vram = max(
            (g.vram_mb for g in hw.gpus if getattr(g, "backend", "") != "cpu"), default=0
        )
        sys_ram = hw.total_ram_mb
        estimate = estimate_hardware_requirements(
            orch, worker, num_workers=4, gpu_vram_mb=gpu_vram, system_ram_mb=sys_ram
        )
        return {
            "fits_gpu": estimate.fits_gpu,
            "fits_ram": estimate.fits_ram,
            "vram_per_worker_mb": estimate.vram_per_worker_mb,
            "vram_orchestrator_mb": estimate.vram_orchestrator_mb,
            "total_vram_needed_mb": estimate.total_vram_needed_mb,
            "total_ram_needed_mb": estimate.total_ram_needed_mb,
            "suggested_worker": estimate.suggested_worker,
            "suggested_orchestrator": estimate.suggested_orchestrator,
            "gpu_vram_mb": gpu_vram,
            "system_ram_mb": sys_ram,
        }
    except Exception:
        return {"error": "Failed to check MoE hardware"}


@router.get("/browser/screenshot")
async def browser_screenshot_live():
    from palimind.agents.tools.browser.tool import screenshot_png

    png = await asyncio.to_thread(screenshot_png)
    if not png:
        raise HTTPException(status_code=404, detail="No active browser session")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )
