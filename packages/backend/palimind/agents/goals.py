"""Agent goals & background tasks.

Phase 4.5 lets agents work autonomously toward an objective:

* A **goal** has a name, an objective, success criteria and a progress value.
* **Background tasks** are queued jobs that run an agent once or on a schedule
  (``/loop 5m check tests``). At most ``GOALS_MAX_TASKS`` (50) may be live and
  a task may not outlive ``GOALS_MAX_DURATION_DAYS`` (7) days.
* A **runner** loop executes due tasks, records results, advances goal progress
  and emits **notifications** on completion.

State is persisted as JSON under ``~/.palimind/agents`` so goals survive
restarts. The runner is started by the API server; the pure state helpers are
synchronous and unit-testable without a running event loop.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from palimind.settings import (
    GOALS_MAX_DURATION_DAYS,
    GOALS_MAX_TASKS,
    GOALS_TICK,
)

AGENTS_DIR = Path.home() / ".palimind" / "agents"
GOALS_FILE = AGENTS_DIR / "goals.json"
TASKS_FILE = AGENTS_DIR / "tasks.json"
NOTIFICATIONS_FILE = AGENTS_DIR / "notifications.json"

_LOCK = threading.RLock()

GOAL_STATUSES = ("active", "paused", "completed", "failed")
TASK_STATUSES = ("pending", "running", "done", "failed", "cancelled", "expired")

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


# ── JSON helpers ──────────────────────────────────────────────────────────


def _load_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2), "utf-8")


# ── parsing ───────────────────────────────────────────────────────────────


def parse_duration(text: str) -> int | None:
    """Parse ``30s``/``5m``/``2h``/``1d`` into seconds, or None if invalid."""
    match = _DURATION_RE.match(str(text or ""))
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2).lower()
    if value <= 0:
        return None
    return value * _UNIT_SECONDS[unit]


def parse_loop_command(text: str) -> dict[str, Any] | None:
    """Parse ``/loop 5m check tests`` into ``{interval_seconds, prompt}``."""
    raw = str(text or "").strip()
    if not raw.lower().startswith("/loop"):
        return None
    rest = raw[5:].strip()
    if not rest:
        return None
    parts = rest.split(None, 1)
    interval = parse_duration(parts[0])
    if interval is None:
        return None
    prompt = parts[1].strip() if len(parts) > 1 else "Run your task."
    return {"interval_seconds": interval, "prompt": prompt}


# ── goals ─────────────────────────────────────────────────────────────────


def _now() -> float:
    return time.time()


def list_goals() -> list[dict[str, Any]]:
    with _LOCK:
        goals = _load_list(GOALS_FILE)
    goals.sort(key=lambda g: float(g.get("created_at", 0) or 0), reverse=True)
    return goals


def get_goal(goal_id: str) -> dict[str, Any] | None:
    for goal in list_goals():
        if goal.get("id") == goal_id:
            return goal
    return None


def create_goal(
    name: str,
    objective: str = "",
    *,
    success_criteria: str = "",
    agent_id: str = "",
    deadline: float | None = None,
) -> dict[str, Any]:
    goal = {
        "id": str(uuid.uuid4()),
        "name": str(name or "Untitled goal").strip()[:200],
        "objective": str(objective)[:4000],
        "success_criteria": str(success_criteria)[:2000],
        "agent_id": agent_id,
        "status": "active",
        "progress": 0.0,
        "created_at": _now(),
        "updated_at": _now(),
        "deadline": deadline,
        "notes": [],
        "task_ids": [],
    }
    with _LOCK:
        goals = _load_list(GOALS_FILE)
        goals.append(goal)
        _save_list(GOALS_FILE, goals)
    return goal


def update_goal(goal_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    with _LOCK:
        goals = _load_list(GOALS_FILE)
        for goal in goals:
            if goal.get("id") != goal_id:
                continue
            for key in ("name", "objective", "success_criteria", "agent_id", "status", "deadline"):
                if key in changes:
                    goal[key] = changes[key]
            if "progress" in changes:
                try:
                    goal["progress"] = max(0.0, min(1.0, float(changes["progress"])))
                except (TypeError, ValueError):
                    pass
            goal["updated_at"] = _now()
            _save_list(GOALS_FILE, goals)
            return goal
    return None


def delete_goal(goal_id: str) -> bool:
    with _LOCK:
        goals = _load_list(GOALS_FILE)
        remaining = [g for g in goals if g.get("id") != goal_id]
        if len(remaining) == len(goals):
            return False
        _save_list(GOALS_FILE, remaining)
        tasks = _load_list(TASKS_FILE)
        _save_list(TASKS_FILE, [t for t in tasks if t.get("goal_id") != goal_id])
    return True


def set_progress(goal_id: str, progress: float, note: str = "") -> dict[str, Any] | None:
    with _LOCK:
        goals = _load_list(GOALS_FILE)
        for goal in goals:
            if goal.get("id") != goal_id:
                continue
            goal["progress"] = max(0.0, min(1.0, float(progress)))
            goal["updated_at"] = _now()
            if note:
                goal.setdefault("notes", []).append({"at": _now(), "text": note[:1000]})
            if goal["progress"] >= 1.0 and goal.get("status") == "active":
                goal["status"] = "completed"
                _notify_locked(
                    "goal_completed",
                    f"Goal completed: {goal.get('name', goal_id)}",
                    {"goal_id": goal_id},
                )
            _save_list(GOALS_FILE, goals)
            return goal
    return None


def recompute_progress(goal_id: str) -> dict[str, Any] | None:
    """Derive progress from the goal's tasks (done / total)."""
    with _LOCK:
        tasks = [t for t in _load_list(TASKS_FILE) if t.get("goal_id") == goal_id]
    if not tasks:
        return get_goal(goal_id)
    done = sum(1 for t in tasks if t.get("status") in ("done", "cancelled"))
    return set_progress(goal_id, done / len(tasks))


