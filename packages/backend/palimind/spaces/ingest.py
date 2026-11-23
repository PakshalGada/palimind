"""Thread-safe source ingestion scheduling.

The API normally has the durable job runner; CLI/test processes do not. This
helper enqueues a job when possible and otherwise runs the same work in a
short-lived background thread, so callers never block on the network.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def ingest_and_index(root: Path, source_id: str) -> dict:
    """Fetch a source, then index that exact file and record the outcome."""
    from palimind.spaces import sources

    record = sources.ingest_web_source(root, source_id)
    if record.get("status") in ("ready", "not_modified", "indexed"):
        indexed = sources.index_source(root, source_id)
        return {**record, **indexed}
    return record


def _work(root: Path, source_ids: list[str]) -> None:
    for source_id in source_ids:
        try:
            ingest_and_index(root, source_id)
        except Exception:  # noqa: BLE001 - one source must not stop the batch
            logger.exception("Source ingestion failed for %s", source_id)


def schedule_ingest(root: Path, source_ids: str | list[str]) -> None:
    ids = [source_ids] if isinstance(source_ids, str) else list(source_ids)
    ids = [str(item) for item in ids if str(item or "").strip()]
    if not ids:
        return
    root = Path(root)
    try:
        from palimind.jobs import enqueue, runner_running

        if runner_running():
            for source_id in ids:
                enqueue(
                    "web_ingest",
                    str(root),
                    {"source_id": source_id, "root": str(root)},
                    idempotency_key=f"web_ingest:{source_id}",
                )
            return
    except Exception:  # noqa: BLE001 - fall back to a local thread
        pass
    threading.Thread(
        target=_work, args=(root, ids), name="palimind-source-ingest", daemon=True
    ).start()
