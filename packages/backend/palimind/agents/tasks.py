"""Agent task lanes.

A task is a separate execution thread of one agent.  The agent keeps one
identity, workspace and profile; each task has its own thread, provider
session, conversation, queue item and result.  The main chat lane does not
count toward the task limit.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from palimind.storage import state_store

DEFAULT_TASK_LIMIT = 2
MAX_TASK_LIMIT = 8
MAX_OPEN_TASKS = 50
ACTIVE_STATUSES = ("open", "running")
TERMINAL_STATUSES = ("completed", "failed", "cancelled", "closed")


def _now() -> float:
    return time.time()


def _load(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    value = _load(row["value"])
    return {
        **value,
        "id": row["id"],
        "agent_id": row["agent_id"],
        "thread_id": row["thread_id"],
        "parent_task_id": row["parent_task_id"],
        "owner_agent_id": row["owner_agent_id"],
        "status": row["status"],
        "priority": row["priority"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "closed_at": row["closed_at"],
    }


def task_limit(definition: Any) -> int:
    raw = definition.get("task_limit", DEFAULT_TASK_LIMIT) if isinstance(definition, dict) else getattr(definition, "task_limit", DEFAULT_TASK_LIMIT)
    try:
        value = int(raw or DEFAULT_TASK_LIMIT)
    except (TypeError, ValueError):
        value = DEFAULT_TASK_LIMIT
    return max(1, min(value, MAX_TASK_LIMIT))


def create_task(
    agent_id: str,
    title: str,
    *,
    input_text: str = "",
    thread_id: str = "",
    parent_task_id: str = "",
    owner_agent_id: str = "",
    priority: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agent_id = str(agent_id or "").strip()
    if not agent_id:
        raise ValueError("agent_id is required")
    if open_task_count(agent_id) >= MAX_OPEN_TASKS:
        raise ValueError(f"agent has reached the open task limit ({MAX_OPEN_TASKS})")
    from palimind.agents import threads

    thread = threads.get_thread(thread_id) if thread_id else None
    if thread is None:
        thread = threads.create_thread(
            agent_id, kind="task", metadata={"title": str(title or "Task")}
        )
    task_id = str(uuid.uuid4())
    now = _now()
    value = {
        "title": str(title or "Task")[:200],
        "input": str(input_text or "")[:4000],
        "result": "",
        "error": "",
        "revision": 1,
        "metadata": dict(metadata or {}),
    }
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO agent_tasks
                (id, agent_id, thread_id, parent_task_id, owner_agent_id, status,
                 priority, value, created_at, updated_at, closed_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, NULL)
            """,
            (
                task_id,
                agent_id,
                str(thread.get("id") or ""),
                str(parent_task_id or ""),
                str(owner_agent_id or agent_id),
                int(priority or 0),
                json.dumps(value),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_task(task_id) or {}


def get_task(task_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    return _row(row)


def list_tasks(
    agent_id: str = "",
    *,
    status: str = "",
    include_closed: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if agent_id:
        clauses.append("agent_id=?")
        args.append(agent_id)
    if status:
        clauses.append("status=?")
        args.append(status)
    elif not include_closed:
        clauses.append("status NOT IN ('closed')")
    args.append(max(1, min(int(limit or 100), 500)))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM agent_tasks {where} ORDER BY priority DESC, created_at DESC LIMIT ?",
            args,
        ).fetchall()
    finally:
        conn.close()
    return [task for task in (_row(row) for row in rows) if task is not None]


def open_task_count(agent_id: str) -> int:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM agent_tasks WHERE agent_id=? AND status IN ('open','running')",
            (agent_id,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0] if row else 0)


def running_task_count(agent_id: str) -> int:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM agent_tasks WHERE agent_id=? AND status='running'",
            (agent_id,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0] if row else 0)


def can_start_task(agent_id: str, definition: Any = None) -> tuple[bool, str]:
    if open_task_count(agent_id) >= MAX_OPEN_TASKS:
        return False, f"open task limit ({MAX_OPEN_TASKS}) reached"
    limit = task_limit(definition) if definition is not None else DEFAULT_TASK_LIMIT
    if running_task_count(agent_id) >= limit:
        return False, f"task limit ({limit}) reached"
    return True, ""


def update_task(task_id: str, **changes: Any) -> dict[str, Any] | None:
    task = get_task(task_id)
    if task is None:
        return None
    value = dict(task)
    for key, item in changes.items():
        if key in {"title", "input", "result", "error", "metadata"}:
            value[key] = item
    status = str(changes.get("status") or task.get("status") or "open")
    now = _now()
    closed_at = task.get("closed_at")
    if status in TERMINAL_STATUSES:
        closed_at = closed_at or now
    elif status in ACTIVE_STATUSES:
        closed_at = None
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            UPDATE agent_tasks SET status=?, priority=?, value=?, updated_at=?, closed_at=?
            WHERE id=?
            """,
            (
                status,
                int(changes.get("priority", task.get("priority") or 0)),
                json.dumps(
                    {
                        "title": value.get("title") or "",
                        "input": value.get("input") or "",
                        "result": value.get("result") or "",
                        "error": value.get("error") or "",
                        "revision": int(task.get("revision") or 1),
                        "metadata": value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
                    }
                ),
                now,
                closed_at,
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_task(task_id)


def mark_running(task_id: str) -> dict[str, Any] | None:
    return update_task(task_id, status="running")


def complete_task(task_id: str, result: str, *, status: str = "completed") -> dict[str, Any] | None:
    return update_task(task_id, status=status, result=str(result or ""), error="" if status == "completed" else None)


def fail_task(task_id: str, error: str) -> dict[str, Any] | None:
    return update_task(task_id, status="failed", error=str(error or ""))


def close_task(task_id: str) -> dict[str, Any] | None:
    return update_task(task_id, status="closed")


def reopen_task(task_id: str) -> dict[str, Any] | None:
    if open_task_count((get_task(task_id) or {}).get("agent_id", "")) >= MAX_OPEN_TASKS:
        raise ValueError(f"open task limit ({MAX_OPEN_TASKS}) reached")
    return update_task(task_id, status="open", closed_at=None)


def stop_task(task_id: str) -> dict[str, Any] | None:
    task = get_task(task_id)
    if task is None:
        return None
    try:
        from palimind.agents import queue

        for item in queue.list_queue("task", task_id, limit=200):
            if item.get("status") in ("queued", "running", "paused"):
                queue.cancel_item(item["id"])
    except Exception:
        pass
    return update_task(task_id, status="cancelled")


def delete_task(task_id: str) -> bool:
    conn = state_store.state_connection()
    try:
        cursor = conn.execute("DELETE FROM agent_tasks WHERE id=?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_tasks_for_agent(agent_id: str) -> int:
    conn = state_store.state_connection()
    try:
        cursor = conn.execute("DELETE FROM agent_tasks WHERE agent_id=?", (agent_id,))
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()
