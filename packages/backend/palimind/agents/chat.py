from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from palimind.settings import AGENT_CHAT_LIMIT

CHAT_ROLES = ("user", "agent")


def _chat_dir() -> Path:
    from palimind.agents.registry import get_registry

    field_root = get_registry().field_root
    if field_root is not None:
        base = field_root / ".palimind" / "agents" / "chats"
    else:
        base = Path.home() / ".palimind" / "agents" / "chats"
    base.mkdir(parents=True, exist_ok=True)
    return base


def chat_path(agent_id: str) -> Path:
    return _chat_dir() / f"{agent_id}.json"


def read_chat(agent_id: str) -> list[dict[str, Any]]:
    """Return the agent's persisted conversation as a list of
    {role, content, timestamp} dicts, oldest first."""
    path = chat_path(agent_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict)]
    except Exception:
        return []


def append_chat(agent_id: str, role: str, content: str) -> None:
    """Append one message to the agent's chat log, dropping the oldest
    entries when AGENT_CHAT_LIMIT is exceeded."""
    if role not in CHAT_ROLES:
        return
    content = str(content or "").strip()
    if not content:
        return
    messages = read_chat(agent_id)
    messages.append({"role": role, "content": content[:8000], "timestamp": time.time()})
    if len(messages) > AGENT_CHAT_LIMIT:
        messages = messages[-AGENT_CHAT_LIMIT:]
    try:
        chat_path(agent_id).write_text(json.dumps(messages, indent=2), "utf-8")
    except OSError as e:
        print(f"[agents] failed to write chat for {agent_id}: {e}")


def clear_chat(agent_id: str) -> None:
    try:
        path = chat_path(agent_id)
        if path.exists():
            path.unlink()
    except OSError as e:
        print(f"[agents] failed to clear chat for {agent_id}: {e}")
