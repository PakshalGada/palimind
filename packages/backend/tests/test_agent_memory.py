"""Tests for agent memory recall and the self-critique definition field."""

from __future__ import annotations

from palimind.agents import memory as mem
from palimind.agents.catalog import AgentDefinition


def test_recall_memory_ranks_by_overlap(monkeypatch) -> None:
    entries = [
        {"timestamp": "2026-01-01", "type": "fact", "content": "User prefers Python and pytest"},
        {"timestamp": "2026-01-02", "type": "fact", "content": "The weather in Paris is mild"},
    ]
    monkeypatch.setattr(mem, "read_memory", lambda _agent_id: entries)
    out = mem.recall_memory("a", "how do I run pytest in python?", k=1)
    assert out and "Python" in out[0]["content"]


def test_recall_memory_falls_back_to_recent(monkeypatch) -> None:
    entries = [
        {"timestamp": "2026-01-01", "type": "fact", "content": "alpha beta gamma"},
        {"timestamp": "2026-01-02", "type": "fact", "content": "delta epsilon zeta"},
    ]
    monkeypatch.setattr(mem, "read_memory", lambda _agent_id: entries)
    out = mem.recall_memory("a", "zzzz qqqq", k=1)
    assert out == entries[-1:]


def test_recall_memory_empty(monkeypatch) -> None:
    monkeypatch.setattr(mem, "read_memory", lambda _agent_id: [])
    assert mem.recall_memory("a", "anything") == []


def test_agent_definition_self_critique_roundtrip() -> None:
    defn = AgentDefinition.new("critic", self_critique=True)
    assert defn.self_critique is True
    restored = AgentDefinition.from_dict(defn.to_dict())
    assert restored.self_critique is True


def test_agent_definition_self_critique_defaults_false() -> None:
    defn = AgentDefinition.from_dict({"name": "plain"})
    assert defn.self_critique is False
