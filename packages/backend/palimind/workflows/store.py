"""Workflow definitions, validation and DAG ordering.

Workflows are small JSON DAGs executed by the durable job service. A node is
either a tool call or an agent run; edges (or ``depends_on``) define ordering.
Definitions are persisted in the global state DB so they survive restarts.
"""

from __future__ import annotations

import secrets
import time
import uuid
from typing import Any

from palimind.storage import state_store

WORKFLOW_NS = "workflows"
RUN_NS = "workflow_runs"
TRIGGER_TYPES = ("manual", "cron", "file", "webhook")
NODE_TYPES = ("tool", "agent")


def _now() -> float:
    return time.time()


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    raw_trigger = data.get("trigger")
    trigger: dict[str, Any] = raw_trigger if isinstance(raw_trigger, dict) else {}
    trigger_type = str(trigger.get("type") or "manual")
    if trigger_type not in TRIGGER_TYPES:
        trigger_type = "manual"
    return {
        "id": str(data.get("id") or uuid.uuid4()),
        "name": str(data.get("name") or "Workflow").strip()[:120],
        "description": str(data.get("description") or "")[:2000],
        "enabled": bool(data.get("enabled", True)),
        "trigger": {
            "type": trigger_type,
            "cron": str(trigger.get("cron") or ""),
            "pattern": str(trigger.get("pattern") or ""),
            "token": str(trigger.get("token") or ""),
        },
        "nodes": [dict(n) for n in (data.get("nodes") or []) if isinstance(n, dict)],
        "edges": [
            [str(e[0]), str(e[1])]
            for e in (data.get("edges") or [])
            if isinstance(e, (list, tuple)) and len(e) == 2
        ],
        "workspace_root": str(data.get("workspace_root") or ""),
        "on_error": str(data.get("on_error") or "stop"),
        "created_at": float(data.get("created_at") or _now()),
        "updated_at": _now(),
    }


def validate_workflow(data: dict[str, Any]) -> str | None:
    if not str(data.get("name") or "").strip():
        return "name is required"
    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    if not nodes:
        return "at least one node is required"
    ids: set[str] = set()
    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            return "every node needs an id"
        if node_id in ids:
            return f"duplicate node id: {node_id}"
        ids.add(node_id)
        node_type = str(node.get("type") or "tool")
        if node_type not in NODE_TYPES:
            return f"node '{node_id}' type must be one of {NODE_TYPES}"
        if node_type == "tool" and not str(node.get("tool") or "").strip():
            return f"tool node '{node_id}' requires 'tool'"
        if (
            node_type == "agent"
            and not str(node.get("agent_id") or node.get("agent") or "").strip()
        ):
            return f"agent node '{node_id}' requires 'agent_id' or 'agent'"
    edges = data.get("edges") or []
    for edge in edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            return "edges must be [from, to] pairs"
        if str(edge[0]) not in ids or str(edge[1]) not in ids:
            return f"edge references unknown node: {edge}"
    try:
        topological_order({**data, "nodes": nodes, "edges": edges})
    except ValueError as exc:
        return str(exc)
    raw_trigger = data.get("trigger")
    trigger: dict[str, Any] = raw_trigger if isinstance(raw_trigger, dict) else {}
    trigger_type = str(trigger.get("type") or "manual")
    if trigger_type not in TRIGGER_TYPES:
        return f"trigger.type must be one of {TRIGGER_TYPES}"
    if trigger_type == "cron":
        from palimind.agents.catalog import validate_cron

        error = validate_cron(str(trigger.get("cron") or ""))
        if error:
            return error
    if trigger_type == "file" and not str(trigger.get("pattern") or "").strip():
        return "file triggers require a glob pattern"
    return None


def topological_order(data: dict[str, Any]) -> list[str]:
    """Return node ids in dependency order or raise ValueError on a cycle."""
    nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    ids = [str(n.get("id")) for n in nodes]
    deps: dict[str, set[str]] = {node_id: set() for node_id in ids}
    for node in nodes:
        node_id = str(node.get("id"))
        for dep in node.get("depends_on") or []:
            if str(dep) in deps:
                deps[node_id].add(str(dep))
    for edge in data.get("edges") or []:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            src, dst = str(edge[0]), str(edge[1])
            if src in deps and dst in deps:
                deps[dst].add(src)
    order: list[str] = []
    ready = [node_id for node_id in ids if not deps[node_id]]
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for other in ids:
            if node_id in deps[other]:
                deps[other].discard(node_id)
                if not deps[other] and other not in order and other not in ready:
                    ready.append(other)
    if len(order) != len(ids):
        raise ValueError("workflow graph contains a cycle")
    return order


def create_workflow(data: dict[str, Any]) -> dict[str, Any]:
    error = validate_workflow(data)
    if error:
        raise ValueError(error)
    workflow = _normalise(data)
    if workflow["trigger"]["type"] == "webhook" and not workflow["trigger"]["token"]:
        workflow["trigger"]["token"] = secrets.token_urlsafe(24)
    state_store.set_json(WORKFLOW_NS, workflow["id"], workflow)
    return workflow


def update_workflow(workflow_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    existing = get_workflow(workflow_id)
    if existing is None:
        raise KeyError("Workflow not found")
    merged = {**existing, **changes, "id": workflow_id, "created_at": existing["created_at"]}
    if isinstance(changes.get("trigger"), dict):
        merged["trigger"] = {**existing.get("trigger", {}), **changes["trigger"]}
    error = validate_workflow(merged)
    if error:
        raise ValueError(error)
    workflow = _normalise(merged)
    if workflow["trigger"]["type"] == "webhook" and not workflow["trigger"]["token"]:
        workflow["trigger"]["token"] = secrets.token_urlsafe(24)
    state_store.set_json(WORKFLOW_NS, workflow_id, workflow)
    return workflow


def get_workflow(workflow_id: str) -> dict[str, Any] | None:
    value = state_store.get_json(WORKFLOW_NS, str(workflow_id or ""), default=None)
    return value if isinstance(value, dict) else None


def get_by_webhook_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    for workflow in list_workflows(limit=1000):
        if secrets.compare_digest(str(workflow.get("trigger", {}).get("token") or ""), token):
            return workflow
    return None


def list_workflows(limit: int = 200) -> list[dict[str, Any]]:
    items = state_store.list_json(WORKFLOW_NS, limit=max(1, min(int(limit or 200), 1000)))
    items.sort(key=lambda w: float(w.get("updated_at", 0) or 0), reverse=True)
    return items


def delete_workflow(workflow_id: str) -> bool:
    if get_workflow(workflow_id) is None:
        return False
    state_store.delete_json(WORKFLOW_NS, str(workflow_id))
    return True


# ── run summaries ─────────────────────────────────────────────────────────


def save_run(run: dict[str, Any]) -> dict[str, Any]:
    run["updated_at"] = _now()
    state_store.set_json(RUN_NS, str(run["run_id"]), run)
    return run


def get_run(run_id: str) -> dict[str, Any] | None:
    value = state_store.get_json(RUN_NS, str(run_id or ""), default=None)
    return value if isinstance(value, dict) else None


def list_runs(workflow_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    items = state_store.list_json(RUN_NS, limit=max(1, min(int(limit or 50), 500)))
    if workflow_id:
        items = [r for r in items if str(r.get("workflow_id") or "") == str(workflow_id)]
    items.sort(key=lambda r: float(r.get("created_at", 0) or 0), reverse=True)
    return items
