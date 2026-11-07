"""In-memory signals for quiet and failed routine runs.

The agent tools set these during a turn.  ``run_routine`` consumes them when
the turn completes, so they never cross turns or processes.
"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_signals: dict[str, dict[str, Any]] = {}


def mark_quiet(run_id: str, reason: str = "") -> None:
    with _lock:
        _signals.setdefault(str(run_id), {})["quiet"] = str(reason or "no-update")


def report_failure(run_id: str, reason: str) -> None:
    with _lock:
        _signals.setdefault(str(run_id), {})["failure"] = str(reason or "routine failed")


def consume(run_id: str) -> dict[str, Any]:
    with _lock:
        return _signals.pop(str(run_id), {})


def clear() -> None:
    with _lock:
        _signals.clear()
