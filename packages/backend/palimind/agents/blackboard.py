"""Durable shared notes ("blackboard") for a team.

The blackboard is the shared context that makes a team feel like a team: a
manager can post a plan, members post findings, and the user can add notes.
It survives restarts and is injected into every member's prompt.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from palimind.storage import state_store

_NAMESPACE = "team_notes"
_MAX_ENTRIES = 200
_MAX_CONTENT = 4000


def entries(team_id: str) -> list[dict[str, Any]]:
    data = state_store.get_json(_NAMESPACE, team_id, default=[])
    return data if isinstance(data, list) else []


def post(
    team_id: str,
    author: str,
    label: str,
    content: str,
    kind: str = "finding",
) -> dict[str, Any]:
    entry = {
        "id": str(uuid.uuid4()),
        "team_id": team_id,
        "author": str(author or "system"),
        "label": str(label or kind)[:120],
        "content": str(content or "")[:_MAX_CONTENT],
        "kind": kind,
        "created_at": time.time(),
    }
    items = entries(team_id)
    items.append(entry)
    state_store.set_json(_NAMESPACE, team_id, items[-_MAX_ENTRIES:])
    return entry


def render(team_id: str, limit_chars: int = 12000) -> str:
    items = entries(team_id)
    if not items:
        return ""
    lines: list[str] = []
    used = 0
    for entry in reversed(items):
        line = f"- [{entry.get('author', '?')}] {entry.get('label', '')}: {entry.get('content', '')}"
        if used + len(line) > limit_chars:
            break
        lines.append(line)
        used += len(line)
    lines.reverse()
    return "[TEAM NOTES]\n" + "\n".join(lines) + "\n"


def clear(team_id: str) -> None:
    state_store.set_json(_NAMESPACE, team_id, [])


def delete(team_id: str) -> None:
    state_store.delete_json(_NAMESPACE, team_id)
