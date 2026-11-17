"""Chat branching: fork points, branch switching and path rendering."""

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


def _ids(session: dict) -> list[int]:
    return [m["id"] for m in session["messages"]]


def _user_msg_ids(session: dict) -> list[int]:
    return [m["id"] for m in session["messages"] if m["role"] == "user"]


def test_linear_session_has_chained_parents_and_full_path(root: Path) -> None:
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.append_message_to_session(root, sid, "user", "one")
    session_store.append_message_to_session(root, sid, "system", "two")
    session_store.append_message_to_session(root, sid, "user", "three")
    session = session_store.load_session_by_id(root, sid)
    assert len(session["messages"]) == 3  # unchanged rendering
    conn = session_store._connect(root)
    try:
        parents = conn.execute(
            "SELECT id, parent_id FROM messages WHERE session_id=? ORDER BY id",
            (sid,),
        ).fetchall()
    finally:
        conn.close()
    # Every row is chained to its predecessor.
    for (mid, parent), (prev, _) in zip(parents[1:], parents[:-1]):
        assert parent == prev


def test_fork_starts_new_branch_on_next_user_message(root: Path) -> None:
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.append_message_to_session(root, sid, "user", "tell me about dogs")
    session_store.append_message_to_session(root, sid, "system", "dogs are great")
    session_store.append_message_to_session(root, sid, "user", "more detail")
    session_store.append_message_to_session(root, sid, "system", "detail answer")

    session = session_store.load_session_by_id(root, sid)
    fork_at = session["messages"][1]["id"]  # the "dogs are great" answer

    result = session_store.fork_session_message(root, sid, fork_at)
    assert "error" not in result
    # The next user append branches instead of continuing the trunk.
    session_store.append_message_to_session(root, sid, "user", "what about cats?")
    session_store.append_message_to_session(root, sid, "system", "cats are also great")

    session = session_store.load_session_by_id(root, sid)
    # The active path now runs trunk up to the fork point, then the branch.
    contents = [m["content"] for m in session["messages"]]
    assert contents == [
        "tell me about dogs",
        "dogs are great",
        "what about cats?",
        "cats are also great",
    ]
    # The fork point now has two children: the trunk continuation and the
    # branch. Both are switchable entries.
    entries = session["branches"][str(fork_at)]
    assert len(entries) == 2
    assert any(entry["active"] for entry in entries)
    assert any(not entry["active"] for entry in entries)
    trunk_leaf = next(entry["leaf_id"] for entry in entries if not entry["active"])


def test_switch_back_to_trunk_branch(root: Path) -> None:
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.append_message_to_session(root, sid, "user", "q1")
    session_store.append_message_to_session(root, sid, "system", "a1")
    session_store.append_message_to_session(root, sid, "user", "q2")
    session_store.append_message_to_session(root, sid, "system", "a2")
    session = session_store.load_session_by_id(root, sid)
    fork_at = session["messages"][1]["id"]

    session_store.fork_session_message(root, sid, fork_at)
    session_store.append_message_to_session(root, sid, "user", "branch q")
    session_store.append_message_to_session(root, sid, "system", "branch a")

    session = session_store.load_session_by_id(root, sid)
    trunk_leaf = next(
        entry["leaf_id"] for entry in session["branches"][str(fork_at)] if not entry["active"]
    )
    result = session_store.set_session_active_leaf(root, sid, trunk_leaf)
    assert "error" not in result
    session = session_store.load_session_by_id(root, sid)
    assert [m["content"] for m in session["messages"]] == ["q1", "a1", "q2", "a2"]
    # The branch remains switchable from the fork point.
    assert len(session["branches"][str(fork_at)]) == 2


