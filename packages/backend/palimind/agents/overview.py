"""Mission-Control overview: agents, teams, approvals, runs, routines."""

from __future__ import annotations

from typing import Any

from palimind.agents import activity, approvals, routines, team_runtime, teams
from palimind.agents.runtime import get_last_run, get_run_history, is_running, running_count


def _agent_status(defn: Any, pending: list[dict[str, Any]]) -> str:
    from palimind.agents.runtime import is_paused

    agent_id = defn.id
    if any(str(p.get("agent_id")) == agent_id for p in pending):
        return "waiting"
    if is_paused(agent_id):
        return "paused"
    if is_running(agent_id):
        return "working"
    if defn.run_mode in ("scheduled", "watcher") and defn.enabled:
        return "scheduled"
    return "idle"


def _team_status(team: dict[str, Any], pending: list[dict[str, Any]]) -> str:
    team_id = str(team.get("id"))
    member_ids = {str(m.get("agent_id")) for m in team.get("members") or []}
    if any(str(p.get("agent_id")) in member_ids for p in pending):
        return "waiting"
    if team_runtime.is_team_running(team_id):
        return "working"
    if any(routine.get("target_type") == "team" and routine.get("target_id") == team_id and routine.get("enabled") for routine in routines.list_routines()):
        return "scheduled"
    return "idle"


def _live_step(live: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for item in live:
        if str(item.get("agent_id")) == key:
            return item
    return None


def overview() -> dict[str, Any]:
    from palimind.agents.registry import get_registry

    pending = approvals.list_pending()
    live = activity.snapshot().get("running", [])
    routine_items = routines.list_routines(limit=100)

    agent_items: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    for defn in get_registry().all():
        last = get_last_run(defn.id)
        if last:
            recent.append(
                {
                    "target_type": "agent",
                    "target_id": defn.id,
                    "target_name": defn.label,
                    "run_id": last.get("run_id"),
                    "status": last.get("status"),
                    "timestamp": last.get("timestamp"),
                    "input": str(last.get("input") or "")[:300],
                    "output": str(last.get("output") or "")[:600],
                }
            )
        step = _live_step(live, defn.id)
        agent_items.append(
            {
                **defn.to_dict(),
                "target_type": "agent",
                "running": is_running(defn.id),
                "active_runs": running_count(defn.id),
                "status": _agent_status(defn, pending),
                "current_step": (step or {}).get("step") if step else "",
                "last_run_status": last.get("status") if last else None,
                "last_run_at": last.get("timestamp") if last else None,
                "pending_approvals": sum(1 for p in pending if str(p.get("agent_id")) == defn.id),
                "next_run": _next_run_for("agent", defn.id),
            }
        )

    team_items: list[dict[str, Any]] = []
    registry = get_registry()
    for team in teams.list_teams():
        team_id = str(team.get("id"))
        resolved_members = []
        for member in team.get("members") or []:
            member_def = registry.get_by_id(str(member.get("agent_id")))
            resolved_members.append(
                {
                    **member,
                    "agent": member_def.to_dict() if member_def else None,
                    "name": member_def.label if member_def else "Unknown",
                }
            )
        team = {**team, "members": resolved_members}
        history = get_run_history(f"team:{team_id}", limit=1)
        last = history[-1] if history else None
        if last:
            recent.append(
                {
                    "target_type": "team",
                    "target_id": team_id,
                    "target_name": team.get("display_name") or team.get("name"),
                    "run_id": last.get("run_id"),
                    "status": last.get("status"),
                    "timestamp": last.get("timestamp"),
                    "input": str(last.get("input") or "")[:300],
                    "output": str(last.get("output") or "")[:600],
                }
            )
        step = _live_step(live, f"team:{team_id}")
        team_items.append(
            {
                **team,
                "target_type": "team",
                "running": team_runtime.is_team_running(team_id),
                "active_runs": 1 if team_runtime.is_team_running(team_id) else 0,
                "status": _team_status(team, pending),
                "current_step": (step or {}).get("step") if step else "",
                "last_run_status": last.get("status") if last else None,
                "last_run_at": last.get("timestamp") if last else None,
                "pending_approvals": sum(
                    1
                    for p in pending
                    if str(p.get("agent_id"))
                    in {str(m.get("agent_id")) for m in team.get("members") or []}
                ),
                "member_count": len(team.get("members") or []),
                "next_run": _next_run_for("team", team_id),
            }
        )

    recent.sort(key=lambda r: float(r.get("timestamp", 0) or 0), reverse=True)
    upcoming = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "target_type": r.get("target_type"),
            "target_id": r.get("target_id"),
            "schedule": r.get("schedule"),
            "run_mode": r.get("run_mode"),
            "next_run": _routine_next(r),
        }
        for r in routine_items
        if r.get("enabled") and r.get("run_mode") in ("scheduled", "watcher")
    ]

    counts = {
        "agents": len(agent_items),
        "teams": len(team_items),
        "working": sum(1 for x in [*agent_items, *team_items] if x.get("status") == "working"),
        "waiting": len(pending),
        "scheduled": len(upcoming),
    }
    return {
        "agents": agent_items,
        "teams": team_items,
        "inbox": pending,
        "recent": recent[:20],
        "upcoming": upcoming[:20],
        "routines": routine_items,
        "counts": counts,
    }


def _routine_next(routine: dict[str, Any]) -> float | None:
    # A lightweight hint for the UI; the scheduler is the source of truth.
    if routine.get("run_mode") == "scheduled" and routine.get("schedule"):
        return None
    return None


def _next_run_for(target_type: str, target_id: str) -> float | None:
    for routine in routines.list_routines(limit=200):
        if (
            routine.get("enabled")
            and routine.get("target_type") == target_type
            and str(routine.get("target_id")) == target_id
            and routine.get("run_mode") == "scheduled"
        ):
            return None
    return None
