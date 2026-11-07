"""Persistent teams of agents.

A team is a durable group with an optional manager, a shared thread and a
blackboard. Teams never contain teams; membership is always a flat list of
agent ids. This module owns validation and storage only, the run coordinator
lives in :mod:`palimind.agents.team_runtime`.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from palimind.agents.catalog import GLOBAL_AGENTS_DIR
from palimind.storage import state_store

_NAME_RE = re.compile(r"^[\w-]{1,64}$")
TEAM_MODES = ("manager", "roundtable", "chain")
MAX_MEMBERS = 8
MAX_CONCURRENCY = 4


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _registry():
    from palimind.agents.registry import get_registry

    return get_registry()


def _team_dir(team_id: str):
    return GLOBAL_AGENTS_DIR / "teams" / team_id


# ── validation ────────────────────────────────────────────────────────────


def validate_team(data: dict[str, Any]) -> str | None:
    name = str(data.get("name") or "").strip()
    if not _NAME_RE.match(name):
        return "name must be 1-64 chars of letters, digits, underscore or dash"
    mode = str(data.get("mode") or "manager")
    if mode not in TEAM_MODES:
        return f"mode must be one of {TEAM_MODES}"

    members = data.get("members") or []
    if not isinstance(members, list):
        return "members must be a list"
    if len(members) < 1:
        return "a team needs at least one member"
    if len(members) > MAX_MEMBERS:
        return f"a team can have at most {MAX_MEMBERS} members"

    registry = _registry()
    seen: set[str] = set()
    for raw in members:
        agent_id = str((raw or {}).get("agent_id") if isinstance(raw, dict) else raw)
        if not agent_id:
            return "every member requires an agent_id"
        if agent_id in seen:
            return "team members must be unique"
        seen.add(agent_id)
        defn = registry.get_by_id(agent_id)
        if defn is None:
            return f"agent not found: {agent_id}"
        if not defn.enabled:
            return f"agent is disabled: {defn.label}"

    manager = str(data.get("manager_agent_id") or "")
    if manager and manager not in seen:
        return "manager must be a team member"
    try:
        concurrency = int(data.get("max_concurrency", 3) or 3)
    except (TypeError, ValueError):
        concurrency = 3
    if not (1 <= concurrency <= MAX_CONCURRENCY):
        return f"max_concurrency must be between 1 and {MAX_CONCURRENCY}"
    return None


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    for raw in data.get("members") or []:
        if isinstance(raw, dict):
            members.append(
                {
                    "agent_id": str(raw.get("agent_id") or ""),
                    "role": str(raw.get("role") or ""),
                    "manager": bool(raw.get("manager")),
                }
            )
        else:
            members.append({"agent_id": str(raw), "role": "", "manager": False})

    manager = str(data.get("manager_agent_id") or "")
    mode = str(data.get("mode") or "manager")
    if mode == "manager" and not manager and members:
        manager = members[0]["agent_id"]
    for member in members:
        member["manager"] = member["agent_id"] == manager

    return {
        "id": str(data.get("id") or uuid.uuid4()),
        "name": str(data.get("name") or "").strip(),
        "display_name": str(data.get("display_name") or data.get("name") or "").strip(),
        "description": str(data.get("description") or ""),
        "avatar": data.get("avatar") if isinstance(data.get("avatar"), dict) else {"type": "users"},
        "mode": mode,
        "manager_agent_id": manager or None,
        "manager_model": str(data.get("manager_model") or ""),
        "members": members,
        "charter": str(data.get("charter") or ""),
        "shared_memory": bool(data.get("shared_memory", False)),
        "working_root": str(data.get("working_root") or ""),
        "max_concurrency": max(1, min(MAX_CONCURRENCY, int(data.get("max_concurrency", 3) or 3))),
        "created_at": str(data.get("created_at") or _now_iso()),
        "updated_at": _now_iso(),
    }


# ── CRUD ──────────────────────────────────────────────────────────────────


def list_teams() -> list[dict[str, Any]]:
    teams = state_store.list_team_records()
    teams.sort(key=lambda t: str(t.get("name", "")).lower())
    return teams


def get_team(team_id: str) -> dict[str, Any] | None:
    return state_store.get_team_record(team_id)


def create_team(data: dict[str, Any]) -> dict[str, Any]:
    if any(str(t.get("name", "")).lower() == str(data.get("name", "")).lower() for t in list_teams()):
        raise ValueError(f"A team named '{data.get('name')}' already exists")
    error = validate_team(data)
    if error:
        raise ValueError(error)
    team = _normalise(data)
    state_store.upsert_team(team)
    _sync_agent_teams()
    return team


def update_team(team_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    existing = get_team(team_id)
    if existing is None:
        raise KeyError(f"Team not found: {team_id}")
    merged = {**existing, **changes, "id": team_id, "created_at": existing.get("created_at")}
    if "members" in changes or "manager_agent_id" in changes or "mode" in changes:
        merged = _normalise(merged)
    error = validate_team(merged)
    if error:
        raise ValueError(error)
    merged["updated_at"] = _now_iso()
    state_store.upsert_team(merged)
    _sync_agent_teams()
    return merged


def delete_team(team_id: str) -> bool:
    existing = get_team(team_id)
    if existing is None:
        return False
    state_store.delete_team_record(team_id)
    state_store.clear_team_messages(team_id)
    state_store.delete_json("team_notes", team_id)
    state_store.delete_team_runs(team_id)
    try:
        from palimind.agents import queue, routines

        for routine in routines.list_routines():
            if routine.get("target_type") == "team" and routine.get("target_id") == team_id:
                routines.delete_routine(str(routine.get("id")))
        queue.clear_target("team", team_id)
    except Exception:
        pass
    _sync_agent_teams()
    return True


def add_member(team_id: str, agent_id: str, role: str = "", manager: bool = False) -> dict[str, Any]:
    team = get_team(team_id)
    if team is None:
        raise KeyError("Team not found")
    members = list(team.get("members") or [])
    if any(str(m.get("agent_id")) == agent_id for m in members):
        raise ValueError("Agent is already a member")
    members.append({"agent_id": agent_id, "role": role, "manager": manager})
    changes: dict[str, Any] = {"members": members}
    if manager:
        changes["manager_agent_id"] = agent_id
    return update_team(team_id, changes)


def remove_member(team_id: str, agent_id: str) -> dict[str, Any]:
    team = get_team(team_id)
    if team is None:
        raise KeyError("Team not found")
    members = [m for m in team.get("members") or [] if str(m.get("agent_id")) != agent_id]
    changes: dict[str, Any] = {"members": members}
    if str(team.get("manager_agent_id") or "") == agent_id:
        changes["manager_agent_id"] = members[0]["agent_id"] if members else None
    return update_team(team_id, changes)


def set_manager(team_id: str, agent_id: str) -> dict[str, Any]:
    return update_team(team_id, {"manager_agent_id": agent_id, "mode": "manager"})


def team_for_agent(agent_id: str) -> list[dict[str, Any]]:
    return [
        team
        for team in list_teams()
        if any(str(m.get("agent_id")) == agent_id for m in team.get("members") or [])
    ]


def remove_agent_from_teams(agent_id: str) -> None:
    for team in team_for_agent(agent_id):
        try:
            remove_member(str(team["id"]), agent_id)
        except Exception:
            continue


def resolve_member(team: dict[str, Any], needle: str) -> dict[str, Any] | None:
    """Resolve a member by id, name, handle or label."""
    registry = _registry()
    needle = str(needle or "").strip().lstrip("@").lower()
    for member in team.get("members") or []:
        agent_id = str(member.get("agent_id"))
        defn = registry.get_by_id(agent_id)
        if defn is None:
            continue
        keys = {agent_id.lower(), defn.name.lower(), defn.label.lower()}
        if needle in keys:
            return {**member, "agent": defn}
    return None


def manager_of(team: dict[str, Any]) -> dict[str, Any] | None:
    manager_id = str(team.get("manager_agent_id") or "")
    members = team.get("members") or []
    if not members:
        return None
    if not manager_id:
        manager_id = str(members[0].get("agent_id"))
    return resolve_member(team, manager_id)


def _sync_agent_teams() -> None:
    """Keep the denormalised ``team_ids`` field on agent definitions fresh."""
    registry = _registry()
    membership: dict[str, list[str]] = {}
    for team in list_teams():
        for member in team.get("members") or []:
            membership.setdefault(str(member.get("agent_id")), []).append(str(team["id"]))
    for defn in registry.all():
        wanted = membership.get(defn.id, [])
        if list(defn.team_ids or []) != wanted:
            try:
                registry.update(defn.id, {"team_ids": wanted})
            except Exception:
                pass
