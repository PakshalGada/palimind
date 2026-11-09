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
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# ── tunables ──────────────────────────────────────────────────────────────
MAX_RESULTS_DEFAULT = 5  # search results used per query
MAX_PAGES_TO_FETCH = 4  # pages actually fetched for content
PAGE_CONTENT_CHARS = 3000  # extracted text kept per page
SNIPPET_CHARS = 500  # snippet text kept when fetch fails
CACHE_TTL_SECONDS = 15 * 60  # 15 minutes
CACHE_MAX_ENTRIES = 128  # LRU bound
MAX_RESULTS_PER_DOMAIN = 2
FETCH_TIMEOUT_SECONDS = 15
MAX_FETCH_WORKERS = 4
MAX_QUERY_VARIANTS = 3

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


def _cache_key(query: str, max_results: int, depth: str, provider: str = "auto") -> str:
    raw = f"{query.strip().lower()}::{max_results}::{depth}::{provider}"
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


_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "please",
    "tell",
    "me",
    "the",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}

# Domains that usually carry authoritative primary information.
_QUALITY_DOMAINS = {
    "arxiv.org",
    "github.com",
    "wikipedia.org",
    "nature.com",
    "science.org",
    "acm.org",
    "ieee.org",
    "nih.gov",
    "who.int",
    "europa.eu",
}


def _query_terms(query: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'+-]{1,}", query)
        if token.lower() not in _QUERY_STOPWORDS
    }


def _relevance(item: dict, terms: set[str]) -> float:
    """Cheap lexical relevance + domain/position prior used for re-ranking."""
    if not terms:
        return 0.0
    title = str(item.get("title") or "").lower()
    snippet = str(item.get("snippet") or "").lower()
    url = str(item.get("url") or "").lower()
    haystack = f"{title} {snippet} {url}"
    overlap = sum(1 for term in terms if term in haystack)
    score = overlap / max(1, len(terms))
    if any(term in title for term in terms):
        score += 0.35
    dom = _domain(url)
    if dom in _QUALITY_DOMAINS or dom.endswith(".gov") or dom.endswith(".edu"):
        score += 0.25
    if dom in _LOW_QUALITY_DOMAINS:
        score -= 0.6
    return score


def _dedupe_results(results: list[dict], limit: int, query: str = "") -> list[dict]:
    """Dedupe by URL, cap per domain, then rank by relevance and quality."""
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}
    unique: list[dict] = []
    terms = _query_terms(query)

    for position, res in enumerate(results):
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
        item["_score"] = _relevance(item, terms) + max(0.0, 0.12 - position * 0.01)
        unique.append(item)

    # Stable sort: provider order breaks ties.
    unique.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
    for item in unique:
        item.pop("_score", None)
    return unique[:limit]


def _is_safe_url(url: str) -> bool:
    """Block requests to internal/private IP addresses to prevent SSRF."""
    import ipaddress
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        # Resolve hostname and check every address it maps to (the HTTP
        # client may connect to any of them, IPv4 or IPv6).
        import socket

        try:
            ips = [ipaddress.ip_address(hostname)]
        except ValueError:
            try:
                infos = socket.getaddrinfo(hostname, None)
                ips = [ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos]
            except (OSError, ValueError):
                return False
        if not ips:
            return False
        for ip in ips:
            mapped = getattr(ip, "ipv4_mapped", None)
            if mapped is not None:
                ip = mapped
            # Block private, loopback, reserved, link-local (cloud metadata),
            # multicast and unspecified (0.0.0.0) addresses
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_reserved
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return False
        return True
    except Exception:
        return False


def _header(headers: object, name: str) -> str:
    """Case-insensitive header lookup on a dict-like headers object."""
    try:
        items = headers.items()  # type: ignore[attr-defined]
    except AttributeError:
        return ""
    for k, v in items:
        if str(k).lower() == name:
            return str(v or "")
    return ""


