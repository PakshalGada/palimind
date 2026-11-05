"""Tests for local SearXNG search-provider selection and DDG fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import palimind.config as config
from palimind.core import search_providers as sp
from palimind.core import web_search


@pytest.fixture(autouse=True)
def _config(monkeypatch, tmp_path: Path):
    path = tmp_path / "global.json"
    monkeypatch.setattr(config, "GLOBAL_CONFIG_PATH", path)
    web_search._cache.clear()
    yield path


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_searxng_results_used_when_configured(_config, monkeypatch) -> None:
    _write(_config, {"search_provider": "searxng", "searxng_url": "http://searx.local"})
    monkeypatch.setattr(sp.SearxNGProvider, "is_available", lambda self, **kw: True)
    monkeypatch.setattr(
        sp.SearxNGProvider,
        "search",
        lambda self, query, max_results=4: [
            sp.SearchResult("Local result", "https://example.org/a", "from searx", "searxng")
        ],
    )
    monkeypatch.setattr(
        sp.DuckDuckGoProvider,
        "search",
        lambda self, query, max_results=4: (_ for _ in ()).throw(AssertionError("DDG called")),
    )
    out = web_search.perform_web_search("unique-searx-query", max_results=1, fetch_content=False)
    assert "Provider: searxng" in out
    assert "https://example.org/a" in out
    assert "Local result" in out


def test_searxng_failure_falls_back_to_ddg(_config, monkeypatch) -> None:
    _write(_config, {"search_provider": "searxng", "searxng_url": "http://searx.local"})
    monkeypatch.setattr(sp.SearxNGProvider, "is_available", lambda self, **kw: True)

    def _fail(self, query, max_results=4):
        raise sp.SearchProviderError("searx timed out")

    monkeypatch.setattr(sp.SearxNGProvider, "search", _fail)
    monkeypatch.setattr(
        sp.DuckDuckGoProvider,
        "search",
        lambda self, query, max_results=4: [
            sp.SearchResult("DDG result", "https://example.com/b", "from ddg", "duckduckgo")
        ],
    )
    router = sp.SearchRouter()
    results, provider = router.search_many(["fallback query"], max_results=1)
    assert provider == "ddg"
    assert results[0].url == "https://example.com/b"
    assert router.fallback_reason


def test_auto_uses_ddg_when_searxng_unreachable(_config, monkeypatch) -> None:
    _write(_config, {"search_provider": "auto", "searxng_url": "http://searx.local"})
    monkeypatch.setattr(sp.SearxNGProvider, "is_available", lambda self, **kw: False)
    monkeypatch.setattr(
        sp.DuckDuckGoProvider,
        "search",
        lambda self, query, max_results=4: [sp.SearchResult("DDG", "https://example.com/c")],
    )
    out = web_search.perform_web_search("auto-query-2", max_results=1, fetch_content=False)
    assert "Provider: ddg" in out
    assert "https://example.com/c" in out


def test_search_status_and_config_endpoints(_config, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    _write(_config, {"search_provider": "searxng", "searxng_url": "http://searx.local"})
    monkeypatch.setattr(sp.SearxNGProvider, "_availability", lambda self, ttl=30.0: (True, "", 0.0))
    client = TestClient(server.app)

    status = client.get("/api/search/status").json()
    assert status["configured"] == "searxng"
    assert status["active"] == "searxng"

    cfg = client.get("/api/search/config").json()
    assert cfg["provider"] == "searxng"
    assert cfg["searxng_url"] == "http://searx.local"

    updated = client.patch(
        "/api/search/config",
        json={"provider": "ddg", "searxng_url": "http://127.0.0.1:8080"},
    )
    assert updated.json()["status"] == "success"
    saved = json.loads(_config.read_text("utf-8"))
    assert saved["search_provider"] == "ddg"
    assert saved["searxng_url"] == "http://127.0.0.1:8080"

    invalid = client.patch("/api/search/config", json={"provider": "bing"})
    assert "error" in invalid.json()
