"""Best-effort removal of everything a deleted agent owns.

Definitions are removed by ``AgentCatalog``; this module cleans the rest:
private/project memory, legacy chat, the agent's session store + workspace,
run history, run journals, pending approvals, plans, goals and tasks.
Shared memory (``_shared.json``) is intentionally preserved.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from palimind.agents.catalog import GLOBAL_AGENTS_DIR


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _purge_project_memory(agent_id: str) -> None:
    try:
        from palimind.agents.scope import configured_fields

        for root in configured_fields():
            _unlink(root / ".palimind" / "agents" / "memory" / f"{agent_id}.json")
    except Exception:
        pass


def _purge_journals(agent_id: str) -> None:
    journal_dir = GLOBAL_AGENTS_DIR / "run_journal"
    if not journal_dir.is_dir():
        return
    for path in journal_dir.glob("*.jsonl"):
        try:
            if agent_id in path.read_text("utf-8", errors="ignore"):
                path.unlink(missing_ok=True)
        except OSError:
            continue


def _purge_plans(agent_id: str) -> None:
    try:
        from palimind.agents import planner

        for plan in planner.list_plans(limit=1000):
            if str(plan.get("agent_id") or "") == agent_id:
                planner.delete_plan(str(plan.get("id")))
    except Exception:
        pass


def purge_agent_data(agent_id: str) -> None:
    """Remove every on-disk artifact tied to *agent_id* (best effort)."""
    try:
        from palimind.agents import teams

        teams.remove_agent_from_teams(agent_id)
    except Exception:
        pass
    try:
        from palimind.agents.workspace import purge_workspace

        purge_workspace(agent_id)
    except Exception:
        pass
    try:
        from palimind.agents import routines, queue

        for routine in routines.list_routines():
            if routine.get("target_type") == "agent" and routine.get("target_id") == agent_id:
                routines.delete_routine(str(routine.get("id")))
        queue.clear_target("agent", agent_id)
    except Exception:
        pass
    # Session store + personal workspace live under the agent directory.
    shutil.rmtree(GLOBAL_AGENTS_DIR / agent_id, ignore_errors=True)
    _unlink(GLOBAL_AGENTS_DIR / "memory" / f"{agent_id}.json")
    _purge_project_memory(agent_id)

    try:
        from palimind.agents.chat import clear_chat

        clear_chat(agent_id)
    except Exception:
        pass
    try:
        from palimind.storage import state_store

        state_store.clear_agent_chat(agent_id)
        state_store.delete_runs(agent_id)
    except Exception:
        pass
    try:
        from palimind.agents import approvals

        approvals.remove(agent_id)
    except Exception:
        pass

    _purge_journals(agent_id)
    _purge_plans(agent_id)

    try:
        from palimind.agents import goals

        for goal in goals.list_goals():
            if str(goal.get("agent_id") or "") == agent_id:
                goals.delete_goal(str(goal.get("id")))
        for task in goals.list_tasks():
            if str(task.get("agent_id") or "") == agent_id:
                goals.delete_task(str(task.get("id")))
    except Exception:
        pass


PRESET_NAMES = ("nova", "atlas", "quill", "sage", "veda", "zephyr")
_PRESET_MARKER = GLOBAL_AGENTS_DIR / ".presets_removed"


def remove_legacy_presets() -> int:
    """One-time removal of the old seeded preset agents (and their data)."""
    if _PRESET_MARKER.exists():
        return 0
    removed = 0
    try:
        from palimind.agents.registry import get_registry

        registry = get_registry()
        for name in PRESET_NAMES:
            defn = registry.get(name)
            if defn is None:
                continue
            try:
                registry.delete(defn.id)
                removed += 1
            except Exception as exc:
                print(f"[agents] failed to remove preset '{name}': {exc}")
        _PRESET_MARKER.write_text(
            "Legacy preset agents were removed during the onboarding redesign.\n",
            "utf-8",
        )
    except Exception as exc:
        print(f"[agents] preset cleanup failed: {exc}")
    return removed
