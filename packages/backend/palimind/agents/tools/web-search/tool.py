from __future__ import annotations

import json

try:
    from ddgs import DDGS

    _DDGS_AVAILABLE = True
except ImportError:
    _DDGS_AVAILABLE = False


def web_search(query: str, max_results: int = 5) -> str:
    """DuckDuckGo web search. Returns a JSON list of {title, url, snippet}."""
    if not query or not str(query).strip():
        return "Error: query is required"
    if not _DDGS_AVAILABLE:
        return "Error: ddgs is not installed (`pip install ddgs`)."

    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(str(query), max_results=int(max_results)))
    except Exception as exc:  # noqa: BLE001 - network errors are expected
        return f"Error: search failed ({exc})"

    results = [
        {"title": h.get("title", ""), "url": h.get("href", ""), "snippet": h.get("body", "")}
        for h in hits
    ]
    if not results:
        return "No results found."
    return json.dumps(results, indent=2, ensure_ascii=False)
