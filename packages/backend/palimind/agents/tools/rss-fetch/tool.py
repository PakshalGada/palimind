from __future__ import annotations

import json
from typing import Any


def fetch_rss(feed_url: str, limit: int = 10) -> str:
    """Fetch and parse an RSS/Atom feed URL, returning a JSON list of
    {title, link, summary, published} entries."""
    import xml.etree.ElementTree as ET
    from urllib.parse import urljoin

    import httpx

    from palimind.core.web_search import _is_safe_url

    if not feed_url or not str(feed_url).startswith(("http://", "https://")):
        return "Error: feed_url must be an http(s) URL"

    # This tool runs without approval, so it must not reach loopback/LAN/
    # cloud-metadata hosts. Redirects are followed manually so every hop is
    # re-checked (a public feed could otherwise 302 to http://127.0.0.1/...).
    max_bytes = 3_000_000
    current = str(feed_url)
    data = b""
    try:
        for _hop in range(6):
            if not current.startswith(("http://", "https://")) or not _is_safe_url(current):
                return f"Error: refusing to fetch internal or invalid address: {current}"
            with httpx.stream(
                "GET",
                current,
                timeout=20,
                follow_redirects=False,
                headers={"User-Agent": "Palimind/2.0"},
            ) as resp:
                if resp.is_redirect:
                    current = urljoin(current, resp.headers.get("location", ""))
                    continue
                if resp.status_code >= 400:
                    return f"Error fetching RSS feed: HTTP {resp.status_code}"
                chunks: list[bytes] = []
                size = 0
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= max_bytes:
                        break
                data = b"".join(chunks)[:max_bytes]
                break
        else:
            return "Error fetching RSS feed: too many redirects"
    except Exception as e:
        return f"Error fetching RSS feed: {e}"

    def _local(tag: str) -> str:
        return tag.split("}")[-1]

    try:
        root_el = ET.fromstring(data)
    except ET.ParseError as e:
        return f"Error parsing feed XML: {e}"

    items: list[dict[str, str]] = []
    for item in root_el.iter():
        tag = _local(item.tag)
        if tag not in ("item", "entry"):
            continue
        entry: dict[str, str] = {}
        for child in item:
            ctag = _local(child.tag)
            text = (child.text or "").strip()
            if ctag == "title" and "title" not in entry:
                entry["title"] = text
            elif ctag == "link":
                link = child.attrib.get("href", "") or text
                if "link" not in entry and link:
                    entry["link"] = link
            elif ctag in ("description", "summary", "content") and "summary" not in entry:
                entry["summary"] = text[:500]
            elif ctag in ("pubDate", "published", "updated", "date") and "published" not in entry:
                entry["published"] = text
        if entry.get("title") or entry.get("link"):
            entry.setdefault("title", "(untitled)")
            entry.setdefault("link", "")
            entry.setdefault("summary", "")
            entry.setdefault("published", "")
            items.append(entry)
        if len(items) >= limit:
            break

    if not items:
        return "No items found in feed"
    return json.dumps(items, ensure_ascii=False)


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Fetch and parse an RSS/Atom feed URL. Returns a JSON list of "
        "{title, link, summary, published} entries."
    ),
    "parameters": {
        "feed_url": {"type": "string", "description": "The RSS/Atom feed URL"},
        "limit": {
            "type": "integer",
            "description": "Maximum number of entries",
            "default": 10,
        },
    },
    "tier": 1,
    "requires_approval": False,
    "parallel_safe": True,
    "idempotent": True,
}
