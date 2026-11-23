"""Web source ingestion tests (local HTTP fixture, no external network)."""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from palimind import spaces
from palimind.spaces import sources, web_source
from palimind.core import web_search as _web_search

_ORIGINAL_SAFE_URL = _web_search._is_safe_url


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):  # noqa: D401 - keep test output clean
        pass

    def _send(self, code: int, body: str, content_type: str = "text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/robots.txt":
            self._send(200, "User-agent: *\nDisallow: /private\n", "text/plain")
            return
        if self.path == "/private":
            self._send(200, "<html><body><article>secret</article></body></html>")
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/plain":
            self._send(200, "just text", "text/plain")
            return
        if self.path == "/header":
            header = self.headers.get("X-Test", "missing")
            self._send(
                200,
                f"<html><head><title>Header {header}</title></head><body><article>auth body</article></body></html>",
            )
            return
        if self.path == "/docs":
            self._send(
                200,
                """
                <html><head><title>Docs</title></head><body><article>
                  <a href="/docs/a">A</a>
                  <a href="/docs/b">B</a>
                  <a href="https://other.example/x">External</a>
                </article></body></html>
                """,
            )
            return
        if self.path in ("/docs/a", "/docs/b"):
            self._send(
                200,
                f"<html><head><title>{self.path}</title></head><body><article>page {self.path}</article></body></html>",
            )
            return
        if self.path == "/etag":
            if self.headers.get("If-None-Match") == '"v1"':
                self.send_response(304)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = b"<html><head><title>Etag page</title></head><body><article>body</article></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("ETag", '"v1"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(
            200,
            """
            <html><head>
              <title>Test Article</title>
              <meta property="og:site_name" content="Example Site">
              <meta name="author" content="Ada Lovelace">
              <meta property="article:published_time" content="2024-05-06T10:00:00Z">
              <link rel="canonical" href="/canonical">
            </head><body>
              <nav>menu</nav>
              <article><h1>Test Article</h1><p>Knowledge graphs connect ideas.</p></article>
              <footer>footer</footer>
            </body></html>
            """,
        )


@pytest.fixture(scope="module")
def server_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _allow_local(monkeypatch, tmp_path: Path):
    import palimind.api_server as server

    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(server, "GLOBAL_CONFIG_PATH", tmp_path / "global.json")
    monkeypatch.setattr(server.state, "fields", [])
    monkeypatch.setattr(server.state, "active_field", None)
    monkeypatch.setattr(server.state, "active_space_id", None)
    # The production guard intentionally blocks loopback; allow the fixture.
    monkeypatch.setattr(
        "palimind.core.web_search._is_safe_url", lambda url: True
    )
    yield


def _space(tmp_path: Path) -> Path:
    parent = tmp_path / "vault"
    parent.mkdir()
    record = spaces.create_space("Web KB", parent_dir=str(parent))
    return Path(record["root"])


def test_ssrf_guard_blocks_loopback_by_default(server_url: str, monkeypatch) -> None:
    monkeypatch.setattr(
        "palimind.core.web_search._is_safe_url", _ORIGINAL_SAFE_URL
    )
    with pytest.raises(web_source.FetchError):
        web_source.fetch_page(server_url + "/", allow_private=False)


def test_ingest_writes_markdown_with_front_matter_and_metadata(
    tmp_path: Path, server_url: str
) -> None:
    root = _space(tmp_path)
    created = sources.create_web_source(root, server_url + "/")
    assert created["status"] == "queued"

    saved = sources.ingest_web_source(root, created["id"])
    assert saved["status"] == "ready", saved
    assert saved["title"] == "Test Article"
    assert saved["author"] == "Ada Lovelace"
    assert saved["site"] == "Example Site"
    assert saved["published_at"].startswith("2024-05-06")
    assert saved["canonical_url"].endswith("/canonical")

    target = root / saved["file_path"]
    text = target.read_text("utf-8")
    assert text.startswith("---")
    assert "source_type: \"web\"" in text
    assert "# Test Article" in text
    assert "Knowledge graphs connect ideas." in text
    assert "menu" not in text  # navigation stripped
    assert (root / saved["snapshot_path"]).is_file()


