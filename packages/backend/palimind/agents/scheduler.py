from __future__ import annotations

import asyncio
import fnmatch
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from palimind.agents.service import is_running, run_agent
from palimind.settings import AGENT_SCHEDULER_TICK

_loop: asyncio.AbstractEventLoop | None = None
_scheduler_task: asyncio.Task | None = None
_fired_keys: deque[str] = deque(maxlen=2000)
_fire_tasks: set[asyncio.Task] = set()


def _spawn(coro: Any) -> None:
    # Keep a strong reference: the loop only holds weak refs to tasks, so a
    # bare create_task() can be garbage-collected before the run finishes.
    task = asyncio.create_task(coro)
    _fire_tasks.add(task)
    task.add_done_callback(_fire_tasks.discard)


# ── cron matcher (shared with the durable job service) ─────────────────

from palimind.jobs.cron import _field_matches, cron_matches, next_cron_time  # noqa: E402,F401

# ── results ───────────────────────────────────────────────────────────────


async def post_result(defn: Any, output: str, status: str, source: str) -> None:
    """Append an automated run's output to the agent's own chat session."""
    from palimind.agents.chat import agent_session_root
    from palimind.memory.session_store import append_message_to_session, load_sessions

    try:
        root = agent_session_root(defn.id)
        data = await asyncio.to_thread(load_sessions, root)
        session_id = data.get("active_session_id")
        if not session_id:
            return
        label = {
            "scheduled": "Scheduled run",
            "watcher": "Watcher run",
            "manual": "Manual run",
        }.get(source, "Automated run")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        suffix = "" if status == "success" else f" · {status}"
        content = f"*{label} · {stamp}{suffix}*\n\n{output}"
        await asyncio.to_thread(
            append_message_to_session,
            root,
            session_id,
            "system",
            content,
            mode="agent",
            mode_params={"agent_id": defn.id, "source": source, "status": status},
        )
        try:
            from palimind.agents import goals

            title = getattr(defn, "display_name", "") or getattr(defn, "name", "Agent")
            if status == "success":
                text = f"{title} finished a {label.lower()}."
            else:
                text = f"{title}'s {label.lower()} ended with {status}."
            goals.notify(
                "agent_run",
                text,
                {"agent_id": defn.id, "source": source, "status": status},
            )
        except Exception:
            pass
    except Exception as e:
        print(f"[agents] failed to post {source} result for {defn.name}: {e}")


# ── firing ────────────────────────────────────────────────────────────────


def recorded_run_status(agent_id: str, input: str, output: str) -> str:
    """Status the runtime recorded for a run that just returned ``output``.

    ``run_with_definition`` reports failures as an output string instead of
    raising, so callers must read the recorded run status (as
    ``routines.run_routine`` does) rather than assume success. Prefers the
    recent record matching this run's input/output (concurrent runs of the
    same agent), then the latest record.
    """
    try:
        from palimind.agents.runtime import get_run_history

        history = get_run_history(agent_id, limit=20) or []
    except Exception:
        history = []
    match = None
    for rec in reversed(history):
        if (
            str(rec.get("output") or "") == output[:100_000]
            and str(rec.get("input") or "") == input[:2000]
        ):
            match = rec
            break
    if match is None and history:
        match = history[-1]
    status = str((match or {}).get("status") or "")
    if status:
        return status
    if not output or output.startswith("[Agent run error]"):
        return "error"
    return "success"


async def _fire_agent(defn: Any, input: str, source: str) -> None:
    try:
        output = await run_agent(defn, input, session_id=f"_{source}", interactive=False)
        status = recorded_run_status(defn.id, input, output)
        await post_result(defn, output, status, source)
    except asyncio.CancelledError:
        await post_result(defn, "[cancelled]", "cancelled", source)
        raise
    except Exception as e:
        print(f"[agents] scheduled run for {defn.name} failed: {e}")
        await post_result(defn, f"[error] {e}", "error", source)


