"""File-backed store for board tasks (Phase 1 Task Board).

Tasks live in a single JSON list at ``~/.palimind/tasks.json``. Each task
carries an assigned agent and a free-form prompt; running a task executes that
agent (see ``api_server.run_task``) and the result is written back here *and*
into the agent's own chat history.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

TASKS_FILE = Path.home() / ".palimind" / "tasks.json"
_LOCK = threading.RLock()

_STATUSES = {"todo", "in_progress", "pending_approval", "completed", "failed"}
_PRIORITIES = {"low", "medium", "high", "critical"}


def _load() -> list[dict[str, Any]]:
    with _LOCK:
        if not TASKS_FILE.exists():
            return []
        try:
            data = json.loads(TASKS_FILE.read_text("utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []


def _save(items: list[dict[str, Any]]) -> None:
    with _LOCK:
        TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TASKS_FILE.write_text(json.dumps(items, indent=2), "utf-8")


def _normalize(raw: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    now = time.time()
    base = existing or {}
    status = str(raw.get("status") or base.get("status") or "todo")
    if status not in _STATUSES:
        status = "todo"
    priority = str(raw.get("priority") or base.get("priority") or "medium")
    if priority not in _PRIORITIES:
        priority = "medium"
    tags = raw.get("tags", base.get("tags", []))
    if not isinstance(tags, list):
        tags = []
    return {
        "id": str(base.get("id") or raw.get("id") or uuid.uuid4().hex),
        "agent_id": str(raw.get("agent_id", base.get("agent_id", "")) or ""),
        "agent_name": str(raw.get("agent_name", base.get("agent_name", "")) or ""),
        "title": str(raw.get("title", base.get("title", "")) or "Untitled task"),
        "description": str(raw.get("description", base.get("description", "")) or ""),
        "prompt": str(raw.get("prompt", base.get("prompt", "")) or ""),
        "status": status,
        "priority": priority,
        "created_at": base.get("created_at") or now,
        "started_at": raw.get("started_at", base.get("started_at")),
        "completed_at": raw.get("completed_at", base.get("completed_at")),
        "duration": raw.get("duration", base.get("duration")),
        "parent_task_id": raw.get("parent_task_id", base.get("parent_task_id", "")),
        "workflow_id": raw.get("workflow_id", base.get("workflow_id", "")),
        "progress": raw.get("progress", base.get("progress", 0)),
        "metadata": raw.get("metadata", base.get("metadata", {})) or {},
        "tags": [str(t) for t in tags],
        "output": str(raw.get("output", base.get("output", "")) or ""),
        "history": base.get("history", []) or [],
    }


def list_tasks() -> list[dict[str, Any]]:
    items = _load()
    items.sort(key=lambda t: t.get("created_at", 0), reverse=True)
    return items


def get_task(task_id: str) -> dict[str, Any] | None:
    for task in _load():
        if task.get("id") == task_id:
            return task
    return None


def create_task(raw: dict[str, Any]) -> dict[str, Any]:
    items = _load()
    task = _normalize(raw)
    task["id"] = str(raw.get("id") or uuid.uuid4().hex)
    items.append(task)
    _save(items)
    return task


def update_task(task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    changes = dict(changes)
    actor = str(changes.pop("_actor", "user"))
    items = _load()
    for i, task in enumerate(items):
        if task.get("id") != task_id:
            continue
        if "status" in changes and changes["status"] != task.get("status"):
            task = {**task, "history": task.get("history", []) + [{
                "id": uuid.uuid4().hex,
                "task_id": task_id,
                "from_status": task.get("status"),
                "to_status": changes["status"],
                "timestamp": time.time(),
                "actor": actor,
            }]}
        merged = {**task, **changes}
        merged["id"] = task_id
        merged["created_at"] = task.get("created_at")
        items[i] = _normalize(merged, task)
        items[i]["id"] = task_id
        _save(items)
        return items[i]
    return None


def delete_task(task_id: str) -> bool:
    items = _load()
    remaining = [t for t in items if t.get("id") != task_id]
    if len(remaining) == len(items):
        return False
    _save(remaining)
    return True
