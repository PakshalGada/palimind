"""Channel routing, task ownership and lifecycle tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.agents import channels
from palimind.agents.catalog import AgentDefinition
from palimind.agents.registry import get_registry
from palimind.storage import state_store


@pytest.fixture()
def agents(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    import palimind.agents.catalog as catalog

    monkeypatch.setattr(catalog, "GLOBAL_AGENTS_DIR", tmp_path / "agents")
    state_store._initialised.clear()
    registry = get_registry()
    registry._by_id = {}
    registry._by_name = {}
    alpha = registry.create(AgentDefinition.new("channel-alpha", display_name="Alpha"))
    beta = registry.create(AgentDefinition.new("channel-beta", display_name="Beta"))
    yield alpha, beta
    registry._by_id = {}
    registry._by_name = {}
    state_store._initialised.clear()


def test_channel_crud_members_and_messages(agents) -> None:
    alpha, beta = agents
    channel = channels.create_channel("Research", members=[alpha.id, beta.id], lead_agent_id=alpha.id)
    assert channel["name"] == "Research"
    assert len(channels.list_members(channel["id"])) == 2
    first = channels.append_message(channel["id"], "hello")
    second = channels.append_message(channel["id"], "world", operation_id="op-1")
    repeated = channels.append_message(channel["id"], "ignored", operation_id="op-1")
    assert repeated["id"] == second["id"]
    assert [m["seq"] for m in channels.list_messages(channel["id"])] == [1, 2]
    assert channels.add_member(channel["id"], alpha.id, role="lead")["role"] == "lead"
    assert channels.remove_member(channel["id"], beta.id) is True
    assert channels.archive_channel(channel["id"])["status"] == "archived"
    assert channels.restore_channel(channel["id"])["status"] == "active"
    assert channels.delete_channel(channel["id"]) is True
    assert channels.get_channel(channel["id"]) is None


def test_deterministic_routing(agents) -> None:
    alpha, beta = agents
    channel = channels.create_channel("Ops", members=[alpha.id, beta.id], lead_agent_id=alpha.id)
    assert channels.select_owner(channel["id"], "hi", explicit_agent_id=beta.id) == beta.id
    assert channels.select_owner(channel["id"], "hi") == alpha.id  # lead when two available
    channels.remove_member(channel["id"], alpha.id)
    assert channels.select_owner(channel["id"], "hi") == beta.id  # sole available member


def test_channel_task_revision_and_stop(agents) -> None:
    alpha, beta = agents
    channel = channels.create_channel("Build", members=[alpha.id, beta.id], lead_agent_id=alpha.id)
    task = channels.create_task(channel["id"], "do work", owner_agent_id=alpha.id)
    assert task["status"] == "open"
    moved = channels.transfer_task(task["id"], beta.id)
    assert moved["owner_agent_id"] == beta.id
    assert moved["revision"] == 2
    assert channels.stop_task(task["id"])["status"] == "cancelled"
    assert channels.list_tasks(channel["id"], status="cancelled")


def test_route_message_creates_task_for_owner(agents) -> None:
    alpha, beta = agents
    channel = channels.create_channel("Route", members=[alpha.id, beta.id], lead_agent_id=alpha.id)
    result = channels.route_message(channel["id"], "please handle this", explicit_agent_id=beta.id)
    assert result["owner_agent_id"] == beta.id
    assert result["task"]["owner_agent_id"] == beta.id
    assert result["message"]["task_id"] == result["task"]["id"]
