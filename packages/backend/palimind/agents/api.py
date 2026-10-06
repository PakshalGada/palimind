from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from palimind.agents import activity, approvals
from palimind.agents.catalog import AgentDefinition
from palimind.agents.chat import clear_chat, read_chat
from palimind.agents.memory import read_memory
from palimind.agents.registry import get_registry
from palimind.agents.runtime import (
    cancel_agent,
    clear_agent_memory,
    delete_memory_entry,
    get_last_run,
    get_run,
    get_run_history,
    resolve_approval,
)
from palimind.agents.service import stream_agent
from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, _register_plugin_tools

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _agent_item(defn: AgentDefinition) -> dict[str, Any]:
    from palimind.agents.runtime import is_running

    item = defn.to_dict()
    last = get_last_run(defn.id)
    item["running"] = is_running(defn.id)
    item["last_run_status"] = last.get("status") if last else None
    item["last_run_at"] = last.get("timestamp") if last else None
    return item


@router.get("")
async def list_agents():
    agents = [_agent_item(d) for d in get_registry().all()]
    return {"agents": agents}


@router.post("/create")
async def create_agent(req: Request):
    body = await req.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return {"error": "name is required"}
    try:
        defn = AgentDefinition.from_dict(body)
        saved = get_registry().create(defn)
        return _agent_item(saved)
    except Exception:
        return {"error": "Failed to create agent"}


@router.patch("/{agent_id}")
async def update_agent(agent_id: str, req: Request):
    changes = await req.json()
    try:
        saved = get_registry().update(agent_id, changes)
        return _agent_item(saved)
    except Exception:
        return {"error": "Failed to update agent"}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    try:
        cancel_agent(agent_id)
        get_registry().delete(agent_id)
        return {"status": "success"}
    except Exception:
        return {"error": "Failed to delete agent"}


@router.get("/tools")
async def agent_tools():
    _register_plugin_tools()
    tools: dict[str, dict[str, Any]] = {}
    for name in sorted(TOOL_REGISTRY):
        info = TOOL_REGISTRY[name]
        meta = info.get("meta", {"tier": 3, "requires_approval": True})
        tools[name] = {
            "id": name,
            "description": info.get("description", ""),
            "parameters": info.get("parameters", {}),
            "tier": int(meta.get("tier", 3)),
            "requires_approval": bool(meta.get("requires_approval", True)),
        }
    return {"tools": tools}


@router.get("/skills")
async def agent_skills():
    """List the skills that can be attached to agents."""
    from palimind.agents.skills import list_skills

    return {"skills": list_skills()}


# ── Phase 4.1: adaptive reasoning ─────────────────────────────────────────


@router.get("/effort-levels")
async def effort_levels():
    from palimind.agents.adaptive_reasoning import list_effort_levels

    return {"levels": list_effort_levels()}


@router.post("/classify-effort")
async def classify_effort(req: Request):
    from palimind.agents.adaptive_reasoning import classify_complexity, effort_indicator

    body = await req.json()
    task = str(body.get("task", ""))
    model = str(body.get("model", "") or "")
    ollama_url = str(body.get("ollama_url", "") or "")
    result = classify_complexity(task, model, ollama_url)
    result["indicator"] = effort_indicator(result["level"])
    return result


# ── Phase 4.3: skills (validate / install / commands / marketplace) ───────


@router.post("/skills/validate")
async def validate_skill_endpoint(req: Request):
    from palimind.agents.skills import validate_skill

    body = await req.json()
    skill = body.get("skill", body)
    error = validate_skill(skill)
    return {"valid": error is None, "error": error}


@router.post("/skills/install")
async def install_skill_endpoint(req: Request):
    from palimind.agents.skills import install_skill

    body = await req.json()
    skill = body.get("skill", body)
    overwrite = bool(body.get("overwrite", False))
    try:
        installed = install_skill(
            skill, source=str(body.get("source", "user")), overwrite=overwrite
        )
        return {"status": "success", "skill": installed}
    except ValueError as e:
        return {"error": str(e)}


