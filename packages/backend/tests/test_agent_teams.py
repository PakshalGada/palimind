"""Tests for teams, team thread, blackboard, routines and queue models."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.agents import blackboard, queue, routines, team_chat, teams
from palimind.agents.catalog import AgentDefinition
from palimind.agents.registry import get_registry
from palimind.storage import state_store


@pytest.fixture()
def two_agents(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(state_store, "state_db_path", lambda: tmp_path / "state.db")
    state_store._initialised.clear()
    registry = get_registry()
    registry._by_id = {}
    registry._by_name = {}
    first = registry.create(AgentDefinition.new("team-alpha", display_name="Alpha"))
    second = registry.create(AgentDefinition.new("team-beta", display_name="Beta"))
    yield first, second
    registry.delete(first.id)
    registry.delete(second.id)


def test_team_crud_and_validation(two_agents) -> None:
    first, second = two_agents
    team = teams.create_team(
        {
            "name": "growth-team",
            "display_name": "Growth",
            "members": [{"agent_id": first.id}, {"agent_id": second.id}],
        }
    )
    assert team["manager_agent_id"] == first.id
    assert teams.get_team(team["id"])["display_name"] == "Growth"
    assert teams.team_for_agent(second.id)[0]["id"] == team["id"]

    with pytest.raises(ValueError):
        teams.create_team({"name": "bad team", "members": [{"agent_id": first.id}]})
    with pytest.raises(ValueError):
        teams.update_team(team["id"], {"manager_agent_id": "missing"})

    assert teams.remove_member(team["id"], first.id)["manager_agent_id"] == second.id
    assert teams.delete_team(team["id"]) is True


def test_thread_and_blackboard(two_agents) -> None:
    first, second = two_agents
    team = teams.create_team(
        {"name": "thread-team", "members": [{"agent_id": first.id}, {"agent_id": second.id}]}
    )
    team_chat.append_message(team["id"], "user", "hello", author="user")
    team_chat.append_message(team["id"], "result", "done", author=f"agent:{first.id}")
    messages = team_chat.list_messages(team["id"])
    assert [m["role"] for m in messages] == ["user", "result"]
    assert [m["seq"] for m in messages] == [1, 2]

    blackboard.post(team["id"], "system", "Note", "remember this")
    assert "remember this" in blackboard.render(team["id"])
    blackboard.clear(team["id"])
    assert blackboard.entries(team["id"]) == []
    teams.delete_team(team["id"])


def test_routines_and_queue(two_agents) -> None:
    first, _second = two_agents
    routine = routines.create_routine(
        {
            "name": "Daily brief",
            "target_type": "agent",
            "target_id": first.id,
            "input": "Write a brief",
            "run_mode": "scheduled",
            "schedule": "0 9 * * 1",
        }
    )
    assert routine["enabled"] is True
    with pytest.raises(ValueError):
        routines.create_routine(
            {
                "name": "Bad cron",
                "target_type": "agent",
                "target_id": first.id,
                "input": "x",
                "run_mode": "scheduled",
                "schedule": "99 99 * * *",
            }
        )
    assert routines.get_routine(routine["id"]) is not None
    assert routines.delete_routine(routine["id"]) is True

    item = queue.enqueue("agent", first.id, "do work", priority=2)
    assert item["status"] == "queued"
    assert queue.next_due()["id"] == item["id"]
    assert queue.cancel_item(item["id"])["status"] == "cancelled"
    queue.clear_target("agent", first.id)
    assert queue.list_queue("agent", first.id) == []


def test_team_target_agent_runs_only_the_mentioned_member(two_agents, monkeypatch) -> None:
    import asyncio

    from palimind.agents import team_runtime

    first, second = two_agents
    team = teams.create_team(
        {"name": "mention-team", "members": [{"agent_id": first.id}, {"agent_id": second.id}]}
    )
    seen: list[str] = []

    async def fake_member(team_arg, member, task, **kwargs):
        seen.append(str(member.get("agent_id")))
        return {"agent_id": member.get("agent_id"), "name": "Beta", "output": "hello", "status": "ok"}

    monkeypatch.setattr(team_runtime, "_run_member", fake_member)

    async def emit(_event):
        return None

    result = asyncio.run(
        team_runtime.run_team(
            team,
            "@team-beta hello",
            emit=emit,
            target_agent_id=second.id,
        )
    )
    assert result["output"] == "hello"
    assert seen == [second.id]
    teams.delete_team(team["id"])
