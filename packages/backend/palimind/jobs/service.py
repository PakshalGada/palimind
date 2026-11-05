"""Durable, SQLite-backed job service.

This is the single scheduler/queue behind agent runs, background tasks, routines,
watcher triggers and the task board. Jobs are rows, not in-memory tasks, so they
survive a restart. The service provides:

* priority ordering and delayed ``run_at`` scheduling
* cron/interval recurrence
* leases with expiry recovery (a crashed worker does not strand a job)
* bounded retries with exponential backoff and a dead-letter state
* cancellation, including a cooperative flag for already-running jobs
* an append-only per-job event log for the UI/API
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from palimind.jobs.cron import next_cron_time
from palimind.storage import state_store

logger = logging.getLogger(__name__)

JOB_STATUSES = (
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "dead_letter",
    "paused",
)
ACTIVE_STATUSES = ("queued", "running", "paused")
TERMINAL_STATUSES = ("completed", "cancelled", "dead_letter")
JOB_KINDS = (
    "agent_run",
    "team_run",
    "queued_run",
    "background_task",
    "routine_run",
    "index",
    "research",
    "workflow",
    "trigger",
)

DEFAULT_MAX_ATTEMPTS = 3
MAX_RESULT_CHARS = 20_000


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _load(value: str, default: Any = None) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = row.keys()
    job = {key: row[key] for key in keys}
    job["payload"] = _load(job.get("payload") or "{}", {})
    job["cancel_requested"] = bool(job.get("cancel_requested"))
    return job


def _event(conn: Any, job_id: str, event: str, payload: dict[str, Any] | None = None) -> None:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM job_events WHERE job_id=?", (job_id,)
    ).fetchone()
    seq = int(row[0] if row else 1)
    conn.execute(
        "INSERT INTO job_events(job_id, seq, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (job_id, seq, event, _json(payload), time.time()),
    )


def enqueue(
    kind: str,
    target: str = "",
    payload: Mapping[str, Any] | None = None,
    *,
    priority: int = 0,
    delay: float = 0,
    run_at: float | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    idempotency_key: str = "",
    parent_id: str = "",
    cron: str = "",
    interval_seconds: int = 0,
) -> dict[str, Any]:
    """Create a job (or return the existing one for an idempotency key)."""
    now = time.time()
    when = float(run_at if run_at is not None else now + max(0.0, float(delay or 0)))
    job_id = str(uuid.uuid4())
    conn = state_store.state_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            existing = conn.execute(
                "SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if existing is not None:
                conn.commit()
                return _row(existing) or {}
        conn.execute(
            """
            INSERT INTO jobs(
                id, kind, target, payload, status, priority, run_at, created_at,
                attempts, max_attempts, last_error, idempotency_key, parent_id,
                cron, interval_seconds, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, 0, ?, '', ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                str(kind),
                str(target or ""),
                _json(dict(payload or {})),
                int(priority or 0),
                when,
                now,
                max(1, int(max_attempts or DEFAULT_MAX_ATTEMPTS)),
                str(idempotency_key or ""),
                str(parent_id or ""),
                str(cron or ""),
                max(0, int(interval_seconds or 0)),
                now,
            ),
        )
        _event(conn, job_id, "enqueued", {"kind": kind, "run_at": when})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_job(job_id) or {}


def get_job(job_id: str) -> dict[str, Any] | None:
    conn = state_store.state_connection()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (str(job_id),)).fetchone()
        return _row(row)
    finally:
        conn.close()


def list_jobs(
    *,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if status:
        clauses.append("status=?")
        args.append(str(status))
    if kind:
        clauses.append("kind=?")
        args.append(str(kind))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(max(1, min(int(limit or 200), 1_000)))
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?", tuple(args)
        ).fetchall()
        return [job for row in rows if (job := _row(row)) is not None]
    finally:
        conn.close()


def list_events(job_id: str, limit: int = 200) -> list[dict[str, Any]]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute(
            "SELECT seq, type, payload, created_at FROM job_events WHERE job_id=? "
            "ORDER BY seq ASC LIMIT ?",
            (str(job_id), max(1, min(int(limit or 200), 1_000))),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "seq": int(row["seq"]),
            "type": str(row["type"]),
            "payload": _load(row["payload"], {}),
            "created_at": float(row["created_at"]),
        }
        for row in rows
    ]


def _recover_expired_locked(conn: Any, now: float) -> int:
    """Requeue or dead-letter jobs whose worker lease expired."""
    rows = conn.execute(
        "SELECT id, attempts, max_attempts FROM jobs "
        "WHERE status='running' AND lease_until IS NOT NULL AND lease_until < ?",
        (now,),
    ).fetchall()
    recovered = 0
    for row in rows:
        job_id = str(row["id"])
        attempts = int(row["attempts"] or 0)
        if attempts >= int(row["max_attempts"] or DEFAULT_MAX_ATTEMPTS):
            conn.execute(
                "UPDATE jobs SET status='dead_letter', lease_until=NULL, worker_id='', "
                "last_error='lease expired', finished_at=?, updated_at=? WHERE id=?",
                (now, now, job_id),
            )
            _event(conn, job_id, "dead_letter", {"reason": "lease expired"})
        else:
            conn.execute(
                "UPDATE jobs SET status='queued', lease_until=NULL, worker_id='', "
                "run_at=?, last_error='lease expired', updated_at=? WHERE id=?",
                (now, now, job_id),
            )
            _event(conn, job_id, "requeued", {"reason": "lease expired"})
        recovered += 1
    return recovered


