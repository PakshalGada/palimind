"""Tests for per-agent chat scope (separate sessions + direct routing)."""

from __future__ import annotations

from pathlib import Path

import palimind.api_server as server


def test_chat_root_agent_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "_agent_chat_root", lambda agent_id: tmp_path / agent_id)
    assert server._chat_root("agent:abc") == tmp_path / "abc"
    # An empty agent id resolves to None (no store).
    assert server._chat_root("agent:") is None
    # Unrelated scopes are untouched.
    assert server._chat_root("chat") == Path.home()


def test_agent_scope_chat_unknown_agent_streams_error() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    resp = client.get("/api/chat?q=hello&scope=agent:does-not-exist")
    assert resp.status_code == 200
    assert '"type": "error"' in resp.text


def test_agent_sessions_seeded_from_chat_log(tmp_path: Path, monkeypatch) -> None:
    from palimind.agents import chat as chatmod
    from palimind.memory import session_store

    monkeypatch.setattr(server, "_agent_chat_root", lambda agent_id: tmp_path / agent_id)
    monkeypatch.setattr(server, "_agent_sessions_seeded", set())
    monkeypatch.setattr(
        chatmod,
        "read_chat",
        lambda _agent_id: [
            {"role": "user", "content": "hello", "timestamp": 1.0},
            {"role": "agent", "content": "hi there", "timestamp": 2.0},
        ],
    )
    server._ensure_agent_sessions("abc")
    data = session_store.load_sessions(tmp_path / "abc")
    messages = data["sessions"][0]["messages"]
    assert [m["role"] for m in messages] == ["user", "system"]
    assert messages[1]["content"] == "hi there"


def test_agent_and_field_sessions_are_isolated(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setattr(server, "_agent_chat_root", lambda agent_id: tmp_path / "agents" / agent_id)
    monkeypatch.setattr(server, "_agent_sessions_seeded", set())
    monkeypatch.setattr(server.state, "active_field", tmp_path / "field")

    client = TestClient(server.app)
    agent_sessions = client.get("/api/sessions?scope=agent:aaa").json()
    field_sessions = client.get("/api/sessions?scope=field").json()
    assert agent_sessions["active_session_id"] != field_sessions["active_session_id"]

    # A new session on the agent must not appear in the field scope.
    client.post("/api/sessions/new?scope=agent:aaa", json={"name": "Agent convo"})
    assert len(client.get("/api/sessions?scope=agent:aaa").json()["sessions"]) == 2
    assert len(client.get("/api/sessions?scope=field").json()["sessions"]) == 1


def test_agent_scope_config(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    resp = client.get("/api/config?scope=agent:does-not-exist")
    assert resp.status_code == 200
    body = resp.json()
    assert "chat_model" in body
    assert body["moe_sub_mode"] == "default"
