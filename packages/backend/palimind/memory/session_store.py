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


def _connect(root: Path) -> sqlite3.Connection:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    key = str(path.resolve())
    if key not in _INITIALISED:
        with _LOCK:
            if key not in _INITIALISED:
                _init_schema(conn)
                _INITIALISED.add(key)
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
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, id);

        CREATE TABLE IF NOT EXISTS session_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _active_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM session_meta WHERE key='active_session_id'").fetchone()
    return row[0] if row else ""


def _set_active(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "INSERT INTO session_meta(key, value) VALUES ('active_session_id', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (session_id,),
    )


def _session_dicts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT id, name, created_at, summary FROM sessions ORDER BY created_at ASC"
    ).fetchall()
    for sid, name, created_at, summary in rows:
        msg_rows = conn.execute(
            "SELECT role, content, timestamp, meta FROM messages "
            "WHERE session_id=? ORDER BY id ASC",
            (sid,),
        ).fetchall()
        messages: list[dict[str, Any]] = []
        for role, content, ts, meta_raw in msg_rows:
            msg: dict[str, Any] = {"role": role, "content": content, "timestamp": ts}
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
        if summary:
            sess["summary"] = summary
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
    for msg in sess.get("messages", []) or []:
        if not isinstance(msg, dict):
            continue
        extra = {k: v for k, v in msg.items() if k not in ("role", "content", "timestamp")}
        conn.execute(
            "INSERT INTO messages(session_id, role, content, timestamp, meta) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                sid,
                str(msg.get("role") or "user"),
                str(msg.get("content") or ""),
                float(msg.get("timestamp") or time.time()),
                json.dumps(extra, ensure_ascii=False, default=str),
            ),
        )


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
            "SELECT role, content, timestamp, meta FROM messages "
            "WHERE session_id=? ORDER BY id ASC",
            (sid,),
        ).fetchall()
    finally:
        conn.close()
    messages: list[dict[str, Any]] = []
    for role, content, ts, meta_raw in msg_rows:
        msg: dict[str, Any] = {"role": role, "content": content, "timestamp": ts}
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
    if summary:
        sess["summary"] = summary
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


def delete_session(root: Path, session_id: str) -> dict:
    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
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
    return load_sessions(root)


def append_message_to_session(
    root: Path,
    session_id: str,
    role: str,
    content: str,
    sources: list[str] | None = None,
    mode: str = "",
    mode_params: dict | None = None,
    citations: list[dict] | dict | None = None,
):
    """Append exactly one message. Other sessions/summaries are untouched."""
    extra: dict[str, Any] = {}
    if mode:
        extra["mode"] = mode
    if mode_params:
        extra["mode_params"] = mode_params
    if sources:
        extra["sources"] = sources
    if citations:
        extra["citations"] = citations

    conn = _connect(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT name FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            conn.rollback()
            return
        # First user message becomes the session title.
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        if msg_count == 0 and role == "user":
            conn.execute("UPDATE sessions SET name=? WHERE id=?", (str(content)[:200], session_id))
        conn.execute(
            "INSERT INTO messages(session_id, role, content, timestamp, meta) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                time.time(),
                json.dumps(extra, ensure_ascii=False, default=str),
            ),
        )
        conn.commit()
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
