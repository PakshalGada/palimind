"""Persisted SSE event log.

Every event is a row with a monotonic id, so a client that reconnects with
``Last-Event-ID`` can replay exactly the events it missed. Events are grouped
by a stream name (``global`` for the app event feed, ``chat:<id>`` for a chat
turn).
"""

from __future__ import annotations

import json
import time
from typing import Any

from palimind.storage import state_store


def append(stream: str, event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    now = time.time()
    conn = state_store.state_connection()
    try:
        cur = conn.execute(
            "INSERT INTO event_log(stream, type, payload, created_at) VALUES (?, ?, ?, ?)",
            (
                str(stream),
                str(payload.get("type") or ""),
                json.dumps(payload, ensure_ascii=False, default=str),
                now,
            ),
        )
        event_id = int(cur.lastrowid or 0)
        conn.commit()
    finally:
        conn.close()
    return {**payload, "event_id": event_id, "stream": str(stream), "created_at": now}


def replay(stream: str, after_id: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            "SELECT id, payload, created_at FROM event_log "
            "WHERE stream=? AND id>? ORDER BY id ASC LIMIT ?",
            (str(stream), int(after_id or 0), max(1, min(int(limit or 1000), 10_000))),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            out.append(
                {**payload, "event_id": int(row["id"]), "created_at": float(row["created_at"])}
            )
    return out


def latest_id(stream: str) -> int:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM event_log WHERE stream=?", (str(stream),)
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def prune(stream: str, keep: int = 10_000) -> int:
    """Keep only the newest *keep* events for a stream (best-effort)."""
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM event_log WHERE stream=?", (str(stream),)
        ).fetchone()
        count = int(row[0] if row else 0)
        excess = max(0, count - max(1, int(keep)))
        if not excess:
            return 0
        conn.execute(
            "DELETE FROM event_log WHERE id IN "
            "(SELECT id FROM event_log WHERE stream=? ORDER BY id ASC LIMIT ?)",
            (str(stream), excess),
        )
        conn.commit()
        return excess
    finally:
        conn.close()