def test_truncate_after_is_branch_safe(root: Path) -> None:
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.append_message_to_session(root, sid, "user", "q1")
    session_store.append_message_to_session(root, sid, "system", "a1")
    session_store.append_message_to_session(root, sid, "user", "q2")
    session_store.append_message_to_session(root, sid, "system", "a2")
    session = session_store.load_session_by_id(root, sid)
    fork_at = session["messages"][1]["id"]
    session_store.fork_session_message(root, sid, fork_at)
    session_store.append_message_to_session(root, sid, "user", "branch q")
    session_store.append_message_to_session(root, sid, "system", "branch a")

    # Regenerate on the branch: only the branch tail is dropped.
    session = session_store.load_session_by_id(root, sid)
    branch_user = _user_msg_ids(session)[-1]
    session_store.truncate_after_message(root, sid, branch_user)
    session = session_store.load_session_by_id(root, sid)
    assert [m["content"] for m in session["messages"]] == ["q1", "a1", "branch q"]
    conn = session_store._connect(root)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=? AND content='branch q'",
            (sid,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1  # the forked branch head survived


def test_fork_armed_but_abandoned_writes_nothing(root: Path) -> None:
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.append_message_to_session(root, sid, "user", "q1")
    session_store.append_message_to_session(root, sid, "system", "a1")
    session = session_store.load_session_by_id(root, sid)
    fork_at = session["messages"][1]["id"]
    session_store.fork_session_message(root, sid, fork_at)
    # TTL expiry: backdate the marker instead of sleeping.
    with session_store._LOCK:
        key = session_store._turn_key(root, sid)
        stamp, target = session_store._FORK_POINTS[key]
        session_store._FORK_POINTS[key] = (
            stamp - session_store._FORK_TTL - 1,
            target,
        )
    session_store.append_message_to_session(root, sid, "user", "normal follow-up")
    session = session_store.load_session_by_id(root, sid)
    assert [m["content"] for m in session["messages"]] == ["q1", "a1", "normal follow-up"]


def test_fork_and_switch_endpoints(root: Path, monkeypatch) -> None:
    import palimind.api_server as api_server

    monkeypatch.setattr(api_server, "_chat_root", lambda scope: root)
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.append_message_to_session(root, sid, "user", "q1")
    session_store.append_message_to_session(root, sid, "system", "a1")
    session_store.append_message_to_session(root, sid, "user", "q2")
    session_store.append_message_to_session(root, sid, "system", "a2")
    session = session_store.load_session_by_id(root, sid)
    fork_at = session["messages"][1]["id"]  # mid-conversation fork point

    import asyncio

    class FakeRequest:
        def __init__(self, data):
            self._data = data

        async def json(self):
            return self._data

    forked = asyncio.run(
        api_server.fork_message_endpoint(
            FakeRequest({"session_id": sid, "message_id": fork_at}), scope="chat"
        )
    )
    assert "error" not in forked
    session_store.append_message_to_session(root, sid, "user", "branch q")
    session_store.append_message_to_session(root, sid, "system", "branch a")

    session = session_store.load_session_by_id(root, sid)
    trunk_leaf = session["branches"][str(fork_at)][0]["leaf_id"]
    switched = asyncio.run(
        api_server.switch_branch_endpoint(
            FakeRequest({"session_id": sid, "message_id": trunk_leaf}), scope="chat"
        )
    )
    assert "error" not in switched
    session = session_store.load_session_by_id(root, sid)
    # The trunk is restored in full; the forked branch remains switchable.
    assert [m["content"] for m in session["messages"]] == ["q1", "a1", "q2", "a2"]
    assert len(session["branches"][str(fork_at)]) == 2
    assert any(not entry["active"] for entry in session["branches"][str(fork_at)])

def test_legacy_full_session_write_keeps_linear_chain(root: Path) -> None:
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.save_single_session(
        root,
        {
            "id": sid,
            "name": "Replaced",
            "created_at": 1.0,
            "messages": [
                {"role": "user", "content": "legacy one", "timestamp": 1},
                {"role": "system", "content": "legacy two", "timestamp": 2},
            ],
        },
    )
    session = session_store.load_session_by_id(root, sid)
    assert len(session["messages"]) == 2
    assert [m["content"] for m in session["messages"]] == ["legacy one", "legacy two"]
