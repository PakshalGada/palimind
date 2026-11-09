"""Per-target task queue with pause/resume/cancel.

The queue is the runtime scheduler behind the human-facing task board: when an
agent or team is already at its concurrency limit, new work is enqueued instead
of raising ``AgentBusyError``. A low-frequency loop drains due items.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from palimind.storage import state_store

QUEUE_LIMIT = 100
TARGET_TYPES = ("agent", "team", "task", "channel")
_ACTIVE_STATUSES = ("queued", "running", "paused")
_loop_task: asyncio.Task | None = None
_locks: dict[str, asyncio.Lock] = {}


def enqueue(
    target_type: str,
    target_id: str,
    input: str,
    priority: int = 0,
    *,
    lane: str = "",
    task_id: str = "",
    idempotency_key: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if target_type not in TARGET_TYPES:
        raise ValueError(f"target_type must be one of {', '.join(TARGET_TYPES)}")
    if not target_id:
        raise ValueError("target_id is required")
    # Only live items count: finished/cancelled history must not fill the queue.
    active = [
        i for i in state_store.list_queue_items(limit=2000) if i.get("status") in _ACTIVE_STATUSES
    ]
    if idempotency_key:
        for item in active:
            if (
                item.get("idempotency_key") == idempotency_key
                and item.get("target_type") == target_type
                and item.get("target_id") == target_id
            ):
                return item
    if len(active) >= QUEUE_LIMIT:
        raise ValueError(f"queue limit reached ({QUEUE_LIMIT})")
    item = {
        "id": str(uuid.uuid4()),
        "target_type": target_type,
        "target_id": target_id,
        "input": str(input or "Run your task."),
        "priority": int(priority or 0),
        "status": "queued",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "run_id": None,
        "error": None,
        "job_id": None,
        "lane": str(lane or ""),
        "task_id": str(task_id or ""),
        "idempotency_key": str(idempotency_key or ""),
        "hold_reason": "",
        "metadata": dict(metadata or {}),
    }
    state_store.upsert_queue_item(item)
    try:
        from palimind.jobs import enqueue as enqueue_job

        job = enqueue_job(
            "queued_run",
            target_id,
            {
                "queue_item_id": item["id"],
                "target_type": target_type,
                "target_id": target_id,
                "input": item["input"],
                "lane": item.get("lane") or "",
                "task_id": item.get("task_id") or "",
                "delivery_id": (item.get("metadata") or {}).get("delivery_id") or "",
            },
            priority=priority,
            idempotency_key=idempotency_key or f"queue:{item['id']}",
        )
        item["job_id"] = job.get("id")
        state_store.upsert_queue_item(item)
    except Exception as exc:  # noqa: BLE001 - the queue item is still usable
        print(f"[queue] could not enqueue durable job: {exc}")
    return item


def list_queue(
    target_type: str | None = None, target_id: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    return state_store.list_queue_items(target_type, target_id, limit)


def get_item(item_id: str) -> dict[str, Any] | None:
    return state_store.get_queue_item(item_id)


def update_item(item_id: str, status: str | None = None, **changes: Any) -> dict[str, Any]:
    item = get_item(item_id)
    if item is None:
        raise KeyError("Queue item not found")
    if status:
        item["status"] = status
        if status == "running":
            item["started_at"] = time.time()
        if status in ("done", "failed", "cancelled"):
            item["finished_at"] = time.time()
    item.update(changes)
    state_store.upsert_queue_item(item)
    return item


def cancel_item(item_id: str) -> dict[str, Any]:
    item = get_item(item_id)
    if item and item.get("job_id"):
        try:
            from palimind.jobs import cancel_job

            cancel_job(str(item["job_id"]))
        except Exception:
            pass
    return update_item(item_id, status="cancelled")


def pause_item(item_id: str) -> dict[str, Any]:
    return update_item(item_id, status="paused")


def resume_item(item_id: str) -> dict[str, Any]:
    return update_item(item_id, status="queued")


def clear_target(target_type: str, target_id: str) -> None:
    state_store.delete_target_queue(target_type, target_id)


def _target_busy(item: dict[str, Any]) -> bool:
    """True when the item's target is at its concurrency limit right now."""
    target_type = str(item.get("target_type") or "agent")
    target_id = str(item.get("target_id") or "")
    if target_type == "team":
        from palimind.agents.team_runtime import is_team_running

        return is_team_running(target_id)
    if target_type == "task":
        from palimind.agents import tasks

        task = tasks.get_task(target_id)
        if task is None:
            return False
        if task.get("status") not in ("open", "running"):
            return True
        from palimind.agents.runtime import running_count

        return (
            running_count(str(task.get("agent_id") or "")) >= 1 and task.get("status") == "running"
        )
    if target_type == "channel":
        try:
            from palimind.agents import channels

            return channels.is_busy(target_id)
        except Exception:
            return False
    from palimind.agents.registry import get_registry
    from palimind.agents.runtime import running_count

    defn = get_registry().get_by_id(target_id)
    if defn is None:
        return False  # _execute marks it failed
    return running_count(defn.id) >= max(1, int(defn.max_concurrent_runs or 1))


def next_due() -> dict[str, Any] | None:
    for item in list_queue(limit=1000):
        if (
            item.get("status") == "queued"
            and not item.get("hold_reason")
            and not _target_busy(item)
        ):
            return item
    return None


def recover_stale_running() -> int:
    """Requeue items a previous process left ``running`` (crash/restart)."""
    count = 0
    for item in list_queue(limit=1000):
        if item.get("status") == "running":
            item["status"] = "queued"
            item["started_at"] = None
            state_store.upsert_queue_item(item)
            count += 1
    return count


