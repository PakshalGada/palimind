"""First-run model download / load status.

Heavy optional models (reranker, OCR, speech) download or load on first use.
In the packaged app the backend's stdout/stderr are redirected to /dev/null,
so the progress bars those libraries print are invisible to the user. This
records a small, thread-safe status per active task, which the UI polls via
``GET /api/setup/status``.

Tasks are removed as soon as they finish; the UI shows a banner only while at
least one task is active.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_tasks: dict[str, dict[str, Any]] = {}


def start(key: str, label: str) -> None:
    with _lock:
        _tasks[key] = {
            "key": key,
            "label": label,
            "status": "active",
            "progress": None,
            "message": "",
            "started_at": time.time(),
        }


def update(key: str, *, progress: float | None = None, message: str | None = None) -> None:
    with _lock:
        task = _tasks.get(key)
        if task is None:
            return
        if progress is not None:
            task["progress"] = max(0.0, min(1.0, float(progress)))
        if message is not None:
            task["message"] = message


def finish(key: str) -> None:
    with _lock:
        _tasks.pop(key, None)


def snapshot() -> list[dict[str, Any]]:
    with _lock:
        return [dict(t) for t in _tasks.values()]
