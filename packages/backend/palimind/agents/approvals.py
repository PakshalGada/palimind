"""Global registry of pending human-in-the-loop approvals.

Agent runs can suspend waiting for approval on a risky tool (write_file,
run_shell, browser interactions…). Those suspensions were previously only
visible on the live run's SSE stream, which meant you had to be watching the
right agent. This registry makes them visible across every agent and session.

Entries are process-lifetime and mirrored to disk so the Inbox can render
immediately; stale entries (for agents that are no longer running) are pruned
on read — so after a restart nothing is shown for runs that no longer exist.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_PATH = Path.home() / ".palimind" / "agents" / "pending_approvals.json"
_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}


def _is_running(agent_id: str) -> bool:
    try:
        from palimind.agents.runtime import is_running

        return is_running(agent_id)
    except Exception:
        return True  # unknown → keep rather than silently drop


def _write_locked() -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(list(_pending.values()), indent=2), "utf-8")
    except OSError:
        pass


def _prune_locked() -> None:
    stale = [aid for aid in _pending if not _is_running(aid)]
    if stale:
        for aid in stale:
            _pending.pop(aid, None)
        _write_locked()


def _load() -> None:
    try:
        if not _PATH.exists():
            return
        data = json.loads(_PATH.read_text("utf-8"))
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and entry.get("agent_id"):
                    _pending[entry["agent_id"]] = entry
    except Exception:
        pass


_load()


def add(
    agent_id: str,
    run_id: str,
    tool: str,
    args: Any = None,
    confidence: float = 0.0,
    reasoning: str = "",
) -> None:
    with _lock:
        _pending[agent_id] = {
            "agent_id": agent_id,
            "run_id": run_id,
            "tool": tool,
            "args": args,
            "confidence": confidence,
            "reasoning": reasoning,
            "created_at": time.time(),
        }
        _write_locked()


def remove(agent_id: str) -> None:
    with _lock:
        if _pending.pop(agent_id, None) is not None:
            _write_locked()


def list_pending() -> list[dict[str, Any]]:
    with _lock:
        _prune_locked()
        return list(_pending.values())


def clear() -> None:
    with _lock:
        _pending.clear()
        _write_locked()