async def _execute(item: dict[str, Any]) -> None:
    from palimind.agents import teams
    from palimind.agents.registry import get_registry
    from palimind.agents.runtime import running_count
    from palimind.agents.service import run_agent
    from palimind.agents.team_runtime import run_team

    target_type = str(item.get("target_type"))
    target_id = str(item.get("target_id"))

    if target_type == "task":
        from palimind.agents import mailbox, tasks
        from palimind.agents.scheduler import recorded_run_status

        task = tasks.get_task(target_id)
        if task is None:
            update_item(item["id"], status="failed", error="Task not found")
            return
        if task.get("status") in ("completed", "failed", "cancelled", "closed"):
            update_item(item["id"], status="done")
            return
        defn = get_registry().get_by_id(str(task.get("agent_id") or ""))
        if defn is None:
            tasks.fail_task(target_id, "Agent not found")
            update_item(item["id"], status="failed", error="Agent not found")
            return
        delivery_id = str((item.get("metadata") or {}).get("delivery_id") or "")
        tasks.mark_running(target_id)
        if delivery_id:
            mailbox.mark_running(delivery_id)
        try:
            agent_input = str(item.get("input") or task.get("input") or "")
            output = await run_agent(
                defn,
                agent_input,
                session_id=f"_task:{target_id}",
                interactive=False,
                task_id=target_id,
            )
            run_status = recorded_run_status(defn.id, agent_input, output)
            if run_status != "success":
                tasks.fail_task(target_id, output[:1000] or run_status)
                if delivery_id:
                    mailbox.fail(delivery_id, output[:1000] or run_status)
                update_item(item["id"], status="failed", error=output[:500] or run_status)
                return
            tasks.complete_task(target_id, output)
            if delivery_id:
                mailbox.complete(delivery_id, output)
            update_item(item["id"], status="done", error=None)
        except Exception as exc:  # noqa: BLE001
            tasks.fail_task(target_id, str(exc))
            if delivery_id:
                mailbox.fail(delivery_id, str(exc))
            update_item(item["id"], status="failed", error=str(exc))
        return

    if target_type == "channel":
        from palimind.agents import channels

        try:
            result = await channels.run_queued(target_id, str(item.get("input") or ""))
            update_item(
                item["id"],
                status="done" if result.get("status") == "success" else "failed",
                error=result.get("error"),
            )
        except Exception as exc:  # noqa: BLE001
            update_item(item["id"], status="failed", error=str(exc))
        return

    if target_type == "agent":
        defn = get_registry().get_by_id(target_id)
        if defn is None:
            update_item(item["id"], status="failed", error="Agent not found")
            return
        if running_count(defn.id) >= max(1, int(defn.max_concurrent_runs or 1)):
            # Still busy: put it back instead of leaving it "running" forever.
            update_item(item["id"], status="queued")
            return
        try:
            agent_input = str(item.get("input") or "")
            output = await run_agent(
                defn, agent_input, session_id=f"_queue:{item['id']}", interactive=False
            )
            from palimind.agents.scheduler import recorded_run_status

            # run_agent returns error text instead of raising: honour the
            # recorded run status so failed runs are not marked "done".
            run_status = recorded_run_status(defn.id, agent_input, output)
            if run_status != "success":
                update_item(item["id"], status="failed", error=output[:500] or run_status)
                return
            update_item(item["id"], status="done", error=None)
            try:
                from palimind.agents import goals

                goals.notify(
                    "queue_done",
                    f"{defn.label} finished a queued task.",
                    {"agent_id": defn.id, "output": output[:1000]},
                )
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            update_item(item["id"], status="failed", error=str(exc))
        return

    team = teams.get_team(target_id)
    if team is None:
        update_item(item["id"], status="failed", error="Team not found")
        return
    try:
        result = await run_team(team, str(item.get("input") or ""), interactive=False)
        update_item(
            item["id"],
            status="done" if result.get("status") == "success" else "failed",
            run_id=result.get("run_id"),
            error=result.get("error"),
        )
    except Exception as exc:  # noqa: BLE001
        update_item(item["id"], status="failed", error=str(exc))


async def _queue_loop() -> None:
    """Reconcile legacy/queued task-board items into durable jobs.

    ``enqueue`` already creates a job for new items; this loop only backfills
    items created before the job service existed (or whose job was removed).
    """
    while True:
        try:
            await asyncio.sleep(5)
            from palimind.jobs import enqueue as enqueue_job

            for item in list_queue(limit=1000):
                if item.get("status") != "queued":
                    continue
                if item.get("job_id"):
                    continue
                job = enqueue_job(
                    "queued_run",
                    str(item.get("target_id") or ""),
                    {
                        "queue_item_id": item["id"],
                        "target_type": item.get("target_type"),
                        "target_id": item.get("target_id"),
                        "input": item.get("input"),
                        "lane": item.get("lane") or "",
                        "task_id": item.get("task_id") or "",
                        "delivery_id": (item.get("metadata") or {}).get("delivery_id") or "",
                    },
                    priority=int(item.get("priority") or 0),
                    idempotency_key=item.get("idempotency_key") or f"queue:{item['id']}",
                )
                update_item(item["id"], job_id=job.get("id"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[queue] loop error: {exc}")


def start_queue_runner() -> asyncio.Task:
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return _loop_task
    try:
        recover_stale_running()
    except Exception as exc:  # noqa: BLE001 - recovery is best-effort
        print(f"[queue] could not recover running items: {exc}")
    _loop_task = asyncio.create_task(_queue_loop())
    return _loop_task


def stop_queue_runner() -> None:
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        _loop_task.cancel()
    _loop_task = None
