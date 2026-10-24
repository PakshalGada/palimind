"""Append-only journal for in-flight agent runs.

Run history used to be written only *after* a run finished, and a cancelled
run re-raised before the write. A crash or cancellation therefore lost the
entire run. Every run now appends start/tool/terminal events to a small JSONL
journal; on startup, journals without a terminal event are marked
``interrupted`` and promoted into normal run history.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TERMINAL = {"completed", "error", "cancelled", "interrupted"}
_lock = threading.Lock()


def _journal_dir() -> Path:
    from palimind.agents.catalog import GLOBAL_AGENTS_DIR

    path = GLOBAL_AGENTS_DIR / "run_journal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(run_id: str) -> Path:
    safe = "".join(c for c in str(run_id) if c.isalnum() or c in "-_")
    return _journal_dir() / f"{safe}.jsonl"


def append(run_id: str, agent_id: str, event: str, payload: dict[str, Any] | None = None) -> None:
    record = {
        "ts": time.time(),
        "run_id": str(run_id),
        "agent_id": str(agent_id),
        "event": event,
        **(payload or {}),
    }
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            with _path(run_id).open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
    except OSError as exc:
        logger.warning("Could not write run journal for %s: %s", run_id, exc)


def start(run_id: str, agent_id: str, input_text: str, session_id: str = "") -> None:
    append(
        run_id,
        agent_id,
        "start",
        {"input": str(input_text)[:2000], "session_id": session_id},
    )


def finish(run_id: str, agent_id: str, status: str, output: str = "") -> None:
    event = {
        "success": "completed",
        "cancelled": "cancelled",
        "error": "error",
        "interrupted": "interrupted",
        "rejected": "completed",
    }.get(status, "completed")
    append(run_id, agent_id, event, {"status": status, "output": str(output)[:2000]})


def read(run_id: str) -> list[dict[str, Any]]:
    path = _path(run_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    except OSError:
        return []
    return events


def _has_terminal(events: list[dict[str, Any]]) -> bool:
    return any(str(e.get("event")) in _TERMINAL for e in events)


def recover_interrupted(
    record: Callable[[str, str, str, str, str, float], None] | None = None,
) -> list[dict[str, Any]]:
    """Mark journals without a terminal event as interrupted.

    *record* is called as ``record(agent_id, run_id, input, output, status,
    duration)`` so the caller can persist a normal run-history entry.
    """
    recovered: list[dict[str, Any]] = []
    for path in sorted(_journal_dir().glob("*.jsonl")):
        events = read(path.stem)
        if not events or _has_terminal(events):
            continue
        start_event = next((e for e in events if e.get("event") == "start"), {})
        last_ts = float(events[-1].get("ts") or start_event.get("ts") or time.time())
        first_ts = float(start_event.get("ts") or last_ts)
        item: dict[str, Any] = {
            "agent_id": str(start_event.get("agent_id") or ""),
            "run_id": str(start_event.get("run_id") or path.stem),
            "input": str(start_event.get("input") or ""),
            "status": "interrupted",
            "duration": max(0.0, last_ts - first_ts),
        }
        if item["agent_id"]:
            append(
                item["run_id"],
                item["agent_id"],
                "interrupted",
                {"status": "interrupted", "output": "[run interrupted by process exit]"},
            )
            if record is not None:
                try:
                    record(
                        item["agent_id"],
                        item["run_id"],
                        item["input"],
                        "[run interrupted by process exit]",
                        "interrupted",
                        item["duration"],
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to record interrupted run %s: %s", item["run_id"], exc)
        recovered.append(item)
        try:
            path.rename(path.with_suffix(".jsonl.recovered"))
        except OSError:
            pass
    return recovered
