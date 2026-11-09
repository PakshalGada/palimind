"""Pending questions an agent asked a human mid-run.

An agent can suspend a run with :func:`palimind.llm.mixture_of_expert.tools.ask_user`
and wait for an answer.  Questions are visible across every agent/session (the
Inbox and the live run both render them), so a user does not have to be watching
the exact conversation that blocked.

The registry is process-lifetime and mirrors to disk for the UI.  Entries are
pruned when the owning run disappears or after a generous timeout, so a restart
never shows a question that can no longer be answered.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

_PATH = Path.home() / ".palimind" / "agents" / "pending_questions.json"
_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}
_events: dict[str, threading.Event] = {}
DEFAULT_TIMEOUT_S = 600
MAX_TIMEOUT_S = 3600


def _write_locked() -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(list(_pending.values()), indent=2), "utf-8")
    except OSError:
        pass


def _load() -> None:
    try:
        if not _PATH.exists():
            return
        data = json.loads(_PATH.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, list):
        return
    now = time.time()
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        if now - float(entry.get("created_at") or now) > MAX_TIMEOUT_S:
            continue
        entry["status"] = "pending"
        _pending[str(entry["id"])] = entry


def _entry_is_live(entry: dict[str, Any]) -> bool:
    agent_id = str(entry.get("agent_id") or "")
    run_id = str(entry.get("run_id") or "")
    try:
        from palimind.agents.runtime import running_runs

        runs = running_runs(agent_id)
        if not runs:
            return False
        if not run_id:
            return True
        return any(run.run_id == run_id for run in runs)
    except Exception:  # noqa: BLE001 - unknown should not hide a question
        return True


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in entry.items()
        if key not in {"event"} and not key.startswith("_")
    }


def _prune_locked() -> None:
    stale = [key for key, entry in _pending.items() if not _entry_is_live(entry)]
    now = time.time()
    expired = [
        key
        for key, entry in _pending.items()
        if now - float(entry.get("created_at") or now) > MAX_TIMEOUT_S
    ]
    removed = set(stale) | set(expired)
    if removed:
        for key in removed:
            _pending.pop(key, None)
            _events.pop(key, None)
        _write_locked()


def ask(
    question: str,
    *,
    agent_id: str,
    run_id: str = "",
    options: list[str] | None = None,
    allow_free_text: bool = True,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    should_cancel: Callable[[], bool] | None = None,
    on_emit: Callable[[str, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Register a question, emit it, and block until answered or timed out."""
    question_id = uuid.uuid4().hex
    event = threading.Event()
    choices = [str(item)[:200] for item in (options or []) if str(item).strip()][:8]
    record: dict[str, Any] = {
        "id": question_id,
        "agent_id": str(agent_id or ""),
        "run_id": str(run_id or ""),
        "question": str(question or "").strip()[:2000] or "The agent needs your input.",
        "options": choices,
        "allow_free_text": bool(allow_free_text),
        "status": "pending",
        "created_at": time.time(),
    }
    with _lock:
        _pending[question_id] = record
        _events[question_id] = event
        _write_locked()

    if on_emit is not None:
        try:
            on_emit(
                "agent:question",
                {
                    "agent_id": record["agent_id"],
                    "run_id": record["run_id"],
                    "question_id": question_id,
                    "question": record["question"],
                    "options": choices,
                    "allow_free_text": record["allow_free_text"],
                    "created_at": record["created_at"],
                },
            )
        except Exception:  # noqa: BLE001 - emitting must not kill the tool
            pass

    timeout = max(5, min(int(timeout_s or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S))
    deadline = time.time() + timeout
    while not event.wait(0.2):
        if should_cancel is not None:
            try:
                cancelled = bool(should_cancel())
            except Exception:  # noqa: BLE001
                cancelled = False
            if cancelled:
                with _lock:
                    record = dict(_pending.get(question_id) or record)
                    record["status"] = "cancelled"
                    _pending.pop(question_id, None)
                    _events.pop(question_id, None)
                    _write_locked()
                return {
                    "status": "cancelled",
                    "question_id": question_id,
                    "answer": "",
                    "choice": "",
                }
        if time.time() >= deadline:
            with _lock:
                record = dict(_pending.get(question_id) or record)
                record["status"] = "timeout"
                _pending.pop(question_id, None)
                _events.pop(question_id, None)
                _write_locked()
            return {"status": "timeout", "question_id": question_id, "answer": "", "choice": ""}

    with _lock:
        record = dict(_pending.get(question_id) or record)
        _pending.pop(question_id, None)
        _events.pop(question_id, None)
        _write_locked()
    return {
        "status": str(record.get("status") or "answered"),
        "question_id": question_id,
        "answer": str(record.get("answer") or ""),
        "choice": str(record.get("choice") or ""),
    }


def answer(question_id: str, answer: str = "", choice: str = "") -> bool:
    """Answer a pending question.  Returns False when it is no longer pending."""
    with _lock:
        record = _pending.get(str(question_id or ""))
        if record is None:
            return False
        record["status"] = "answered"
        record["answer"] = str(answer or "")[:4000]
        record["choice"] = str(choice or "")[:200]
        record["answered_at"] = time.time()
        event = _events.get(record["id"])
        _write_locked()
    if event is not None:
        event.set()
    return True


def list_pending(agent_id: str = "") -> list[dict[str, Any]]:
    with _lock:
        _prune_locked()
        return [
            _public(entry)
            for entry in _pending.values()
            if not agent_id or str(entry.get("agent_id")) == str(agent_id)
        ]


def get(question_id: str) -> dict[str, Any] | None:
    with _lock:
        entry = _pending.get(str(question_id or ""))
        return _public(entry) if entry else None


def clear(run_id: str = "", agent_id: str = "") -> int:
    """Drop pending questions for a finished run (or an agent)."""
    with _lock:
        removed = [
            key
            for key, entry in _pending.items()
            if (run_id and str(entry.get("run_id")) == str(run_id))
            or (not run_id and agent_id and str(entry.get("agent_id")) == str(agent_id))
        ]
        for key in removed:
            _pending.pop(key, None)
            _events.pop(key, None)
        if removed:
            _write_locked()
        return len(removed)


_load()