def _fetch_page_content(url: str) -> str:
    """Fetch a page with scrapling and extract readable text; never raises."""
    if not _is_safe_url(url):
        return ""
    try:
        from scrapling import Fetcher

        # Scrapling (curl_cffi) follows redirects itself, which would let a
        # public page bounce the request to loopback/LAN/metadata hosts
        # without our SSRF check. Disable auto-redirects and follow each hop
        # manually, re-checking it.
        page = None
        current = url
        for _hop in range(6):
            if not _is_safe_url(current):
                return ""
            page = Fetcher().get(current, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False)
            location = _header(page.headers, "location")
            if not (300 <= page.status < 400 and location):
                break
            current = urljoin(current, location)
        else:
            return ""
        if page is None or page.status >= 300:
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

        # Follow redirects manually so every hop is re-checked: a public page
        # redirecting to http://127.0.0.1/... (or a LAN host) must not bypass
        # the SSRF guard applied to the original URL.
        resp = None
        current = url
        for _hop in range(6):
            if not _is_safe_url(current):
                return ""
            resp = httpx.get(
                current,
                timeout=FETCH_TIMEOUT_SECONDS,
                follow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            )
            if not resp.is_redirect:
                break
            current = urljoin(current, resp.headers.get("location", ""))
        else:
            return ""
        if resp is None or resp.is_redirect or resp.status_code >= 400:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(
            ["script", "style", "nav", "header", "footer", "aside", "noscript", "form"]
        ):
            tag.decompose()
        # Prefer the main content region when the page marks one; this drops
        # menus, cookie banners and related-link blocks from the extract.
        main = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"})
        text = (main or soup).get_text(separator="\n")
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


_QUESTION_PREFIX_RE = re.compile(
    r"^(?:(?:please|can you|could you|tell me|explain|what is|what are|how do|"
    r"how does|how to|why is|why are|who is|who are|when did|where is)\s+)+",
    re.IGNORECASE,
)
_FRESHNESS_RE = re.compile(
    r"\b(latest|current|today|news|recent|this year|now|update|release|price)\b",
    re.IGNORECASE,
)


def _build_query_variants(query: str) -> list[str]:
    """Cheap deterministic query variants (no LLM call).

    Search engines respond better to the keywords than to a full question, and
    a year-qualified variant surfaces fresher pages for time-sensitive asks.
    """
    variants: list[str] = []

    def add(value: str) -> None:
        value = " ".join(value.split()).strip()
        if value and value.lower() not in {v.lower() for v in variants}:
            variants.append(value)

    add(query)
    stripped = query.strip().rstrip("?.!")
    keyword_query = _QUESTION_PREFIX_RE.sub("", stripped).strip()
    keyword_query = re.sub(r"^(?:the|a|an)\s+", "", keyword_query, flags=re.IGNORECASE)
    # Prefer the keyword and freshness variants over a punctuation-only copy.
    add(keyword_query)
    if _FRESHNESS_RE.search(query) and not re.search(r"\b20\d{2}\b", query):
        add(f"{keyword_query or stripped} {time.gmtime().tm_year}")
    add(stripped)
    return variants[:MAX_QUERY_VARIANTS]


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

    from palimind.core.search_providers import SearchRouter

    router = SearchRouter()
    depth = "deep" if fetch_content else "snippets"
    key = _cache_key(query, max_results, depth, router.requested)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    # 1. Multi-query search through the configured provider (SearXNG or DDG).
    # Ask for a wider candidate set than we need, then re-rank locally by
    # lexical relevance, domain quality and provider position.
    variants = _build_query_variants(query)
    candidate_limit = max(max_results, min(max_results * 3, 15))
    raw_results, provider_name = router.search_many(variants, candidate_limit)
    raw_dicts = [result.to_dict() for result in raw_results]
    results = _dedupe_results(raw_dicts, max_results, query)
    if not results:
        # Not cached: an empty result is usually a transient DDG failure or
        # rate-limit, which would otherwise stick for the whole cache TTL.
        return f"No web search results found for query: '{query}'"

    # 2. Fetch page content for top results in parallel: search latency stays
    # close to the slowest page instead of the sum of every page.
    if fetch_content:
        pages_to_fetch = results[:MAX_PAGES_TO_FETCH]
        with ThreadPoolExecutor(max_workers=min(MAX_FETCH_WORKERS, len(pages_to_fetch))) as pool:
            contents = list(pool.map(lambda item: _fetch_page_content(item["url"]), pages_to_fetch))
        for item, content in zip(pages_to_fetch, contents, strict=True):
            item["content"] = content if content else None

    # 3. Format
    parts = [
        f"=== WEB SEARCH RESULTS FOR: '{query}' ===\n",
        f"Provider: {provider_name}\n",
        f"Sources: {len(results)}\n",
    ]
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
