"""Event waits.

An agent can end a turn with an open wait instead of polling.  A routine or a
local script wakes matching waits, which repeats the request and the note.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from palimind.storage import state_store

MAX_OPEN_WAITS = 20


def _now() -> float:
    return time.time()


def _load(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        **_load(row["value"]),
        "id": row["id"],
        "agent_id": row["agent_id"],
        "routine_id": row["routine_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "closed_at": row["closed_at"],
    }


def open_wait_count(agent_id: str) -> int:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM agent_waits WHERE agent_id=? AND status='open'", (agent_id,)
        ).fetchone()
    finally:
        conn.close()
    return int(row[0] if row else 0)


def create_wait(
    agent_id: str,
    note: str,
    *,
    routine_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not str(agent_id or "").strip():
        raise ValueError("agent_id is required")
    if open_wait_count(agent_id) >= MAX_OPEN_WAITS:
        raise ValueError(f"open wait limit ({MAX_OPEN_WAITS}) reached")
    wait_id = str(uuid.uuid4())
    now = _now()
    value = {"note": str(note or "")[:4000], "metadata": dict(metadata or {})}
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO agent_waits(id, agent_id, routine_id, status, value, created_at, closed_at)
            VALUES (?, ?, ?, 'open', ?, ?, NULL)
            """,
            (wait_id, agent_id, str(routine_id or ""), json.dumps(value), now),
        )
        conn.commit()
    finally:
        conn.close()
    return get_wait(wait_id) or {}


def get_wait(wait_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM agent_waits WHERE id=?", (wait_id,)).fetchone()
    finally:
        conn.close()
    return _row(row)


def list_waits(
    agent_id: str = "", *, status: str = "open", limit: int = 100
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if agent_id:
        clauses.append("agent_id=?")
        args.append(agent_id)
    if status:
        clauses.append("status=?")
        args.append(status)
    args.append(max(1, min(int(limit or 100), 500)))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM agent_waits {where} ORDER BY created_at ASC LIMIT ?", args
        ).fetchall()
    finally:
        conn.close()
    return [wait for wait in (_row(row) for row in rows) if wait is not None]


def close_wait(wait_id: str, *, reason: str = "") -> dict[str, Any] | None:
    wait = get_wait(wait_id)
    if wait is None:
        return None
    metadata = dict(wait.get("metadata") or {})
    metadata["close_reason"] = str(reason or "")
    conn = state_store.state_connection()
    try:
        conn.execute(
            "UPDATE agent_waits SET status='closed', value=?, closed_at=? WHERE id=?",
            (
                json.dumps({"note": wait.get("note") or "", "metadata": metadata}),
                _now(),
                wait_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_wait(wait_id)


def wake(
    agent_id: str,
    *,
    routine_id: str = "",
    wait_id: str = "",
    payload: str = "",
) -> list[dict[str, Any]]:
    """Wake matching open waits and return the woken records."""
    waits = list_waits(agent_id, status="open", limit=500)
    woken = []
    for wait in waits:
        if wait_id and wait["id"] != wait_id:
            continue
        if routine_id and wait.get("routine_id") not in ("", routine_id):
            continue
        metadata = dict(wait.get("metadata") or {})
        metadata["wake_payload"] = str(payload or "")[:4000]
        conn = state_store.state_connection()
        try:
            conn.execute(
                "UPDATE agent_waits SET status='woken', value=?, closed_at=? WHERE id=?",
                (
                    json.dumps({"note": wait.get("note") or "", "metadata": metadata}),
                    _now(),
                    wait["id"],
                ),
            )
            conn.commit()
        finally:
            conn.close()
        woken.append(get_wait(wait["id"]) or wait)
    return woken


def delete_for_agent(agent_id: str) -> int:
    conn = state_store.state_connection()
    try:
        cursor = conn.execute("DELETE FROM agent_waits WHERE agent_id=?", (agent_id,))
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()
