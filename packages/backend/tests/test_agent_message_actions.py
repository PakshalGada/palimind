"""Deterministic tests for message identity, edits, read state and reactions."""

from __future__ import annotations

from pathlib import Path

import pytest

from palimind.memory import session_store


@pytest.fixture()
def root(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    from palimind.storage import state_store

    state_store._initialised.clear()
    return tmp_path


def _seed(root: Path) -> tuple[str, dict]:
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    user_id = session_store.append_message_to_session(root, sid, "user", "hello")
    reply_id = session_store.append_message_to_session(root, sid, "system", "hi there")
    return sid, {"user": user_id, "reply": reply_id}


def test_messages_have_stable_ids_and_meta(root: Path) -> None:
    sid, ids = _seed(root)
    data = session_store.load_sessions(root)
    session = next(s for s in data["sessions"] if s["id"] == sid)
    assert [m["id"] for m in session["messages"]] == [ids["user"], ids["reply"]]
    loaded = session_store.load_session_by_id(root, sid)
    assert loaded is not None
    assert loaded["messages"][0]["id"] == ids["user"]


def test_edit_and_soft_delete_round_trip(root: Path) -> None:
    sid, ids = _seed(root)
    edited = session_store.update_session_message(
        root, sid, ids["reply"], content="hello again", edited=True
    )
    assert edited is not None
    assert edited["content"] == "hello again"
    assert edited["edited_at"]
    session = session_store.load_session_by_id(root, sid)
    assert session["messages"][1]["content"] == "hello again"

    deleted = session_store.update_session_message(root, sid, ids["reply"], deleted=True)
    assert deleted is not None
    assert deleted["deleted_at"]
    session = session_store.load_session_by_id(root, sid)
    assert session["messages"][1]["deleted_at"]


def test_truncate_after_message_and_regenerate_selection(root: Path) -> None:
    sid, ids = _seed(root)
    session_store.append_message_to_session(root, sid, "system", "second answer")
    session_store.truncate_after_message(root, sid, ids["user"])
    session = session_store.load_session_by_id(root, sid)
    assert [m["id"] for m in session["messages"]] == [ids["user"]]


def test_last_read_survives_reload(root: Path) -> None:
    sid, ids = _seed(root)
    session_store.set_last_read_message(root, sid, ids["reply"])
    data = session_store.load_sessions(root)
    session = next(s for s in data["sessions"] if s["id"] == sid)
    assert session["last_read_message_id"] == ids["reply"]


def test_activity_labels_are_human_readable() -> None:
    from palimind.agents.service import _activity_label

    assert _activity_label("web_search") == "Searching the web"
    assert _activity_label("read_file") == "Reading files"
    assert _activity_label("run_shell") == "Running a command"
    assert _activity_label("unknown_tool") == "Working"


def test_chat_style_uses_personality() -> None:
    from palimind.agents.catalog import AgentDefinition
    from palimind.agents.service import CHAT_REPLY_STYLE, chat_style_for

    plain = AgentDefinition.new("plain")
    assert chat_style_for(plain) == CHAT_REPLY_STYLE
    warm = AgentDefinition.new("warm", personality_style="Warm, concise, a little funny")
    style = chat_style_for(warm)
    assert "Warm, concise" in style
    assert "like a person" in style
