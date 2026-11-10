from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from palimind.agents import activity, approvals, questions
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
    is_running,
    resolve_approval,
    set_agent_plan,
    validate_approval_args,
)
from palimind.agents.service import stream_agent
from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY, _register_plugin_tools

router = APIRouter(prefix="/api/agents", tags=["agents"])

_background_tasks: set[asyncio.Task] = set()


def _agent_item(defn: AgentDefinition) -> dict[str, Any]:
    from palimind.agents.runtime import is_running, running_count

    item = defn.to_dict()
    last = get_last_run(defn.id)
    item["running"] = is_running(defn.id)
    item["active_runs"] = running_count(defn.id)
    item["last_run_status"] = last.get("status") if last else None
    item["last_run_at"] = last.get("timestamp") if last else None
    item["unread_count"] = _unread_count(defn.id)
    return item


def _unread_count(agent_id: str) -> int:
    """Count agent replies after the active conversation's last-read marker."""
    try:
        from palimind.agents.chat import agent_session_root
        from palimind.memory import session_store

        root = agent_session_root(agent_id)
        if not session_store.has_session_data(root):
            return 0
        data = session_store.load_sessions(root)
        active = data.get("active_session_id")
        session = next((item for item in data.get("sessions", []) if item.get("id") == active), None)
        if not session:
            return 0
        last_read = int(session.get("last_read_message_id") or 0)
        if last_read <= 0:
            return 0
        return sum(
            1
            for message in session.get("messages", [])
            if int(message.get("id") or 0) > last_read and message.get("role") != "user"
        )
    except Exception:
        return 0


@router.get("/setup-status")
async def agent_setup_status():
    """Readiness for the agent wizard. Lists models; never runs a completion."""
    import asyncio

    from palimind.agents.providers_api import _opencode_catalog, _opencode_key_present
    from palimind.config import load_global_config
    from palimind.opencode.router import fetch_ollama_model_ids

    config = load_global_config()
    ollama_url = str(config.get("ollama_base_url") or "http://localhost:11434")
    try:
        local_models = sorted(
            await asyncio.to_thread(fetch_ollama_model_ids, ollama_url)
        )
    except Exception:
        local_models = []
    key_present = await asyncio.to_thread(_opencode_key_present)
    hosted_models = await asyncio.to_thread(_opencode_catalog) if key_present else []
    return {
        "local": {
            "ollama_url": ollama_url,
            "ready": bool(local_models),
            "models": local_models,
        },
        "opencode": {
            "key_present": key_present,
            "ready": bool(key_present and hosted_models),
            "models": [model.get("id") for model in hosted_models],
        },
        "default_model": str(config.get("chat_model") or ""),
    }


@router.get("")
async def list_agents(include_hidden: bool = False):
    agents = [
        _agent_item(d)
        for d in get_registry().all()
        if include_hidden or not getattr(d, "hidden_at", "")
    ]
    return {"agents": agents}


@router.get("/hidden")
async def list_hidden_agents():
    return {"agents": [_agent_item(d) for d in get_registry().all() if getattr(d, "hidden_at", "")]}


@router.post("/{agent_id}/hide")
async def hide_agent(agent_id: str):
    from datetime import UTC, datetime

    try:
        saved = get_registry().update(agent_id, {"hidden_at": datetime.now(UTC).isoformat()})
        return _agent_item(saved)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/{agent_id}/restore")
async def restore_agent(agent_id: str):
    try:
        saved = get_registry().update(agent_id, {"hidden_at": ""})
        return _agent_item(saved)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


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
    except ValueError as e:
        return {"error": str(e) or "Invalid agent definition"}
    except Exception as e:
        return {"error": f"Failed to create agent: {e}"}


@router.patch("/{agent_id}")
async def update_agent(agent_id: str, req: Request):
    changes = await req.json()
    try:
        saved = get_registry().update(agent_id, changes)
        return _agent_item(saved)
    except ValueError as e:
        return {"error": str(e) or "Invalid agent definition"}
    except KeyError:
        return {"error": "Agent not found"}
    except Exception as e:
        return {"error": f"Failed to update agent: {e}"}


