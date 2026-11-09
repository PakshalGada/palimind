"""Repeatable work: routines for agents and teams.

A routine captures a prompt (often from a run), a target and a trigger
(manual / cron schedule / file watcher). The scheduler fires due routines and
posts the result as a notification.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from palimind.agents.catalog import validate_cron
from palimind.storage import state_store

ROUTINE_LIMIT = 50
RUN_HISTORY_LIMIT = 20
RUN_MODES = ("manual", "scheduled", "watcher")
TOOL_PACKS = ("auto", "research", "code", "data", "web", "custom")
RUN_SOURCES = ("test", "script", "webhook", "schedule", "manual")
MISSED_POLICIES = ("run", "skip", "catch_up")
SESSION_MODES = ("chat", "routine")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(data.get("id") or uuid.uuid4()),
        "name": str(data.get("name") or "Routine").strip()[:120],
        "target_type": str(data.get("target_type") or "agent"),
        "target_id": str(data.get("target_id") or ""),
        "channel_id": str(data.get("channel_id") or ""),
        "owner_kind": str(data.get("owner_kind") or "agent"),
        "input": str(data.get("input") or ""),
        "run_mode": str(data.get("run_mode") or "manual"),
        "schedule": data.get("schedule") or None,
        "watcher_pattern": data.get("watcher_pattern") or None,
        "working_root": str(data.get("working_root") or ""),
        "tool_pack": str(data.get("tool_pack") or "auto"),
        "source_run_id": data.get("source_run_id") or None,
        "enabled": bool(data.get("enabled", True)),
        "quiet": bool(data.get("quiet", False)),
        "run_source": str(data.get("run_source") or "manual"),
        "missed_policy": str(data.get("missed_policy") or "run"),
        "session_mode": str(data.get("session_mode") or "routine"),
        "created_at": str(data.get("created_at") or _now_iso()),
        "last_run_at": data.get("last_run_at"),
        "last_status": data.get("last_status"),
        "runs": list(data.get("runs") or [])[-RUN_HISTORY_LIMIT:],
    }


def validate_routine(data: dict[str, Any]) -> str | None:
    if not str(data.get("name") or "").strip():
        return "name is required"
    if str(data.get("target_type")) not in ("agent", "team", "channel"):
        return "target_type must be agent, team, or channel"
    if not str(data.get("target_id") or ""):
        return "target_id is required"
    if not str(data.get("input") or "").strip():
        return "input is required"
    mode = str(data.get("run_mode") or "manual")
    if mode not in RUN_MODES:
        return f"run_mode must be one of {RUN_MODES}"
    if mode == "scheduled":
        error = validate_cron(str(data.get("schedule") or ""))
        if error:
            return error
    if mode == "watcher" and not str(data.get("watcher_pattern") or "").strip():
        return "watcher_pattern is required for watcher routines"
    if str(data.get("tool_pack") or "auto") not in TOOL_PACKS:
        return f"tool_pack must be one of {TOOL_PACKS}"
    if str(data.get("run_source") or "manual") not in RUN_SOURCES:
        return f"run_source must be one of {RUN_SOURCES}"
    if str(data.get("missed_policy") or "run") not in MISSED_POLICIES:
        return f"missed_policy must be one of {MISSED_POLICIES}"
    if str(data.get("session_mode") or "routine") not in SESSION_MODES:
        return f"session_mode must be one of {SESSION_MODES}"
    return None


def list_routines(limit: int = 200) -> list[dict[str, Any]]:
    return state_store.list_routines(limit=limit)


def get_routine(routine_id: str) -> dict[str, Any] | None:
    return state_store.get_routine(routine_id)


def create_routine(data: dict[str, Any]) -> dict[str, Any]:
    error = validate_routine(data)
    if error:
        raise ValueError(error)
    if len(list_routines(limit=1000)) >= ROUTINE_LIMIT:
        raise ValueError(f"routine limit reached ({ROUTINE_LIMIT})")
    routine = _normalise(data)
    state_store.upsert_routine(routine)
    return routine


def update_routine(routine_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    existing = get_routine(routine_id)
    if existing is None:
        raise KeyError("Routine not found")
    merged = {**existing, **changes, "id": routine_id, "created_at": existing.get("created_at")}
    error = validate_routine(merged)
    if error:
        raise ValueError(error)
    routine = _normalise(merged)
    state_store.upsert_routine(routine)
    return routine


def delete_routine(routine_id: str) -> bool:
    if get_routine(routine_id) is None:
        return False
    state_store.delete_routine(routine_id)
    return True


def mark_run(routine_id: str, run_id: str, status: str) -> dict[str, Any] | None:
    routine = get_routine(routine_id)
    if routine is None:
        return None
    runs = list(routine.get("runs") or [])
    runs.append({"run_id": run_id, "status": status, "at": time.time()})
    routine["runs"] = runs[-RUN_HISTORY_LIMIT:]
    routine["last_run_at"] = time.time()
    routine["last_status"] = status
    state_store.upsert_routine(routine)
    return routine


async def run_routine(routine_id: str, payload: str = "") -> str:
    """Run a routine now. Returns the id used for the resulting run record."""
    routine = get_routine(routine_id)
    if routine is None:
        raise KeyError("Routine not found")
    input_text = str(routine.get("input") or "")
    if payload:
        input_text = f"{input_text}\n\n--- event input ---\n{str(payload)[:4000]}"
    target_type = str(routine.get("target_type") or "agent")
    target_id = str(routine.get("target_id") or "")
    run_source = str(routine.get("run_source") or "manual")

    if target_type == "channel":
        from palimind.agents import channels

        result = await channels.run_queued(target_id, input_text)
        run_id = str((result.get("task") or {}).get("id") or "")
        status = "success" if result.get("status") == "success" else "error"
        mark_run(routine_id, run_id, status)
        if status == "error":
            raise RuntimeError(str(result.get("error") or "channel run failed"))
        return run_id

    if target_type == "team":
        from palimind.agents import teams
        from palimind.agents.team_runtime import run_team

        team = teams.get_team(target_id)
        if team is None:
            raise KeyError("Team not found")
        result = await run_team(team, input_text, interactive=False)
        run_id = str(result.get("run_id") or "")
        status = str(result.get("status") or "success")
        mark_run(routine_id, run_id, status)
        if status == "error":
            raise RuntimeError(
                str(result.get("error") or result.get("output") or "team run failed")
            )
        return run_id

    from palimind.agents.registry import get_registry
    from palimind.agents.service import run_agent

    defn = get_registry().get_by_id(target_id)
    if defn is None:
        raise KeyError("Agent not found")
    output = await run_agent(
        defn, input_text, session_id=f"_routine:{routine_id}", interactive=False
    )
    last = None
    try:
        from palimind.agents.runtime import get_last_run

        last = get_last_run(defn.id)
    except Exception:
        pass
    run_id = str((last or {}).get("run_id") or "")
    # run_agent reports failures as an output string, so trust the recorded
    # run status rather than "non-empty output" (which is always true).
    status = str((last or {}).get("status") or ("success" if output else "error"))
    if status == "success":
        from palimind.agents import routine_signals

        signals = routine_signals.consume(run_id)
        if signals.get("quiet") or "[[no-update]]" in str(output):
            status = "quiet"
        elif signals.get("failure"):
            status = "failed"
            output = str(signals["failure"])
    try:
        from palimind.agents import waits

        waits.wake(defn.id, routine_id=routine_id, payload=str(output or ""))
    except Exception:
        pass
    try:
        from palimind.agents import flows

        flows.record_result(
            defn.id,
            routine_id,
            run_id,
            status=status,
            output=str(output or ""),
            error="" if status in ("success", "quiet") else str(output or ""),
        )
    except Exception:
        pass
    mark_run(routine_id, run_id, status)
    if status in ("error", "failed"):
        raise RuntimeError(output[:500] or f"run {run_source} failed")
    return run_id


def due_routines(now: datetime | None = None) -> list[dict[str, Any]]:
    from palimind.agents.scheduler import cron_matches

    now = now or datetime.now()
    due: list[dict[str, Any]] = []
    for routine in list_routines(limit=1000):
        if not routine.get("enabled"):
            continue
        if routine.get("run_mode") != "scheduled" or not routine.get("schedule"):
            continue
        if cron_matches(str(routine["schedule"]), now):
            due.append(routine)
    return due


def save_run_as_routine(
    run_id: str,
    target_type: str,
    target_id: str,
    name: str,
    *,
    schedule: str | None = None,
    run_mode: str = "manual",
    tool_pack: str = "auto",
    working_root: str = "",
) -> dict[str, Any]:
    record = None
    key = f"team:{target_id}" if target_type == "team" else target_id
    try:
        from palimind.agents.runtime import get_run

        record = get_run(key, run_id)
    except Exception:
        record = None
    return create_routine(
        {
            "name": name,
            "target_type": target_type,
            "target_id": target_id,
            "input": str((record or {}).get("input") or ""),
            "run_mode": run_mode,
            "schedule": schedule,
            "tool_pack": tool_pack,
            "working_root": working_root,
            "source_run_id": run_id,
        }
    )
