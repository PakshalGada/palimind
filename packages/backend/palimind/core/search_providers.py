"""Pluggable local web-search providers.

The default is DuckDuckGo (no key, public fallback). A local SearXNG instance
can be selected explicitly or with ``auto``; when it is unreachable the router
falls back to DuckDuckGo and reports the degradation instead of failing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from palimind.config import load_global_config
from palimind.settings import SEARCH_PROVIDER, SEARCH_TIMEOUT, SEARXNG_URL

logger = logging.getLogger(__name__)

# Shared across router instances: searching repeatedly must not re-probe the
# local SearXNG port on every query.
_AVAILABILITY_CACHE: dict[str, tuple[float, bool, str]] = {}


class SearchProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    engine: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "engine": self.engine,
        }


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int = 4) -> list[SearchResult]: ...

    def status(self) -> dict[str, Any]: ...


class DuckDuckGoProvider:
    name = "ddg"

    def search(self, query: str, max_results: int = 4) -> list[SearchResult]:
        try:
            from ddgs import DDGS

            with DDGS() as ddgs:
                hits = list(ddgs.text(query, max_results=max_results))
        except Exception as exc:  # noqa: BLE001
            raise SearchProviderError(f"DuckDuckGo search failed: {exc}") from exc
        results: list[SearchResult] = []
        for hit in hits:
            url = str(hit.get("href") or hit.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                SearchResult(
                    title=str(hit.get("title") or "Untitled").strip(),
                    url=url,
                    snippet=str(hit.get("body") or hit.get("snippet") or "").strip(),
                    engine="duckduckgo",
                )
            )
        return results[:max_results]

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "available": True, "reason": ""}


class SearxNGProvider:
    name = "searxng"

    def __init__(self, base_url: str, timeout: float = SEARCH_TIMEOUT) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout = max(1.0, float(timeout or 8.0))

    def is_available(self, *, ttl: float = 30.0) -> bool:
        return self._availability(ttl)[0]

    def _availability(self, ttl: float = 30.0) -> tuple[bool, str, float]:
        now = time.time()
        cached = _AVAILABILITY_CACHE.get(self.base_url)
        if cached and now - cached[0] < ttl:
            return cached[1], cached[2], cached[0]
        if not self.base_url:
            _AVAILABILITY_CACHE[self.base_url] = (now, False, "SearXNG URL is not configured")
            return False, _AVAILABILITY_CACHE[self.base_url][2], now
        available = False
        reason = ""
        try:
            resp = httpx.get(
                f"{self.base_url}/",
                timeout=min(3.0, self.timeout),
                follow_redirects=True,
            )
            available = resp.status_code < 500
            if not available:
                reason = f"SearXNG returned HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            reason = f"SearXNG is not reachable: {exc}"
        _AVAILABILITY_CACHE[self.base_url] = (now, available, reason)
        return available, reason, now

    def search(self, query: str, max_results: int = 4) -> list[SearchResult]:
        if not self.base_url:
            raise SearchProviderError("SearXNG URL is not configured")
        try:
            resp = httpx.get(
                f"{self.base_url}/search",
                params={
                    "q": str(query),
                    "format": "json",
                    "safesearch": "1",
                    "language": "en",
                },
                timeout=self.timeout,
            )
            if resp.status_code >= 400:
                raise SearchProviderError(f"SearXNG returned HTTP {resp.status_code}")
            data = resp.json()
        except SearchProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SearchProviderError(f"SearXNG search failed: {exc}") from exc
        raw = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            raise SearchProviderError("SearXNG response did not contain a results list")
        results: list[SearchResult] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    snippet=str(item.get("content") or item.get("snippet") or "").strip(),
                    engine=str(item.get("engine") or "searxng"),
                )
            )
            if len(results) >= max_results:
                break
        return results

    def status(self) -> dict[str, Any]:
        available, reason, checked = self._availability()
        return {
            "name": self.name,
            "url": self.base_url,
            "available": available,
            "reason": reason,
            "checked_at": checked,
        }


class SearchRouter:
    """Select a provider and transparently fall back to DuckDuckGo."""

    def __init__(
        self,
        preferred: str | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if config is not None else load_global_config()
        self.requested = str(preferred or cfg.get("search_provider") or SEARCH_PROVIDER).lower()
        if self.requested not in ("auto", "ddg", "searxng"):
            self.requested = "auto"
        url = str(cfg.get("searxng_url") or SEARXNG_URL or "")
        self.searxng = SearxNGProvider(url)
        self.ddg = DuckDuckGoProvider()
        self.fallback_reason = ""

    def select(self) -> SearchProvider:
        self.fallback_reason = ""
        if self.requested == "ddg":
            return self.ddg
        if self.requested == "searxng":
            if self.searxng.is_available():
                return self.searxng
            self.fallback_reason = str(self.searxng.status().get("reason") or "")
            return self.ddg
        # auto: prefer local SearXNG when reachable.
        if self.searxng.is_available():
            return self.searxng
        return self.ddg

    def search_many(
        self, queries: list[str], max_results: int = 4
    ) -> tuple[list[SearchResult], str]:
        provider = self.select()
        results: list[SearchResult] = []
        try:
            for query in queries:
                results.extend(provider.search(query, max_results=max_results))
        except SearchProviderError as exc:
            if provider.name != "searxng":
                logger.warning("%s", exc)
                return results, provider.name
            self.fallback_reason = str(exc)
            provider = self.ddg
            results = []
            try:
                for query in queries:
                    results.extend(provider.search(query, max_results=max_results))
            except SearchProviderError as ddg_exc:
                logger.warning("%s", ddg_exc)
        return results, provider.name

    def status(self) -> dict[str, Any]:
        provider = self.select()
        searx = self.searxng.status()
        return {
            "configured": self.requested,
            "active": provider.name,
            "fallback": bool(self.fallback_reason),
            "fallback_reason": self.fallback_reason,
            "providers": {
                "searxng": searx,
                "ddg": self.ddg.status(),
            },
        }


def provider_status(preferred: str | None = None) -> dict[str, Any]:
    return SearchRouter(preferred).status()
