"""Regression tests: document-mode streaming, filtered FTS, SSRF in rss-fetch
and web-search page fetch. No network beyond a loopback test server, nothing
written to ~/.palimind.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _sse_events(chunks: list) -> list[dict]:
    out = []
    for c in chunks:
        c = c.decode() if isinstance(c, bytes) else c
        if c.startswith("data: "):
            out.append(json.loads(c[len("data: ") :]))
    return out


# ── 1. document-mode stream: off-loop + all reasoning delivered ───────────


def _run_document_stream(monkeypatch, make_tokens) -> tuple[list[dict], int]:
    import palimind.document.engine as engine_mod
    from palimind.document import stream as doc_stream

    class FakeEngine:
        def __init__(self, *a, **k):
            pass

        def ensure_graph(self):
            return None

        def retrieve_context(self, q, **kw):
            return {"sources": [], "total_results": 0, "errors": [], "results": []}

        def stream_answer(self, q, context, on_reasoning=None, **kw):
            return make_tokens(on_reasoning)

    monkeypatch.setattr(engine_mod, "DocumentEngine", FakeEngine)
    monkeypatch.setattr(doc_stream, "load_config", lambda root: {"retrieval_limit": 5})

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        t = asyncio.create_task(ticker())
        resp = await doc_stream.document_mode_stream(
            "q", None, None, None, None, "http://x", "m", Path("/nonexistent"), "off"
        )
        chunks = [c async for c in resp.body_iterator]
        t.cancel()
        return chunks, ticks

    chunks, ticks = asyncio.run(main())
    return _sse_events(chunks), ticks


def test_document_stream_emits_interleaved_and_trailing_reasoning(monkeypatch) -> None:
    def tokens(on_reasoning):
        on_reasoning("first ")
        yield "A"
        on_reasoning("second ")
        yield "B"
        on_reasoning("trailing")

    events, _ = _run_document_stream(monkeypatch, tokens)
    thinking = "".join(e["text"] for e in events if e["type"] == "thinking")
    assert thinking == "first second trailing"
    assert [e["text"] for e in events if e["type"] == "token"] == ["A", "B"]
    assert events[-1]["type"] == "done"


def test_document_stream_reasoning_only_is_not_dropped(monkeypatch) -> None:
    def tokens(on_reasoning):
        on_reasoning("only thinking")
        return
        yield  # pragma: no cover

    events, _ = _run_document_stream(monkeypatch, tokens)
    assert [e["text"] for e in events if e["type"] == "thinking"] == ["only thinking"]


def test_document_stream_does_not_block_event_loop(monkeypatch) -> None:
    def tokens(on_reasoning):
        for i in range(5):
            time.sleep(0.05)
            yield str(i)

    events, ticks = _run_document_stream(monkeypatch, tokens)
    assert "".join(e["text"] for e in events if e["type"] == "token") == "01234"
    assert ticks >= 5


# ── 2. filtered FTS with FTS5 operator characters ─────────────────────────


@pytest.mark.parametrize(
    "query",
    ["COVID-19 report", "revenue AND profit", "NOT", "foo -bar", "NEAR(a b)", 'he said "x'],
)
def test_fts_with_candidates_survives_fts5_operators(tmp_path: Path, query: str) -> None:
    from palimind.rag.retrieve import _fts_with_candidates
    from palimind.storage import db

    (tmp_path / ".palimind").mkdir()
    db.init_db(tmp_path)
    conn = db.get_connection(tmp_path)
    try:
        fid = db.upsert_file(conn, "doc.txt", "h", 0.0)
        db.insert_chunks(
            conn,
            fid,
            [(0, "text", "COVID-19 report: revenue and profit, NOT near foo bar said x")],
        )
        conn.commit()
        ids = {r[0] for r in conn.execute("SELECT id FROM chunks")}
        assert _fts_with_candidates(conn, query, ids, 5), query
        assert _fts_with_candidates(conn, query, set(), 5) == []
    finally:
        conn.close()


# ── local redirecting server for SSRF tests ───────────────────────────────

_FEED = (
    b'<?xml version="1.0"?><rss><channel><item><title>Hello</title>'
    b"<link>https://example.com/a</link></item></channel></rss>"
)


@pytest.fixture()
def redirect_server():
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            hits.append(self.path)
            if self.path.startswith("/redir-unsafe"):
                self.send_response(302)
                self.send_header("Location", "/secret")
                self.end_headers()
            elif self.path.startswith("/redir-safe"):
                self.send_response(301)
                self.send_header("Location", "/page-feed" if "feed" in self.path else "/page")
                self.end_headers()
            elif self.path.startswith("/secret"):
                body = b"<html><body>SECRET METADATA</body></html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/page"):
                body = _FEED if "feed" in self.path else b"<html><body>public page</body></html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    finally:
        srv.shutdown()
        srv.server_close()


def _allow_all_but_secret(url: str) -> bool:
    # Loopback is itself "unsafe": treat the test server as public except for
    # the /secret path, which stands in for an internal address.
    return "/secret" not in url


def _load_rss_tool():
    path = BACKEND / "palimind" / "agents" / "tools" / "rss-fetch" / "tool.py"
    spec = importlib.util.spec_from_file_location("_rss_fetch_tool_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 3. rss-fetch SSRF ─────────────────────────────────────────────────────


def test_rss_fetch_rejects_loopback_and_metadata() -> None:
    rss = _load_rss_tool()
    for url in ("http://127.0.0.1:1/feed", "http://169.254.169.254/latest", "http://10.0.0.1/"):
        assert rss.fetch_rss(url).startswith("Error: refusing"), url


def test_rss_fetch_rechecks_every_redirect_hop(monkeypatch, redirect_server) -> None:
    from palimind.core import web_search

    base, hits = redirect_server
    monkeypatch.setattr(web_search, "_is_safe_url", _allow_all_but_secret)
    rss = _load_rss_tool()

    out = rss.fetch_rss(f"{base}/redir-unsafe")
    assert out.startswith("Error: refusing")
    assert "/secret" not in hits

    # A redirect to an allowed URL is still followed.
    out = rss.fetch_rss(f"{base}/redir-safe-feed")
    assert json.loads(out)[0]["title"] == "Hello"


# ── 4. web_search scrapling primary path SSRF ─────────────────────────────


class _FakePage:
    def __init__(self, resp: httpx.Response):
        self.status = resp.status_code
        self.headers = dict(resp.headers)
        self.url = str(resp.url)
        self._text = resp.text

    def get_all_text(self) -> str:
        return self._text


def _install_fake_scrapling(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    class Fetcher:
        def get(self, url, **kwargs):
            calls.append(kwargs)
            # Mirror scrapling/curl_cffi: auto-follows redirects unless told not to.
            follow = bool(kwargs.get("follow_redirects", True))
            return _FakePage(httpx.get(url, follow_redirects=follow, timeout=5))

    mod = types.ModuleType("scrapling")
    mod.Fetcher = Fetcher
    monkeypatch.setitem(sys.modules, "scrapling", mod)
    return calls


def test_fetch_page_content_does_not_follow_redirect_to_unsafe(
    monkeypatch, redirect_server
) -> None:
    from palimind.core import web_search

    base, hits = redirect_server
    calls = _install_fake_scrapling(monkeypatch)
    monkeypatch.setattr(web_search, "_is_safe_url", _allow_all_but_secret)

    assert web_search._fetch_page_content(f"{base}/redir-unsafe") == ""
    assert "/secret" not in hits
    assert calls and all(c.get("follow_redirects") is False for c in calls)

    assert "public page" in web_search._fetch_page_content(f"{base}/redir-safe")


def test_is_safe_url_blocks_internal_targets() -> None:
    from palimind.core.web_search import _is_safe_url

    for url in (
        "http://127.0.0.1/",
        "http://localhost/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://192.168.1.1/",
    ):
        assert not _is_safe_url(url), url
    assert _is_safe_url("http://93.184.215.14/")
