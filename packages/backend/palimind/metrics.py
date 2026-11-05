"""Process-local observability metrics.

Everything here stays in memory (or is computed from the local SQLite stores)
and is never exported anywhere. ``GET /api/metrics`` and the local dashboard are
read-only views over these counters.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware

_lock = threading.Lock()
_started_at = time.time()

_requests_total = 0
_requests_by_status: dict[str, int] = {}
_requests_by_route: dict[str, dict[str, Any]] = {}
_latencies: dict[str, deque[float]] = {}

_tokens_total = 0
_completion_tokens_total = 0
_tokens_by_model: dict[str, dict[str, int]] = {}

_tools: dict[str, dict[str, Any]] = {}
_agent_runs: dict[str, int] = {}

_index_runs = 0
_index_files = 0
_index_deleted = 0
_index_chunks = 0
_index_seconds = 0.0


def reset() -> None:
    global _requests_total, _tokens_total, _completion_tokens_total
    global _index_runs, _index_files, _index_deleted, _index_chunks, _index_seconds
    with _lock:
        _started_at = time.time()
        _requests_total = 0
        _requests_by_status.clear()
        _requests_by_route.clear()
        _latencies.clear()
        _tokens_total = 0
        _completion_tokens_total = 0
        _tokens_by_model.clear()
        _tools.clear()
        _agent_runs.clear()
        _index_runs = 0
        _index_files = 0
        _index_deleted = 0
        _index_chunks = 0
        _index_seconds = 0.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * pct))
    return round(ordered[max(0, min(idx, len(ordered) - 1))], 2)


def record_request(method: str, path: str, status: int, duration_ms: float) -> None:
    global _requests_total
    with _lock:
        _requests_total += 1
        key = f"{int(status) // 100}xx"
        _requests_by_status[key] = _requests_by_status.get(key, 0) + 1
        route = str(path or "unknown")
        bucket = _requests_by_route.setdefault(route, {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
        bucket["count"] += 1
        bucket["total_ms"] = round(float(bucket["total_ms"]) + float(duration_ms), 2)
        bucket["max_ms"] = round(max(float(bucket["max_ms"]), float(duration_ms)), 2)
        samples = _latencies.setdefault(route, deque(maxlen=1000))
        samples.append(float(duration_ms))


def record_tokens(model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    global _tokens_total, _completion_tokens_total
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    if not prompt and not completion:
        return
    with _lock:
        _tokens_total += prompt
        _completion_tokens_total += completion
        bucket = _tokens_by_model.setdefault(
            str(model or "unknown"), {"prompt": 0, "completion": 0, "total": 0}
        )
        bucket["prompt"] += prompt
        bucket["completion"] += completion
        bucket["total"] += prompt + completion


def record_tool(name: str, ok: bool, duration_ms: float) -> None:
    with _lock:
        bucket = _tools.setdefault(
            str(name or "unknown"),
            {"success": 0, "failure": 0, "total": 0, "total_ms": 0.0},
        )
        if ok:
            bucket["success"] += 1
        else:
            bucket["failure"] += 1
        bucket["total"] += 1
        bucket["total_ms"] = round(float(bucket["total_ms"]) + float(duration_ms), 2)


def record_agent_run(status: str) -> None:
    with _lock:
        key = str(status or "unknown")
        _agent_runs[key] = _agent_runs.get(key, 0) + 1


def record_index_run(
    *,
    indexed_files: int = 0,
    deleted_files: int = 0,
    chunks_indexed: int = 0,
    duration_s: float = 0.0,
) -> None:
    global _index_runs, _index_files, _index_deleted, _index_chunks, _index_seconds
    with _lock:
        _index_runs += 1
        _index_files += max(0, int(indexed_files or 0))
        _index_deleted += max(0, int(deleted_files or 0))
        _index_chunks += max(0, int(chunks_indexed or 0))
        _index_seconds += max(0.0, float(duration_s or 0.0))


def _queue_depth() -> dict[str, Any]:
    out: dict[str, Any] = {"jobs": {}, "task_board_active": 0}
    try:
        from palimind.jobs import stats as job_stats

        out["jobs"] = job_stats()
    except Exception:
        pass
    try:
        from palimind.agents import queue as agent_queue

        active = {"queued", "running", "paused"}
        out["task_board_active"] = sum(
            1
            for item in agent_queue.list_queue(limit=1000)
            if str(item.get("status") or "") in active
        )
    except Exception:
        pass
    return out


def snapshot() -> dict[str, Any]:
    with _lock:
        routes: dict[str, Any] = {}
        for route, bucket in _requests_by_route.items():
            samples = list(_latencies.get(route, ()))
            count = int(bucket["count"])
            routes[route] = {
                "count": count,
                "avg_ms": round(float(bucket["total_ms"]) / count, 2) if count else 0.0,
                "p95_ms": _percentile(samples, 0.95),
                "max_ms": float(bucket["max_ms"]),
            }
        tools = {name: dict(bucket) for name, bucket in _tools.items()}
        for bucket in tools.values():
            total = int(bucket.get("total") or 0)
            bucket["avg_ms"] = (
                round(float(bucket.get("total_ms") or 0.0) / total, 2) if total else 0.0
            )
        index_avg = _index_seconds / _index_runs if _index_runs else 0.0
        index_rate = (_index_files / _index_seconds * 60.0) if _index_seconds else 0.0
        data = {
            "generated_at": time.time(),
            "uptime_s": round(time.time() - _started_at, 1),
            "local_only": True,
            "requests": {
                "total": _requests_total,
                "by_status": dict(_requests_by_status),
                "by_route": routes,
            },
            "tokens": {
                "prompt": _tokens_total,
                "completion": _completion_tokens_total,
                "total": _tokens_total + _completion_tokens_total,
                "by_model": {k: dict(v) for k, v in _tokens_by_model.items()},
            },
            "tools": tools,
            "agent_runs": dict(_agent_runs),
            "index": {
                "runs": _index_runs,
                "indexed_files": _index_files,
                "deleted_files": _index_deleted,
                "chunks_indexed": _index_chunks,
                "total_seconds": round(_index_seconds, 2),
                "avg_seconds": round(index_avg, 2),
                "files_per_minute": round(index_rate, 2),
            },
            "queue": {},
        }
    data["queue"] = _queue_depth()
    return data


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count/status/latency with route-template cardinality."""

    async def dispatch(self, request: Any, call_next: Any) -> Any:
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = int(getattr(response, "status_code", 500))
            return response
        finally:
            route = request.scope.get("route")
            path = str(getattr(route, "path", "") or request.url.path)
            record_request(
                request.method,
                path,
                status,
                (time.perf_counter() - started) * 1000.0,
            )
