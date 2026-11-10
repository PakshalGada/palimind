"""Durable mailbox deliveries.

Messages to an agent, task, channel or another agent become delivery records.
A delivery is independent of the provider: it keeps the text, attachments,
sender, status, hold reason, attempts, answer and error.  The queue moves a
delivery; the provider only sees the turn it starts.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from palimind.storage import state_store

STATUSES = ("queued", "starting", "running", "completed", "failed", "interrupted", "cancelled")
ACTIVE_STATUSES = ("queued", "starting", "running")
HOLD_REASONS = (
    "",
    "task-limit",
    "agent-busy",
    "usage-limit",
    "restarting",
    "hidden",
    "one-turn",
    "server-busy",
)


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
    value = _load(row["value"])
    return {
        **value,
        "id": row["id"],
        "target_agent_id": row["target_agent_id"],
        "target_thread_id": row["target_thread_id"],
        "task_id": row["task_id"],
        "status": row["status"],
        "idempotency_key": row["idempotency_key"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _event(delivery_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
    conn = state_store.state_connection()
    try:
        conn.execute(
            "INSERT INTO delivery_events(delivery_id, type, payload, created_at) VALUES (?, ?, ?, ?)",
            (delivery_id, event_type, json.dumps(payload or {}), _now()),
        )
        conn.commit()
    finally:
        conn.close()


def find_by_idempotency(target_agent_id: str, key: str) -> dict[str, Any] | None:
    if not key:
        return None
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT * FROM mailbox_deliveries WHERE target_agent_id=? AND idempotency_key=?",
            (target_agent_id, key),
        ).fetchone()
    finally:
        conn.close()
    return _row(row)


def send(
    target_agent_id: str,
    text: str,
    *,
    sender_kind: str = "user",
    sender_id: str = "",
    target_thread_id: str = "",
    task_id: str = "",
    attachments: list[dict[str, Any]] | None = None,
    idempotency_key: str = "",
    expects_reply: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_agent_id = str(target_agent_id or "").strip()
    if not target_agent_id:
        raise ValueError("target_agent_id is required")
    if idempotency_key:
        existing = find_by_idempotency(target_agent_id, idempotency_key)
        if existing is not None:
            return existing
    from palimind.agents import tasks, threads

    thread_id = str(target_thread_id or "")
    if not thread_id and task_id:
        task = tasks.get_task(task_id)
        if task:
            thread_id = str(task.get("thread_id") or "")
    if not thread_id:
        thread_id = str(threads.ensure_chat_thread(target_agent_id).get("id") or "")

    delivery_id = str(uuid.uuid4())
    now = _now()
    value = {
        "text": str(text or "")[:100_000],
        "sender_kind": str(sender_kind or "user"),
        "sender_id": str(sender_id or ""),
        "attachments": list(attachments or []),
        "expects_reply": bool(expects_reply),
        "answer": "",
        "error": "",
        "attempts": 0,
        "hold_reason": "",
        "metadata": dict(metadata or {}),
    }
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO mailbox_deliveries
                (id, target_agent_id, target_thread_id, task_id, status,
                 idempotency_key, value, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (
                delivery_id,
                target_agent_id,
                thread_id,
                str(task_id or ""),
                str(idempotency_key or ""),
                json.dumps(value),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    _event(delivery_id, "queued", {"sender_kind": sender_kind, "sender_id": sender_id})
    return get_delivery(delivery_id) or {}


def get_delivery(delivery_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM mailbox_deliveries WHERE id=?", (delivery_id,)).fetchone()
    finally:
        conn.close()
    return _row(row)


def list_deliveries(
    target_agent_id: str = "",
    *,
    status: str = "",
    task_id: str = "",
    thread_id: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if target_agent_id:
        clauses.append("target_agent_id=?")
        args.append(target_agent_id)
    if status:
        clauses.append("status=?")
        args.append(status)
    if task_id:
        clauses.append("task_id=?")
        args.append(task_id)
    if thread_id:
        clauses.append("target_thread_id=?")
        args.append(thread_id)
    args.append(max(1, min(int(limit or 200), 1000)))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM mailbox_deliveries {where} ORDER BY created_at DESC LIMIT ?", args
        ).fetchall()
    finally:
        conn.close()
    return [d for d in (_row(row) for row in rows) if d is not None]


def pending_count(target_agent_id: str) -> int:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM mailbox_deliveries WHERE target_agent_id=? AND status IN ('queued','starting','running')",
            (target_agent_id,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0] if row else 0)


def next_queued(target_agent_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            """
            SELECT * FROM mailbox_deliveries
            WHERE target_agent_id=? AND status='queued'
              AND (json_extract(value, '$.hold_reason') IS NULL OR json_extract(value, '$.hold_reason') = '')
            ORDER BY created_at ASC LIMIT 1
            """,
            (target_agent_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row(row)


def update_delivery(delivery_id: str, **changes: Any) -> dict[str, Any] | None:
    delivery = get_delivery(delivery_id)
    if delivery is None:
        return None
    value = dict(delivery)
    for key in (
        "text",
        "sender_kind",
        "sender_id",
        "attachments",
        "expects_reply",
        "answer",
        "error",
        "attempts",
        "hold_reason",
        "metadata",
    ):
        if key in changes:
            value[key] = changes[key]
    status = str(changes.get("status") or delivery.get("status") or "queued")
    if status not in STATUSES:
        raise ValueError(f"unknown delivery status: {status}")
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            UPDATE mailbox_deliveries SET status=?, value=?, updated_at=? WHERE id=?
            """,
            (
                status,
                json.dumps(
                    {
                        "text": value.get("text") or "",
                        "sender_kind": value.get("sender_kind") or "user",
                        "sender_id": value.get("sender_id") or "",
                        "attachments": value.get("attachments") or [],
                        "expects_reply": bool(value.get("expects_reply")),
                        "answer": value.get("answer") or "",
                        "error": value.get("error") or "",
                        "attempts": int(value.get("attempts") or 0),
                        "hold_reason": str(value.get("hold_reason") or ""),
                        "metadata": value.get("metadata")
                        if isinstance(value.get("metadata"), dict)
                        else {},
                    }
                ),
                _now(),
                delivery_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    _event(delivery_id, status, changes)
    return get_delivery(delivery_id)


def claim(delivery_id: str) -> dict[str, Any] | None:
    delivery = get_delivery(delivery_id)
    if delivery is None:
        return None
    if delivery.get("status") not in ("queued",):
        return delivery
    return update_delivery(
        delivery_id, status="starting", attempts=int(delivery.get("attempts") or 0) + 1
    )


def mark_running(delivery_id: str) -> dict[str, Any] | None:
    return update_delivery(delivery_id, status="running")


def complete(delivery_id: str, answer: str) -> dict[str, Any] | None:
    return update_delivery(delivery_id, status="completed", answer=str(answer or ""), error="")


def fail(delivery_id: str, error: str) -> dict[str, Any] | None:
    return update_delivery(delivery_id, status="failed", error=str(error or ""))


def interrupt(delivery_id: str, reason: str = "") -> dict[str, Any] | None:
    return update_delivery(delivery_id, status="interrupted", error=str(reason or ""))


def cancel(delivery_id: str) -> dict[str, Any] | None:
    return update_delivery(delivery_id, status="cancelled")


def retry(delivery_id: str) -> dict[str, Any] | None:
    return update_delivery(delivery_id, status="queued", error="", answer="")


def hold(delivery_id: str, reason: str) -> dict[str, Any] | None:
    if reason not in HOLD_REASONS:
        raise ValueError(f"unknown hold reason: {reason}")
    return update_delivery(delivery_id, hold_reason=reason)


def release(delivery_id: str) -> dict[str, Any] | None:
    return update_delivery(delivery_id, hold_reason="")


def react(
    message_id: str,
    emoji: str,
    *,
    actor_kind: str = "agent",
    actor_id: str = "",
) -> dict[str, Any]:
    reaction_id = str(uuid.uuid4())
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_reactions
                (id, message_id, actor_kind, actor_id, emoji, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (reaction_id, message_id, actor_kind, actor_id, emoji, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM agent_reactions WHERE message_id=? AND actor_kind=? AND actor_id=? AND emoji=?",
            (message_id, actor_kind, actor_id, emoji),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else {}


def list_reactions(message_id: str) -> list[dict[str, Any]]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM agent_reactions WHERE message_id=? ORDER BY created_at", (message_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def unreact(
    message_id: str,
    emoji: str,
    *,
    actor_kind: str = "agent",
    actor_id: str = "",
) -> bool:
    """Remove one reaction. Returns True when a row was deleted."""
    conn = state_store.state_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM agent_reactions "
            "WHERE message_id=? AND actor_kind=? AND actor_id=? AND emoji=?",
            (message_id, actor_kind, actor_id, emoji),
        )
        conn.commit()
        return bool(cursor.rowcount)
    finally:
        conn.close()


def events(delivery_id: str) -> list[dict[str, Any]]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM delivery_events WHERE delivery_id=? ORDER BY id", (delivery_id,)
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "delivery_id": row["delivery_id"],
            "type": row["type"],
            "payload": _load(row["payload"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def delete_for_agent(agent_id: str) -> int:
    conn = state_store.state_connection()
    try:
        cursor = conn.execute("DELETE FROM mailbox_deliveries WHERE target_agent_id=?", (agent_id,))
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()
