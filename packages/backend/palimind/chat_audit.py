"""Local audit trail for chat, data and export actions."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from palimind.security.tokens import palimind_home

_LOCK = threading.Lock()


def audit_path() -> Path:
    return palimind_home() / "chat_audit.jsonl"


def append_chat_audit(
    event: str,
    *,
    session_id: str = "",
    scope: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    entry = {
        "timestamp": time.time(),
        "event": str(event or "unknown"),
        "session_id": str(session_id or ""),
        "scope": str(scope or ""),
        "detail": detail or {},
    }
    path = audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
    except OSError:
        # Auditing must never break the user's action.
        pass


def read_chat_audit(limit: int = 100, session_id: str = "") -> list[dict[str, Any]]:
    path = audit_path()
    if not path.is_file():
        return []
    cap = max(1, min(int(limit or 100), 500))
    entries: list[dict[str, Any]] = []
    try:
        with _LOCK:
            lines = path.read_text("utf-8").splitlines()
        for line in reversed(lines):
            if len(entries) >= cap:
                break
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_id and str(item.get("session_id") or "") != session_id:
                continue
            if isinstance(item, dict):
                entries.append(item)
    except OSError:
        return []
    return entries
