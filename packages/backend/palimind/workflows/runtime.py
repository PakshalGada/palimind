"""Workflow execution on top of the durable job service."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from palimind.workflows import store

_TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def _lookup(path: str, context: dict[str, Any]) -> Any:
    value: Any = context
    for part in str(path).strip().split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, (list, tuple)):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                return ""
        else:
            return ""
    return value


def render(value: Any, context: dict[str, Any]) -> Any:
    """Render ``{{input}}`` / ``{{nodes.id.output}}`` templates recursively."""
    if isinstance(value, str):
        whole = _TEMPLATE_RE.fullmatch(value.strip())
        if whole:
            resolved = _lookup(whole.group(1), context)
            return "" if resolved is None else resolved
        return _TEMPLATE_RE.sub(lambda m: str(_lookup(m.group(1), context) or ""), value)
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, context) for v in value]
    return value


async def execute_workflow(
    workflow_id: str,
    *,
    input_text: str = "",
    trigger: dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
    run_id: str | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute one workflow and persist its node-by-node run summary."""
    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        raise KeyError(f"Workflow not found: {workflow_id}")
    run_id = run_id or str(uuid.uuid4())
    root = str(workspace_root or workflow.get("workspace_root") or "")
    order = store.topological_order(workflow)
    node_map = {str(n.get("id")): n for n in workflow.get("nodes") or []}
    run: dict[str, Any] = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_name": workflow.get("name") or "",
        "status": "running",
        "trigger": trigger or {"type": "manual"},
        "input": str(input_text or "")[:4000],
        "nodes": {},
        "created_at": time.time(),
        "started_at": time.time(),
        "finished_at": None,
        "error": "",
    }
    store.save_run(run)
    if on_event:
        on_event({"type": "workflow_start", "run_id": run_id, "workflow_id": workflow_id})

    context: dict[str, Any] = {"input": input_text, "nodes": {}}
    tool_ctx_set = False
    try:
        if root:
            from palimind.llm.mixture_of_expert.tools import set_tool_context

            set_tool_context(
                Path(root),
                agent_id="",
                session_id=f"_workflow:{run_id}",
                allow_network=False,
            )
            tool_ctx_set = True

        for node_id in order:
            if root:
                # An agent node installs its own tool context; restore the
                # workflow's workspace before the next tool node.
                from palimind.llm.mixture_of_expert.tools import set_tool_context

                set_tool_context(Path(root), agent_id="", session_id=f"_workflow:{run_id}")
            node = node_map.get(node_id) or {}
            node_type = str(node.get("type") or "tool")
            if on_event:
                on_event(
                    {
                        "type": "workflow_node_start",
                        "run_id": run_id,
                        "node_id": node_id,
                        "node_type": node_type,
                    }
                )
            try:
                if node_type == "agent":
                    output, status = await _run_agent_node(
                        node, context, input_text, workflow, run_id
                    )
                else:
                    output, status = await _run_tool_node(node, context)
            except Exception as exc:  # noqa: BLE001 - one node must not kill the report
                output, status = f"{type(exc).__name__}: {exc}", "error"
            context["nodes"][node_id] = {"output": output, "status": status}
            run["nodes"][node_id] = {
                "status": status,
                "output": str(output)[:20_000],
                "type": node_type,
                "updated_at": time.time(),
            }
            store.save_run(run)
            if on_event:
                on_event(
                    {
                        "type": "workflow_node_complete",
                        "run_id": run_id,
                        "node_id": node_id,
                        "status": status,
                    }
                )
            if status != "success" and str(workflow.get("on_error") or "stop") != "continue":
                run["status"] = "failed"
                run["error"] = f"node '{node_id}' failed: {output}"[:2000]
                break
        else:
            run["status"] = "completed"
    except Exception as exc:  # noqa: BLE001
        run["status"] = "failed"
        run["error"] = str(exc)[:2000]
    finally:
        if tool_ctx_set:
            try:
                from palimind.llm.mixture_of_expert.tools import set_tool_context

                set_tool_context(None)
            except Exception:
                pass
        run["finished_at"] = time.time()
        store.save_run(run)
        if on_event:
            on_event(
                {
                    "type": "workflow_complete",
                    "run_id": run_id,
                    "workflow_id": workflow_id,
                    "status": run["status"],
                }
            )
    return run


async def _run_tool_node(node: dict[str, Any], context: dict[str, Any]) -> tuple[str, str]:
    from palimind.llm.mixture_of_expert.tools import call_tool

    tool_name = str(node.get("tool") or "")
    raw_args = node.get("args")
    if not isinstance(raw_args, dict):
        raw_args = {"input": node.get("input") or "{{input}}"}
    args = render(raw_args, context)
    output = await asyncio.to_thread(call_tool, tool_name, **args)
    status = "error" if str(output).startswith("Error") else "success"
    return str(output), status


async def _run_agent_node(
    node: dict[str, Any],
    context: dict[str, Any],
    input_text: str,
    workflow: dict[str, Any],
    run_id: str,
) -> tuple[str, str]:
    from palimind.agents.registry import get_registry
    from palimind.agents.scheduler import recorded_run_status
    from palimind.agents.service import run_agent

    registry = get_registry()
    agent_id = str(node.get("agent_id") or "")
    defn = registry.get_by_id(agent_id) if agent_id else registry.get(str(node.get("agent") or ""))
    if defn is None:
        return f"Agent not found: {agent_id or node.get('agent')}", "error"
    prompt = render(node.get("input") or "{{input}}", context)
    if isinstance(prompt, dict):
        prompt = prompt.get("text") or str(prompt)
    output = await run_agent(
        defn,
        str(prompt or input_text),
        session_id=f"_workflow:{run_id}",
        interactive=False,
    )
    status = recorded_run_status(defn.id, str(prompt or input_text), output)
    return str(output), status


def enqueue_workflow(
    workflow_id: str,
    *,
    input_text: str = "",
    trigger: dict[str, Any] | None = None,
    workspace_root: str | Path | None = None,
    priority: int = 0,
    idempotency_key: str = "",
    max_attempts: int = 1,
) -> dict[str, Any]:
    """Enqueue one workflow run as a durable job."""
    from palimind.jobs import enqueue

    workflow = store.get_workflow(workflow_id)
    if workflow is None:
        raise KeyError(f"Workflow not found: {workflow_id}")
    return enqueue(
        "workflow",
        workflow_id,
        {
            "workflow_id": workflow_id,
            "input": str(input_text or ""),
            "trigger": trigger or {"type": "manual"},
            "workspace_root": str(workspace_root or workflow.get("workspace_root") or ""),
        },
        priority=int(priority or 0),
        idempotency_key=idempotency_key,
        max_attempts=max(1, int(max_attempts or 1)),
    )


def get_run(run_id: str) -> dict[str, Any] | None:
    return store.get_run(run_id)


def list_runs(workflow_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return store.list_runs(workflow_id, limit)