@router.post("/skills/uninstall")
async def uninstall_skill_endpoint(req: Request):
    from palimind.agents.skills import uninstall_skill

    body = await req.json()
    ok = uninstall_skill(str(body.get("id", "")))
    return {"status": "success" if ok else "not_found"}


@router.get("/skills/export")
async def export_skill_endpoint(id: str):
    from palimind.agents.skills import export_skill

    skill = export_skill(id)
    if skill is None:
        return {"error": "skill not found"}
    return {"skill": skill}


@router.get("/skills/marketplace")
async def marketplace_list():
    from palimind.agents.skills import list_marketplace

    return {"skills": list_marketplace()}


@router.post("/skills/marketplace/install")
async def marketplace_install(req: Request):
    from palimind.agents.skills import install_from_marketplace

    body = await req.json()
    try:
        installed = install_from_marketplace(
            str(body.get("id", "")), overwrite=bool(body.get("overwrite", False))
        )
        return {"status": "success", "skill": installed}
    except ValueError as e:
        return {"error": str(e)}


@router.get("/skills/commands")
async def skill_commands_endpoint():
    from palimind.agents.skills import skill_commands

    return {"commands": skill_commands()}


@router.post("/skills/resolve")
async def resolve_skill_command(req: Request):
    from palimind.agents.skills import resolve_command

    body = await req.json()
    resolved = resolve_command(str(body.get("text", "")))
    if resolved is None:
        return {"resolved": False}
    return {"resolved": True, **resolved}


# ── Phase 4.4: planning mode ──────────────────────────────────────────────


@router.get("/plan-templates")
async def plan_templates():
    from palimind.agents.planner import list_templates

    return {"templates": list_templates()}


@router.post("/plan")
async def create_plan(req: Request):
    from palimind.agents.planner import build_plan_from_template, generate_plan, save_plan

    body = await req.json()
    task = str(body.get("task", "")).strip()
    template = str(body.get("template", "") or "")
    if template:
        plan = build_plan_from_template(template, task)
        save_plan(plan)
        return {"plan": plan}
    model = str(body.get("model", "") or "")
    ollama_url = str(body.get("ollama_url", "") or "")
    agent_id = str(body.get("agent_id", "") or "")
    plan = generate_plan(task, model, ollama_url, agent_id=agent_id)
    save_plan(plan)
    return {"plan": plan}


@router.get("/plans")
async def list_plans_endpoint(limit: int = 50):
    from palimind.agents.planner import list_plans

    return {"plans": list_plans(limit=max(1, min(int(limit or 50), 200)))}


@router.get("/plans/{plan_id}")
async def get_plan_endpoint(plan_id: str):
    from palimind.agents.planner import get_plan

    plan = get_plan(plan_id)
    return plan if plan is not None else {"error": "plan not found"}


@router.patch("/plans/{plan_id}")
async def update_plan_endpoint(plan_id: str, req: Request):
    from palimind.agents.planner import update_plan

    body = await req.json()
    plan = update_plan(plan_id, body)
    return plan if plan is not None else {"error": "plan not found"}


@router.delete("/plans/{plan_id}")
async def delete_plan_endpoint(plan_id: str):
    from palimind.agents.planner import delete_plan

    ok = delete_plan(plan_id)
    return {"status": "success" if ok else "not_found"}


@router.post("/plans/{plan_id}/approve")
async def approve_plan_endpoint(plan_id: str, req: Request):
    from palimind.agents.planner import resolve_plan_review

    body = await req.json()
    approved = bool(body.get("approved", False))
    steps = body.get("steps")
    ok = resolve_plan_review(plan_id, approved, steps if isinstance(steps, list) else None)
    return {"status": "ok" if ok else "no_pending"}


