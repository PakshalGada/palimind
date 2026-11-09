"""Durable agent threads and provider-session bindings.

A thread is the stable identity of one conversation.  A task, a channel turn,
a routine run and the main chat all create their own thread.  Provider session
ids live beside the thread so a provider switch keeps the public conversation
and only changes the private resume handle.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from palimind.storage import state_store

KINDS = ("chat", "task", "channel", "routine", "messaging")
STATUSES = ("active", "idle", "archived", "closed")


def _now() -> float:
    return time.time()


def _load(raw: Any, default: Any = None) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {} if default is None else default


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    value = _load(row["value"])
    return {
        **value,
        "id": row["id"],
        "agent_id": row["agent_id"],
        "kind": row["kind"],
        "provider": row["provider"],
        "provider_session_id": row["provider_session_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived_at": row["archived_at"],
    }


def create_thread(
    agent_id: str,
    *,
    kind: str = "chat",
    provider: str = "",
    thread_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    agent_id = str(agent_id or "").strip()
    if not agent_id:
        raise ValueError("agent_id is required")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    thread_id = str(thread_id or uuid.uuid4())
    now = _now()
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO agent_threads
                (id, agent_id, kind, provider, provider_session_id, status, value,
                 created_at, updated_at, archived_at)
            VALUES (?, ?, ?, ?, '', 'active', ?, ?, ?, NULL)
            """,
            (
                thread_id,
                agent_id,
                kind,
                provider,
                json.dumps({"metadata": metadata or {}}),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_thread(thread_id) or {}


def get_thread(thread_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM agent_threads WHERE id=?", (thread_id,)).fetchone()
    finally:
        conn.close()
    return _row(row)


def list_threads(
    agent_id: str = "", *, kind: str = "", include_archived: bool = False, limit: int = 200
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if agent_id:
        clauses.append("agent_id=?")
        args.append(agent_id)
    if kind:
        clauses.append("kind=?")
        args.append(kind)
    if not include_archived:
        clauses.append("archived_at IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(max(1, min(int(limit or 200), 1000)))
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM agent_threads {where} ORDER BY updated_at DESC LIMIT ?", args
        ).fetchall()
    finally:
        conn.close()
    return [t for t in (_row(row) for row in rows) if t is not None]


def find_chat_thread(agent_id: str) -> dict[str, Any] | None:
    for thread in list_threads(agent_id, kind="chat", limit=1):
        return thread
    return None


def ensure_chat_thread(agent_id: str) -> dict[str, Any]:
    thread = find_chat_thread(agent_id)
    if thread is not None:
        return thread
    return create_thread(agent_id, kind="chat")


def ensure_all_chat_threads(agent_ids: list[str] | None = None) -> int:
    if agent_ids is None:
        from palimind.agents.registry import get_registry

        agent_ids = [defn.id for defn in get_registry().all()]
    count = 0
    for agent_id in agent_ids:
        if find_chat_thread(agent_id) is None:
            create_thread(agent_id, kind="chat")
            count += 1
    return count


def update_thread(thread_id: str, **changes: Any) -> dict[str, Any] | None:
    thread = get_thread(thread_id)
    if thread is None:
        return None
    allowed = {
        "provider",
        "provider_session_id",
        "status",
        "archived_at",
        "metadata",
    }
    value = dict(thread)
    for key, item in changes.items():
        if key in allowed:
            value[key] = item
    now = _now()
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            UPDATE agent_threads SET provider=?, provider_session_id=?, status=?,
                value=?, updated_at=?, archived_at=? WHERE id=?
            """,
            (
                str(value.get("provider") or ""),
                str(value.get("provider_session_id") or ""),
                str(value.get("status") or "active"),
                json.dumps(
                    {
                        "metadata": value.get("metadata")
                        if isinstance(value.get("metadata"), dict)
                        else {}
                    }
                ),
                now,
                value.get("archived_at"),
                thread_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_thread(thread_id)


def bind_provider_session(
    thread_id: str,
    provider: str,
    session_id: str,
    *,
    fingerprint: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _now()
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO provider_sessions(thread_id, provider, session_id, fingerprint, value, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                provider=excluded.provider, session_id=excluded.session_id,
                fingerprint=excluded.fingerprint, value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (thread_id, provider, session_id, fingerprint, json.dumps(metadata or {}), now),
        )
        conn.execute(
            "UPDATE agent_threads SET provider=?, provider_session_id=?, updated_at=? WHERE id=?",
            (provider, session_id, now, thread_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_provider_session(thread_id) or {}


def get_provider_session(thread_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT * FROM provider_sessions WHERE thread_id=?", (thread_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "thread_id": row["thread_id"],
        "provider": row["provider"],
        "session_id": row["session_id"],
        "fingerprint": row["fingerprint"],
        "metadata": _load(row["value"]),
        "updated_at": row["updated_at"],
    }


def clear_provider_session(thread_id: str) -> None:
    conn = state_store.state_connection()
    try:
        conn.execute("DELETE FROM provider_sessions WHERE thread_id=?", (thread_id,))
        conn.execute(
            "UPDATE agent_threads SET provider_session_id='', updated_at=? WHERE id=?",
            (_now(), thread_id),
        )
        conn.commit()
    finally:
        conn.close()


def reset_thread(thread_id: str, *, reason: str = "context-reset") -> dict[str, Any] | None:
    """End provider sessions for a thread and leave a reset marker."""
    thread = get_thread(thread_id)
    if thread is None:
        return None
    clear_provider_session(thread_id)
    metadata = dict(thread.get("metadata") or {})
    markers = list(metadata.get("context_resets") or [])
    markers.append({"at": _now(), "reason": reason})
    metadata["context_resets"] = markers[-20:]
    return update_thread(thread_id, metadata=metadata, status="active")


def archive_thread(thread_id: str) -> dict[str, Any] | None:
    return update_thread(thread_id, status="archived", archived_at=_now())


def delete_threads_for_agent(agent_id: str) -> int:
    conn = state_store.state_connection()
    try:
        ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM agent_threads WHERE agent_id=?", (agent_id,)
            ).fetchall()
        ]
        for thread_id in ids:
            conn.execute("DELETE FROM provider_sessions WHERE thread_id=?", (thread_id,))
        conn.execute("DELETE FROM agent_threads WHERE agent_id=?", (agent_id,))
        conn.commit()
        return len(ids)
    finally:
        conn.close()
