"""Durable checkpoints for in-flight agent runs.

A crash or a server restart used to lose everything except the forensic
``run_journal`` events. This module persists a bounded snapshot of the agent
loop at every step boundary (after each LLM/tool step), so a run can be resumed
with its message history, working notes and iteration budget intact.

Checkpoints intentionally contain no credentials or tool closures. They are
keyed by ``run_id`` in the global state database, so they survive a process
restart and the API can expose them directly.
"""

from __future__ import annotations

import time
from typing import Any

from palimind.storage import state_store

NAMESPACE = "agent_run_state"
MAX_MESSAGES = 80
MAX_MESSAGE_CHARS = 8_000
MAX_NOTES = 80
MAX_NOTE_CHARS = 1_200
MAX_TOOL_SIGNATURES = 60
MAX_LOG_LINES = 60
MAX_OUTPUT_CHARS = 40_000

RESUMABLE_STATUSES = ("running", "resumable", "interrupted", "cancelled", "error")


def _clip(text: Any, limit: int) -> str:
    return str(text or "")[:limit]


def _bounded(state: dict[str, Any]) -> dict[str, Any]:
    """Trim a checkpoint so one long tool result cannot bloat the state DB."""
    messages: list[dict[str, Any]] = []
    for message in (state.get("messages") or [])[-MAX_MESSAGES:]:
        if not isinstance(message, dict):
            continue
        messages.append(
            {
                "role": str(message.get("role") or "user"),
                "content": _clip(message.get("content"), MAX_MESSAGE_CHARS),
            }
        )
    notes = [
        _clip(note, MAX_NOTE_CHARS)
        for note in (state.get("working_notes") or [])[-MAX_NOTES:]
        if str(note).strip()
    ]
    signatures = [_clip(sig, 500) for sig in (state.get("recent_tool_calls") or [])]
    log = [_clip(line, 500) for line in (state.get("full_log") or [])][-MAX_LOG_LINES:]
    usage = state.get("usage") or {}
    bounded = {
        "run_id": str(state.get("run_id") or ""),
        "agent_id": str(state.get("agent_id") or ""),
        "input": _clip(state.get("input"), 4_000),
        "session_id": str(state.get("session_id") or ""),
        "model": str(state.get("model") or ""),
        "ollama_url": str(state.get("ollama_url") or ""),
        "messages": messages,
        "working_notes": notes,
        "recent_tool_calls": signatures[-MAX_TOOL_SIGNATURES:],
        "full_log": log,
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        },
        "iteration": max(0, int(state.get("iteration", 0) or 0)),
        "status": str(state.get("status") or "running"),
        "output": _clip(state.get("output"), MAX_OUTPUT_CHARS),
        "resumable": bool(state.get("resumable")),
        "resumed_from": str(state.get("resumed_from") or ""),
        "resumed_by": str(state.get("resumed_by") or ""),
        "updated_at": float(state.get("updated_at") or time.time()),
    }
    if state.get("interrupted_at") is not None:
        bounded["interrupted_at"] = float(state["interrupted_at"])
    return bounded


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    """Persist a bounded checkpoint and return the stored value."""
    run_id = str(state.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("run_id is required for a checkpoint")
    payload = _bounded({**state, "run_id": run_id, "updated_at": time.time()})
    state_store.set_json(NAMESPACE, run_id, payload)
    return payload


def load_state(run_id: str) -> dict[str, Any] | None:
    if not str(run_id or "").strip():
        return None
    value = state_store.get_json(NAMESPACE, str(run_id), default=None)
    return value if isinstance(value, dict) else None


def update_state(run_id: str, **changes: Any) -> dict[str, Any] | None:
    state = load_state(run_id)
    if state is None:
        return None
    state.update(changes)
    return save_state(state)


def finalize(run_id: str, status: str, output: str = "") -> dict[str, Any] | None:
    """Mark a checkpoint terminal/resumable with its final output."""
    state = load_state(run_id)
    if state is None:
        return None
    state.update(
        {
            "status": str(status or "completed"),
            "output": _clip(output, MAX_OUTPUT_CHARS),
            "resumable": str(status) in RESUMABLE_STATUSES and bool(state.get("messages")),
        }
    )
    return save_state(state)


def mark_resumed(old_run_id: str, new_run_id: str) -> None:
    """Link an old checkpoint to the run that continued it."""
    state = load_state(old_run_id)
    if state is None:
        return
    state.update(
        {
            "status": "resumed",
            "resumable": False,
            "resumed_by": str(new_run_id),
        }
    )
    save_state(state)


def list_states(
    agent_id: str | None = None,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    states = state_store.list_json(NAMESPACE, limit=max(1, min(int(limit or 100), 500)))
    out: list[dict[str, Any]] = []
    for state in states:
        if agent_id and str(state.get("agent_id") or "") != str(agent_id):
            continue
        if status and str(state.get("status") or "") != str(status):
            continue
        out.append(state)
    return out


def recover_interrupted() -> list[dict[str, Any]]:
    """At startup, turn every stale ``running`` checkpoint into ``resumable``.

    A checkpoint only says ``running`` if the process that wrote it did not get
    to finalise. At startup no run is actually in flight, so those are exactly
    the runs a user may resume.
    """
    recovered: list[dict[str, Any]] = []
    now = time.time()
    for state in list_states(status="running"):
        state.update(
            {
                "status": "resumable",
                "resumable": True,
                "interrupted_at": now,
            }
        )
        payload = save_state(state)
        recovered.append(payload)
    return recovered


def delete_state(run_id: str) -> bool:
    state = load_state(run_id)
    if state is None:
        return False
    state_store.delete_json(NAMESPACE, str(run_id))
    return True
