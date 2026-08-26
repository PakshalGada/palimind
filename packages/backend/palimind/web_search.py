"""Web search with DuckDuckGo discovery + scrapling page-content extraction.

Pipeline:
1. Run DDG text search for the query (optionally multiple query variants).
2. Merge and deduplicate results by URL, capping results per domain.
3. Fetch the top pages with scrapling and extract readable main content.
4. Return a structured, context-budgeted string suitable for LLM prompts.

Results are cached in-memory with a TTL so parallel agents and follow-up
queries don't hammer DuckDuckGo or re-fetch the same pages.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from urllib.parse import urlparse

from ddgs import DDGS

logger = logging.getLogger(__name__)

# ── tunables ──────────────────────────────────────────────────────────────
MAX_RESULTS_DEFAULT = 4  # DDG results used per query
MAX_PAGES_TO_FETCH = 3  # pages actually fetched for content
PAGE_CONTENT_CHARS = 2500  # extracted text kept per page
SNIPPET_CHARS = 400  # snippet text kept when fetch fails
CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
CACHE_MAX_ENTRIES = 128  # LRU bound
MAX_RESULTS_PER_DOMAIN = 2
FETCH_TIMEOUT_SECONDS = 15

# Boilerplate/spam domains worth deprioritizing
_LOW_QUALITY_DOMAINS = {
    "pinterest.com",
    "quora.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "reddit.com",
}

_cache_lock = threading.Lock()
_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()


def _cache_key(query: str, max_results: int, depth: str) -> str:
    raw = f"{query.strip().lower()}::{max_results}::{depth}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> str | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > CACHE_TTL_SECONDS:
            del _cache[key]
            return None
        _cache.move_to_end(key)
        return value


def _cache_put(key: str, value: str) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """Run one DuckDuckGo text search; never raises."""
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        logger.warning(f"DDG search failed for '{query}': {e}")
        return []


def _dedupe_results(results: list[dict], limit: int) -> list[dict]:
    """Dedupe by URL, cap per domain, deprioritize low-quality domains."""
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}
    good: list[dict] = []
    lowq: list[dict] = []

    for res in results:
        url = (res.get("href") or res.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        dom = _domain(url)
        if url in seen_urls or not dom:
            continue
        seen_urls.add(url)
        if domain_counts.get(dom, 0) >= MAX_RESULTS_PER_DOMAIN:
            continue
        domain_counts[dom] = domain_counts.get(dom, 0) + 1
        item = {
            "title": (res.get("title") or "Untitled").strip(),
            "url": url,
            "snippet": (res.get("body") or res.get("snippet") or "").strip(),
        }
        if dom in _LOW_QUALITY_DOMAINS:
            lowq.append(item)
        else:
            good.append(item)

    ranked = good + lowq
    return ranked[:limit]


def _fetch_page_content(url: str) -> str:
    """Fetch a page with scrapling and extract readable text; never raises."""
    try:
        from scrapling import Fetcher

        page = Fetcher().get(url, timeout=FETCH_TIMEOUT_SECONDS)
        if page.status >= 400:
            return ""
        text = page.get_all_text() or ""
    except Exception as e:
        logger.info(f"Scrapling fetch failed for {url}: {e}")
        text = _fetch_page_fallback(url)
    if not text:
        return ""
    # Collapse whitespace and truncate
    lines = [ln.strip() for ln in text.splitlines()]
    collapsed = " ".join(ln for ln in lines if ln)
    return collapsed[:PAGE_CONTENT_CHARS]


def _fetch_page_fallback(url: str) -> str:
    """Lightweight fallback: httpx + BeautifulSoup main-text extraction."""
    try:
        import httpx
        from bs4 import BeautifulSoup

        resp = httpx.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )
        if resp.status_code >= 400:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        return text
    except Exception as e:
        logger.info(f"Fallback fetch failed for {url}: {e}")
        return ""


def fetch_url_content(url: str, max_chars: int = PAGE_CONTENT_CHARS) -> str:
    """Fetch a single URL and return its extracted readable content."""
    content = _fetch_page_content(url)
    if not content:
        return f"Error: could not fetch or extract content from {url}"
    return f"=== CONTENT FOR: {url} ===\n{content[:max_chars]}\n{'=' * 39}\n"


def _build_query_variants(query: str) -> list[str]:
    """Cheap deterministic query variants (no LLM call)."""
    variants = [query]
    stripped = query.strip().rstrip("?.!")
    if stripped and stripped.lower() != query.lower():
        variants.append(stripped)
    return variants


def perform_web_search(
    query: str,
    max_results: int = MAX_RESULTS_DEFAULT,
    fetch_content: bool = True,
) -> str:
    """Search the web, fetch top pages, and return formatted results.

    Args:
        query: The search query.
        max_results: Number of DDG results to consider.
        fetch_content: When True, fetch and extract page content for the
            top results instead of returning snippets only.
    """
    if not query or not query.strip():
        return "Error: empty web search query."

    depth = "deep" if fetch_content else "snippets"
    key = _cache_key(query, max_results, depth)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    # 1. Multi-query DDG search
    raw_results: list[dict] = []
    for qv in _build_query_variants(query):
        raw_results.extend(_ddg_search(qv, max_results))
        if len(raw_results) >= max_results * 3:
            break

    results = _dedupe_results(raw_results, max_results)
    if not results:
        out = f"No web search results found for query: '{query}'"
        _cache_put(key, out)
        return out

    # 2. Fetch page content for top results
    pages_to_fetch = results[:MAX_PAGES_TO_FETCH] if fetch_content else []
    for item in pages_to_fetch:
        content = _fetch_page_content(item["url"])
        item["content"] = content if content else None

    # 3. Format
    parts = [f"=== WEB SEARCH RESULTS FOR: '{query}' ===\n"]
    for idx, item in enumerate(results, start=1):
        parts.append(
            f"Source [{idx}]: {item['title']}\n"
            f"URL: {item['url']}\n"
            f"Summary: {item['snippet'][:SNIPPET_CHARS]}\n"
        )
        if item.get("content"):
            parts.append(f"Page Content:\n{item['content']}\n")
        parts.append("")

    out = "\n".join(parts) + "=" * 39 + "\n"
    _cache_put(key, out)
    return out
