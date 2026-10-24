from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from palimind.settings import AGENT_CHAT_LIMIT
from palimind.storage import state_store

logger = logging.getLogger(__name__)

CHAT_ROLES = ("user", "agent")


def _chat_dir() -> Path:
    """Agent conversations are global — one chat per agent across all
    knowledge bases, stored under ~/.palimind/agents/chats."""
    base = Path.home() / ".palimind" / "agents" / "chats"
    base.mkdir(parents=True, exist_ok=True)
    return base


def chat_path(agent_id: str) -> Path:
    """Legacy path (used only for one-time migration)."""
    return _chat_dir() / f"{agent_id}.json"


def _migrate(agent_id: str) -> None:
    path = chat_path(agent_id)
    if not path.exists():
        return
    try:
        import json

        data = json.loads(path.read_text("utf-8"))
    except Exception as exc:
        logger.error("Could not migrate agent chat %s: %s", path, exc)
        return
    if isinstance(data, list):
        for entry in data[-AGENT_CHAT_LIMIT:]:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role") or "")
            content = str(entry.get("content") or "")
            if role in CHAT_ROLES and content:
                state_store.append_agent_chat(agent_id, role, content, AGENT_CHAT_LIMIT)
    try:
        path.rename(path.with_suffix(".json.migrated"))
    except OSError:
        pass


def read_chat(agent_id: str) -> list[dict[str, Any]]:
    """Return the agent's persisted conversation as a list of
    {role, content, timestamp} dicts, oldest first."""
    if not state_store.read_agent_chat(agent_id, limit=1):
        _migrate(agent_id)
    return state_store.read_agent_chat(agent_id, limit=AGENT_CHAT_LIMIT)


def append_chat(agent_id: str, role: str, content: str) -> None:
    """Append one message to the agent's chat log, dropping the oldest
    entries when AGENT_CHAT_LIMIT is exceeded."""
    if role not in CHAT_ROLES:
        return
    content = str(content or "").strip()
    if not content:
        return
    try:
        state_store.append_agent_chat(agent_id, role, content[:100_000], AGENT_CHAT_LIMIT)
    except Exception as e:
        print(f"[agents] failed to write chat for {agent_id}: {e}")


def clear_chat(agent_id: str) -> None:
    try:
        state_store.clear_agent_chat(agent_id)
    except Exception as e:
        print(f"[agents] failed to clear chat for {agent_id}: {e}")
