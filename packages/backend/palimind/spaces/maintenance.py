"""Background freshness for saved sources.

Only sources with an explicit ``refresh_interval`` (seconds) are refreshed, so
nothing is crawled unless the user opted in. The loop is intentionally small:
it wakes periodically, re-checks each space, and yields to the durable job
runner for indexing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CHECK_EVERY_SECONDS = 15 * 60


def due_sources(root: Path) -> list[dict]:
    from palimind.storage.db import SOURCE_COLUMNS, get_connection

    root = Path(root)
    conn = get_connection(root)
    try:
        rows = conn.execute(
            f"""
            SELECT {", ".join(SOURCE_COLUMNS)} FROM sources
            WHERE kind = 'web' AND refresh_interval > 0
              AND status IN ('ready', 'not_modified', 'failed')
            """
        ).fetchall()
    finally:
        conn.close()
    now = time.time()
    due = []
    for row in rows:
        record = {name: row[index] for index, name in enumerate(SOURCE_COLUMNS)}
        last = float(record.get("last_checked") or record.get("fetched_at") or 0)
        if now - last >= max(60, int(record.get("refresh_interval") or 0)):
            due.append(record)
    return due


def refresh_due_sources() -> dict:
    """Refresh opted-in sources across every registered space."""
    from palimind import knowledge, spaces
    from palimind.spaces import sources as sources_mod

    refreshed = failed = 0
    for space in spaces.list_spaces():
        root = Path(str(space.get("root") or ""))
        if not root.is_dir():
            continue
        for record in due_sources(root):
            try:
                result = sources_mod.ingest_web_source(root, str(record["id"]))
                if result.get("status") in ("ready", "not_modified"):
                    refreshed += 1
                else:
                    failed += 1
            except Exception:  # noqa: BLE001 - one bad page must not stop the loop
                failed += 1
                logger.exception("Scheduled refresh failed for %s", record.get("url"))
        if refreshed:
            try:
                knowledge.run_index(root, wait=False)
            except Exception:  # noqa: BLE001
                logger.debug("Index enqueue after refresh failed", exc_info=True)
    return {"refreshed": refreshed, "failed": failed}


async def maintenance_loop(stop_event: asyncio.Event, interval: int = CHECK_EVERY_SECONDS) -> None:
    while not stop_event.is_set():
        try:
            result = await asyncio.to_thread(refresh_due_sources)
            if result.get("refreshed") or result.get("failed"):
                logger.info("Source refresh: %s", result)
        except Exception:  # noqa: BLE001
            logger.exception("Source maintenance loop failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


def start_maintenance(loop: asyncio.AbstractEventLoop, interval: int = CHECK_EVERY_SECONDS):
    """Start the background loop; returns its task."""
    stop_event = asyncio.Event()
    task = loop.create_task(maintenance_loop(stop_event, interval))
    try:
        task._palimind_stop = stop_event  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover - C Task implementations
        pass
    return task