# ── background tasks ──────────────────────────────────────────────────────


def _active_task_count(tasks: list[dict[str, Any]]) -> int:
    return sum(1 for t in tasks if t.get("status") in ("pending", "running"))


def create_task(
    *,
    agent_id: str,
    prompt: str,
    goal_id: str = "",
    kind: str = "once",
    interval_seconds: int = 0,
    start_at: float | None = None,
) -> dict[str, Any]:
    """Create a background task, enforcing the count and duration limits."""
    if kind not in ("once", "loop"):
        raise ValueError("kind must be 'once' or 'loop'")
    if kind == "loop" and int(interval_seconds or 0) < 10:
        raise ValueError("loop interval must be at least 10 seconds")

    now = _now()
    expires_at = now + GOALS_MAX_DURATION_DAYS * 86400
    if start_at is not None and start_at + GOALS_MAX_DURATION_DAYS * 86400 < expires_at:
        expires_at = start_at + GOALS_MAX_DURATION_DAYS * 86400

    with _LOCK:
        tasks = _load_list(TASKS_FILE)
        # Expire stale tasks before counting so completed loops don't block new work.
        changed = False
        for t in tasks:
            if (
                t.get("status") in ("pending", "running")
                and float(t.get("expires_at", 0) or 0) < now
            ):
                t["status"] = "expired"
                changed = True
        if changed:
            _save_list(TASKS_FILE, tasks)
        if _active_task_count(tasks) >= GOALS_MAX_TASKS:
            raise ValueError(
                f"background task limit reached ({GOALS_MAX_TASKS}); cancel a task first"
            )

        task = {
            "id": str(uuid.uuid4()),
            "goal_id": goal_id,
            "agent_id": agent_id,
            "prompt": str(prompt)[:8000],
            "kind": kind,
            "interval_seconds": int(interval_seconds or 0),
            "next_run": float(start_at if start_at is not None else now),
            "created_at": now,
            "expires_at": expires_at,
            "status": "pending",
            "run_count": 0,
            "last_run": None,
            "last_status": "",
            "last_output": "",
        }
        tasks.append(task)
        _save_list(TASKS_FILE, tasks)

    if goal_id:
        _append_goal_task(goal_id, str(task["id"]))
    return task


