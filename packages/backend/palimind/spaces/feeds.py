"""RSS/Atom feed subscriptions.

A feed is a lightweight source row; each item becomes a normal web source so
it flows through the same fetch → Markdown → index → graph pipeline.
"""

from __future__ import annotations

import logging
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

from palimind.spaces import web_source
from palimind.storage.db import (
    find_source,
    get_connection,
    get_source,
    upsert_source,
)

logger = logging.getLogger(__name__)

MAX_FEED_BYTES = 4 * 1024 * 1024
MAX_ITEMS = 50


class FeedError(RuntimeError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element, *names: str) -> str:
    for child in list(element):
        if _local(child.tag) in names:
            text = (child.text or "").strip()
            if text:
                return text
            href = (child.get("href") or "").strip()
            if href:
                return href
    return ""


def parse_feed(xml_text: str, base_url: str = "") -> tuple[str, list[dict]]:
    """Parse RSS 2.0 or Atom into ``(feed_title, items)``."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as exc:
        raise FeedError(f"Not a valid feed: {exc}") from exc

    feed_title = ""
    items: list[dict] = []
    for element in root.iter():
        name = _local(element.tag)
        if name in ("title",) and not feed_title:
            # The first title in document order is normally the feed/channel.
            feed_title = (element.text or "").strip()
        if name not in ("item", "entry"):
            continue
        link = _child_text(element, "link")
        if not link:
            link = _child_text(element, "guid", "id")
        if not link:
            continue
        link = urljoin(base_url, link)
        if not link.startswith(("http://", "https://")):
            continue
        items.append(
            {
                "title": _child_text(element, "title"),
                "url": link,
                "published": _child_text(
                    element, "pubdate", "published", "updated", "date"
                ),
                "summary": _child_text(element, "description", "summary", "content"),
            }
        )
        if len(items) >= MAX_ITEMS:
            break
    return feed_title, items


def fetch_feed(url: str, *, allow_private: bool = False) -> tuple[str, list[dict], str]:
    import httpx

    start = web_source.normalise_url(url)
    if not web_source._safe_url(start, allow_private=allow_private):
        raise FeedError("That address is not allowed (private or internal network).")
    if not web_source._robots_allowed(start, allow_private=allow_private):
        raise FeedError("robots.txt does not allow reading this feed.")

    current = start
    response = None
    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        for _hop in range(6):
            if not web_source._safe_url(current, allow_private=allow_private):
                raise FeedError("A redirect pointed at a private address.")
            try:
                response = client.get(
                    current, headers={"User-Agent": web_source.USER_AGENT}
                )
            except httpx.HTTPError as exc:
                raise FeedError(f"Could not fetch the feed: {exc}") from exc
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location", "")
                if not location:
                    raise FeedError("The feed returned an empty redirect.")
                current = urljoin(current, location)
                continue
            break
        else:
            raise FeedError("Too many redirects.")
    if response is None or response.status_code >= 400:
        raise FeedError(f"The feed returned HTTP {getattr(response, 'status_code', 0)}.")
    raw = response.content
    if len(raw) > MAX_FEED_BYTES:
        raise FeedError("The feed is too large (max 4 MB).")
    title, items = parse_feed(response.text, current)
    return title, items, current


def add_feed(
    root: Path,
    url: str,
    *,
    limit: int = 30,
    allow_private: bool = False,
) -> dict:
    """Create a feed row and its current items as saved web sources."""
    root = Path(root)
    title, items, final_url = fetch_feed(url, allow_private=allow_private)
    canonical = web_source.canonicalise(final_url)
    conn = get_connection(root)
    try:
        existing = find_source(conn, canonical_url=canonical)
        if existing is not None:
            feed = existing
        else:
            feed_id = uuid.uuid4().hex[:12]
            now = time.time()
            feed = upsert_source(
                conn,
                {
                    "id": feed_id,
                    "kind": "feed",
                    "url": final_url,
                    "canonical_url": canonical,
                    "title": title or final_url,
                    "site": web_source._site_from_url(final_url),
                    "status": "ready",
                    "fetched_at": now,
                    "last_checked": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )
    finally:
        conn.close()

    from palimind.spaces import sources as sources_mod

    created = []
    for item in items[: max(1, min(int(limit or 30), MAX_ITEMS))]:
        record = sources_mod.create_web_source(
            root,
            item["url"],
            title=item.get("title") or "",
            parent_id=str(feed["id"]),
        )
        created.append(record)
    return {"feed": feed, "items": created}


def refresh_feed(root: Path, feed_id: str, *, allow_private: bool = False) -> dict:
    root = Path(root)
    conn = get_connection(root)
    try:
        feed = get_source(conn, feed_id)
    finally:
        conn.close()
    if feed is None or feed.get("kind") != "feed":
        return {"error": "Feed not found"}
    try:
        title, items, final_url = fetch_feed(
            str(feed.get("url") or ""), allow_private=allow_private
        )
    except FeedError as exc:
        conn = get_connection(root)
        try:
            feed["status"] = "failed"
            feed["error"] = str(exc)
            feed["last_checked"] = time.time()
            upsert_source(conn, feed)
        finally:
            conn.close()
        return {"error": str(exc), "feed": feed}

    from palimind.spaces import sources as sources_mod

    created = []
    for item in items[:MAX_ITEMS]:
        record = sources_mod.create_web_source(
            root,
            item["url"],
            title=item.get("title") or "",
            parent_id=feed_id,
        )
        created.append(record)

    conn = get_connection(root)
    try:
        feed.update(
            {
                "title": title or feed.get("title") or final_url,
                "url": final_url,
                "status": "ready",
                "error": "",
                "last_checked": time.time(),
                "fetched_at": time.time(),
            }
        )
        upsert_source(conn, feed)
    finally:
        conn.close()
    return {"feed": feed, "items": created, "new_items": len(created)}
