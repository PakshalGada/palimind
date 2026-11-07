"""Shared channel chats.

A channel is a durable group conversation with participating agents and one
lead.  Deterministic routing selects one owner; only when that fails does the
lead route the request.  Channel tasks reuse the mailbox and task primitives.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from palimind.storage import state_store

STATUSES = ("active", "archived")
TASK_STATUSES = ("open", "running", "completed", "failed", "cancelled", "closed")


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


def _channel_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        **_load(row["value"]),
        "id": row["id"],
        "name": row["name"],
        "purpose": row["purpose"],
        "lead_agent_id": row["lead_agent_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived_at": row["archived_at"],
    }


def _task_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        **_load(row["value"]),
        "id": row["id"],
        "channel_id": row["channel_id"],
        "owner_agent_id": row["owner_agent_id"],
        "parent_task_id": row["parent_task_id"],
        "revision": row["revision"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_channel(
    name: str,
    *,
    purpose: str = "",
    members: list[str] | None = None,
    lead_agent_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise ValueError("channel name is required")
    channel_id = str(uuid.uuid4())
    now = _now()
    conn = state_store.state_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO channels(id, name, purpose, lead_agent_id, status, value,
                                 created_at, updated_at, archived_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?, NULL)
            """,
            (channel_id, name[:120], str(purpose or "")[:2000], str(lead_agent_id or ""), json.dumps(metadata or {}), now, now),
        )
        for agent_id in members or []:
            if not agent_id:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO channel_members(channel_id, agent_id, role, instructions, created_at)
                VALUES (?, ?, '', '', ?)
                """,
                (channel_id, str(agent_id), now),
            )
        if not lead_agent_id and members:
            conn.execute(
                "UPDATE channels SET lead_agent_id=? WHERE id=?",
                (str(members[0]), channel_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_channel(channel_id) or {}


def get_channel(channel_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
    finally:
        conn.close()
    return _channel_row(row)


def channel_detail(channel_id: str) -> dict[str, Any] | None:
    channel = get_channel(channel_id)
    if channel is None:
        return None
    channel["members"] = list_members(channel_id)
    channel["messages"] = list_messages(channel_id, limit=100)
    channel["tasks"] = list_tasks(channel_id, limit=100)
    channel["memories"] = list_memories(channel_id)
    return channel


def list_channels(*, include_archived: bool = True, limit: int = 200) -> list[dict[str, Any]]:
    clause = "" if include_archived else "WHERE status='active'"
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM channels {clause} ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit or 200), 500)),),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        channel = _channel_row(row)
        if channel is None:
            continue
        channel["member_count"] = len(list_members(channel["id"]))
        out.append(channel)
    return out


def update_channel(channel_id: str, **changes: Any) -> dict[str, Any] | None:
    channel = get_channel(channel_id)
    if channel is None:
        return None
    allowed = {"name", "purpose", "lead_agent_id", "status", "metadata"}
    value = dict(channel)
    for key, item in changes.items():
        if key in allowed:
            value[key] = item
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            UPDATE channels SET name=?, purpose=?, lead_agent_id=?, status=?, value=?, updated_at=?, archived_at=?
            WHERE id=?
            """,
            (
                str(value.get("name") or channel["name"])[:120],
                str(value.get("purpose") or "")[:2000],
                str(value.get("lead_agent_id") or ""),
                str(value.get("status") or "active"),
                json.dumps(value.get("metadata") if isinstance(value.get("metadata"), dict) else {}),
                _now(),
                value.get("archived_at"),
                channel_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_channel(channel_id)


def archive_channel(channel_id: str) -> dict[str, Any] | None:
    for task in list_tasks(channel_id, status="open", limit=500):
        stop_task(task["id"])
    return update_channel(channel_id, status="archived", archived_at=_now())


def restore_channel(channel_id: str) -> dict[str, Any] | None:
    return update_channel(channel_id, status="active", archived_at=None)


def delete_channel(channel_id: str) -> bool:
    conn = state_store.state_connection()
    try:
        conn.execute("DELETE FROM channel_members WHERE channel_id=?", (channel_id,))
        conn.execute("DELETE FROM channel_messages WHERE channel_id=?", (channel_id,))
        conn.execute("DELETE FROM channel_tasks WHERE channel_id=?", (channel_id,))
        conn.execute("DELETE FROM channel_receipts WHERE channel_id=?", (channel_id,))
        conn.execute("DELETE FROM channel_memories WHERE channel_id=?", (channel_id,))
        cursor = conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_members(channel_id: str) -> list[dict[str, Any]]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM channel_members WHERE channel_id=? ORDER BY created_at", (channel_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def add_member(channel_id: str, agent_id: str, *, role: str = "", instructions: str = "") -> dict[str, Any]:
    if get_channel(channel_id) is None:
        raise ValueError("channel not found")
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO channel_members(channel_id, agent_id, role, instructions, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, agent_id) DO UPDATE SET
                role=excluded.role, instructions=excluded.instructions
            """,
            (channel_id, str(agent_id), str(role or ""), str(instructions or ""), _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return next(m for m in list_members(channel_id) if m["agent_id"] == agent_id)


def remove_member(channel_id: str, agent_id: str) -> bool:
    conn = state_store.state_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM channel_members WHERE channel_id=? AND agent_id=?",
            (channel_id, agent_id),
        )
        channel = get_channel(channel_id)
        if channel and channel.get("lead_agent_id") == agent_id:
            conn.execute("UPDATE channels SET lead_agent_id='' WHERE id=?", (channel_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_member_instructions(channel_id: str, agent_id: str, instructions: str) -> dict[str, Any]:
    return add_member(channel_id, agent_id, instructions=instructions)


def set_lead(channel_id: str, agent_id: str) -> dict[str, Any] | None:
    if agent_id and not any(m["agent_id"] == agent_id for m in list_members(channel_id)):
        raise ValueError("lead must be a channel member")
    return update_channel(channel_id, lead_agent_id=agent_id)


def append_message(
    channel_id: str,
    text: str,
    *,
    author_kind: str = "user",
    author_id: str = "user",
    task_id: str = "",
    attachments: list[dict[str, Any]] | None = None,
    operation_id: str = "",
) -> dict[str, Any]:
    if get_channel(channel_id) is None:
        raise ValueError("channel not found")
    if operation_id:
        receipt = get_receipt(channel_id, operation_id)
        if receipt is not None:
            return receipt
    conn = state_store.state_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM channel_messages WHERE channel_id=?",
            (channel_id,),
        ).fetchone()
        seq = int(row[0] if row else 1)
        message = {
            "id": str(uuid.uuid4()),
            "channel_id": channel_id,
            "seq": seq,
            "author_kind": str(author_kind or "user"),
            "author_id": str(author_id or "user"),
            "text": str(text or "")[:100_000],
            "task_id": str(task_id or ""),
            "attachments": list(attachments or []),
            "created_at": _now(),
            "operation_id": str(operation_id or ""),
        }
        conn.execute(
            "INSERT INTO channel_messages(channel_id, seq, value, created_at) VALUES (?, ?, ?, ?)",
            (channel_id, seq, json.dumps(message), message["created_at"]),
        )
        conn.execute(
            "UPDATE channels SET updated_at=? WHERE id=?", (message["created_at"], channel_id)
        )
        if operation_id:
            conn.execute(
                """
                INSERT OR REPLACE INTO channel_receipts(channel_id, operation_id, actor_id, value, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (channel_id, operation_id, str(author_id), json.dumps(message), message["created_at"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return message


def list_messages(
    channel_id: str, *, limit: int = 100, before_seq: int | None = None
) -> list[dict[str, Any]]:
    clauses = ["channel_id=?"]
    args: list[Any] = [channel_id]
    if before_seq is not None:
        clauses.append("seq < ?")
        args.append(int(before_seq))
    args.append(max(1, min(int(limit or 100), 500)))
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM channel_messages WHERE {' AND '.join(clauses)} ORDER BY seq DESC LIMIT ?",
            args,
        ).fetchall()
    finally:
        conn.close()
    return [message for message in (_load(row["value"]) for row in rows) if message][::-1]


def get_receipt(channel_id: str, operation_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute(
            "SELECT * FROM channel_receipts WHERE channel_id=? AND operation_id=?",
            (channel_id, operation_id),
        ).fetchone()
    finally:
        conn.close()
    return _load(row["value"]) if row is not None else None


def create_task(
    channel_id: str,
    request: str,
    *,
    owner_agent_id: str = "",
    parent_task_id: str = "",
    revision: int = 1,
) -> dict[str, Any]:
    channel = get_channel(channel_id)
    if channel is None:
        raise ValueError("channel not found")
    members = {m["agent_id"] for m in list_members(channel_id)}
    if owner_agent_id and owner_agent_id not in members:
        raise ValueError("owner must be a channel member")
    task_id = str(uuid.uuid4())
    now = _now()
    value = {
        "request": str(request or "")[:100_000],
        "result": "",
        "error": "",
        "metadata": {},
    }
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO channel_tasks(id, channel_id, owner_agent_id, parent_task_id,
                                      revision, status, value, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (task_id, channel_id, owner_agent_id, str(parent_task_id or ""), int(revision or 1), json.dumps(value), now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return get_task(task_id) or {}


def get_task(task_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM channel_tasks WHERE id=?", (task_id,)).fetchone()
    finally:
        conn.close()
    return _task_row(row)


def list_tasks(
    channel_id: str = "", *, status: str = "", limit: int = 100
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if channel_id:
        clauses.append("channel_id=?")
        args.append(channel_id)
    if status:
        clauses.append("status=?")
        args.append(status)
    args.append(max(1, min(int(limit or 100), 500)))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM channel_tasks {where} ORDER BY updated_at DESC LIMIT ?", args
        ).fetchall()
    finally:
        conn.close()
    return [task for task in (_task_row(row) for row in rows) if task is not None]


def update_task(task_id: str, **changes: Any) -> dict[str, Any] | None:
    task = get_task(task_id)
    if task is None:
        return None
    value = dict(task)
    for key in ("request", "result", "error", "metadata"):
        if key in changes:
            value[key] = changes[key]
    status = str(changes.get("status") or task.get("status") or "open")
    if status not in TASK_STATUSES:
        raise ValueError(f"unknown task status: {status}")
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            UPDATE channel_tasks SET owner_agent_id=?, revision=?, status=?, value=?, updated_at=?
            WHERE id=?
            """,
            (
                str(changes.get("owner_agent_id", task.get("owner_agent_id")) or ""),
                int(changes.get("revision", task.get("revision") or 1)),
                status,
                json.dumps(
                    {
                        "request": value.get("request") or "",
                        "result": value.get("result") or "",
                        "error": value.get("error") or "",
                        "metadata": value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
                    }
                ),
                _now(),
                task_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_task(task_id)


def assign_task(task_id: str, agent_id: str) -> dict[str, Any] | None:
    task = get_task(task_id)
    if task is None:
        return None
    return update_task(task_id, owner_agent_id=agent_id, revision=int(task.get("revision") or 1) + 1)


def transfer_task(task_id: str, agent_id: str) -> dict[str, Any] | None:
    return assign_task(task_id, agent_id)


def complete_task(task_id: str, result: str, *, status: str = "completed") -> dict[str, Any] | None:
    return update_task(task_id, status=status, result=str(result or ""), error="")


def stop_task(task_id: str) -> dict[str, Any] | None:
    return update_task(task_id, status="cancelled")


def select_owner(
    channel_id: str,
    text: str,
    *,
    explicit_agent_id: str = "",
    reply_to_task_id: str = "",
) -> str:
    members = {m["agent_id"] for m in list_members(channel_id)}
    if explicit_agent_id and explicit_agent_id in members:
        return explicit_agent_id
    if reply_to_task_id:
        task = get_task(reply_to_task_id)
        if task and str(task.get("owner_agent_id")) in members:
            return str(task["owner_agent_id"])
    open_tasks = list_tasks(channel_id, status="open", limit=10)
    if len(open_tasks) == 1 and str(open_tasks[0].get("owner_agent_id")) in members:
        return str(open_tasks[0]["owner_agent_id"])
    available = []
    for agent_id in members:
        if not is_agent_busy(agent_id):
            available.append(agent_id)
    if len(available) == 1:
        return available[0]
    channel = get_channel(channel_id) or {}
    lead = str(channel.get("lead_agent_id") or "")
    return lead if lead in members else ""


def is_agent_busy(agent_id: str) -> bool:
    from palimind.agents.runtime import running_count

    return running_count(agent_id) > 0


def is_busy(channel_id: str) -> bool:
    return bool(list_tasks(channel_id, status="running", limit=1))


def route_message(
    channel_id: str,
    text: str,
    *,
    author_kind: str = "user",
    author_id: str = "user",
    explicit_agent_id: str = "",
    reply_to_task_id: str = "",
    operation_id: str = "",
) -> dict[str, Any]:
    message = append_message(
        channel_id,
        text,
        author_kind=author_kind,
        author_id=author_id,
        operation_id=operation_id,
    )
    owner = select_owner(
        channel_id, text, explicit_agent_id=explicit_agent_id, reply_to_task_id=reply_to_task_id
    )
    if not owner:
        return {"message": message, "task": None, "error": "channelLeadRequired"}
    task = create_task(channel_id, text, owner_agent_id=owner)
    message["task_id"] = task["id"]
    return {"message": message, "task": task, "owner_agent_id": owner}


async def run_queued(channel_id: str, input_text: str) -> dict[str, Any]:
    """Run one routed channel turn.  Used by the durable queue."""
    from palimind.agents.registry import get_registry
    from palimind.agents.service import run_agent

    routed = route_message(channel_id, input_text, author_kind="user", author_id="user")
    task = routed.get("task")
    if not task:
        return {"status": "error", "error": routed.get("error") or "no owner"}
    owner = str(task.get("owner_agent_id") or "")
    defn = get_registry().get_by_id(owner)
    if defn is None:
        update_task(task["id"], status="failed", error="owner agent not found")
        return {"status": "error", "error": "owner agent not found"}
    update_task(task["id"], status="running")
    try:
        output = await run_agent(
            defn,
            input_text,
            session_id=f"_channel:{task['id']}",
            interactive=False,
            channel_id=channel_id,
            task_id=str(task["id"]),
        )
        append_message(
            channel_id,
            output,
            author_kind="agent",
            author_id=owner,
            task_id=task["id"],
        )
        complete_task(task["id"], output)
        return {"status": "success", "output": output, "task": get_task(task["id"])}
    except Exception as exc:  # noqa: BLE001
        update_task(task["id"], status="failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


def set_memory(channel_id: str, key: str, value: str) -> dict[str, Any]:
    if get_channel(channel_id) is None:
        raise ValueError("channel not found")
    conn = state_store.state_connection()
    try:
        conn.execute(
            """
            INSERT INTO channel_memories(channel_id, key, value, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (channel_id, str(key)[:200], str(value)[:10_000], _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"channel_id": channel_id, "key": key, "value": value}


def list_memories(channel_id: str) -> list[dict[str, Any]]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM channel_memories WHERE channel_id=? ORDER BY updated_at DESC",
            (channel_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]