def _append_goal_task(goal_id: str, task_id: str) -> None:
    with _LOCK:
        goals = _load_list(GOALS_FILE)
        for goal in goals:
            if goal.get("id") == goal_id:
                goal.setdefault("task_ids", []).append(task_id)
                goal["updated_at"] = _now()
                _save_list(GOALS_FILE, goals)
                return


def list_tasks(goal_id: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        tasks = _load_list(TASKS_FILE)
    if goal_id:
        tasks = [t for t in tasks if t.get("goal_id") == goal_id]
    tasks.sort(key=lambda t: float(t.get("created_at", 0) or 0), reverse=True)
    return tasks


def get_task(task_id: str) -> dict[str, Any] | None:
    for task in list_tasks():
        if task.get("id") == task_id:
            return task
    return None


def cancel_task(task_id: str) -> dict[str, Any] | None:
    return _update_task(task_id, {"status": "cancelled"})


def delete_task(task_id: str) -> bool:
    with _LOCK:
        tasks = _load_list(TASKS_FILE)
        remaining = [t for t in tasks if t.get("id") != task_id]
        if len(remaining) == len(tasks):
            return False
        _save_list(TASKS_FILE, remaining)
    return True


def _update_task(task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    with _LOCK:
        tasks = _load_list(TASKS_FILE)
        for task in tasks:
            if task.get("id") != task_id:
                continue
            task.update(changes)
            _save_list(TASKS_FILE, tasks)
            return task
    return None


def due_tasks(now: float | None = None) -> list[dict[str, Any]]:
    """Pending tasks whose ``next_run`` has arrived and are not expired."""
    moment = now if now is not None else _now()
    due: list[dict[str, Any]] = []
    with _LOCK:
        tasks = _load_list(TASKS_FILE)
        changed = False
        for task in tasks:
            if task.get("status") != "pending":
                continue
            if float(task.get("expires_at", 0) or 0) < moment:
                task["status"] = "expired"
                changed = True
                continue
            if float(task.get("next_run", 0) or 0) <= moment:
                due.append(task)
        if changed:
            _save_list(TASKS_FILE, tasks)
    return due


def complete_task(
    task_id: str,
    *,
    status: str,
    output: str,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Record a finished run and reschedule a loop (or finish a one-shot)."""
    moment = now if now is not None else _now()
    with _LOCK:
        tasks = _load_list(TASKS_FILE)
        updated: dict[str, Any] | None = None
        for task in tasks:
            if task.get("id") != task_id:
                continue
            task["run_count"] = int(task.get("run_count", 0)) + 1
            task["last_run"] = moment
            task["last_status"] = status
            task["last_output"] = str(output)[:8000]
            if task.get("kind") == "loop" and float(task.get("expires_at", 0) or 0) > moment:
                task["status"] = "pending"
                task["next_run"] = moment + int(task.get("interval_seconds", 60) or 60)
            else:
                task["status"] = "done" if status == "success" else "failed"
            updated = dict(task)
            break
        if updated is not None:
            _save_list(TASKS_FILE, tasks)
    if updated and updated.get("goal_id"):
        recompute_progress(updated["goal_id"])
    return updated


def mark_running(task_id: str) -> dict[str, Any] | None:
    return _update_task(task_id, {"status": "running"})


# ── notifications ─────────────────────────────────────────────────────────


def _notify_locked(kind: str, text: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    items = _load_list(NOTIFICATIONS_FILE)
    note = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "text": str(text)[:1000],
        "meta": meta or {},
        "created_at": _now(),
        "read": False,
    }
    items.append(note)
    _save_list(NOTIFICATIONS_FILE, items[-200:])
    return note


def notify(kind: str, text: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    with _LOCK:
        return _notify_locked(kind, text, meta)


def list_notifications(unread_only: bool = False) -> list[dict[str, Any]]:
    with _LOCK:
        items = _load_list(NOTIFICATIONS_FILE)
    if unread_only:
        items = [n for n in items if not n.get("read")]
    items.sort(key=lambda n: float(n.get("created_at", 0) or 0), reverse=True)
    return items


def mark_notifications_read(ids: list[str] | None = None) -> int:
    with _LOCK:
        items = _load_list(NOTIFICATIONS_FILE)
        count = 0
        for note in items:
            if ids and note.get("id") not in ids:
                continue
            if not note.get("read"):
                note["read"] = True
                count += 1
        _save_list(NOTIFICATIONS_FILE, items)
    return count


def clear_notifications() -> None:
    with _LOCK:
        _save_list(NOTIFICATIONS_FILE, [])


# ── runner ────────────────────────────────────────────────────────────────

_runner_task: asyncio.Task | None = None
_runner_lock = asyncio.Lock()
# task ids currently executing, so a slow run cannot be started twice.
_in_flight: set[str] = set()


async def _default_run(task: dict[str, Any]) -> tuple[str, str]:
    """Run a task's agent via the standard service entry point."""
    from palimind.agents.registry import get_registry
    from palimind.agents.service import run_agent

    defn = get_registry().get_by_id(task.get("agent_id", ""))
    if defn is None:
        return "error", f"Agent not found: {task.get('agent_id')}"
    prompt = str(task.get("prompt") or "Run your task.")
    output = await run_agent(defn, prompt, session_id=f"_task:{task.get('id', '')}")
    return "success", output


async def _run_one(task: dict[str, Any], run_callable: Any) -> None:
    task_id = task["id"]
    _in_flight.add(task_id)
    mark_running(task_id)
    try:
        status, output = await run_callable(task)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 - a failing task must not kill the runner
        status, output = "error", f"[task error] {e}"
    finally:
        _in_flight.discard(task_id)
    complete_task(task_id, status=status, output=output)
    if status != "success":
        notify(
            "task_failed",
            f"Background task failed: {task.get('prompt', '')[:120]}",
            {"task_id": task_id, "goal_id": task.get("goal_id", "")},
        )


async def _goals_loop(run_callable: Any) -> None:
    while True:
        try:
            await asyncio.sleep(GOALS_TICK)
            for task in due_tasks():
                if task["id"] in _in_flight:
                    continue
                asyncio.create_task(_run_one(task, run_callable))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[goals] runner tick error: {e}")


def start_runner(run_callable: Any | None = None) -> asyncio.Task | None:
    """Start the background-task runner. Registered at FastAPI startup."""
    global _runner_task
    if _runner_task is not None and not _runner_task.done():
        return _runner_task
    _runner_task = asyncio.create_task(_goals_loop(run_callable or _default_run))
    return _runner_task


def stop_runner() -> None:
    global _runner_task
    if _runner_task is not None and not _runner_task.done():
        _runner_task.cancel()
    _runner_task = None


__all__ = [
    "GOAL_STATUSES",
    "TASK_STATUSES",
    "cancel_task",
    "clear_notifications",
    "complete_task",
    "create_goal",
    "create_task",
    "delete_goal",
    "delete_task",
    "due_tasks",
    "get_goal",
    "get_task",
    "list_goals",
    "list_notifications",
    "list_tasks",
    "mark_notifications_read",
    "notify",
    "parse_duration",
    "parse_loop_command",
    "recompute_progress",
    "set_progress",
    "start_runner",
    "stop_runner",
    "update_goal",
]
