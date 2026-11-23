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
    """Refresh opted-in sources and build due daily digests."""
    from palimind import spaces
    from palimind.spaces import ingest as ingest_mod

    refreshed = failed = 0
    for space in spaces.list_spaces():
        root = Path(str(space.get("root") or ""))
        if not root.is_dir():
            continue
        for record in due_sources(root):
            try:
                result = ingest_mod.ingest_and_index(root, str(record["id"]))
                if result.get("status") in ("indexed", "ready", "not_modified"):
                    refreshed += 1
                else:
                    failed += 1
            except Exception:  # noqa: BLE001 - one bad page must not stop the loop
                failed += 1
                logger.exception("Scheduled refresh failed for %s", record.get("url"))

    digest_created = digest_failed = 0
    try:
        from palimind.spaces import digest as digest_mod

        digest_result = digest_mod.run_due_digests()
        digest_created = int(digest_result.get("created") or 0)
        digest_failed = int(digest_result.get("failed") or 0)
    except Exception:  # noqa: BLE001
        logger.exception("Digest generation failed")

    retention_removed = 0
    try:
        from palimind.spaces import retention as retention_mod

        retention_result = retention_mod.run_due_retention()
        retention_removed = int(retention_result.get("removed") or 0)
    except Exception:  # noqa: BLE001
        logger.exception("Retention prune failed")

    alerts_created = 0
    try:
        from palimind.spaces import searches as searches_mod

        alert_result = searches_mod.run_due_searches()
        alerts_created = int(alert_result.get("created") or 0)
    except Exception:  # noqa: BLE001
        logger.exception("Saved-search alerts failed")
    return {
        "refreshed": refreshed,
        "failed": failed,
        "digests_created": digest_created,
        "digests_failed": digest_failed,
        "retention_removed": retention_removed,
        "alerts_created": alerts_created,
    }


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
