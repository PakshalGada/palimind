"""Retention policy for saved sources.

Only app-managed sources are pruned (never the user's pre-existing files in a
linked folder). Digests and feed rows are kept; feed items are pruned with the
normal cutoff. Deletion goes through the source service so vectors, chunks and
graph nodes are removed too.
"""

from __future__ import annotations

import time
from pathlib import Path

from palimind.storage.db import SOURCE_COLUMNS, get_connection
from palimind.spaces import sources as sources_mod


def prune_space(root: Path, days: int, *, dry_run: bool = False) -> dict:
    root = Path(root)
    days = int(days or 0)
    if days <= 0:
        return {"removed": 0, "kept": 0, "dry_run": dry_run, "days": days}
    cutoff = time.time() - days * 86400
    conn = get_connection(root)
    try:
        rows = conn.execute(
            f"""
            SELECT {", ".join(SOURCE_COLUMNS)} FROM sources
            WHERE kind NOT IN ('digest', 'feed')
              AND COALESCE(fetched_at, created_at, 0) < ?
            ORDER BY COALESCE(fetched_at, created_at, 0) ASC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    records = [
        {name: row[index] for index, name in enumerate(SOURCE_COLUMNS)} for row in rows
    ]
    removed = 0
    errors = 0
    if not dry_run:
        for record in records:
            try:
                if sources_mod.delete_space_source(
                    root, str(record["id"]), delete_file=True
                ):
                    removed += 1
            except Exception:  # noqa: BLE001 - continue through the batch
                errors += 1
    return {
        "removed": removed if not dry_run else 0,
        "would_remove": len(records) if dry_run else 0,
        "kept": 0,
        "errors": errors,
        "dry_run": dry_run,
        "days": days,
        "cutoff": cutoff,
        "paths": [record.get("file_path") or record.get("url") for record in records],
    }


def run_due_retention() -> dict:
    from palimind import spaces

    removed = failed = 0
    for space in spaces.list_spaces():
        days = int(space.get("retention_days") or 0)
        if days <= 0:
            continue
        root = Path(str(space.get("root") or ""))
        if not root.is_dir():
            continue
        try:
            result = prune_space(root, days)
            removed += int(result.get("removed") or 0)
            failed += int(result.get("errors") or 0)
        except Exception:  # noqa: BLE001
            failed += 1
    return {"removed": removed, "failed": failed}
