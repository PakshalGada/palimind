from __future__ import annotations

from pathlib import Path
from typing import Any


def _root(space_id: str = "") -> Path | None:
    if space_id:
        from palimind import spaces

        return spaces.resolve_space(space_id)
    from palimind.llm.mixture_of_expert.tools import _get_context

    ctx = _get_context()
    root = ctx.get("root")
    return Path(root) if root else None


def knowledge_space(
    action: str = "search",
    url: str = "",
    text: str = "",
    query: str = "",
    title: str = "",
    space_id: str = "",
    limit: int = 5,
) -> str:
    """Search the active knowledge space or save a URL/note into it.

    ``action="search"`` runs hybrid retrieval and returns cited passages.
    ``action="add_url"`` fetches, extracts, saves and indexes a web page.
    ``action="add_note"`` saves pasted text as a searchable note.
    """
    root = _root(space_id)
    if root is None:
        return "Error: no active knowledge space. Select one in the Knowledge view."

    action = (action or "search").strip().lower()
    if action == "search":
        if not query.strip():
            return "Error: query is required."
        from palimind import knowledge

        result = knowledge.search(root, query, limit=max(1, min(int(limit or 5), 20)))
        hits = result.get("results") or []
        if not hits:
            return f"No passages found in the knowledge space for: {query}"
        lines = [f"Found {len(hits)} passage(s) for: {query}"]
        for index, hit in enumerate(hits, start=1):
            where = hit.get("file_path") or "unknown"
            if hit.get("section"):
                where += f" → {hit.get('section')}"
            lines.append(f"[{index}] {where}\n{hit.get('content', '')[:700]}")
        return "\n\n".join(lines)

    if action == "search_all":
        if not query.strip():
            return "Error: query is required."
        from palimind.spaces import search as search_mod

        payload = search_mod.search_all(
            query, limit_per_space=3, max_results=max(1, min(int(limit or 8), 30))
        )
        hits = payload.get("results") or []
        if not hits:
            return f"No passages found across {payload.get('spaces_searched', 0)} space(s)."
        lines = [
            f"Found {len(hits)} result(s) across {payload.get('spaces_searched', 0)} space(s):"
        ]
        for index, hit in enumerate(hits, start=1):
            lines.append(
                f"[{index}] {hit.get('space_name')} · {hit.get('title') or hit.get('file_path')}"
                f"\n{hit.get('content', '')[:600]}"
            )
        return "\n\n".join(lines)

    if action == "digest":
        from palimind.spaces import digest as digest_mod

        result = digest_mod.create_digest(root, days=1)
        if result.get("status") == "error":
            return f"Error: {result.get('error')}"
        source = result.get("source") or {}
        return (
            f"Digest {result.get('status')}: "
            f"{source.get('title') or (result.get('digest') or {}).get('title')}"
        )

    if action == "add_url":
        if not url.strip():
            return "Error: url is required."
        from palimind import knowledge
        from palimind.spaces import sources as sources_mod

        record = sources_mod.create_web_source(root, url, title=title)
        if record.get("error"):
            return f"Error: {record['error']}"
        saved = sources_mod.ingest_web_source(root, str(record["id"]))
        if saved.get("error"):
            return f"Error saving {url}: {saved['error']}"
        try:
            knowledge.run_index(root, wait=False)
        except Exception:  # noqa: BLE001 - the source is saved; sync can retry
            pass
        return f"Saved and indexed: {saved.get('title') or url}"

    if action == "add_note":
        if not text.strip():
            return "Error: text is required."
        from palimind import knowledge
        from palimind.spaces import sources as sources_mod

        record = sources_mod.create_text_source(root, text, title=title)
        if record.get("error"):
            return f"Error: {record['error']}"
        try:
            knowledge.run_index(root, wait=False)
        except Exception:  # noqa: BLE001
            pass
        return f"Saved note: {record.get('title') or 'Note'}"

    return "Error: action must be search, add_url or add_note."


TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Work with knowledge spaces: search one space, search every space, build a "
        "daily digest, or save a URL or note so it becomes searchable and appears "
        "in the graph."
    ),
    "parameters": {
        "action": {
            "type": "string",
            "description": "search | search_all | digest | add_url | add_note",
            "required": True,
        },
        "query": {"type": "string", "description": "Search query", "required": False},
        "url": {"type": "string", "description": "URL to save (add_url)", "required": False},
        "text": {"type": "string", "description": "Note text (add_note)", "required": False},
        "title": {"type": "string", "description": "Optional title", "required": False},
        "space_id": {
            "type": "string",
            "description": "Optional space id; defaults to the active space",
            "required": False,
        },
        "limit": {"type": "integer", "description": "Search result cap", "required": False},
    },
    "tier": 1,
    "requires_approval": False,
    "parallel_safe": False,
    "idempotent": False,
}
