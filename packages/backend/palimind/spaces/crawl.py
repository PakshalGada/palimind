"""One-level site crawl for saved domains.

Starting from a page, collect same-site links (bounded by ``max_pages``) and
create a web source for each. The crawl never leaves the starting host and is
always user-initiated.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

from palimind.spaces import web_source
from palimind.spaces import sources as sources_mod

logger = logging.getLogger(__name__)

SKIP_EXTENSIONS = (
    ".pdf",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
    ".json",
    ".xml",
)


def _same_site(base: str, candidate: str) -> bool:
    base_host = urlparse(base).netloc.lower().removeprefix("www.")
    host = urlparse(candidate).netloc.lower().removeprefix("www.")
    return bool(host) and (host == base_host or host.endswith("." + base_host))


def _links(html: str, base_url: str) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href)
        try:
            url = web_source.canonicalise(url)
        except web_source.FetchError:
            continue
        if not _same_site(base_url, url) or url in seen:
            continue
        if urlparse(url).path.lower().endswith(SKIP_EXTENSIONS):
            continue
        seen.add(url)
        found.append(url)
    return found


def crawl_site(
    root: Path,
    url: str,
    *,
    max_pages: int = 10,
    allow_private: bool = False,
) -> dict:
    root = Path(root)
    start = web_source.normalise_url(url)
    from palimind.spaces import policy

    allowed, reason = policy.domain_allowed(root, start)
    if not allowed:
        return {"error": reason}
    space = policy._space(root) or {}
    page = web_source.fetch_page(
        start,
        allow_private=allow_private,
        respect_robots=space.get("respect_robots") is not False,
    )
    if page.content_type and page.content_type != "text/html":
        return {"error": "The start page is not HTML."}

    created = []
    first = sources_mod.create_web_source(root, page.url, title=page.title)
    if first.get("status") in ("queued", "failed", "blocked"):
        created.append(first)
        sources_mod.ingest_web_source(root, str(first["id"]), allow_private=allow_private)

    pages = max(1, min(int(max_pages or 10), 50))
    for link in _links(page.html, page.url):
        if len(created) >= pages:
            break
        try:
            record = sources_mod.create_web_source(root, link)
            if record.get("error"):
                continue
            created.append(record)
            if record.get("status") in ("queued", "failed", "blocked"):
                sources_mod.ingest_web_source(
                    root, str(record["id"]), allow_private=allow_private
                )
        except Exception:  # noqa: BLE001 - one bad link must not stop the crawl
            logger.debug("Could not queue %s", link, exc_info=True)
    return {"status": "success", "start": page.url, "sources": created[:pages]}