def claim_next(worker_id: str = "", lease_seconds: float = 300.0) -> dict[str, Any] | None:
    """Atomically lease the next due job, if one is available."""
    now = time.time()
    conn = state_store.state_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _recover_expired_locked(conn, now)
        row = conn.execute(
            "SELECT * FROM jobs WHERE status='queued' AND run_at<=? AND cancel_requested=0 "
            "ORDER BY priority DESC, run_at ASC, created_at ASC LIMIT 1",
            (now,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        job_id = str(row["id"])
        conn.execute(
            "UPDATE jobs SET status='running', started_at=?, attempts=attempts+1, "
            "lease_until=?, worker_id=?, finished_at=NULL, updated_at=? "
            "WHERE id=? AND status='queued'",
            (now, now + max(5.0, float(lease_seconds or 300.0)), str(worker_id), now, job_id),
        )
        _event(conn, job_id, "started", {"worker": worker_id})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_job(job_id)


def heartbeat(job_id: str, lease_seconds: float = 300.0) -> bool:
    now = time.time()
    conn = state_store.state_connection()
    try:
        cur = conn.execute(
            "UPDATE jobs SET lease_until=?, updated_at=? WHERE id=? AND status='running'",
            (now + max(5.0, float(lease_seconds or 300.0)), now, str(job_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _next_recurrence(job: dict[str, Any], now: float) -> float | None:
    interval = int(job.get("interval_seconds") or 0)
    if interval > 0:
        return now + interval
    cron = str(job.get("cron") or "")
    if cron:
        next_dt = next_cron_time(cron, datetime.fromtimestamp(now))
        return next_dt.timestamp() if next_dt else None
    return None


def complete(
    job_id: str,
    *,
    status: str = "success",
    result: Any = "",
    error: str = "",
) -> dict[str, Any] | None:
    """Record a terminal attempt, scheduling a retry or recurrence as needed."""
    now = time.time()
    conn = state_store.state_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (str(job_id),)).fetchone()
        if row is None:
            conn.commit()
            return None
        job = _row(row) or {}
        cancelled = bool(job.get("cancel_requested")) or str(status) == "cancelled"
        text = str(result if result is not None else "")[:MAX_RESULT_CHARS]
        if cancelled:
            conn.execute(
                "UPDATE jobs SET status='cancelled', result=?, finished_at=?, lease_until=NULL, "
                "worker_id='', updated_at=? WHERE id=?",
                (text, now, now, job_id),
            )
            _event(conn, str(job_id), "cancelled", {})
        elif str(status) in ("success", "completed", "done"):
            next_run = _next_recurrence(job, now)
            if next_run is not None:
                conn.execute(
                    "UPDATE jobs SET status='queued', run_at=?, attempts=0, last_error='', "
                    "result=?, finished_at=?, lease_until=NULL, worker_id='', updated_at=? "
                    "WHERE id=?",
                    (next_run, text, now, now, job_id),
                )
                _event(conn, str(job_id), "rescheduled", {"run_at": next_run})
            else:
                conn.execute(
                    "UPDATE jobs SET status='completed', result=?, finished_at=?, "
                    "lease_until=NULL, worker_id='', updated_at=? WHERE id=?",
                    (text, now, now, job_id),
                )
                _event(conn, str(job_id), "completed", {})
        else:
            attempts = int(job.get("attempts") or 0)
            max_attempts = int(job.get("max_attempts") or DEFAULT_MAX_ATTEMPTS)
            if attempts < max_attempts:
                backoff = min(300.0, float(2 ** max(0, attempts - 1)))
                conn.execute(
                    "UPDATE jobs SET status='queued', run_at=?, last_error=?, result=?, "
                    "lease_until=NULL, worker_id='', updated_at=? WHERE id=?",
                    (now + backoff, str(error or text)[:2000], text, now, job_id),
                )
                _event(
                    conn,
                    str(job_id),
                    "retry",
                    {"attempt": attempts, "max_attempts": max_attempts, "backoff": backoff},
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status='dead_letter', last_error=?, result=?, "
                    "finished_at=?, lease_until=NULL, worker_id='', updated_at=? WHERE id=?",
                    (str(error or text)[:2000], text, now, now, job_id),
                )
                _event(conn, str(job_id), "dead_letter", {"attempts": attempts})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_job(job_id)


def cancel_job(job_id: str) -> dict[str, Any] | None:
    now = time.time()
    conn = state_store.state_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (str(job_id),)).fetchone()
        if row is None:
            conn.commit()
            return None
        status = str(row["status"])
        if status in ("queued", "paused"):
            conn.execute(
                "UPDATE jobs SET status='cancelled', cancel_requested=1, finished_at=?, "
                "lease_until=NULL, worker_id='', updated_at=? WHERE id=?",
                (now, now, job_id),
            )
            _event(conn, str(job_id), "cancelled", {})
        elif status == "running":
            conn.execute(
                "UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?",
                (now, job_id),
            )
            _event(conn, str(job_id), "cancel_requested", {})
        conn.commit()
    finally:
        conn.close()
    return get_job(job_id)


def retry_job(job_id: str) -> dict[str, Any] | None:
    now = time.time()
    conn = state_store.state_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE jobs SET status='queued', attempts=0, run_at=?, last_error='', "
            "cancel_requested=0, finished_at=NULL, lease_until=NULL, updated_at=? WHERE id=?",
            (now, now, job_id),
        )
        _event(conn, str(job_id), "manual_retry", {})
        conn.commit()
    finally:
        conn.close()
    return get_job(job_id)


def delete_job(job_id: str) -> bool:
    conn = state_store.state_connection()
    try:
        cur = conn.execute("DELETE FROM jobs WHERE id=?", (str(job_id),))
        conn.execute("DELETE FROM job_events WHERE job_id=?", (str(job_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def recover_orphans() -> int:
    """Requeue/dead-letter running jobs left by a previous process."""
    conn = state_store.state_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        count = _recover_expired_locked(conn, time.time())
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def stats() -> dict[str, int]:
    conn = state_store.state_connection()
    try:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
    finally:
        conn.close()
    out = {status: 0 for status in JOB_STATUSES}
    for row in rows:
        out[str(row["status"])] = int(row["n"])
    return out


JobHandler = Callable[[dict[str, Any]], Awaitable[Any] | Any]


class JobRunner:
    """Async workers that claim and execute durable jobs."""

    def __init__(
        self,
        handlers: Mapping[str, JobHandler],
        *,
        concurrency: int = 2,
        poll_interval: float = 2.0,
        lease_seconds: float = 300.0,
    ) -> None:
        self.handlers = dict(handlers)
        self.concurrency = max(1, int(concurrency or 1))
        self.poll_interval = max(0.2, float(poll_interval or 2.0))
        self.lease_seconds = max(5.0, float(lease_seconds or 300.0))
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._tasks and any(not task.done() for task in self._tasks):
            return
        self._stop = asyncio.Event()
        await asyncio.to_thread(recover_orphans)
        self._tasks = [
            asyncio.create_task(self._worker(f"job-worker-{i}")) for i in range(self.concurrency)
        ]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []

    async def _heartbeat(self, job_id: str) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(max(1.0, self.lease_seconds / 3))
            try:
                await asyncio.to_thread(heartbeat, job_id, self.lease_seconds)
            except Exception:
                return

    async def _run_job(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        hb = asyncio.create_task(self._heartbeat(job_id))
        try:
            handler = self.handlers.get(str(job.get("kind") or ""))
            if handler is None:
                await asyncio.to_thread(
                    complete,
                    job_id,
                    status="error",
                    error=f"no handler for job kind {job.get('kind')}",
                )
                return
            output = handler(job)
            if inspect.isawaitable(output):
                output = await output
            status = "success"
            result: Any = output
            if isinstance(output, dict):
                status = str(output.get("status") or "success")
                result = output.get("output", output.get("result", output))
            await asyncio.to_thread(complete, job_id, status=status, result=result)
        except asyncio.CancelledError:
            await asyncio.to_thread(complete, job_id, status="cancelled", error="worker stopped")
            raise
        except Exception as exc:  # noqa: BLE001 - one job must not kill the worker
            await asyncio.to_thread(complete, job_id, status="error", error=str(exc))
        finally:
            hb.cancel()

    async def _worker(self, worker_id: str) -> None:
        while not self._stop.is_set():
            try:
                job = await asyncio.to_thread(claim_next, worker_id, self.lease_seconds)
                if job is None:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
                    except TimeoutError:
                        pass
                    continue
                await self._run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("job worker %s error: %s", worker_id, exc)
                await asyncio.sleep(self.poll_interval)


_runner: JobRunner | None = None


async def start_runner(
    handlers: Mapping[str, JobHandler] | None = None,
    *,
    concurrency: int | None = None,
) -> JobRunner:
    global _runner
    if _runner is not None and _runner._tasks and any(not t.done() for t in _runner._tasks):
        return _runner
    from palimind.jobs.handlers import default_handlers
    from palimind.settings import JOB_CONCURRENCY, JOB_LEASE_SECONDS, JOB_POLL_INTERVAL

    _runner = JobRunner(
        handlers or default_handlers(),
        concurrency=concurrency or JOB_CONCURRENCY,
        poll_interval=JOB_POLL_INTERVAL,
        lease_seconds=JOB_LEASE_SECONDS,
    )
    await _runner.start()
    return _runner


async def stop_runner() -> None:
    global _runner
    if _runner is not None:
        await _runner.stop()
    _runner = None
