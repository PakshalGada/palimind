"""Tests for global agents + selected-knowledge-base workspace context."""

from __future__ import annotations

import json
from pathlib import Path

from palimind.agents.runtime import _workspace_context_block


def test_workspace_context_reflects_selected_kb(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("hello", "utf-8")
    (tmp_path / "notes.txt").write_text("world", "utf-8")
    (tmp_path / ".palimind").mkdir()

    block = _workspace_context_block(tmp_path)
    assert block.startswith("[WORKSPACE CONTEXT]")
    assert "a.md" in block
    assert "notes.txt" in block
    assert ".palimind" not in block


def test_workspace_context_ignores_context_fields(tmp_path: Path) -> None:
    # The prompt must reflect the selected KB, not any saved context_fields.
    (tmp_path / "one.md").write_text("x", "utf-8")
    # A knowledge base OUTSIDE the selected root must not appear.
    outside = tmp_path / ".." / "some-other-kb"
    outside = outside.resolve()
    outside.mkdir(exist_ok=True)
    (outside / "hidden.md").write_text("y", "utf-8")

    block = _workspace_context_block(tmp_path)
    assert "one.md" in block
    assert "hidden.md" not in block
    assert "some-other-kb" not in block


def test_workspace_context_empty_for_none() -> None:
    assert _workspace_context_block(None) == ""
    assert _workspace_context_block(Path("/nonexistent-dir-xyz")) == ""


# ── global agent conversations ────────────────────────────────────────────


def test_chat_path_is_global_not_field_scoped(tmp_path: Path, monkeypatch) -> None:
    from palimind.agents import chat as chat_mod
    from palimind.agents.registry import get_registry

    monkeypatch.setattr(chat_mod.Path, "home", staticmethod(lambda: tmp_path))
    # Simulate an active field — chat path must ignore it.
    get_registry().field_root = tmp_path / "active-field"
    try:
        p = chat_mod.chat_path("agent-123")
        assert p == tmp_path / ".palimind" / "agents" / "chats" / "agent-123.json"
        assert "active-field" not in p.parts
    finally:
        get_registry().field_root = None


def test_migrate_field_chats_merges_and_deletes(tmp_path: Path, monkeypatch) -> None:
    from palimind.agents.catalog import migrate_field_chats

    monkeypatch.setattr("palimind.agents.catalog.Path.home", staticmethod(lambda: tmp_path))

    kb1 = tmp_path / "kb1"
    kb2 = tmp_path / "kb2"
    c1 = kb1 / ".palimind" / "agents" / "chats"
    c2 = kb2 / ".palimind" / "agents" / "chats"
    c1.mkdir(parents=True)
    c2.mkdir(parents=True)
    (c1 / "agent-123.json").write_text(
        json.dumps([{"role": "user", "content": "hi", "timestamp": 1.0}]), "utf-8"
    )
    (c2 / "agent-123.json").write_text(
        json.dumps([{"role": "agent", "content": "hello", "timestamp": 2.0}]), "utf-8"
    )

    migrated = migrate_field_chats([kb1, kb2])
    assert migrated == 2

    global_file = tmp_path / ".palimind" / "agents" / "chats" / "agent-123.json"
    assert global_file.exists()
    data = json.loads(global_file.read_text("utf-8"))
    assert len(data) == 2  # merged from both KBs
    # Field copies are gone
    assert not (c1 / "agent-123.json").exists()
    assert not (c2 / "agent-123.json").exists()
