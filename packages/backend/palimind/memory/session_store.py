"""Concurrent-safe session persistence backed by SQLite (WAL).

The old implementation stored every session in its own JSON file and rewrote
all of them (plus an index) on every append. Two SSE streams could therefore
drop messages or overwrite a summary. Sessions now live in a per-workspace
``.palimind/state.db``:

* transactional inserts/updates (``BEGIN IMMEDIATE``);
* WAL mode for concurrent readers;
* an automatic one-time import of the legacy JSON layout.

The public functions are unchanged so the API/frontend keep working.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_INITIALISED: set[str] = set()


def get_sessions_index_file(root: Path) -> Path:
    return root / ".palimind" / "sessions_index.json"


def get_sessions_dir(root: Path) -> Path:
    return root / ".palimind" / "sessions"


def get_session_file(root: Path, session_id: str) -> Path:
    return get_sessions_dir(root) / f"{session_id}.json"


def _state_path(root: Path) -> Path:
    return root / ".palimind" / "state.db"


def has_session_data(root: Path) -> bool:
    """True when the session store already contains at least one message."""
    path = _state_path(root)
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
            return bool(row and row[0])
        finally:
            conn.close()
    except Exception:
        return False


def _connect(root: Path) -> sqlite3.Connection:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # The DB was removed out from under us (e.g. "clear agent sessions"
        # deletes the whole .palimind dir): re-create the schema instead of
        # failing with "no such table" until the server restarts.
        _INITIALISED.discard(str(path.resolve()))
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    key = str(path.resolve())
    if key not in _INITIALISED:
        # One-time, per-file setup: concurrent journal_mode switches from
        # fresh connections fail fast with "database is locked".
        with _LOCK:
            if key not in _INITIALISED:
                conn.execute("PRAGMA journal_mode=WAL")
                _init_schema(conn)
                _INITIALISED.add(key)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            summary    TEXT NOT NULL DEFAULT ''
        );


        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            timestamp  REAL NOT NULL,
            meta       TEXT NOT NULL DEFAULT '{}',
            parent_id  INTEGER,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, id);
        CREATE INDEX IF NOT EXISTS idx_messages_parent
            ON messages(parent_id);

        CREATE TABLE IF NOT EXISTS session_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- Full-text index over message content (external-content FTS5 kept in
        -- sync by triggers). Powers /api/search/sessions. Only the text lives
        -- in the index; metadata is joined back from messages via rowid.
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            content,
            content='messages',
            content_rowid='id'
        );
        CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
        END;
        CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
            INSERT INTO messages_fts(messages_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
            INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
        END;
        """
    )
    _migrate_message_parents(conn)
    _backfill_messages_fts(conn)
    conn.commit()


