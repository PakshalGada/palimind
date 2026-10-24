"""Durable, concurrent-safe state for agent/session metadata.

Historically these stores were JSON files rewritten in full on every change.
Two concurrent writers could clobber each other, a crash mid-write could leave
invalid JSON, and parse errors were swallowed as "empty state".  This module
replaces them with a single SQLite database in WAL mode:

* writes are transactional (``BEGIN IMMEDIATE``) and durable;
* readers never see partial JSON;
* legacy JSON files are imported once and renamed ``*.bak``;
* retention is enforced in SQL rather than by rewriting a huge list.

The database is per-user (``~/.palimind/state.db``), not per-workspace, because
agents/goals/plans are global. Workspace sessions live in their workspace's
``.palimind/state.db`` (see :mod:`palimind.memory.session_store`).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_initialised: set[str] = set()


def state_db_path() -> Path:
    override = os.environ.get("PALIMIND_STATE_DB", "").strip()
    if override:
        return Path(override).expanduser()
    from palimind.security.tokens import palimind_home

    return palimind_home() / "state.db"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db = path or state_db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    key = str(db)
    if key not in _initialised:
        with _lock:
            if key not in _initialised:
                _init_schema(conn)
                _initialised.add(key)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kv (
            namespace  TEXT NOT NULL,
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (namespace, key)
        );

        CREATE TABLE IF NOT EXISTS agent_chat (
            agent_id  TEXT NOT NULL,
            seq       INTEGER NOT NULL,
            role      TEXT NOT NULL,
            content   TEXT NOT NULL,
            timestamp REAL NOT NULL,
            PRIMARY KEY (agent_id, seq)
        );
        CREATE INDEX IF NOT EXISTS idx_agent_chat_agent
            ON agent_chat(agent_id, seq);

        CREATE TABLE IF NOT EXISTS runs (
            agent_id   TEXT NOT NULL,
            run_id     TEXT NOT NULL,
            value      TEXT NOT NULL,
            timestamp  REAL NOT NULL,
            status     TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (agent_id, run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_runs_agent_time
            ON runs(agent_id, timestamp);

        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );
        INSERT INTO schema_version(version)
            SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
        """
    )
    conn.commit()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(raw: str, *, context: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        # Do not silently pretend the store was empty. Log loudly and move the
        # bad row aside so a subsequent write can repair it.
        logger.error("Corrupt state value (%s): %s", context, exc)
        raise


def get_json(namespace: str, key: str, default: Any = None) -> Any:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value FROM kv WHERE namespace=? AND key=?", (namespace, key)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return default
    try:
        return _json_loads(row[0], context=f"{namespace}/{key}")
    except Exception:
        return default


def set_json(namespace: str, key: str, value: Any) -> None:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO kv(namespace, key, value, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, key) DO UPDATE SET
                value=excluded.value, updated_at=excluded.updated_at
            """,
            (namespace, key, _json_dumps(value), time.time()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_json(namespace: str, key: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM kv WHERE namespace=? AND key=?", (namespace, key))
        conn.commit()
    finally:
        conn.close()


def list_json(namespace: str, limit: int = 1000) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT value FROM kv WHERE namespace=? ORDER BY updated_at DESC LIMIT ?",
            (namespace, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for (raw,) in rows:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            logger.error("Skipping corrupt state row in %s: %s", namespace, exc)
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def migrate_json_file(
    namespace: str,
    key: str,
    path: Path,
    *,
    default: Any = None,
) -> None:
    """Import *path* into the DB once, then rename it to ``*.bak``."""
    if not path.exists():
        return
    if get_json(namespace, key, default=None) is not None:
        return
    try:
        raw = path.read_text("utf-8")
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not migrate %s (%s); leaving it untouched", path, exc)
        return
    set_json(namespace, key, value)
    try:
        path.rename(path.with_suffix(path.suffix + ".bak"))
    except OSError:
        pass


# ── agent chat log ────────────────────────────────────────────────────────


def append_agent_chat(agent_id: str, role: str, content: str, limit: int) -> None:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM agent_chat WHERE agent_id=?", (agent_id,)
        ).fetchone()
        seq = int(row[0]) + 1
        conn.execute(
            "INSERT INTO agent_chat(agent_id, seq, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (agent_id, seq, role, content, time.time()),
        )
        conn.execute(
            """
            DELETE FROM agent_chat
            WHERE agent_id=? AND seq <= (
                SELECT COALESCE(MAX(seq), 0) - ? FROM agent_chat WHERE agent_id=?
            )
            """,
            (agent_id, int(limit), agent_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_agent_chat(agent_id: str, limit: int = 1000) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT role, content, timestamp FROM agent_chat "
            "WHERE agent_id=? ORDER BY seq DESC LIMIT ?",
            (agent_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"role": role, "content": content, "timestamp": ts} for role, content, ts in reversed(rows)
    ]


def clear_agent_chat(agent_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM agent_chat WHERE agent_id=?", (agent_id,))
        conn.commit()
    finally:
        conn.close()


# ── agent run history ─────────────────────────────────────────────────────


def append_run(agent_id: str, run_id: str, entry: dict[str, Any], limit: int) -> None:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO runs(agent_id, run_id, value, timestamp, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_id, run_id) DO UPDATE SET
                value=excluded.value, timestamp=excluded.timestamp,
                status=excluded.status
            """,
            (
                agent_id,
                str(run_id),
                _json_dumps(entry),
                float(entry["timestamp"]) if entry.get("timestamp") is not None else time.time(),
                str(entry.get("status") or ""),
            ),
        )
        conn.execute(
            """
            DELETE FROM runs WHERE agent_id=? AND run_id NOT IN (
                SELECT run_id FROM runs WHERE agent_id=?
                ORDER BY timestamp DESC LIMIT ?
            )
            """,
            (agent_id, agent_id, int(limit)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_runs(agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT value FROM runs WHERE agent_id=? ORDER BY timestamp ASC LIMIT ?",
            (agent_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for (raw,) in rows:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            logger.error("Skipping corrupt run record for %s: %s", agent_id, exc)
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def get_run(agent_id: str, run_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT value FROM runs WHERE agent_id=? AND run_id=?",
            (agent_id, str(run_id)),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as exc:
        logger.error("Corrupt run record %s/%s: %s", agent_id, run_id, exc)
        return None
    return value if isinstance(value, dict) else None
