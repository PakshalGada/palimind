"""Incremental indexing runs with durable jobs, cancellation and resume.

The existing ``update_index`` already detects unchanged/deleted files by hash,
but it ran as one opaque call. This module adds a durable run around it:

* every run is planned up-front and persisted (queued / skipped / deleted files)
* one durable ``index`` job executes the run through the job service
* progress is written to ``index_events`` and published to listeners
* cancellation is cooperative (checked between batches), and committed batches
  are preserved
* resume re-plans against the current hashes, so already indexed files are
  skipped and only the remaining work is processed
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from palimind.config import load_config
from palimind.exceptions import IndexCancelledError
from palimind.rag.indexing import (
    index_exists,
    initialize_index,
    update_index,
)
from palimind.storage import state_store
from palimind.storage.db import get_connection, init_db

RUN_NAMESPACE = "index_runs"
ACTIVE_STATUSES = ("queued", "running")
RESUMABLE_STATUSES = ("cancelled", "failed", "interrupted", "queued")


def _now() -> float:
    return time.time()


def _save(summary: dict[str, Any]) -> dict[str, Any]:
    summary["updated_at"] = _now()
    state_store.set_json(RUN_NAMESPACE, str(summary["run_id"]), summary)
    return summary


def get_run(run_id: str) -> dict[str, Any] | None:
    value = state_store.get_json(RUN_NAMESPACE, str(run_id or ""), default=None)
    return value if isinstance(value, dict) else None


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    runs = state_store.list_json(RUN_NAMESPACE, limit=max(1, min(int(limit or 50), 200)))
    runs.sort(key=lambda r: float(r.get("created_at", 0) or 0), reverse=True)
    return runs


def list_run_files(root: Path, run_id: str, status: str | None = None) -> list[dict[str, Any]]:
    conn = get_connection(root)
    try:
        clause = " AND status=?" if status else ""
        args: tuple[Any, ...] = (run_id, status) if status else (run_id,)
        rows = conn.execute(
            "SELECT path, md5, status, error, attempts, updated_at FROM index_files "
            f"WHERE run_id=?{clause} ORDER BY path",
            args,
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "path": row[0],
            "md5": row[1],
            "status": row[2],
            "error": row[3],
            "attempts": int(row[4] or 0),
            "updated_at": row[5],
        }
        for row in rows
    ]


def _upsert_file(
    root: Path,
    run_id: str,
    path: str,
    md5: str,
    status: str,
    *,
    error: str = "",
) -> None:
    conn = get_connection(root)
    try:
        conn.execute(
            """
            INSERT INTO index_files(run_id, path, md5, status, error, attempts, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(run_id, path) DO UPDATE SET
                md5=excluded.md5, status=excluded.status,
                error=excluded.error, updated_at=excluded.updated_at
            """,
            (run_id, path, md5, status, error, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _update_file_status(root: Path, run_id: str, path: str, status: str, error: str = "") -> None:
    conn = get_connection(root)
    try:
        conn.execute(
            "UPDATE index_files SET status=?, error=?, updated_at=? WHERE run_id=? AND path=?",
            (status, error, _now(), run_id, path),
        )
        conn.commit()
    finally:
        conn.close()


def _append_event(root: Path, run_id: str, event: dict[str, Any]) -> None:
    conn = get_connection(root)
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM index_events WHERE run_id=?", (run_id,)
        ).fetchone()
        seq = int(row[0] if row else 1)
        conn.execute(
            "INSERT INTO index_events(run_id, seq, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                seq,
                str(event.get("type") or "progress"),
                json.dumps(event, default=str),
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_events(root: Path, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    conn = get_connection(root)
    try:
        rows = conn.execute(
            "SELECT seq, type, payload, created_at FROM index_events WHERE run_id=? "
            "ORDER BY seq ASC LIMIT ?",
            (run_id, max(1, min(int(limit or 200), 1000))),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row[2])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        out.append(
            {
                "seq": int(row[0]),
                "type": row[1],
                "payload": payload,
                "created_at": float(row[3]),
            }
        )
    return out


def _pending_paths(root: Path, run_id: str) -> set[str]:
    conn = get_connection(root)
    try:
        rows = conn.execute(
            "SELECT path, status FROM index_files WHERE run_id=? "
            "AND status IN ('queued','parsing','embedding','failed','deleted')",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def _finalize_files(root: Path, run_id: str, *, completed: bool) -> dict[str, int]:
    """Reconcile planned files with the actual index and return status counts."""
    conn = get_connection(root)
    counts = {"queued": 0, "indexed": 0, "deleted": 0, "failed": 0, "skipped": 0}
    try:
        rows = conn.execute(
            "SELECT path, md5, status FROM index_files WHERE run_id=?", (run_id,)
        ).fetchall()
        for path, md5, status in rows:
            path = str(path)
            status = str(status or "queued")
            if status == "skipped":
                counts["skipped"] += 1
                continue
            exists = conn.execute("SELECT 1 FROM files WHERE path=?", (path,)).fetchone()
            if status == "deleted":
                new_status = "deleted" if exists is None else ("failed" if completed else "queued")
            elif exists is not None:
                indexed = conn.execute(
                    "SELECT md5_hash FROM files WHERE path=?", (path,)
                ).fetchone()
                new_status = (
                    "indexed"
                    if indexed is not None and str(indexed[0] or "") == str(md5 or "")
                    else ("failed" if completed else "queued")
                )
            else:
                new_status = "failed" if completed else "queued"
            if new_status != status:
                conn.execute(
                    "UPDATE index_files SET status=?, updated_at=? WHERE run_id=? AND path=?",
                    (new_status, _now(), run_id, path),
                )
            counts[new_status] = counts.get(new_status, 0) + 1
        conn.commit()
    finally:
        conn.close()
    return counts


def _full_rebuild_reason(root: Path, config: dict) -> str:
    """Return why an existing index must be rebuilt, or an empty string.

    A chunker-version or embedding-model change invalidates every stored chunk,
    but the incremental planner otherwise sees all files as "unchanged" and
    would report a completed run without reindexing anything.
    """
    from palimind.storage.vector_store import _index_path, read_stamp

    if not _index_path(root).exists():
        return ""
    stamp = read_stamp(root) or {}
    stamped_chunker = int(stamp.get("chunker") or 1)
    configured_chunker = int(config.get("chunker_version") or 1)
    if stamped_chunker != configured_chunker:
        return f"chunk layout v{stamped_chunker} -> v{configured_chunker}"
    stamped_model = str(stamp.get("model") or "")
    configured_model = str(config.get("embed_model") or "")
    if stamped_model and configured_model and stamped_model != configured_model:
        return f"embedding model {stamped_model} -> {configured_model}"
    if not stamp:
        return "index has no embedding/chunker stamp"
    return ""


def plan_run(
    root: Path,
    *,
    source_root: Path | None = None,
    priority: int = 0,
) -> dict[str, Any]:
    """Plan an incremental run and persist its per-file rows."""
    from palimind.ingestion.crawler import crawl_directory

    root = Path(root).resolve()
    source = Path(source_root or root).resolve()
    if not index_exists(root):
        initialize_index(root)
    init_db(root)
    config = load_config(root)
    new_or_modified, unchanged, deleted, hashes = crawl_directory(
        source, index_root=root, config=config
    )
    rebuild_reason = _full_rebuild_reason(root, config)
    if rebuild_reason and unchanged:
        # Force every unchanged file through the rebuild as well. The actual
        # reset happens inside update_index, which clears the hashes so these
        # paths are parsed and embedded from scratch. Their hashes must be
        # captured here too, otherwise the run bookkeeping marks them failed.
        from palimind.ingestion.crawler import compute_md5

        for path in unchanged:
            rel = str(path.relative_to(source))
            if rel not in hashes:
                digest = compute_md5(path)
                if digest:
                    hashes[rel] = digest
        new_or_modified = list(new_or_modified) + list(unchanged)
        unchanged = []
    run_id = str(uuid.uuid4())
    now = _now()
    summary: dict[str, Any] = {
        "run_id": run_id,
        "root": str(root),
        "source_root": str(source),
        "status": "queued" if (new_or_modified or deleted) else "completed",
        "priority": int(priority or 0),
        "total": len(new_or_modified) + len(deleted),
        "processed": 0,
        "queued": len(new_or_modified),
        "indexed": 0,
        "deleted": len(deleted),
        "unchanged": len(unchanged),
        "failed": 0,
        "phase": "queued",
        "message": f"Full rebuild: {rebuild_reason}" if rebuild_reason else "",
        "cancel_requested": False,
        "created_at": now,
        "started_at": None,
        "finished_at": now if not (new_or_modified or deleted) else None,
        "job_id": "",
        "error": "",
    }
    for path in new_or_modified:
        rel = str(path.relative_to(source))
        _upsert_file(root, run_id, rel, hashes.get(rel, ""), "queued")
    for path in unchanged:
        rel = str(path.relative_to(source))
        _upsert_file(root, run_id, rel, "", "skipped")
    for rel in deleted:
        _upsert_file(root, run_id, rel, "", "deleted")
    _save(summary)
    _append_event(
        root,
        run_id,
        {"type": "planned", **{k: summary[k] for k in ("total", "queued", "deleted", "unchanged")}},
    )
    return summary


def enqueue_run(
    root: Path,
    *,
    source_root: Path | None = None,
    priority: int = 0,
    reuse: bool = True,
) -> dict[str, Any]:
    """Plan a run and enqueue its durable job; reuse an active run if asked."""
    from palimind.jobs import enqueue

    root = Path(root).resolve()
    if reuse:
        for existing in list_runs(limit=50):
            if (
                str(existing.get("root") or "") == str(root)
                and str(existing.get("status") or "") in ACTIVE_STATUSES
            ):
                return existing
    summary = plan_run(root, source_root=source_root, priority=priority)
    if summary["status"] == "completed":
        return summary
    job = enqueue(
        "index",
        str(root),
        {
            "run_id": summary["run_id"],
            "root": str(root),
            "source_root": summary["source_root"],
        },
        priority=priority,
        idempotency_key=f"index:{summary['run_id']}",
    )
    summary["job_id"] = str(job.get("id") or "")
    _save(summary)
    return summary


def _cancel_requested(run_id: str) -> bool:
    summary = get_run(run_id)
    return bool(summary and summary.get("cancel_requested"))


def _progress_reporter(
    root: Path,
    run_id: str,
    on_event: Callable[[dict[str, Any]], None] | None,
    events_buffer: list[dict[str, Any]],
) -> Callable[..., None]:
    last_save = [0.0]

    def report(
        phase: str, *, current: int = 0, total: int | None = None, message: str = ""
    ) -> None:
        summary = get_run(run_id)
        if summary is None:
            return
        summary.update(
            {
                "phase": phase,
                "message": str(message or "")[:500],
                "phase_current": int(current or 0),
                "phase_total": int(total or 0),
            }
        )
        event = {
            "type": "index_progress",
            "run_id": run_id,
            "phase": phase,
            "current": int(current or 0),
            "total": int(total or 0),
            "message": str(message or "")[:500],
        }
        # Do not write to the workspace DB here: update_index holds a write
        # transaction, and a second connection would block on it. Buffer the
        # events and flush them once the indexer releases the connection.
        events_buffer.append(event)
        if time.time() - last_save[0] >= 0.2 or phase in ("crawl", "embed", "delete"):
            last_save[0] = time.time()
            _save(summary)
        if on_event is not None:
            try:
                on_event(event)
            except Exception:
                pass

    return report


def _record_metrics(summary: dict[str, Any], duration: float) -> None:
    try:
        from palimind import metrics

        metrics.record_index_run(
            indexed_files=int(summary.get("indexed") or 0),
            deleted_files=int(summary.get("deleted") or 0),
            chunks_indexed=int(summary.get("chunks_indexed") or 0),
            duration_s=max(0.0, float(duration)),
        )
    except Exception:
        pass


def process_run(
    run_id: str,
    *,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute a planned incremental run (idempotent; safe to resume)."""
    summary = get_run(run_id)
    if summary is None:
        raise KeyError(f"index run not found: {run_id}")
    started = time.time()
    root = Path(str(summary.get("root") or ""))
    source = Path(str(summary.get("source_root") or root))
    if summary.get("cancel_requested"):
        summary.update({"status": "cancelled", "finished_at": _now(), "phase": "cancelled"})
        _save(summary)
        _append_event(root, run_id, {"type": "cancelled", "run_id": run_id})
        return summary

    summary.update({"status": "running", "started_at": _now(), "phase": "starting"})
    _save(summary)
    _append_event(root, run_id, {"type": "started", "run_id": run_id})
    if on_event:
        on_event({"type": "index_start", "run_id": run_id})

    pending = _pending_paths(root, run_id)
    if not pending:
        counts = _finalize_files(root, run_id, completed=True)
        summary = get_run(run_id) or summary
        summary.update(
            {
                "status": "completed",
                "phase": "completed",
                "finished_at": _now(),
                **counts,
            }
        )
        _save(summary)
        _append_event(root, run_id, {"type": "completed", **counts})
        _record_metrics(summary, time.time() - started)
        if on_event:
            on_event({"type": "index_complete", "run_id": run_id, **counts})
        return summary
    events_buffer: list[dict[str, Any]] = []
    reporter = _progress_reporter(root, run_id, on_event, events_buffer)

    def flush_events() -> None:
        for event in events_buffer:
            _append_event(root, run_id, event)
        events_buffer.clear()

    try:
        result = update_index(
            root,
            source_root=source,
            paths=pending or None,
            on_progress=reporter,
            cancel_check=lambda: _cancel_requested(run_id),
        )
    except IndexCancelledError:
        flush_events()
        counts = _finalize_files(root, run_id, completed=False)
        summary = get_run(run_id) or summary
        summary.update(
            {
                "status": "cancelled",
                "phase": "cancelled",
                "finished_at": _now(),
                **counts,
            }
        )
        _save(summary)
        _append_event(root, run_id, {"type": "cancelled", **counts})
        _record_metrics(summary, time.time() - started)
        if on_event:
            on_event({"type": "index_cancelled", "run_id": run_id, **counts})
        return summary
    except Exception as exc:  # noqa: BLE001 - the job service records the failure
        flush_events()
        counts = _finalize_files(root, run_id, completed=False)
        summary = get_run(run_id) or summary
        summary.update(
            {
                "status": "failed",
                "phase": "error",
                "error": str(exc)[:2000],
                "finished_at": _now(),
                **counts,
            }
        )
        _save(summary)
        _append_event(root, run_id, {"type": "error", "message": str(exc)[:2000], **counts})
        _record_metrics(summary, time.time() - started)
        if on_event:
            on_event({"type": "index_error", "run_id": run_id, "message": str(exc)})
        return summary

    flush_events()
    counts = _finalize_files(root, run_id, completed=True)
    summary = get_run(run_id) or summary
    summary.update(
        {
            "status": "completed",
            "phase": "completed",
            "finished_at": _now(),
            "indexed": int(result.indexed_files),
            "deleted": int(result.deleted_files),
            "unchanged": int(result.unchanged_files),
            "failed": len(result.file_errors),
            "processed": int(result.indexed_files)
            + int(result.deleted_files)
            + len(result.file_errors),
            "queued": counts.get("queued", 0),
            "chunks_indexed": int(result.chunks_indexed),
            "errors": [{"path": err.path, "error": err.error} for err in result.file_errors],
        }
    )
    _save(summary)
    _append_event(root, run_id, {"type": "completed", **counts})
    _record_metrics(summary, time.time() - started)
    if on_event:
        on_event({"type": "index_complete", "run_id": run_id, **counts})
    return summary


def cancel_run(run_id: str) -> dict[str, Any] | None:
    summary = get_run(run_id)
    if summary is None:
        return None
    summary["cancel_requested"] = True
    if str(summary.get("status") or "") in ACTIVE_STATUSES:
        summary["status"] = "cancelled"
        summary["finished_at"] = _now()
        summary["phase"] = "cancelled"
    _save(summary)
    job_id = str(summary.get("job_id") or "")
    if job_id:
        try:
            from palimind.jobs import cancel_job

            cancel_job(job_id)
        except Exception:
            pass
    return summary


def resume_run(run_id: str) -> dict[str, Any] | None:
    from palimind.jobs import enqueue

    summary = get_run(run_id)
    if summary is None:
        return None
    if str(summary.get("status") or "") not in RESUMABLE_STATUSES:
        return summary
    summary.update(
        {
            "status": "queued",
            "phase": "queued",
            "cancel_requested": False,
            "error": "",
            "finished_at": None,
        }
    )
    _save(summary)
    job = enqueue(
        "index",
        str(summary.get("root") or ""),
        {
            "run_id": run_id,
            "root": str(summary.get("root") or ""),
            "source_root": str(summary.get("source_root") or ""),
        },
        priority=int(summary.get("priority") or 0),
        idempotency_key=f"index:{run_id}:resume:{int(time.time())}",
    )
    summary["job_id"] = str(job.get("id") or "")
    _save(summary)
    return summary
