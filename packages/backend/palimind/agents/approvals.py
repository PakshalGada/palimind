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


def _entry_is_live(entry: dict[str, Any]) -> bool:
    agent_id = str(entry.get("agent_id") or "")
    try:
        from palimind.agents.runtime import running_runs

        runs = running_runs(agent_id)
        if not runs:
            return False
        run_id = entry.get("run_id")
        if not run_id:
            return True
        return any(run.run_id == run_id for run in runs)
    except Exception:
        return True  # unknown → keep rather than silently drop


def _key(agent_id: str, run_id: str | None = None) -> str:
    return f"{agent_id}:{run_id}" if run_id else agent_id


def _strip_key(key: str) -> str:
    return key.rsplit(":", 1)[0] if ":" in key else key


def _write_locked() -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(list(_pending.values()), indent=2), "utf-8")
    except OSError:
        pass


def _prune_locked() -> None:
    stale = [key for key, entry in _pending.items() if not _entry_is_live(entry)]
    if stale:
        for key in stale:
            _pending.pop(key, None)
        _write_locked()


def _load() -> None:
    try:
        if not _PATH.exists():
            return
        data = json.loads(_PATH.read_text("utf-8"))
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and entry.get("agent_id"):
                    _pending[_key(str(entry["agent_id"]), entry.get("run_id"))] = entry
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
        _pending[_key(agent_id, run_id)] = {
            "agent_id": agent_id,
            "run_id": run_id,
            "tool": tool,
            "args": args,
            "confidence": confidence,
            "reasoning": reasoning,
            "created_at": time.time(),
        }
        _write_locked()


def remove(agent_id: str, run_id: str | None = None) -> None:
    with _lock:
        changed = False
        if run_id:
            if _pending.pop(_key(agent_id, run_id), None) is not None:
                changed = True
        else:
            for key in [k for k in _pending if _strip_key(k) == agent_id]:
                _pending.pop(key, None)
                changed = True
        if changed:
            _write_locked()


def list_pending() -> list[dict[str, Any]]:
    with _lock:
        _prune_locked()
        return list(_pending.values())


def clear() -> None:
    with _lock:
        _pending.clear()
        _write_locked()