@router.post("/plans/{plan_id}/execute")
async def execute_plan_endpoint(plan_id: str, req: Request):
    from palimind.agents.planner import execute_plan, get_plan

    plan = get_plan(plan_id)
    if plan is None:
        return {"error": "plan not found"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    from pathlib import Path as _Path

    working_root = body.get("working_root")
    result = await asyncio.to_thread(
        execute_plan,
        plan,
        working_root=_Path(working_root) if working_root else get_registry().field_root,
        auto_approve=bool(body.get("auto_approve", True)),
        rollback_on_failure=bool(body.get("rollback_on_failure", True)),
    )
    return {"plan": result}


# ── Phase 4.5: goals & background tasks ───────────────────────────────────


@router.get("/goals")
async def list_goals_endpoint():
    from palimind.agents.goals import list_goals

    return {"goals": list_goals()}


@router.post("/goals")
async def create_goal_endpoint(req: Request):
    from palimind.agents.goals import create_goal

    body = await req.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return {"error": "name is required"}
    goal = create_goal(
        name,
        str(body.get("objective", "")),
        success_criteria=str(body.get("success_criteria", "")),
        agent_id=str(body.get("agent_id", "") or ""),
        deadline=body.get("deadline"),
    )
    return {"goal": goal}


@router.get("/goals/{goal_id}")
async def get_goal_endpoint(goal_id: str):
    from palimind.agents.goals import get_goal

    goal = get_goal(goal_id)
    return goal if goal is not None else {"error": "goal not found"}


@router.patch("/goals/{goal_id}")
async def update_goal_endpoint(goal_id: str, req: Request):
    from palimind.agents.goals import update_goal

    body = await req.json()
    goal = update_goal(goal_id, body)
    return goal if goal is not None else {"error": "goal not found"}


@router.delete("/goals/{goal_id}")
async def delete_goal_endpoint(goal_id: str):
    from palimind.agents.goals import delete_goal

    ok = delete_goal(goal_id)
    return {"status": "success" if ok else "not_found"}


@router.post("/goals/{goal_id}/progress")
async def set_goal_progress(goal_id: str, req: Request):
    from palimind.agents.goals import set_progress

    body = await req.json()
    try:
        progress = float(body.get("progress", 0.0))
    except (TypeError, ValueError):
        return {"error": "progress must be a number"}
    goal = set_progress(goal_id, progress, note=str(body.get("note", "")))
    return goal if goal is not None else {"error": "goal not found"}


@router.get("/tasks")
async def list_tasks_endpoint(goal_id: str | None = None):
    from palimind.agents.goals import list_tasks

    return {"tasks": list_tasks(goal_id)}


@router.post("/tasks")
async def create_task_endpoint(req: Request):
    from palimind.agents.goals import create_task, parse_loop_command

    body = await req.json()
    # Accept either a "/loop 5m …" command or explicit fields.
    command = str(body.get("command", "") or "")
    parsed = parse_loop_command(command) if command else None
    if parsed is not None:
        interval = parsed["interval_seconds"]
        prompt = parsed["prompt"]
        kind = "loop"
    else:
        interval = int(body.get("interval_seconds", 0) or 0)
        prompt = str(body.get("prompt", "")).strip() or "Run your task."
        kind = "loop" if interval > 0 else "once"
    try:
        task = create_task(
            agent_id=str(body.get("agent_id", "") or ""),
            prompt=prompt,
            goal_id=str(body.get("goal_id", "") or ""),
            kind=kind,
            interval_seconds=interval,
        )
    except ValueError as e:
        return {"error": str(e)}
    return {"task": task}


@router.delete("/tasks/{task_id}")
async def delete_task_endpoint(task_id: str):
    from palimind.agents.goals import delete_task

    ok = delete_task(task_id)
    return {"status": "success" if ok else "not_found"}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task_endpoint(task_id: str):
    from palimind.agents.goals import cancel_task

    task = cancel_task(task_id)
    return {"task": task} if task is not None else {"error": "task not found"}


@router.get("/notifications")
async def notifications_endpoint(unread_only: bool = False):
    from palimind.agents.goals import list_notifications

    return {"notifications": list_notifications(unread_only=unread_only)}


@router.post("/notifications/read")
async def mark_notifications_endpoint(req: Request):
    from palimind.agents.goals import mark_notifications_read

    try:
        body = await req.json()
    except Exception:
        body = {}
    ids = body.get("ids")
    count = mark_notifications_read(ids if isinstance(ids, list) else None)
    return {"status": "success", "updated": count}


@router.delete("/notifications")
async def clear_notifications_endpoint():
    from palimind.agents.goals import clear_notifications

    clear_notifications()
    return {"status": "success"}


# ── Phase 4.6: verification ───────────────────────────────────────────────


@router.get("/verification/checklists")
async def verification_checklists():
    from palimind.agents.self_critique import TASK_TYPES, build_checklist

    return {"checklists": {task_type: build_checklist(task_type) for task_type in TASK_TYPES}}


@router.post("/verify")
async def verify_endpoint(req: Request):
    from palimind.agents.self_critique import verify_output

    body = await req.json()
    report = verify_output(
        str(body.get("task", "")),
        str(body.get("output", "")),
        str(body.get("model", "") or ""),
        str(body.get("ollama_url", "") or ""),
        task_type=body.get("task_type"),
        success_criteria=str(body.get("success_criteria", "")),
    )
    return {"report": report}


@router.get("/activity")
async def agent_activity():
    """Live activity for the Mission Control wall: what each agent is doing
    right now, plus a bounded wire of recent events."""
    return activity.snapshot()


@router.get("/approvals")
async def agent_approvals():
    """All pending human-in-the-loop approvals across agents (the Inbox)."""
    return {"approvals": approvals.list_pending()}


@router.get("/runs/recent")
async def recent_runs(limit: int = 30):
    """Recent runs across every agent, newest first (traces stripped)."""
    cap = max(1, min(int(limit or 30), 100))
    items: list[dict] = []
    for defn in get_registry().all():
        for record in get_run_history(defn.id, limit=cap):
            stripped = {k: v for k, v in record.items() if k != "trace"}
            items.append({"agent_id": defn.id, "agent_name": defn.name, **stripped})
    items.sort(key=lambda r: float(r.get("timestamp", 0) or 0), reverse=True)
    return {"runs": items[:cap]}


@router.post("/hooks/{token}")
async def agent_webhook(token: str, req: Request):
    """Run a webhook-mode agent. The token is the agent's webhook_token."""
    defn = get_registry().get_by_webhook_token(token)
    if defn is None:
        return {"error": "unknown webhook token"}
    if not defn.enabled:
        return {"error": "agent is disabled"}
    if defn.run_mode != "webhook":
        return {"error": "agent is not in webhook mode"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    payload = str(body.get("input") or body.get("q") or "").strip() or "Run your task."
    from palimind.agents.service import run_agent

    output = await run_agent(defn, payload, session_id="_webhook")
    return {"status": "success", "output": output}


@router.post("/validate-cron")
async def validate_cron(req: Request):
    from palimind.agents.catalog import validate_cron as vc

    body = await req.json()
    error = vc(str(body.get("schedule", "")))
    return {"valid": error is None, "error": error}


@router.post("/{agent_id}/recall-preview")
async def recall_preview(agent_id: str, req: Request):
    """Preview which memory entries would be recalled for a query."""
    body = await req.json()
    from palimind.agents.memory import recall_memory

    query = str(body.get("query", ""))
    k = int(body.get("k", 8) or 8)
    return {"entries": recall_memory(agent_id, query, k=k)}


@router.get("/{agent_id}/memory")
async def agent_memory(agent_id: str, page: int = 1, per_page: int = 20):
    entries = list(reversed(read_memory(agent_id)))  # newest first
    total = len(entries)
    per_page = max(1, min(per_page, 100))
    page = max(1, page)
    start = (page - 1) * per_page
    return {
        "entries": entries[start : start + per_page],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.delete("/{agent_id}/memory")
async def delete_agent_memory_entry(agent_id: str, index: int):
    # The frontend paginates newest-first; convert to the stored oldest-first index.
    total = len(read_memory(agent_id))
    delete_memory_entry(agent_id, total - 1 - index)
    return {"status": "success"}


@router.post("/{agent_id}/memory/clear")
async def clear_memory(agent_id: str):
    clear_agent_memory(agent_id)
    return {"status": "success"}


@router.get("/{agent_id}/history")
async def agent_history(agent_id: str, limit: int = 50):
    history = list(reversed(get_run_history(agent_id, limit=limit)))
    # The list view omits the (potentially large) reasoning trace; fetch a
    # single run via /runs/{run_id} when the user expands it.
    for record in history:
        record.pop("trace", None)
    return {"history": history}


@router.get("/{agent_id}/runs/{run_id}")
async def agent_run_detail(agent_id: str, run_id: str):
    record = get_run(agent_id, run_id)
    if record is None:
        return {"error": "run not found"}
    return record


@router.post("/{agent_id}/run")
async def run_agent(agent_id: str, req: Request):
    body = await req.json()
    agent_input = str(body.get("input", "")).strip() or "Run your task."
    session_id = str(body.get("session_id", "") or "")

    defn = get_registry().get_by_id(agent_id)
    if defn is None:

        async def err_stream():
            yield 'data: {"type": "error", "text": "Agent not found"}\n\n'
            yield 'data: {"type": "done"}\n\n'

        return StreamingResponse(err_stream(), media_type="text/event-stream")

    async def gen():
        import json

        async for ev in stream_agent(defn, agent_input, session_id):
            yield f"data: {json.dumps(ev)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/{agent_id}/orchestrate")
async def orchestrate_agent(agent_id: str, req: Request):
    """Run an agent in multi-agent orchestration mode (fan-out or arena)."""
    from dataclasses import replace

    from palimind.agents.service import agent_sse, stream_agent

    body = await req.json()
    task = str(body.get("task") or body.get("input") or "").strip() or "Run your task."
    mode = str(body.get("mode", "fan_out") or "fan_out")
    if mode not in ("fan_out", "arena"):
        mode = "fan_out"

    defn = get_registry().get_by_id(agent_id)
    if defn is None:

        async def err_stream():
            yield agent_sse("error", {"text": "Agent not found"})
            yield agent_sse("done", {})

        return StreamingResponse(err_stream(), media_type="text/event-stream")

    try:
        num_agents = int(body.get("num_agents") or defn.orchestration_agents or 0)
    except (TypeError, ValueError):
        num_agents = 0
    run_defn = replace(defn, orchestration=mode, orchestration_agents=num_agents)
    session_id = str(body.get("session_id", "") or "")

    async def gen():
        import json as _json

        async for ev in stream_agent(run_defn, task, session_id):
            yield f"data: {_json.dumps(ev)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{agent_id}/chat")
async def agent_chat(agent_id: str):
    return {"messages": read_chat(agent_id)}


@router.delete("/{agent_id}/chat")
async def delete_agent_chat(agent_id: str):
    clear_chat(agent_id)
    return {"status": "success"}


@router.post("/{agent_id}/cancel")
async def cancel(agent_id: str):
    ok = cancel_agent(agent_id)
    return {"status": "cancelled" if ok else "not_running"}


@router.post("/{agent_id}/approve")
async def approve(agent_id: str, req: Request):
    body = await req.json()
    approved = bool(body.get("approved", False))
    correction = str(body.get("correction", ""))
    ok = await resolve_approval(agent_id, approved, correction)
    return {"status": "ok" if ok else "no_pending"}
