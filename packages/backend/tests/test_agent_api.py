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
    created = http.post(
        f"/api/agents/{agent.id}/tasks", json={"title": "API task", "input": "do it"}
    ).json()
    task_id = created["task"]["id"]
    assert http.get(f"/api/agents/{agent.id}/tasks").json()["tasks"]
    assert http.get(f"/api/agents/{agent.id}/tasks/{task_id}").json()["task"]["id"] == task_id

    sent = http.post(
        f"/api/agents/{agent.id}/messages", json={"text": "hello", "client_message_id": "k1"}
    ).json()
    assert (
        http.get(f"/api/agents/{agent.id}/deliveries/{sent['messageId']}").json()["delivery"]["id"]
        == sent["messageId"]
    )
    assert http.post(f"/api/agents/{agent.id}/context/clear").json()["ok"] is True

    section = http.post("/api/agents/sections/create", json={"name": "API section"}).json()[
        "section"
    ]
    assert any(
        s["id"] == section["id"] for s in http.get("/api/agents/sections/all").json()["sections"]
    )
    assert http.delete(f"/api/agents/sections/{section['id']}").json()["deleted"] is True


def test_channel_provider_usage_and_browser_routes(client) -> None:
    http, agent = client
    channel = http.post(
        "/api/channels", json={"name": "API channel", "members": [agent.id]}
    ).json()["channel"]
    assert http.get("/api/channels").json()["channels"]
    message = http.post(f"/api/channels/{channel['id']}/messages", json={"text": "hello"}).json()
    assert message["message"]["text"] == "hello"
    assert http.get(f"/api/channels/{channel['id']}/messages").json()["messages"]

    assert "providers" in http.get("/api/providers").json()
    assert "total" in http.get("/api/usage").json()

    profile = http.post("/api/browser/profiles", json={"name": "API profile"}).json()["profile"]
    assert any(
        p["id"] == profile["id"] for p in http.get("/api/browser/profiles").json()["profiles"]
    )
    assert http.delete(f"/api/browser/profiles/{profile['id']}").json()["deleted"] is True


def test_session_message_actions_routes(client) -> None:
    from palimind.memory import session_store

    http, agent = client
    scope = f"agent:{agent.id}"
    data = http.get(f"/api/sessions?scope={scope}").json()
    sid = data["active_session_id"]

    from palimind.agents.chat import agent_session_root

    root = agent_session_root(agent.id)
    user_id = session_store.append_message_to_session(root, sid, "user", "hello")
    reply_id = session_store.append_message_to_session(root, sid, "system", "hi")

    edited = http.post(
        f"/api/sessions/message/edit?scope={scope}",
        json={"session_id": sid, "message_id": user_id, "content": "hello again", "resend": False},
    ).json()
    assert edited["message"]["content"] == "hello again"

    reaction = http.post(
        "/api/sessions/message/reactions",
        json={"session_id": sid, "message_id": reply_id, "emoji": "👍", "actor": "user"},
    ).json()
    assert reaction["reactions"][0]["emoji"] == "👍"

    removed = http.post(
        "/api/sessions/message/reactions",
        json={"session_id": sid, "message_id": reply_id, "emoji": "👍", "actor": "user"},
    ).json()
    assert removed["reactions"] == []

    read = http.post(
        f"/api/sessions/message/read?scope={scope}",
        json={"session_id": sid, "message_id": reply_id},
    ).json()
    session = next(s for s in read["sessions"] if s["id"] == sid)
    assert session["last_read_message_id"] == reply_id

    deleted = http.post(
        f"/api/sessions/message/delete?scope={scope}",
        json={"session_id": sid, "message_id": reply_id},
    ).json()
    assert deleted["message"]["deleted_at"]


def test_agent_model_notice_for_missing_opencode_key(client, monkeypatch) -> None:
    from palimind.agents.providers import resolver

    http, agent = client
    monkeypatch.setattr(resolver, "_opencode_key", lambda: "")
    from palimind.agents.registry import get_registry

    get_registry().update(agent.id, {"provider": "opencode", "model": "grok-4.7"})
    with http.stream(
        "GET",
        f"/api/chat?q=hello&scope=agent:{agent.id}&chat_mode=llm",
    ) as response:
        body = "".join(response.iter_text())
    assert "agent:model_notice" in body
    assert "add-key" in body
    assert "OpenCode" in body


def test_agent_setup_status_route(client, monkeypatch) -> None:
    http, _agent = client
    monkeypatch.setattr(
        "palimind.opencode.router.fetch_ollama_model_ids",
        lambda _url: {"qwen3.5:4b"},
    )
    monkeypatch.setattr(
        "palimind.agents.providers_api._opencode_key_present", lambda: True
    )
    monkeypatch.setattr(
        "palimind.agents.providers_api._opencode_catalog",
        lambda: [{"id": "grok-4.7"}],
    )
    data = http.get("/api/agents/setup-status").json()
    assert data["local"]["ready"] is True
    assert data["local"]["models"] == ["qwen3.5:4b"]
    assert data["opencode"]["key_present"] is True
    assert data["opencode"]["models"] == ["grok-4.7"]


def test_prepare_regenerate_keeps_one_prompt(client) -> None:
    from palimind.agents.chat import agent_session_root
    from palimind.memory import session_store

    http, agent = client
    scope = f"agent:{agent.id}"
    sid = http.get(f"/api/sessions?scope={scope}").json()["active_session_id"]
    root = agent_session_root(agent.id)
    user_id = session_store.append_message_to_session(root, sid, "user", "first prompt")
    session_store.append_message_to_session(root, sid, "system", "first answer")

    data = http.post(
        f"/api/sessions/message/prepare_regenerate?scope={scope}",
        json={"session_id": sid, "message_id": user_id},
    ).json()
    assert data["input"] == "first prompt"
    session = next(s for s in data["sessions"] if s["id"] == sid)
    assert session["messages"] == []


def test_unread_count_after_read_marker(client) -> None:
    from palimind.agents.chat import agent_session_root
    from palimind.memory import session_store

    http, agent = client
    root = agent_session_root(agent.id)
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.append_message_to_session(root, sid, "user", "question")
    reply = session_store.append_message_to_session(root, sid, "system", "answer")
    session_store.set_last_read_message(root, sid, reply)
    assert http.get("/api/agents").json()["agents"][0].get("unread_count", 0) == 0
    session_store.append_message_to_session(root, sid, "system", "new answer")
    assert http.get("/api/agents").json()["agents"][0].get("unread_count", 0) == 1
