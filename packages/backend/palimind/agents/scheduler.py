from __future__ import annotations

import asyncio
import fnmatch
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from palimind.agents.service import is_running, run_agent
from palimind.settings import AGENT_SCHEDULER_TICK

RESULTS_SESSION_NAME = "_agent_results"

_loop: asyncio.AbstractEventLoop | None = None
_scheduler_task: asyncio.Task | None = None
_fired_keys: deque[str] = deque(maxlen=2000)


# ── cron matcher (5-field, supports */n, lists, ranges) ───────────────────


def _field_matches(expr: str, value: int, lo: int, hi: int) -> bool:
    for atom in expr.split(","):
        atom = atom.strip()
        if atom == "*":
            return True
        if "/" in atom:
            base, step = atom.split("/", 1)
            try:
                step = int(step)
            except ValueError:
                continue
            if step <= 0:
                continue
            if base == "*":
                if value % step == 0:
                    return True
            else:
                try:
                    start = int(base)
                except ValueError:
                    continue
                if value >= start and (value - start) % step == 0:
                    return True
            continue
        if "-" in atom:
            try:
                a, b = atom.split("-", 1)
                if lo <= int(a) <= int(b) <= hi and int(a) <= value <= int(b):
                    return True
            except ValueError:
                continue
            continue
        try:
            if int(atom) == value:
                return True
        except ValueError:
            continue
    return False


def cron_matches(expr: str, dt: datetime | None = None) -> bool:
    """Return True if the 5-field cron expression matches *dt* (default now)."""
    if not expr:
        return False
    parts = expr.split()
    if len(parts) != 5:
        return False
    now = dt or datetime.now()
    # cron dow: 0/7 = Sunday .. 6 = Saturday; Python weekday: 0 = Monday
    dow = (now.weekday() + 1) % 7
    minute, hour, dom, month = now.minute, now.hour, now.day, now.month
    if not _field_matches(parts[0], minute, 0, 59):
        return False
    if not _field_matches(parts[1], hour, 0, 23):
        return False
    if not _field_matches(parts[2], dom, 1, 31):
        return False
    if not _field_matches(parts[3], month, 1, 12):
        return False
    # accept 7 as Sunday too
    return _field_matches(parts[4], dow, 0, 7)


# ── results session ───────────────────────────────────────────────────────


def ensure_results_session(field_root: Path) -> str:
    from palimind.memory.session_store import add_new_session, load_sessions

    try:
        data = load_sessions(field_root)
        for sess in data.get("sessions", []):
            if sess.get("name") == RESULTS_SESSION_NAME or sess.get("id") == RESULTS_SESSION_NAME:
                return sess["id"]
        data = add_new_session(field_root, RESULTS_SESSION_NAME)
        return data["active_session_id"]
    except Exception as e:
        print(f"[agents] ensure results session failed: {e}")
        return RESULTS_SESSION_NAME


async def post_result(
    field_root: Path, defn_name: str, input: str, output: str, status: str
) -> None:
    """Post a run's result into the field's _agent_results session."""
    from palimind.memory.session_store import append_message_to_session

    try:
        session_id = ensure_results_session(field_root)
        await asyncio.to_thread(
            append_message_to_session,
            field_root,
            session_id,
            "system",
            f"**[Agent {defn_name}]** {input[:200]}\n\n{output}",
            mode="agent",
            mode_params={"agent_name": defn_name, "status": status},
        )
    except Exception as e:
        print(f"[agents] failed to post result: {e}")


# ── firing ────────────────────────────────────────────────────────────────


async def _fire_agent(defn: Any, input: str, source: str) -> None:
    from palimind.agents.registry import get_registry

    field_root = get_registry().field_root
    try:
        output = await run_agent(defn, input, session_id=f"_{source}")
        if field_root is not None:
            await post_result(field_root, defn.name, input, output, "success")
    except asyncio.CancelledError:
        if field_root is not None:
            await post_result(field_root, defn.name, input, "[cancelled]", "cancelled")
        raise
    except Exception as e:
        print(f"[agents] scheduled run for {defn.name} failed: {e}")
        if field_root is not None:
            await post_result(field_root, defn.name, input, f"[error] {e}", "error")


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
            continue
        input = f"[Scheduled trigger at {now.isoformat()}]\nExecute your scheduled task now."
        asyncio.create_task(_fire_agent(defn, input, source="scheduled"))


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
            continue
        input = (
            f"[Watcher trigger] File changed: {rel}\nInvestigate the change and act accordingly."
        )
        asyncio.run_coroutine_threadsafe(_fire_agent(defn, input, source="watcher"), _loop)