@router.delete("/all")
async def delete_all_agents():
    """Wipe every agent definition (and its memory/chat files)."""
    try:
        count = get_registry().delete_all()
        return {"status": "success", "deleted": count}
    except Exception:
        return {"error": "Failed to delete all agents"}


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
    from palimind.agents.tools.base import parameters_to_schema

    tools: dict[str, dict[str, Any]] = {}
    for name in sorted(TOOL_REGISTRY):
        info = TOOL_REGISTRY[name]
        meta = info.get("meta", {"tier": 3, "requires_approval": True})
        tools[name] = {
            "id": name,
            "description": info.get("description", ""),
            "parameters": parameters_to_schema(info.get("parameters") or {}),
            "tier": int(meta.get("tier", 3)),
            "requires_approval": bool(meta.get("requires_approval", True)),
            "timeout_s": int(info.get("timeout_s") or 0),
            "parallel_safe": bool(info.get("parallel_safe", False)),
            "idempotent": bool(info.get("idempotent", False)),
            "source": str(info.get("source", "builtin")),
        }
    return {"tools": tools}


@router.post("/tools/reload")
async def reload_agent_tools():
    """Re-scan built-in and ~/.palimind/tools drop-in tools without a restart."""
    from palimind.agents.tools.registry import reload_tools

    try:
        discovered = reload_tools()
        _register_plugin_tools(force=True)
        return {
            "status": "success",
            "discovered": len(discovered),
            "tools": sorted(TOOL_REGISTRY),
        }
    except Exception as exc:
        return {"error": f"Failed to reload tools: {exc}"}


@router.post("/{agent_id}/tools/{tool_name}/invoke")
async def invoke_agent_tool(agent_id: str, tool_name: str, req: Request):
    """Run one tool in the agent's workspace (Inspector tool playground)."""
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    _register_plugin_tools()
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        body = await req.json()
    except Exception:  # noqa: BLE001
        body = {}
    args = body.get("args") if isinstance(body, dict) else None
    if not isinstance(args, dict):
        args = {}

    from palimind.agents.scope import resolve_scope
    from palimind.llm.mixture_of_expert.tools import call_tool, set_tool_context

    primary_root, extra_roots = resolve_scope(defn, get_registry().field_root)

    def _run() -> str:
        set_tool_context(
            primary_root,
            extra_roots=extra_roots,
            read_only_roots=extra_roots,
            agent_id=defn.id,
            write_access=bool(defn.write_access),
            desktop_access=bool(getattr(defn, "desktop_access", False)),
            desktop_control=bool(getattr(defn, "desktop_control", False)),
            desktop_allowed_apps=list(getattr(defn, "desktop_allowed_apps", []) or []),
        )
        return call_tool(tool_name, **args)

    try:
        output = await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001 - the playground shows the error
        return {"error": str(exc)}
    return {"tool": tool_name, "output": output}


@router.get("/plugins")
async def agent_plugins():
    from palimind.agents.plugins import list_plugins

    return {"plugins": list_plugins()}


