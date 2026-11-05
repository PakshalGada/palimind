"""Tests for memory 2.0: hybrid recall, editing, superseding, consolidation."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.agents import memory as mem


@pytest.fixture(autouse=True)
def _isolated_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(mem, "_memory_path", lambda _agent_id: tmp_path / "memory.json")
    monkeypatch.setattr(mem, "MEMORY_EMBEDDINGS", "hash")
    yield


def test_hybrid_recall_prefers_relevant_entry() -> None:
    mem.append_memory("a", "fact", "User prefers Python and pytest for backend work")
    mem.append_memory("a", "fact", "The weather in Paris is mild in spring")
    out = mem.recall_memory("a", "how do I run pytest with python?", k=1)
    assert out and "pytest" in out[0]["content"]


def test_entries_have_stable_ids_and_can_be_edited_and_deleted() -> None:
    first = mem.append_memory("a", "fact", "Original fact")
    assert first is not None and first["id"]
    read = mem.read_memory("a")
    assert read[0]["id"] == first["id"]

    updated = mem.update_memory_entry(
        "a", first["id"], content="Edited fact", entry_type="preference", confidence=0.8
    )
    assert updated is not None
    assert updated["content"] == "Edited fact"
    assert updated["type"] == "preference"
    assert updated["confidence"] == 0.8

    assert mem.delete_memory_entry_by_id("a", first["id"]) is True
    assert mem.read_memory("a") == []


def test_supersede_hides_old_entry_by_default() -> None:
    old = mem.append_memory("a", "preference", "User likes dark mode")
    assert old is not None
    new = mem.append_memory(
        "a", "preference", "User now prefers light mode", supersedes=[old["id"]]
    )
    assert new is not None

    active = mem.recall_memory("a", "mode preference", k=10)
    assert [e["id"] for e in active] == [new["id"]]

    all_entries = mem.recall_memory("a", "mode preference", k=10, include_superseded=True)
    assert {e["id"] for e in all_entries} == {old["id"], new["id"]}
    assert mem.memory_stats("a")["superseded"] == 1


def test_consolidate_marks_near_duplicates() -> None:
    mem.append_memory("a", "fact", "User likes Python for data work")
    mem.append_memory("a", "fact", "User likes Python for data work.")
    marked = mem.consolidate_memory("a", threshold=0.9)
    assert marked >= 1
    stats = mem.memory_stats("a")
    assert stats["superseded"] >= 1
    assert stats["active"] >= 1


def test_memory_center_endpoints() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    created = client.post(
        "/api/memory",
        json={"agent_id": "a", "type": "fact", "content": "User prefers tabs"},
    )
    assert created.status_code == 200
    entry = created.json()["entry"]
    assert entry["content"] == "User prefers tabs"

    listed = client.get("/api/memory", params={"agent_id": "a"})
    assert listed.status_code == 200
    assert listed.json()["entries"][0]["id"] == entry["id"]

    searched = client.get("/api/memory", params={"agent_id": "a", "q": "tabs preference"})
    assert searched.status_code == 200
    assert searched.json()["entries"]

    updated = client.patch(
        f"/api/memory/{entry['id']}",
        json={"agent_id": "a", "content": "User prefers tabs and spaces"},
    )
    assert updated.json()["entry"]["content"].endswith("spaces")

    stats = client.get("/api/memory/stats", params={"agent_id": "a"}).json()
    assert stats["total"] == 1

    deleted = client.delete(f"/api/memory/{entry['id']}", params={"agent_id": "a"})
    assert deleted.json()["status"] == "success"


def test_remember_and_forget_tools() -> None:
    from palimind.llm.mixture_of_expert.tools import call_tool, set_tool_context

    set_tool_context(None, agent_id="a")
    try:
        out = call_tool("remember", content="User prefers dark mode", entry_type="preference")
        assert "Remembered" in out
        entries = mem.read_memory("a")
        assert entries and entries[0]["content"] == "User prefers dark mode"

        forget_out = call_tool("forget", entry_id=entries[0]["id"])
        assert forget_out == "Forgotten."
        assert mem.read_memory("a") == []
    finally:
        set_tool_context(None)
