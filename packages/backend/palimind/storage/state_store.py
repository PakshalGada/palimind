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
    if not db.exists():
        # Re-create the schema if the DB file was deleted while running.
        _initialised.discard(str(db))
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    key = str(db)
    if key not in _initialised:
        # One-time, per-file setup. journal_mode is persistent; switching it
        # concurrently from many fresh connections fails fast with "database
        # is locked" (the busy handler is not consulted), dropping writes.
        with _lock:
            if key not in _initialised:
                conn.execute("PRAGMA journal_mode=WAL")
                _init_schema(conn)
                _initialised.add(key)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def state_connection() -> sqlite3.Connection:
    """Public connection helper for modules that own their own schema."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
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

        CREATE TABLE IF NOT EXISTS teams (
            id         TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS team_messages (
            team_id    TEXT NOT NULL,
            seq        INTEGER NOT NULL,
            value      TEXT NOT NULL,
            timestamp  REAL NOT NULL,
            PRIMARY KEY (team_id, seq)
        );
        CREATE INDEX IF NOT EXISTS idx_team_messages_team
            ON team_messages(team_id, seq);

        CREATE TABLE IF NOT EXISTS routines (
            id         TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            enabled    INTEGER NOT NULL DEFAULT 1,
            next_run   REAL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS queue_items (
            id          TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_id   TEXT NOT NULL,
            status      TEXT NOT NULL,
            priority    INTEGER NOT NULL DEFAULT 0,
            value       TEXT NOT NULL,
            created_at  REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_queue_target
            ON queue_items(target_type, target_id, status, priority);

        CREATE TABLE IF NOT EXISTS jobs (
            id                TEXT PRIMARY KEY,
            kind              TEXT NOT NULL,
            target            TEXT NOT NULL DEFAULT '',
            payload           TEXT NOT NULL DEFAULT '{}',
            status            TEXT NOT NULL,
            priority          INTEGER NOT NULL DEFAULT 0,
            run_at            REAL NOT NULL,
            created_at        REAL NOT NULL,
            started_at        REAL,
            finished_at       REAL,
            attempts          INTEGER NOT NULL DEFAULT 0,
            max_attempts      INTEGER NOT NULL DEFAULT 3,
            last_error        TEXT NOT NULL DEFAULT '',
            lease_until       REAL,
            worker_id         TEXT NOT NULL DEFAULT '',
            idempotency_key   TEXT,
            parent_id         TEXT NOT NULL DEFAULT '',
            cron              TEXT NOT NULL DEFAULT '',
            interval_seconds  INTEGER NOT NULL DEFAULT 0,
            cancel_requested  INTEGER NOT NULL DEFAULT 0,
            result            TEXT NOT NULL DEFAULT '',
            updated_at        REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_due
            ON jobs(status, run_at, priority);
        CREATE INDEX IF NOT EXISTS idx_jobs_kind
            ON jobs(kind, status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idempotency
            ON jobs(idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key != '';

        CREATE TABLE IF NOT EXISTS job_events (
            job_id     TEXT NOT NULL,
            seq        INTEGER NOT NULL,
            type       TEXT NOT NULL,
            payload    TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            PRIMARY KEY (job_id, seq)
        );
        CREATE INDEX IF NOT EXISTS idx_job_events_job
            ON job_events(job_id, seq);

        CREATE TABLE IF NOT EXISTS event_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            stream     TEXT NOT NULL,
            type       TEXT NOT NULL DEFAULT '',
            payload    TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_event_log_stream
            ON event_log(stream, id);

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
            "SELECT value FROM runs WHERE agent_id=? ORDER BY timestamp DESC LIMIT ?",
            (agent_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    # Keep the *newest* ``limit`` runs (callers treat ``[-1]`` as the latest
    # run) but return them in chronological order.
    out: list[dict[str, Any]] = []
    for (raw,) in reversed(rows):
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            logger.error("Skipping corrupt run record for %s: %s", agent_id, exc)
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def delete_runs(agent_id: str) -> None:
    """Remove every persisted run record for *agent_id*."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM runs WHERE agent_id=?", (agent_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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


# ── teams / routines / queue ─────────────────────────────────────────────


def _read_row(raw: str, context: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        logger.error("Corrupt state value (%s): %s", context, exc)
        return None
    return value if isinstance(value, dict) else None


def upsert_team(team: dict[str, Any]) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO teams(id, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                value=excluded.value, updated_at=excluded.updated_at
            """,
            (str(team["id"]), _json_dumps(team), time.time()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_team_record(team_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM teams WHERE id=?", (str(team_id),)).fetchone()
    finally:
        conn.close()
    return _read_row(row[0], f"team/{team_id}") if row else None


def list_team_records() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT value FROM teams ORDER BY updated_at ASC").fetchall()
    finally:
        conn.close()
    out = [v for (raw,) in rows if (v := _read_row(raw, "teams"))]
    return out


def delete_team_record(team_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM teams WHERE id=?", (str(team_id),))
        conn.execute("DELETE FROM team_messages WHERE team_id=?", (str(team_id),))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def append_team_message(team_id: str, message: dict[str, Any], limit: int = 2000) -> None:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM team_messages WHERE team_id=?",
            (str(team_id),),
        ).fetchone()
        next_seq = int(row[0] or 0) + 1
        message = {**message, "seq": next_seq}
        conn.execute(
            "INSERT INTO team_messages(team_id, seq, value, timestamp) VALUES (?, ?, ?, ?)",
            (
                str(team_id),
                next_seq,
                _json_dumps(message),
                float(message.get("created_at") or time.time()),
            ),
        )
        conn.execute(
            """
            DELETE FROM team_messages WHERE team_id=? AND seq <= ?
            """,
            (str(team_id), max(0, next_seq - int(limit))),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_team_messages(
    team_id: str, limit: int = 100, before_seq: int | None = None
) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        if before_seq is not None:
            rows = conn.execute(
                "SELECT value FROM team_messages WHERE team_id=? AND seq < ? "
                "ORDER BY seq DESC LIMIT ?",
                (str(team_id), int(before_seq), int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT value FROM team_messages WHERE team_id=? ORDER BY seq DESC LIMIT ?",
                (str(team_id), int(limit)),
            ).fetchall()
    finally:
        conn.close()
    out = [v for (raw,) in rows if (v := _read_row(raw, f"team_messages/{team_id}"))]
    out.reverse()
    return out


def clear_team_messages(team_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM team_messages WHERE team_id=?", (str(team_id),))
        conn.commit()
    finally:
        conn.close()


def delete_team_runs(team_id: str) -> None:
    delete_runs(f"team:{team_id}")


def upsert_routine(routine: dict[str, Any]) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO routines(id, value, enabled, next_run, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                value=excluded.value, enabled=excluded.enabled,
                next_run=excluded.next_run, updated_at=excluded.updated_at
            """,
            (
                str(routine["id"]),
                _json_dumps(routine),
                1 if routine.get("enabled", True) else 0,
                routine.get("next_run"),
                time.time(),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_routine(routine_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM routines WHERE id=?", (str(routine_id),)).fetchone()
    finally:
        conn.close()
    return _read_row(row[0], f"routines/{routine_id}") if row else None


def list_routines(limit: int = 200) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT value FROM routines ORDER BY updated_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
    finally:
        conn.close()
    return [v for (raw,) in rows if (v := _read_row(raw, "routines"))]


def delete_routine(routine_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM routines WHERE id=?", (str(routine_id),))
        conn.commit()
    finally:
        conn.close()


def upsert_queue_item(item: dict[str, Any]) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO queue_items(id, target_type, target_id, status, priority, value, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status, priority=excluded.priority, value=excluded.value
            """,
            (
                str(item["id"]),
                str(item.get("target_type", "agent")),
                str(item.get("target_id", "")),
                str(item.get("status", "queued")),
                int(item.get("priority", 0) or 0),
                _json_dumps(item),
                float(item.get("created_at") or time.time()),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_queue_item(item_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM queue_items WHERE id=?", (str(item_id),)).fetchone()
    finally:
        conn.close()
    return _read_row(row[0], f"queue/{item_id}") if row else None


def list_queue_items(
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = "SELECT value FROM queue_items"
    clauses: list[str] = []
    params: list[Any] = []
    if target_type:
        clauses.append("target_type=?")
        params.append(target_type)
    if target_id:
        clauses.append("target_id=?")
        params.append(target_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY priority DESC, created_at ASC LIMIT ?"
    params.append(int(limit))
    conn = _connect()
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()
    return [v for (raw,) in rows if (v := _read_row(raw, "queue"))]


def delete_queue_item(item_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM queue_items WHERE id=?", (str(item_id),))
        conn.commit()
    finally:
        conn.close()


def delete_target_queue(target_type: str, target_id: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM queue_items WHERE target_type=? AND target_id=?",
            (target_type, target_id),
        )
        conn.commit()
    finally:
        conn.close()