@router.post("/plugins/install")
async def install_agent_plugin(req: Request):
    from palimind.agents.plugins import install_plugin

    body = await req.json()
    try:
        return {
            "plugin": install_plugin(
                str(body.get("plugin_id") or ""),
                overwrite=bool(body.get("overwrite", False)),
            )
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.delete("/plugins/{plugin_id}")
async def uninstall_agent_plugin(plugin_id: str):
    from palimind.agents.plugins import uninstall_plugin

    return {"deleted": uninstall_plugin(plugin_id)}


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
    # LLM call: run off the event loop so it doesn't stall every request.
    result = await asyncio.to_thread(classify_complexity, task, model, ollama_url)
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
    plan = await asyncio.to_thread(generate_plan, task, model, ollama_url, agent_id=agent_id)
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
    report = await asyncio.to_thread(
        verify_output,
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


@router.get("/questions")
async def agent_questions(agent_id: str = ""):
    """Questions an agent asked a human and is still waiting on."""
    return {"questions": questions.list_pending(agent_id)}


@router.post("/{agent_id}/answer")
async def answer_agent_question(agent_id: str, req: Request):
    body = await req.json()
    question_id = str(body.get("question_id") or "")
    answer = str(body.get("answer") or "")
    choice = str(body.get("choice") or "")
    ok = questions.answer(question_id, answer=answer, choice=choice)
    return {"status": "ok" if ok else "no_pending"}


@router.post("/{agent_id}/runs/{run_id}/plan")
async def set_run_plan(agent_id: str, run_id: str, req: Request):
    body = await req.json()
    items = body.get("items")
    if not isinstance(items, list):
        return {"error": "items must be a list"}
    ok = set_agent_plan(agent_id, items, run_id)
    return {"status": "ok" if ok else "not_running"}


@router.get("/{agent_id}/starters")
async def agent_starters(agent_id: str):
    """Deterministic starter prompts derived from the agent's own brief."""
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found", "prompts": []}
    from palimind.agents.suggestions import starter_prompts

    return {"prompts": starter_prompts(defn)}


@router.get("/runs/recent")
async def recent_runs(limit: int = 30):
    """Recent runs across every agent and team, newest first (traces stripped)."""
    cap = max(1, min(int(limit or 30), 100))
    items: list[dict] = []
    from palimind.agents import run_state as run_state_mod

    for defn in get_registry().all():
        for record in get_run_history(defn.id, limit=cap):
            stripped = {k: v for k, v in record.items() if k != "trace"}
            checkpoint = run_state_mod.load_state(str(record.get("run_id") or ""))
            if checkpoint:
                stripped["checkpoint_status"] = checkpoint.get("status")
                stripped["checkpoint_step"] = checkpoint.get("iteration")
                stripped["resumable"] = bool(checkpoint.get("resumable")) or (
                    str(checkpoint.get("status") or "") in run_state_mod.RESUMABLE_STATUSES
                    and bool(checkpoint.get("messages"))
                )
            items.append({"agent_id": defn.id, "agent_name": defn.name, **stripped})
    try:
        from palimind.agents import teams

        for team in teams.list_teams():
            team_key = f"team:{team['id']}"
            for record in get_run_history(team_key, limit=cap):
                stripped = {k: v for k, v in record.items() if k != "trace"}
                items.append(
                    {
                        "agent_id": team_key,
                        "agent_name": team.get("display_name") or team.get("name") or "Team",
                        **stripped,
                    }
                )
    except Exception:
        pass
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

    output = await run_agent(defn, payload, session_id="_webhook", interactive=False)
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


@router.delete("/{agent_id}/runs")
async def clear_agent_runs(agent_id: str):
    from palimind.storage import state_store

    try:
        state_store.delete_runs(agent_id)
        return {"status": "success"}
    except Exception:
        return {"error": "Failed to clear run history"}


@router.get("/{agent_id}/runs/{run_id}")
async def agent_run_detail(agent_id: str, run_id: str):
    record = get_run(agent_id, run_id)
    if record is None:
        return {"error": "run not found"}
    return record


@router.get("/{agent_id}/runs/{run_id}/state")
async def agent_run_state(agent_id: str, run_id: str):
    """Return the persisted checkpoint for a run (if one exists)."""
    from palimind.agents import run_state

    state = run_state.load_state(run_id)
    if state is None:
        return {"error": "run state not found"}
    if state.get("agent_id") and str(state["agent_id"]) != agent_id:
        return {"error": "run does not belong to this agent"}
    status = str(state.get("status") or "")
    resumable = bool(state.get("resumable")) or (
        status in run_state.RESUMABLE_STATUSES and bool(state.get("messages"))
    )
    return {
        "state": state,
        "resumable": resumable,
        "running": is_running(agent_id),
    }


@router.post("/{agent_id}/runs/{run_id}/resume")
async def resume_agent_run(agent_id: str, run_id: str, req: Request):
    """Resume a checkpointed run from its last completed step.

    Streams the same ``agent:*`` SSE events as ``POST /{agent_id}/run``. The
    resumed run gets a new run id and is linked back to the original checkpoint.
    """
    import json

    from palimind.agents import run_state

    try:
        body = await req.json()
    except Exception:
        body = {}

    state = run_state.load_state(run_id)
    if state is None:
        return {"error": "run state not found"}
    if state.get("agent_id") and str(state["agent_id"]) != agent_id:
        return {"error": "run does not belong to this agent"}
    status = str(state.get("status") or "")
    if status not in run_state.RESUMABLE_STATUSES or not state.get("messages"):
        return {"error": f"run is not resumable (status={status or 'unknown'})"}
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    if not defn.enabled:
        return {"error": "Agent is disabled"}
    if status == "running" and is_running(agent_id):
        return {"error": "run is still active; stop it before resuming"}

    input_text = str(body.get("input") or state.get("input") or "Run your task.").strip()
    session_id = str(body.get("session_id") or state.get("session_id") or "")

    async def gen():
        async for ev in stream_agent(
            defn,
            input_text,
            session_id,
            resume_state=state,
            resume_from_run_id=run_id,
        ):
            yield f"data: {json.dumps(ev)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


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

    if not defn.enabled:

        async def err_stream():
            yield 'data: {"type": "error", "text": "Agent is disabled"}\n\n'
            yield 'data: {"type": "done"}\n\n'

        return StreamingResponse(err_stream(), media_type="text/event-stream")

    async def gen():
        import json

        async for ev in stream_agent(defn, agent_input, session_id):
            yield f"data: {json.dumps(ev)}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/{agent_id}/run-now")
async def run_agent_now(agent_id: str, req: Request):
    """Start a manual background run (no approval prompts) and return at once."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    agent_input = str((body or {}).get("input", "")).strip() or "Run your task."
    defn = get_registry().get_by_id(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    if not defn.enabled:
        return {"error": "Agent is disabled"}

    from palimind.agents.runtime import running_count
    from palimind.agents.scheduler import post_result, recorded_run_status
    from palimind.agents.service import run_agent as run_once

    if running_count(defn.id) >= max(1, int(defn.max_concurrent_runs or 1)):
        try:
            from palimind.agents import queue

            item = queue.enqueue("agent", defn.id, agent_input)
            return {"status": "queued", "item_id": item.get("id")}
        except Exception:
            pass

    async def _run():
        try:
            output = await run_once(defn, agent_input, session_id="_manual", interactive=False)
            status = recorded_run_status(defn.id, agent_input, output)
            await post_result(defn, output, status, "manual")
        except asyncio.CancelledError:
            await post_result(defn, "[cancelled]", "cancelled", "manual")
            raise
        except Exception as e:
            await post_result(defn, f"[error] {e}", "error", "manual")

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started"}


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

    if not defn.enabled:

        async def err_stream():
            yield agent_sse("error", {"text": "Agent is disabled"})
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


@router.delete("/{agent_id}/sessions")
async def clear_agent_sessions(agent_id: str):
    """Clear the agent's private conversation store (not its workspace)."""
    import shutil

    from palimind.agents.chat import agent_session_root

    try:
        root = agent_session_root(agent_id)
        shutil.rmtree(root / ".palimind", ignore_errors=True)
        clear_chat(agent_id)
        return {"status": "success"}
    except Exception:
        return {"error": "Failed to clear agent conversation"}


@router.post("/{agent_id}/cancel")
async def cancel(agent_id: str, req: Request):
    run_id = ""
    try:
        body = await req.json()
        if isinstance(body, dict):
            run_id = str(body.get("run_id", "") or "")
    except Exception:
        run_id = ""
    count = cancel_agent(agent_id, run_id or None)
    return {"status": "cancelled" if count else "not_running", "cancelled": count}


@router.post("/{agent_id}/approve")
async def approve(agent_id: str, req: Request):
    body = await req.json()
    approved = bool(body.get("approved", False))
    correction = str(body.get("correction", ""))
    run_id = str(body.get("run_id", "") or "")
    override = body.get("args")
    if approved and override is not None:
        if not isinstance(override, dict):
            return {"status": "error", "error": "args must be an object"}
        error = validate_approval_args(agent_id, override, run_id or None)
        if error:
            return {"status": "error", "error": error}
    ok = await resolve_approval(
        agent_id,
        approved,
        correction,
        run_id or None,
        args=override if isinstance(override, dict) else None,
    )
    return {"status": "ok" if ok else "no_pending"}