async def _tick_scheduled() -> None:
    from palimind.agents.registry import get_registry

    now = datetime.now()
    for defn in get_registry().enabled_agents():
        if defn.run_mode != "scheduled" or not defn.schedule:
            continue
        if not cron_matches(defn.schedule, now):
            continue
        key = f"{defn.id}:{now.strftime('%Y%m%d%H%M')}"
        if key in _fired_keys:
            continue
        _fired_keys.append(key)
        if is_running(defn.id):
            from palimind.agents.runtime import running_count

            if running_count(defn.id) >= max(1, int(defn.max_concurrent_runs or 1)):
                continue
        input = f"[Scheduled trigger at {now.isoformat()}]\nExecute your scheduled task now."
        from palimind.jobs import enqueue

        enqueue(
            "agent_run",
            defn.id,
            {"input": input, "source": "scheduled"},
            idempotency_key=f"scheduled:{defn.id}:{now.strftime('%Y%m%d%H%M')}",
        )

    await _tick_routines(now)
    try:
        from palimind.workflows import triggers as workflow_triggers

        workflow_triggers.enqueue_due_cron(now)
    except Exception as exc:  # noqa: BLE001
        print(f"[agents] workflow cron triggers failed: {exc}")


async def _tick_routines(now: datetime) -> None:
    from palimind.agents import routines
    from palimind.jobs import enqueue

    for routine in routines.due_routines(now):
        enqueue(
            "routine_run",
            str(routine.get("id")),
            {"routine_id": str(routine.get("id"))},
            idempotency_key=f"routine:{routine.get('id')}:{now.strftime('%Y%m%d%H%M')}",
        )


async def post_routine_notification(routine: dict[str, Any], status: str, error: str = "") -> None:
    try:
        from palimind.agents import goals

        label = routine.get("name") or "Routine"
        text = (
            f"Routine '{label}' finished."
            if status == "success"
            else f"Routine '{label}' failed: {error[:300]}"
        )
        goals.notify(
            "routine",
            text,
            {
                "routine_id": routine.get("id"),
                "target_type": routine.get("target_type"),
                "target_id": routine.get("target_id"),
                "status": status,
            },
        )
    except Exception:
        pass


async def _scheduler_loop() -> None:
    while True:
        try:
            await asyncio.sleep(AGENT_SCHEDULER_TICK)
            await _tick_scheduled()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[agents] scheduler tick error: {e}")


def start_scheduler(loop: asyncio.AbstractEventLoop | None = None) -> asyncio.Task | None:
    """Start the background scheduler task. Registered at FastAPI startup."""
    global _loop, _scheduler_task
    _loop = loop or asyncio.get_running_loop()
    if _scheduler_task is not None and not _scheduler_task.done():
        return _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    return _scheduler_task


def stop_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is not None and not _scheduler_task.done():
        _scheduler_task.cancel()
    _scheduler_task = None


def check_watcher_triggers(root: Path, changed_path: str = "") -> None:
    """Fire watcher-mode agents whose watcher_pattern matches the changed path.

    Called from the file watcher after the existing indexing logic runs.
    Thread-safe: schedules the fire on the event loop.
    """
    if _loop is None:
        return
    from palimind.agents.registry import get_registry

    rel = changed_path
    try:
        rel = str(Path(changed_path).resolve().relative_to(root.resolve()))
    except Exception:
        pass

    for defn in get_registry().enabled_agents():
        if defn.run_mode != "watcher" or not defn.watcher_pattern:
            continue
        pattern = defn.watcher_pattern
        matched = fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(Path(rel).name, pattern)
        if not matched:
            continue
        if is_running(defn.id):
            from palimind.agents.runtime import running_count

            if running_count(defn.id) >= max(1, int(defn.max_concurrent_runs or 1)):
                continue
        input = (
            f"[Watcher trigger] File changed: {rel}\nInvestigate the change and act accordingly."
        )
        import time

        from palimind.jobs import enqueue

        enqueue(
            "agent_run",
            defn.id,
            {"input": input, "source": "watcher"},
            idempotency_key=f"watcher:{defn.id}:{rel}:{int(time.time())}",
        )

    try:
        from palimind.agents import routines
        from palimind.jobs import enqueue

        for routine in routines.list_routines(limit=1000):
            if not routine.get("enabled") or routine.get("run_mode") != "watcher":
                continue
            pattern = str(routine.get("watcher_pattern") or "")
            if not pattern:
                continue
            if not (fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(Path(rel).name, pattern)):
                continue
            import time

            enqueue(
                "routine_run",
                str(routine.get("id")),
                {"routine_id": str(routine.get("id"))},
                idempotency_key=f"watcher-routine:{routine.get('id')}:{rel}:{int(time.time())}",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[agents] watcher routine check failed: {exc}")

    try:
        from palimind.workflows import triggers as workflow_triggers

        workflow_triggers.enqueue_file_triggers(root, rel)
    except Exception as exc:  # noqa: BLE001
        print(f"[agents] workflow file triggers failed: {exc}")
