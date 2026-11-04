"""Persistent shared thread for a team.

Messages are the team's durable memory of work: the user asks, the manager
plans, members receive handoffs and post results, approvals surface in the
thread and a synthesis closes the run.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from palimind.storage import state_store

MESSAGE_LIMIT = 2000


def append_message(
    team_id: str,
    role: str,
    content: str,
    author: str = "system",
    run_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = {
        "id": str(uuid.uuid4()),
        "team_id": team_id,
        "author": author,
        "role": role,
        "content": str(content or ""),
        "run_id": run_id,
        "meta": meta or {},
        "created_at": time.time(),
    }
    state_store.append_team_message(team_id, message, MESSAGE_LIMIT)
    # Re-read so the caller receives the assigned sequence number.
    stored = state_store.list_team_messages(team_id, limit=1)
    return stored[-1] if stored else message


def list_messages(
    team_id: str, limit: int = 100, before_seq: int | None = None
) -> list[dict[str, Any]]:
    return state_store.list_team_messages(team_id, limit=limit, before_seq=before_seq)


def clear_messages(team_id: str) -> None:
    state_store.clear_team_messages(team_id)
