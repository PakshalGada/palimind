"""HTTP route smoke tests for the new agent surfaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.agents.catalog import AgentDefinition
from palimind.agents.registry import get_registry
from palimind.storage import state_store


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    import palimind.agents.catalog as catalog

    monkeypatch.setattr(catalog, "GLOBAL_AGENTS_DIR", tmp_path / "agents")
    state_store._initialised.clear()
    registry = get_registry()
    registry._by_id = {}
    registry._by_name = {}
    agent = registry.create(AgentDefinition.new("api-alpha", display_name="Alpha"))
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    test_client = TestClient(server.app)
    yield test_client, agent
    registry._by_id = {}
    registry._by_name = {}
    state_store._initialised.clear()


def test_task_mailbox_sections_and_context_routes(client) -> None:
    http, agent = client
    created = http.post(f"/api/agents/{agent.id}/tasks", json={"title": "API task", "input": "do it"}).json()
    task_id = created["task"]["id"]
    assert http.get(f"/api/agents/{agent.id}/tasks").json()["tasks"]
    assert http.get(f"/api/agents/{agent.id}/tasks/{task_id}").json()["task"]["id"] == task_id

    sent = http.post(f"/api/agents/{agent.id}/messages", json={"text": "hello", "client_message_id": "k1"}).json()
    assert http.get(f"/api/agents/{agent.id}/deliveries/{sent['messageId']}").json()["delivery"]["id"] == sent["messageId"]
    assert http.post(f"/api/agents/{agent.id}/context/clear").json()["ok"] is True

    section = http.post("/api/agents/sections/create", json={"name": "API section"}).json()["section"]
    assert any(s["id"] == section["id"] for s in http.get("/api/agents/sections/all").json()["sections"])
    assert http.delete(f"/api/agents/sections/{section['id']}").json()["deleted"] is True


def test_channel_provider_usage_and_browser_routes(client) -> None:
    http, agent = client
    channel = http.post("/api/channels", json={"name": "API channel", "members": [agent.id]}).json()["channel"]
    assert http.get("/api/channels").json()["channels"]
    message = http.post(f"/api/channels/{channel['id']}/messages", json={"text": "hello"}).json()
    assert message["message"]["text"] == "hello"
    assert http.get(f"/api/channels/{channel['id']}/messages").json()["messages"]

    assert "providers" in http.get("/api/providers").json()
    assert "total" in http.get("/api/usage").json()

    profile = http.post("/api/browser/profiles", json={"name": "API profile"}).json()["profile"]
    assert any(p["id"] == profile["id"] for p in http.get("/api/browser/profiles").json()["profiles"])
    assert http.delete(f"/api/browser/profiles/{profile['id']}").json()["deleted"] is True