def _migrate_message_parents(conn: sqlite3.Connection) -> None:
    """Add the branching column to databases created before forking existed.

    Existing linear transcripts are chained (each row's parent is its
    predecessor) so every conversation is a tree; a NULL parent only means
    "first message of a session". The active path starts at the last message.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    if not columns:
        return  # fresh database — the CREATE TABLE already has parent_id
    if "parent_id" not in columns:
        conn.execute("ALTER TABLE messages ADD COLUMN parent_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(parent_id)")
        conn.execute(
            """
            UPDATE messages SET parent_id = (
                SELECT m2.id FROM messages m2
                WHERE m2.session_id = messages.session_id AND m2.id < messages.id
                ORDER BY m2.id DESC LIMIT 1
            )
            """
        )
    # Seed the active-path leaf for every session that has none yet.
    conn.execute(
        """
        INSERT INTO session_meta(key, value)
        SELECT 'active_leaf:' || s.session_id, s.maxid FROM (
            SELECT session_id, MAX(id) AS maxid FROM messages GROUP BY session_id
        ) s
        WHERE NOT EXISTS (
            SELECT 1 FROM session_meta sm WHERE sm.key = 'active_leaf:' || s.session_id
        )
        """
    )


def _backfill_messages_fts(conn: sqlite3.Connection) -> None:
    """Index messages written before the FTS table existed (one-time per DB)."""
    try:
        row = conn.execute(
            "SELECT value FROM session_meta WHERE key='messages_fts_ready'"
        ).fetchone()
        if row:
            return
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
        conn.execute(
            "INSERT INTO session_meta(key, value) VALUES ('messages_fts_ready', '1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
    except Exception as exc:  # noqa: BLE001
        # Search degrades to a LIKE scan when FTS5 is unavailable.
        logger.warning("messages_fts backfill failed: %s", exc)


def _active_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM session_meta WHERE key='active_session_id'").fetchone()
    return row[0] if row else ""


def _set_active(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO session_meta(key, value) VALUES ('active_session_id', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (session_id,),
    )


# ── Branching (conversation tree) ────────────────────────────────────────
# Every message carries parent_id, so a session is a tree: a normal append
# continues the active path, a fork starts a new child at any message. The
# linear transcript the API returns is the root→active-leaf path; sibling
# branches are returned per fork point so the UI can switch between them.


def _leaf_key(session_id: str) -> str:
    return f"active_leaf:{session_id}"


def _active_leaf(conn: sqlite3.Connection, session_id: str) -> int | None:
    row = conn.execute(
        "SELECT value FROM session_meta WHERE key=?", (_leaf_key(session_id),)
    ).fetchone()
    if not row:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _set_leaf(conn: sqlite3.Connection, session_id: str, message_id: int) -> None:
    conn.execute(
        "INSERT INTO session_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_leaf_key(session_id), str(int(message_id))),
    )


def _path_ids(conn: sqlite3.Connection, session_id: str, leaf_id: int | None) -> list[int]:
    """Message ids on the root→leaf path, root first."""
    ids: list[int] = []
    seen: set[int] = set()
    current = leaf_id
    while current is not None and current not in seen:
        seen.add(current)
        ids.append(current)
        row = conn.execute(
            "SELECT parent_id FROM messages WHERE session_id=? AND id=?",
            (session_id, current),
        ).fetchone()
        if row is None:
            break
        current = row[0]
    ids.reverse()
    return ids


def _latest_leaf(conn: sqlite3.Connection, session_id: str, start_id: int) -> int:
    """Deepest message in a subtree, following the newest child each step."""
    current = start_id
    while True:
        row = conn.execute(
            "SELECT id FROM messages WHERE session_id=? AND parent_id=? ORDER BY id DESC LIMIT 1",
            (session_id, current),
        ).fetchone()
        if row is None:
            return current
        current = int(row[0])


def _last_message_id(conn: sqlite3.Connection, session_id: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return int(row[0]) if row else None


def _session_path(
    conn: sqlite3.Connection, session_id: str
) -> tuple[list[int], int | None, dict[str, list[dict[str, Any]]]]:
    """Active path ids, the leaf, and sibling branches per fork point."""
    leaf = _active_leaf(conn, session_id)
    if leaf is None:
        leaf = _last_message_id(conn, session_id)
    path = _path_ids(conn, session_id, leaf)
    path_set = set(path)

    branches: dict[str, list[dict[str, Any]]] = {}
    if not path:
        return path, leaf, branches
    placeholders = ",".join("?" for _ in path)
    rows = conn.execute(
        "SELECT parent_id, id, timestamp, meta FROM messages "
        f"WHERE session_id=? AND parent_id IN ({placeholders}) ORDER BY id ASC",
        (session_id, *path),
    ).fetchall()
    children: dict[int, list[tuple[int, float, str]]] = {}
    for parent_id, message_id, ts, meta_raw in rows:
        children.setdefault(int(parent_id), []).append((int(message_id), ts, meta_raw))
    # Only fork points (more than one child) carry switcher data.
    for parent_id, kids in children.items():
        if len(kids) <= 1:
            continue
        entries: list[dict[str, Any]] = []
        for message_id, ts, meta_raw in kids:
            try:
                extra = json.loads(meta_raw or "{}")
            except (TypeError, json.JSONDecodeError):
                extra = {}
            label = str(extra.get("branch_label") or "").strip()
            entries.append(
                {
                    "message_id": message_id,
                    "leaf_id": _latest_leaf(conn, session_id, message_id),
                    "timestamp": ts,
                    "label": label or "Branch",
                    "active": message_id in path_set,
                }
            )
        branches[str(parent_id)] = entries
    return path, leaf, branches


def _session_dicts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT id, name, created_at, summary FROM sessions ORDER BY created_at ASC"
    ).fetchall()
    # Fetch every message in one pass instead of one query per session. The
    # frontend reloads all sessions after each turn, so N+1 here is felt
    # directly as chat latency once the history grows.
    grouped: dict[str, list[tuple[Any, ...]]] = {}
    msg_rows = conn.execute(
        "SELECT session_id, id, role, content, timestamp, meta FROM messages "
        "ORDER BY session_id ASC, id ASC"
    ).fetchall()
    for msg_row in msg_rows:
        grouped.setdefault(msg_row[0], []).append(msg_row[1:])
    last_read = {
        str(key).removeprefix("last_read:"): str(value)
        for key, value in conn.execute(
            "SELECT key, value FROM session_meta WHERE key LIKE 'last_read:%'"
        ).fetchall()
    }
    pinned = {
        str(key).removeprefix("pin:")
        for (key,) in conn.execute(
            "SELECT key FROM session_meta WHERE key LIKE 'pin:%'"
        ).fetchall()
    }

    for sid, name, created_at, summary in rows:
        path, leaf, branches = _session_path(conn, sid)
        by_id = {int(row[0]): row for row in grouped.get(sid, ())}
        messages: list[dict[str, Any]] = []
        for message_id in path:
            row = by_id.get(int(message_id))
            if row is None:
                continue
            role, content, ts, meta_raw = row[1], row[2], row[3], row[4]
            msg: dict[str, Any] = {
                "id": int(message_id),
                "role": role,
                "content": content,
                "timestamp": ts,
            }
            try:
                extra = json.loads(meta_raw or "{}")
            except (TypeError, json.JSONDecodeError):
                extra = {}
            if isinstance(extra, dict):
                msg.update(extra)
            messages.append(msg)
        sess: dict[str, Any] = {
            "id": sid,
            "name": name,
            "created_at": created_at,
            "messages": messages,
        }
        if branches:
            sess["branches"] = branches
        if leaf:
            sess["active_leaf"] = leaf
        if summary:
            sess["summary"] = summary
        if sid in pinned:
            sess["pinned"] = True
        if sid in last_read:
            try:
                sess["last_read_message_id"] = int(last_read[sid])
            except (TypeError, ValueError):
                sess["last_read_message_id"] = last_read[sid]
        sessions.append(sess)
    return sessions


def _migrate_legacy(root: Path, conn: sqlite3.Connection) -> bool:
    """Import the pre-SQLite layout exactly once. Returns True if imported."""
    index_file = get_sessions_index_file(root)
    old_file = root / ".palimind" / "sessions.json"
    if not index_file.exists() and not old_file.exists():
        return False

    sessions: list[dict[str, Any]] = []
    active_id = ""
    try:
        if index_file.exists():
            index_data = json.loads(index_file.read_text("utf-8"))
            active_id = str(index_data.get("active_session_id") or "")
            for meta in index_data.get("sessions", []):
                sid = str(meta.get("id") or "")
                if not sid:
                    continue
                sf = get_session_file(root, sid)
                if sf.exists():
                    sessions.append(json.loads(sf.read_text("utf-8")))
                else:
                    sessions.append(
                        {
                            "id": sid,
                            "name": meta.get("name", "Default Session"),
                            "created_at": meta.get("created_at", time.time()),
                            "messages": [],
                        }
                    )
        elif old_file.exists():
            data = json.loads(old_file.read_text("utf-8"))
            active_id = str(data.get("active_session_id") or "")
            sessions = [s for s in data.get("sessions", []) if isinstance(s, dict)]
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Legacy session migration failed (%s); starting fresh", exc)
        return False

    if not sessions:
        return False

    for sess in sessions:
        _upsert_session(conn, sess)
    if active_id:
        _set_active(conn, active_id)
    conn.commit()

    # Keep the originals as a safety net, but get them out of the read path.
    for path in (index_file, old_file):
        if path.exists():
            try:
                path.rename(path.with_suffix(path.suffix + ".migrated"))
            except OSError:
                pass
    sessions_dir = get_sessions_dir(root)
    if sessions_dir.is_dir():
        for f in sessions_dir.glob("*.json"):
            try:
                f.rename(f.with_suffix(".json.migrated"))
            except OSError:
                pass
    logger.info("Migrated %d legacy sessions into SQLite", len(sessions))
    return True


def _upsert_session(conn: sqlite3.Connection, sess: dict[str, Any]) -> None:
    sid = str(sess.get("id") or "")
    if not sid:
        return
    conn.execute(
        """
        INSERT INTO sessions(id, name, created_at, summary) VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, created_at=excluded.created_at, summary=excluded.summary
        """,
        (
            sid,
            str(sess.get("name") or "Default Session"),
            float(sess.get("created_at") or time.time()),
            str(sess.get("summary") or ""),
        ),
    )
    # Full-session writes replace the message list; incremental appends use
    # append_message_to_session and never touch other sessions.
    conn.execute("DELETE FROM messages WHERE session_id=?", (sid,))
    last_id = 0
    for msg in sess.get("messages", []) or []:
        if not isinstance(msg, dict):
            continue
        extra = {k: v for k, v in msg.items() if k not in ("role", "content", "timestamp")}
        cursor = conn.execute(
            "INSERT INTO messages(session_id, role, content, timestamp, meta, parent_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                sid,
                str(msg.get("role") or "user"),
                str(msg.get("content") or ""),
                float(msg.get("timestamp") or time.time()),
                json.dumps(extra, ensure_ascii=False, default=str),
                last_id or None,
            ),
        )
        last_id = int(cursor.lastrowid or 0)
    if last_id:
        _set_leaf(conn, sid, last_id)


def _default_session(root: Path) -> dict[str, Any]:
    sid = str(uuid.uuid4())
    sess = {
        "id": sid,
        "name": "Default Session",
        "created_at": time.time(),
        "messages": [],
    }
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _upsert_session(conn, sess)
        _set_active(conn, sid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"active_session_id": sid, "sessions": [sess]}


def load_session_by_id(root: Path, session_id: str) -> dict | None:
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT id, name, created_at, summary FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        sid, name, created_at, summary = row
        msg_rows = conn.execute(
            "SELECT id, role, content, timestamp, meta FROM messages "
            "WHERE session_id=? ORDER BY id ASC",
            (sid,),
        ).fetchall()
        path, leaf, branches = _session_path(conn, sid)
    finally:
        conn.close()
    by_id = {int(r[0]): r for r in msg_rows}
    messages: list[dict[str, Any]] = []
    for message_id in path:
        row = by_id.get(int(message_id))
        if row is None:
            continue
        _, role, content, ts, meta_raw = row
        msg: dict[str, Any] = {
            "id": int(message_id),
            "role": role,
            "content": content,
            "timestamp": ts,
        }
        try:
            extra = json.loads(meta_raw or "{}")
        except (TypeError, json.JSONDecodeError):
            extra = {}
        if isinstance(extra, dict):
            msg.update(extra)
        messages.append(msg)
    sess: dict[str, Any] = {
        "id": sid,
        "name": name,
        "created_at": created_at,
        "messages": messages,
    }
    if branches:
        sess["branches"] = branches
    if leaf:
        sess["active_leaf"] = leaf
    if summary:
        sess["summary"] = summary
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT value FROM session_meta WHERE key=?", (f"last_read:{sid}",)
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        try:
            sess["last_read_message_id"] = int(row[0])
        except (TypeError, ValueError):
            sess["last_read_message_id"] = row[0]
    return sess


def save_single_session(root: Path, session_data: dict):
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _upsert_session(conn, session_data)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_sessions(root: Path) -> dict:
    conn = _connect(root)
    try:
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        if count == 0:
            if not _migrate_legacy(root, conn):
                conn.rollback()
                conn.close()
                return _default_session(root)
        sessions = _session_dicts(conn)
        active = _active_id(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not sessions:
        return _default_session(root)
    if not active or not any(s["id"] == active for s in sessions):
        active = sessions[0]["id"]
    return {"active_session_id": active, "sessions": sessions}


def _write_sessions_data(root: Path, data: dict):
    """Replace the entire session set (used by explicit save operations)."""
    sessions = data.get("sessions", []) or []
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        keep = {str(s.get("id")) for s in sessions if isinstance(s, dict) and s.get("id")}
        if keep:
            placeholders = ",".join("?" for _ in keep)
            conn.execute(f"DELETE FROM sessions WHERE id NOT IN ({placeholders})", tuple(keep))
        else:
            conn.execute("DELETE FROM sessions")
        for sess in sessions:
            if isinstance(sess, dict):
                _upsert_session(conn, sess)
        _set_active(conn, str(data.get("active_session_id") or ""))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_sessions(root: Path, data: dict):
    _write_sessions_data(root, data)


def add_new_session(root: Path, name: str) -> dict:
    sid = str(uuid.uuid4())
    sess = {
        "id": sid,
        "name": name,
        "created_at": time.time(),
        "messages": [],
    }
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _upsert_session(conn, sess)
        _set_active(conn, sid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return load_sessions(root)


def set_active_session_id(root: Path, session_id: str) -> dict:
    conn = _connect(root)
    try:
        row = conn.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is not None:
            conn.execute("BEGIN IMMEDIATE")
            _set_active(conn, session_id)
            conn.commit()
    finally:
        conn.close()
    return load_sessions(root)


def rename_session(root: Path, session_id: str, name: str) -> dict:
    """Rename a session. Subsequent first-messages do not clobber this
    (auto-titling only fires for sessions with no messages yet)."""
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE sessions SET name=? WHERE id=?",
            (str(name or "").strip() or "Untitled chat", session_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return load_sessions(root)


def set_session_pinned(root: Path, session_id: str, pinned: bool) -> dict:
    """Pin/unpin a session (pinned chats sort to the top of the sidebar)."""
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if pinned:
            conn.execute(
                "INSERT INTO session_meta(key, value) VALUES (?, '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"pin:{session_id}",),
            )
        else:
            conn.execute("DELETE FROM session_meta WHERE key=?", (f"pin:{session_id}",))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return load_sessions(root)


def delete_session(root: Path, session_id: str) -> dict:
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        conn.execute("DELETE FROM session_meta WHERE key=?", (f"pin:{session_id}",))
        remaining = [
            row[0]
            for row in conn.execute("SELECT id FROM sessions ORDER BY created_at ASC").fetchall()
        ]
        if not remaining:
            sid = str(uuid.uuid4())
            _upsert_session(
                conn,
                {
                    "id": sid,
                    "name": "Default Session",
                    "created_at": time.time(),
                    "messages": [],
                },
            )
            _set_active(conn, sid)
        elif _active_id(conn) == session_id:
            _set_active(conn, remaining[0])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _delete_session_episodes(root, session_id)
    return load_sessions(root)


def _delete_session_episodes(root: Path, session_id: str) -> None:
    """Remove a deleted session's turns from episodic (long-term) memory.

    Otherwise a deleted conversation keeps resurfacing as "relevant past
    turns" in every other chat.
    """
    try:
        from palimind.storage.chat_store import ChatVectorStore

        with ChatVectorStore(root) as vstore:
            vstore.delete_session(session_id)
    except Exception as exc:
        logger.warning("Failed to purge episodic memory for session %s: %s", session_id, exc)


# ── Stopped turns ────────────────────────────────────────────────────────
# When the user presses Stop, the API saves the partial answer synchronously
# (``persist_stopped_turn``) and the stream generator's ``finally`` later tries
# to append its own copy once it notices the disconnect. The marker below makes
# that late append a no-op so the partial answer is stored exactly once. It is
# cleared by the next user message (a new turn) or after ``_STOPPED_TURN_TTL``.
_STOPPED_TURN_TTL = 300.0
_STOPPED_TURNS: dict[tuple[str, str], float] = {}


def _turn_key(root: Path, session_id: str) -> tuple[str, str]:
    try:
        base = str(Path(root).resolve())
    except OSError:
        base = str(root)
    return (base, str(session_id))


def _consume_stopped_marker(root: Path, session_id: str) -> bool:
    """Pop the stop marker for a session; True when it was set and fresh."""
    stamp = _STOPPED_TURNS.pop(_turn_key(root, session_id), None)
    return stamp is not None and time.monotonic() - stamp < _STOPPED_TURN_TTL


def _insert_message(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    content: str,
    extra: dict[str, Any],
    parent_id: int | None = None,
) -> int:
    # First user message becomes the session title.
    msg_count = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)
    ).fetchone()[0]
    if msg_count == 0 and role == "user":
        conn.execute("UPDATE sessions SET name=? WHERE id=?", (str(content)[:200], session_id))
    if parent_id is None:
        # A normal append continues the active path: parent = current leaf.
        parent_id = _active_leaf(conn, session_id)
        if parent_id is None:
            parent_id = _last_message_id(conn, session_id)
    cursor = conn.execute(
        "INSERT INTO messages(session_id, role, content, timestamp, meta, parent_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            session_id,
            role,
            content,
            time.time(),
            json.dumps(extra, ensure_ascii=False, default=str),
            parent_id,
        ),
    )
    message_id = int(cursor.lastrowid or 0)
    if message_id:
        # The active path now ends at this message.
        _set_leaf(conn, session_id, message_id)
    return message_id


def _message_extra(
    sources: list[str] | None,
    mode: str,
    mode_params: dict | None,
    citations: list[dict] | dict | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = dict(extra or {})
    if mode:
        out["mode"] = mode
    if mode_params:
        out["mode_params"] = mode_params
    if sources:
        out["sources"] = sources
    if citations:
        out["citations"] = citations
    return out


def persist_stopped_turn(
    root: Path,
    session_id: str,
    content: str,
    sources: list[str] | None = None,
    mode: str = "",
    mode_params: dict | None = None,
    citations: list[dict] | dict | None = None,
) -> bool:
    """Save the partial answer of a stream the user stopped — at most once.

    The answer is only appended when the session's last message is the user's
    turn (so a stream that already saved its final answer is not duplicated).
    Whatever the outcome, the session is marked so the stream generator's own
    late append of the same turn is dropped. Returns True when a message was
    written.
    """
    with _LOCK:
        _STOPPED_TURNS[_turn_key(root, session_id)] = time.monotonic()
        if not str(content or "").strip():
            return False
        conn = _connect(root)
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is None:
                conn.rollback()
                return False
            last = conn.execute(
                "SELECT role FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if last is None or last[0] != "user":
                conn.rollback()
                return False
            _insert_message(
                conn,
                session_id,
                "system",
                content,
                _message_extra(sources, mode, mode_params, citations),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def append_message_to_session(
    root: Path,
    session_id: str,
    role: str,
    content: str,
    sources: list[str] | None = None,
    mode: str = "",
    mode_params: dict | None = None,
    citations: list[dict] | dict | None = None,
    extra: dict[str, Any] | None = None,
) -> int:
    """Append exactly one message and return its SQLite id.

    An assistant append for a turn that was already saved by
    ``persist_stopped_turn`` is skipped (see the stop marker above).
    """
    if role == "user":
        # A new turn starts: any stop marker from the previous one is stale.
        with _LOCK:
            _STOPPED_TURNS.pop(_turn_key(root, session_id), None)
        return _append_message_row(
            root, session_id, role, content, sources, mode, mode_params, citations, extra
        )    # Check-and-insert atomically against ``persist_stopped_turn``.
    with _LOCK:
        if _consume_stopped_marker(root, session_id):
            return 0
        return _append_message_row(
            root, session_id, role, content, sources, mode, mode_params, citations, extra
        )


def _append_message_row(
    root: Path,
    session_id: str,
    role: str,
    content: str,
    sources: list[str] | None,
    mode: str,
    mode_params: dict | None,
    citations: list[dict] | dict | None,
    extra: dict[str, Any] | None = None,
) -> int:
    message_extra = _message_extra(sources, mode, mode_params, citations, extra)
    # A pending fork re-parents this append so it starts a new branch.
    fork_parent = _consume_fork_point(root, session_id) if role == "user" else None
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT name FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            conn.rollback()
            return 0
        message_id = _insert_message(conn, session_id, role, content, message_extra, fork_parent)
        conn.commit()
        return message_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def truncate_session_messages(root: Path, session_id: str, keep_count: int) -> dict:
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM messages WHERE session_id=? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        ]
        drop = ids[max(0, int(keep_count)) :]
        if drop:
            placeholders = ",".join("?" for _ in drop)
            conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", tuple(drop))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return load_sessions(root)


def delete_session_message(root: Path, session_id: str, index: int) -> dict:
    if int(index) < 0:
        # SQLite treats a negative OFFSET as 0, so a missing/-1 index (the API
        # default) used to delete the session's *first* message.
        return load_sessions(root)
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT id FROM messages WHERE session_id=? ORDER BY id ASC LIMIT 1 OFFSET ?",
            (session_id, int(index)),
        ).fetchone()
        if row is not None:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM messages WHERE id=?", (row[0],))
            conn.commit()
    finally:
        conn.close()
    return load_sessions(root)


# ── Message identity, edits, reactions and read state ────────────────────


def _message_payload(message_id: int, role: str, content: str, ts: float, meta_raw: str) -> dict:
    msg: dict[str, Any] = {
        "id": int(message_id),
        "role": role,
        "content": content,
        "timestamp": ts,
    }
    try:
        extra = json.loads(meta_raw or "{}")
    except (TypeError, json.JSONDecodeError):
        extra = {}
    if isinstance(extra, dict):
        msg.update(extra)
    return msg


def get_session_message(root: Path, session_id: str, message_id: int) -> dict | None:
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT id, role, content, timestamp, meta FROM messages "
            "WHERE session_id=? AND id=?",
            (session_id, int(message_id)),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _message_payload(*row)


def update_session_message(
    root: Path,
    session_id: str,
    message_id: int,
    *,
    content: str | None = None,
    meta: dict[str, Any] | None = None,
    deleted: bool = False,
    edited: bool = False,
) -> dict | None:
    """Patch one message in place. Returns the hydrated message or None."""
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT id, role, content, timestamp, meta FROM messages "
            "WHERE session_id=? AND id=?",
            (session_id, int(message_id)),
        ).fetchone()
        if row is None:
            return None
        mid, role, current, ts, meta_raw = row
        try:
            extra = json.loads(meta_raw or "{}")
        except (TypeError, json.JSONDecodeError):
            extra = {}
        if not isinstance(extra, dict):
            extra = {}
        if meta:
            extra.update(meta)
        if deleted:
            extra["deleted_at"] = time.time()
        if edited:
            extra["edited_at"] = time.time()
        new_content = current if content is None else str(content)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE messages SET content=?, meta=? WHERE session_id=? AND id=?",
            (
                new_content,
                json.dumps(extra, ensure_ascii=False, default=str),
                session_id,
                int(message_id),
            ),
        )
        conn.commit()
        return _message_payload(
            mid,
            role,
            new_content,
            ts,
            json.dumps(extra, ensure_ascii=False, default=str),
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def truncate_after_message(root: Path, session_id: str, message_id: int) -> dict:
    """Drop the active path after ``message_id`` (the message itself stays).

    Branch-aware: only messages on the current root→leaf path are deleted, so
    sibling branches keep existing for the branch switcher.
    """
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        leaf = _active_leaf(conn, session_id)
        path = _path_ids(conn, session_id, leaf) if leaf else []
        drop = [mid for mid in path if mid > int(message_id)]
        if not path or int(message_id) not in path:
            # Unknown fork point: fall back to the id-ordered truncation.
            drop = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM messages WHERE session_id=? AND id>? ORDER BY id ASC",
                    (session_id, int(message_id)),
                ).fetchall()
            ]
        if drop:
            placeholders = ",".join("?" for _ in drop)
            conn.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", tuple(drop))
        _set_leaf(conn, session_id, int(message_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return load_sessions(root)


# ── Forking and branch switching ─────────────────────────────────────────


def fork_session_message(
    root: Path,
    session_id: str,
    message_id: int,
) -> dict:
    """Arm a fork at ``message_id``: the next user turn starts a new branch.

    The marker is consumed by the next ``append_message_to_session`` (the
    /api/chat stream's user message), which is then parented to the fork point
    instead of the current leaf. Nothing is written until that turn arrives,
    so an abandoned fork leaves the transcript untouched. The visible path is
    not rewound — the marker only changes how the next append is parented.
    """
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            conn.rollback()
            return {"error": "Session not found"}
        target = conn.execute(
            "SELECT id FROM messages WHERE session_id=? AND id=?",
            (session_id, int(message_id)),
        ).fetchone()
        if target is None:
            conn.rollback()
            return {"error": "Message not found"}
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    with _LOCK:
        _FORK_POINTS[_turn_key(root, session_id)] = (time.monotonic(), int(message_id))
    return load_sessions(root)


_FORK_TTL = 300.0
_FORK_POINTS: dict[tuple[str, str], tuple[float, int]] = {}


def _consume_fork_point(root: Path, session_id: str) -> int | None:
    """Pop a pending fork; returns the message id the next append branches at."""
    stamp = _FORK_POINTS.get(_turn_key(root, session_id))
    if stamp is None:
        return None
    if time.monotonic() - stamp[0] > _FORK_TTL:
        _FORK_POINTS.pop(_turn_key(root, session_id), None)
        return None
    _FORK_POINTS.pop(_turn_key(root, session_id), None)
    return stamp[1]


def clear_fork(root: Path, session_id: str) -> None:
    """Disarm a pending fork (user cancelled the branch composer)."""
    with _LOCK:
        _FORK_POINTS.pop(_turn_key(root, session_id), None)


def set_session_active_leaf(root: Path, session_id: str, message_id: int) -> dict:
    """Switch the visible transcript to the branch ending at ``message_id``."""
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id FROM messages WHERE session_id=? AND id=?",
            (session_id, int(message_id)),
        ).fetchone()
        if row is None:
            conn.rollback()
            return {"error": "Message not found"}
        _set_leaf(conn, session_id, int(message_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return load_sessions(root)


def set_last_read_message(root: Path, session_id: str, message_id: int | str) -> dict:
    conn = _connect(root)
    try:
        conn.execute(
            "INSERT INTO session_meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (f"last_read:{session_id}", str(message_id)),
        )
        conn.commit()
    finally:
        conn.close()
    return load_sessions(root)


def clear_deleted_message(root: Path, session_id: str, message_id: int) -> None:
    """Hard-delete one message. Used by the explicit Delete action."""
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM messages WHERE session_id=? AND id=?",
            (session_id, int(message_id)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def background_update_memory(
    root: Path, session_id: str, new_user_msg: str, new_bot_msg: str
):
    await asyncio.sleep(2)
    from palimind.config import load_config
    from palimind.core.embedder import generate_embeddings_batch
    from palimind.generative.summariser import summarise_conversation
    from palimind.storage.chat_store import ChatVectorStore

    config = load_config(root)
    ollama_url = config.get("ollama_base_url")
    chat_model = config.get("chat_model")
    embed_model = config.get("embed_model")

    target_sess = load_session_by_id(root, session_id)
    if not target_sess:
        return

    recent_messages = target_sess.get("messages", [])[-6:]
    previous_summary = target_sess.get("summary", "")

    try:
        new_summary = await asyncio.to_thread(
            summarise_conversation,
            recent_messages,
            previous_summary,
            str(ollama_url or ""),
            str(chat_model or ""),
        )
        if new_summary:
            # Update only the summary; do not rewrite messages (which could
            # clobber a concurrent append).
            conn = _connect(root)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("UPDATE sessions SET summary=? WHERE id=?", (new_summary, session_id))
                conn.commit()
            finally:
                conn.close()
    except Exception as e:
        print(f"Failed to update summary: {e}")

    turn_content = f"User: {new_user_msg}\nAssistant: {new_bot_msg}"
    try:
        embs = await asyncio.to_thread(
            generate_embeddings_batch,
            [turn_content],
            str(ollama_url or ""),
            str(embed_model or ""),
        )
        if embs and embs[0]:
            chunk_id = int(uuid.uuid4().int % (2**63))
            with ChatVectorStore(root) as vstore:
                vstore.insert(
                    [
                        {
                            "vector": embs[0],
                            "chunk_id": chunk_id,
                            "session_id": session_id,
                            "content": turn_content,
                        }
                    ]
                )
    except Exception as e:
        print(f"Failed to update episodic memory: {e}")


# -- Full-text search over session content --


def _fts_match_expr(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression (OR of prefixes)."""
    import re

    tokens = re.findall(r"\w+", query.lower())
    if not tokens:
        return ""
    return " OR ".join(f"{token}*" for token in tokens)


def search_messages(
    root: Path,
    query: str,
    limit: int = 30,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Search message content across all sessions in a scope's store.

    Returns hits as
    ``{session_id, session_name, message_id, role, snippet, timestamp}``,
    newest first, excluding soft-deleted messages. Falls back to a LIKE scan
    when FTS5 or the match expression is unavailable.
    """
    text = str(query or "").strip()
    if not text:
        return []
    conn = _connect(root)
    try:
        try:
            return _search_messages_fts(conn, text, limit, session_id)
        except sqlite3.OperationalError:
            pass
        return _search_messages_like(conn, text, limit, session_id)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _search_messages_fts(
    conn: sqlite3.Connection,
    text: str,
    limit: int,
    session_id: str | None,
) -> list[dict[str, Any]]:
    match = _fts_match_expr(text)
    if not match:
        raise sqlite3.OperationalError("empty match expression")
    sql = """
        SELECT m.session_id, s.name, m.id, m.role,
               snippet(messages_fts, 0, '', '', '…', 16) AS snippet,
               m.timestamp
        FROM messages_fts
        JOIN messages m ON m.id = messages_fts.rowid
        LEFT JOIN sessions s ON s.id = m.session_id
        WHERE messages_fts MATCH ?
          AND json_extract(m.meta, '$.deleted_at') IS NULL
    """
    params: list[Any] = [match]
    if session_id:
        sql += " AND m.session_id = ?"
        params.append(session_id)
    sql += " ORDER BY m.timestamp DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, tuple(params)).fetchall()
    results: list[dict[str, Any]] = []
    for session_id, session_name, message_id, role, snippet, timestamp in rows:
        results.append(
            {
                "session_id": session_id,
                "session_name": session_name or session_id,
                "message_id": int(message_id),
                "role": role,
                "snippet": snippet,
                "timestamp": timestamp,
            }
        )
    return results


def _search_messages_like(
    conn: sqlite3.Connection,
    text: str,
    limit: int,
    session_id: str | None,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT m.id, m.session_id, s.name, m.role, m.content, m.timestamp "
        "FROM messages m LEFT JOIN sessions s ON s.id = m.session_id "
        "WHERE m.content LIKE ? ESCAPE '\\' "
        "AND json_extract(m.meta, '$.deleted_at') IS NULL"
    )
    params: list[Any] = [f"%{text.replace(chr(92), chr(92) * 2).replace('%', chr(92) + '%').replace('_', chr(92) + '_')}%"]
    if session_id:
        sql += " AND m.session_id = ?"
        params.append(session_id)
    sql += " ORDER BY m.timestamp DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, tuple(params)).fetchall()
    results: list[dict[str, Any]] = []
    for message_id, sid, session_name, role, content, timestamp in rows:
        lowered = content.lower()
        pos = lowered.find(text.lower())
        start = max(0, pos - 60)
        snippet = ("…" if start > 0 else "") + content[start : pos + len(text) + 80] + (
            "…" if pos + len(text) + 80 < len(content) else ""
        )
        results.append(
            {
                "session_id": sid,
                "session_name": session_name or sid,
                "message_id": int(message_id),
                "role": role,
                "snippet": snippet,
                "timestamp": timestamp,
            }
        )
    return results
