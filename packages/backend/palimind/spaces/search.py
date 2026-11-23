"""Cross-space retrieval: ask every registered knowledge space at once.

Each space keeps its own index. Results are merged, annotated with the space
they came from, deduplicated and sorted by score so the UI can group them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def search_all(
    query: str,
    *,
    limit_per_space: int = 5,
    max_results: int = 30,
    space_ids: list[str] | None = None,
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"query": "", "results": [], "spaces_searched": 0, "errors": []}

    from palimind import knowledge, spaces

    wanted = {str(item) for item in (space_ids or []) if item}
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    searched = 0
    seen: set[str] = set()
    limit_per_space = max(1, min(int(limit_per_space or 5), 20))

    for space in spaces.list_spaces():
        if wanted and str(space["id"]) not in wanted:
            continue
        root = Path(str(space.get("root") or ""))
        if not root.is_dir():
            continue
        searched += 1
        try:
            payload = knowledge.search(
                root, query, limit=limit_per_space
            )
        except Exception as exc:  # noqa: BLE001 - one bad index must not hide the rest
            logger.exception("Cross-space search failed for %s", root)
            errors.append({"space_id": str(space["id"]), "error": str(exc)})
            continue
        for item in payload.get("results") or []:
            hit = dict(item)
            hit["space_id"] = space["id"]
            hit["space_name"] = space["name"]
            hit["space_root"] = space["root"]
            key = (
                f"{space['id']}:{hit.get('file_path')}:"
                f"{hit.get('section')}:{hit.get('url')}"
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(hit)
        if payload.get("errors"):
            errors.append(
                {
                    "space_id": str(space["id"]),
                    "error": "; ".join(str(e) for e in payload["errors"][:2]),
                }
            )

    def _score(item: dict[str, Any]) -> tuple[float, str, str]:
        try:
            score = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        return (-score, str(item.get("space_name") or ""), str(item.get("title") or ""))

    results.sort(key=_score)
    results = results[: max(1, min(int(max_results or 30), 100))]
    by_space: dict[str, int] = {}
    for item in results:
        by_space[str(item["space_name"])] = by_space.get(str(item["space_name"]), 0) + 1
    return {
        "query": query,
        "results": results,
        "total": len(results),
        "spaces_searched": searched,
        "by_space": by_space,
        "errors": errors,
    }
