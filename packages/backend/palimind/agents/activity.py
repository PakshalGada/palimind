"""In-memory live activity for the agents Mission Control wall.

Tracks what each agent is doing *right now* (current step) plus a bounded
wire of recent start/step/finish events. Deliberately ephemeral: it is a
live feed, not a durable log (run history is persisted separately).

All access is guarded by a lock because agent runs execute on worker threads.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_running: dict[str, dict[str, Any]] = {}
_recent: list[dict[str, Any]] = []
_RECENT_LIMIT = 80


def _push(ev: dict[str, Any]) -> None:
    _recent.append(ev)
    if len(_recent) > _RECENT_LIMIT:
        del _recent[:-_RECENT_LIMIT]


def _display_source(session_id: str) -> str:
    return (session_id or "manual").lstrip("_") or "manual"


def start(agent_id: str, name: str, run_id: str, session_id: str = "") -> None:
    source = _display_source(session_id)
    with _lock:
        _running[agent_id] = {
            "agent_id": agent_id,
            "name": name,
            "run_id": run_id,
            "source": source,
            "step": "starting",
            "status": "running",
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        _push(
            {
                "type": "start",
                "agent_id": agent_id,
                "name": name,
                "run_id": run_id,
                "source": source,
                "text": "run started",
                "ts": time.time(),
            }
        )


def step(agent_id: str, text: str, kind: str = "thought") -> None:
    text = str(text).strip()
    if not text:
        return
    with _lock:
        activity = _running.get(agent_id)
        name = activity["name"] if activity else ""
        if activity:
            activity["step"] = text[:160]
            activity["updated_at"] = time.time()
        _push(
            {
                "type": "step",
                "kind": kind,
                "agent_id": agent_id,
                "name": name,
                "text": text[:200],
                "ts": time.time(),
            }
        )


def finish(agent_id: str, status: str, summary: str = "") -> None:
    with _lock:
        activity = _running.pop(agent_id, None)
        name = activity["name"] if activity else ""
        _push(
            {
                "type": "finish",
                "agent_id": agent_id,
                "name": name,
                "status": status,
                "text": (summary or "").strip()[:200],
                "ts": time.time(),
            }
        )


def snapshot() -> dict[str, Any]:
    with _lock:
        return {"running": list(_running.values()), "recent": list(_recent)}


def clear() -> None:
    with _lock:
        _running.clear()
        _recent.clear()
