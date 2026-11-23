"""Saving research results into a knowledge space.

Research projects already collect cited sources. This module turns those into
normal sources (and can run the same fetch/index path as manual saves), so a
research session leaves durable, searchable evidence behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from palimind.spaces import sources as sources_mod


def _url(item: dict) -> str:
    return str(item.get("url") or item.get("link") or "").strip()


def save_research_sources(
    root: Path,
    items: Iterable[dict],
    *,
    tags: Any = None,
    note: str = "",
) -> dict:
    """Create web sources for every cited URL; dedupe is handled per URL."""
    root = Path(root)
    created: list[dict] = []
    errors: list[dict] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = _url(item)
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            record = sources_mod.create_web_source(
                root,
                url,
                title=str(item.get("title") or ""),
                tags=tags,
                note=note,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"url": url, "error": str(exc)})
            continue
        if record.get("error"):
            errors.append({"url": url, "error": record["error"]})
            continue
        created.append(record)
    return {"sources": created, "errors": errors}


def save_and_schedule(
    root: Path,
    items: Iterable[dict],
    *,
    tags: Any = None,
    note: str = "",
) -> dict:
    from palimind.spaces import ingest as ingest_mod

    result = save_research_sources(root, items, tags=tags, note=note)
    queued = [
        item["id"]
        for item in result.get("sources") or []
        if item.get("status") in ("queued", "failed", "blocked")
    ]
    if queued:
        ingest_mod.schedule_ingest(root, queued)
    result["queued"] = queued
    return result
