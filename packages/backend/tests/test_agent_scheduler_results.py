"""Scheduled/watcher results must land in the agent's own chat, not a field."""

from __future__ import annotations

import asyncio
from pathlib import Path

from palimind.agents import chat as chatmod
from palimind.agents import scheduler
from palimind.agents.catalog import AgentDefinition
from palimind.memory import session_store


def test_post_result_writes_to_agent_session(tmp_path: Path, monkeypatch) -> None:
    defn = AgentDefinition.new("brief-bot")
    agent_root = tmp_path / "agents" / defn.id
    monkeypatch.setattr(chatmod, "agent_session_root", lambda _agent_id: agent_root)

    initial = session_store.load_sessions(agent_root)
    session_id = initial["active_session_id"]

    asyncio.run(
        scheduler.post_result(defn, "Morning brief: all systems nominal.", "success", "scheduled")
    )

    data = session_store.load_sessions(agent_root)
    session = next(s for s in data["sessions"] if s["id"] == session_id)
    assert any("Morning brief: all systems nominal." in m["content"] for m in session["messages"])
    assert any("Scheduled run" in m["content"] for m in session["messages"])


def test_post_result_labels_watcher_runs(tmp_path: Path, monkeypatch) -> None:
    defn = AgentDefinition.new("file-bot")
    agent_root = tmp_path / "agents" / defn.id
    monkeypatch.setattr(chatmod, "agent_session_root", lambda _agent_id: agent_root)

    asyncio.run(scheduler.post_result(defn, "Handled the change.", "success", "watcher"))

    data = session_store.load_sessions(agent_root)
    text = "\n".join(m["content"] for s in data["sessions"] for m in s["messages"])
    assert "Watcher run" in text
    assert "Handled the change." in text
