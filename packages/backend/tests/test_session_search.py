"""Full-text search over session message content (/api/search/sessions)."""

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


def _seed_history(root: Path) -> tuple[str, str]:
    data = session_store.load_sessions(root)
    sid = data["active_session_id"]
    session_store.append_message_to_session(root, sid, "user", "What churn metrics should we track?")
    session_store.append_message_to_session(
        root, sid, "system", "Focus on churn rate, retention curves and expansion revenue."
    )
    new = session_store.add_new_session(root, "Grocery list")
    sid2 = new["active_session_id"]
    session_store.append_message_to_session(root, sid2, "user", "Buy milk and eggs")
    return sid, sid2


def test_fts_backfill_indexes_existing_messages(root: Path) -> None:
    sid, _ = _seed_history(root)
    # Backfill happens at schema init; a direct FTS query finds seeded text.
    conn = session_store._connect(root)
    try:
        count = conn.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    finally:
        conn.close()
    assert count >= 3


def test_search_finds_message_and_returns_snippet(root: Path) -> None:
    sid, _ = _seed_history(root)
    results = session_store.search_messages(root, "churn metrics")
    assert results, "expected a hit for churn"
    assert all(r["session_id"] == sid for r in results)
    # Newest first; both the question and the answer mention churn.
    assert {r["role"] for r in results} == {"user", "system"}
    assert all("churn" in r["snippet"].lower() for r in results)
    assert results[0]["timestamp"] >= results[-1]["timestamp"]
    assert results[0]["session_name"]


def test_search_excludes_soft_deleted_messages(root: Path) -> None:
    sid, _ = _seed_history(root)
    data = session_store.load_session_by_id(root, sid)
    target = next(m for m in data["messages"] if m["role"] == "user")
    session_store.update_session_message(root, sid, target["id"], deleted=True)
    assert not session_store.search_messages(root, "should we track")


def test_search_updates_after_edit(root: Path) -> None:
    sid, _ = _seed_history(root)
    data = session_store.load_session_by_id(root, sid)
    user_msg = data["messages"][0]
    session_store.update_session_message(
        root, sid, user_msg["id"], content="Tell me about quokkas instead", edited=True
    )
    assert not session_store.search_messages(root, "should we track")
    hits = session_store.search_messages(root, "quokkas")
    assert hits and hits[0]["message_id"] == user_msg["id"]


def test_search_removed_rows_after_truncate(root: Path) -> None:
    sid, _ = _seed_history(root)
    data = session_store.load_session_by_id(root, sid)
    user_msg = data["messages"][0]
    session_store.truncate_after_message(root, sid, user_msg["id"])
    hits = session_store.search_messages(root, "expansion revenue")
    assert not hits
    assert session_store.search_messages(root, "churn")


def test_search_like_fallback(root: Path) -> None:
    _seed_history(root)
    conn = session_store._connect(root)
    try:
        results = session_store._search_messages_like(conn, "milk", 10, None)
    finally:
        conn.close()
    assert results and results[0]["role"] == "user"
    assert "milk" in results[0]["snippet"].lower()


def test_search_empty_query_returns_nothing(root: Path) -> None:
    _seed_history(root)
    assert session_store.search_messages(root, "   ") == []


def test_search_messages_scoped_to_session(root: Path) -> None:
    sid, sid2 = _seed_history(root)
    hits = session_store.search_messages(root, "milk", session_id=sid)
    assert not hits
    hits = session_store.search_messages(root, "milk", session_id=sid2)
    assert hits


def test_search_endpoint(tmp_path: Path, monkeypatch) -> None:
    import palimind.api_server as api_server
    from palimind.memory import session_store

    monkeypatch.setattr(api_server, "_chat_root", lambda scope: tmp_path)
    data = session_store.load_sessions(tmp_path)
    sid = data["active_session_id"]
    session_store.append_message_to_session(
        tmp_path, sid, "user", "unique_fts_probe needle content"
    )
    import asyncio

    response = asyncio.run(
        api_server.search_sessions(q="unique_fts_probe", scope="chat", limit=10)
    )
    assert response["results"], response
    assert response["results"][0]["session_id"] == sid


def test_legacy_database_without_parent_id_upgrades(tmp_path: Path) -> None:
    """A pre-branching store must migrate instead of failing schema setup."""
    import sqlite3

    db = tmp_path / ".palimind" / "state.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL, summary TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL, timestamp REAL NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE session_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO sessions VALUES ('s1', 'Legacy chat', 1, '');
        INSERT INTO messages(session_id, role, content, timestamp)
            VALUES ('s1', 'user', 'legacy one', 1),
                   ('s1', 'system', 'legacy two', 2);
        """
    )
    conn.commit()
    conn.close()

    hits = session_store.search_messages(tmp_path, "legacy")
    assert hits, "search should work after the legacy store is migrated"

    conn = sqlite3.connect(db)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        assert "parent_id" in columns
        parents = [row[0] for row in conn.execute("SELECT parent_id FROM messages ORDER BY id")]
        assert parents == [None, 1], "existing messages should be chained"
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_messages_parent'"
        ).fetchone()
    finally:
        conn.close()