def test_canonical_url_deduplicates(tmp_path: Path, server_url: str) -> None:
    root = _space(tmp_path)
    first = sources.create_web_source(root, server_url + "/?utm_source=x")
    second = sources.create_web_source(root, server_url + "/#section")
    assert first["id"] == second["id"]


def test_redirect_and_unsupported_content(tmp_path: Path, server_url: str) -> None:
    root = _space(tmp_path)
    redirected = sources.create_web_source(root, server_url + "/redirect")
    saved = sources.ingest_web_source(root, redirected["id"])
    assert saved["status"] == "ready"

    plain = sources.create_web_source(root, server_url + "/plain")
    failed = sources.ingest_web_source(root, plain["id"])
    assert failed["status"] == "failed"
    assert "content type" in failed["error"].lower()


def test_robots_disallow_marks_blocked(tmp_path: Path, server_url: str) -> None:
    root = _space(tmp_path)
    row = sources.create_web_source(root, server_url + "/private")
    saved = sources.ingest_web_source(root, row["id"])
    assert saved["status"] == "blocked"
    assert "robots" in saved["error"].lower()


def test_conditional_refresh_keeps_content(tmp_path: Path, server_url: str) -> None:
    root = _space(tmp_path)
    row = sources.create_web_source(root, server_url + "/etag")
    first = sources.ingest_web_source(root, row["id"])
    assert first["status"] == "ready"
    assert first["etag"] == '"v1"'

    second = sources.ingest_web_source(root, row["id"])
    assert second["status"] == "ready", second.get("error")
    assert second["file_path"] == first["file_path"]


def test_text_source_and_delete(tmp_path: Path) -> None:
    root = _space(tmp_path)
    record = sources.create_text_source(root, "Remember the milk.", title="Note")
    assert record["status"] == "ready"
    assert (root / record["file_path"]).is_file()

    content = sources.source_content(root, record["id"])
    assert "Remember the milk." in content["content"]

    assert sources.delete_space_source(root, record["id"], delete_file=True) is True
    assert not (root / record["file_path"]).exists()


def test_front_matter_stripped_from_chunks(tmp_path: Path) -> None:
    from palimind.rag.indexing import _strip_front_matter

    text = '---\ntitle: "x"\n---\n\n# Heading\n\nBody'
    assert _strip_front_matter(text).strip() == "# Heading\n\nBody"


def test_site_crawl_stays_on_the_same_host(tmp_path: Path, server_url: str) -> None:
    from palimind.spaces import crawl

    root = _space(tmp_path)
    result = crawl.crawl_site(root, server_url + "/docs", max_pages=5)
    assert result["status"] == "success"
    urls = {item["canonical_url"] for item in result["sources"]}
    assert any(url.endswith("/docs") for url in urls)
    assert any(url.endswith("/docs/a") for url in urls)
    assert any(url.endswith("/docs/b") for url in urls)
    assert not any("other.example" in url for url in urls)


def test_derive_tags_is_deterministic() -> None:
    tags = web_source.derive_tags(
        "Knowledge graphs connect knowledge. Knowledge graphs help. Graphs are useful.",
        site="example.com",
    )
    assert tags[0] == "Example"
    assert any(tag.lower() == "graphs" for tag in tags)


def test_capture_profile_headers_reach_the_request(tmp_path: Path, server_url: str) -> None:
    from palimind.spaces import profiles

    root = _space(tmp_path)
    profiles.upsert_profile(
        root,
        {
            "name": "Local auth",
            "domain": "127.0.0.1",
            "headers": {"X-Test": "hello"},
            "cookies": "session=abc",
        },
    )
    row = sources.create_web_source(root, server_url + "/header")
    saved = sources.ingest_web_source(root, row["id"])
    assert saved["status"] == "ready", saved
    assert saved["title"] == "Header hello"
