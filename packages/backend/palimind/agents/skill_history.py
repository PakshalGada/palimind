"""Local skill run history."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from palimind.security.tokens import palimind_home

_LOCK = threading.Lock()


def _path() -> Path:
    return palimind_home() / "skill_history.jsonl"


def record_skill_run(
    *,
    skill_id: str,
    command: str,
    query: str = "",
    status: str = "sent",
) -> dict[str, Any]:
    entry = {
        "timestamp": time.time(),
        "skill_id": str(skill_id or ""),
        "command": str(command or ""),
        "query": str(query or "")[:500],
        "status": str(status or "sent"),
    }
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return entry


def read_skill_history(limit: int = 50) -> list[dict[str, Any]]:
    path = _path()
    if not path.is_file():
        return []
    cap = max(1, min(int(limit or 50), 500))
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
            if isinstance(item, dict):
                entries.append(item)
    except OSError:
        return []
    return entries
