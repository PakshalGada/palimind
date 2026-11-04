"""Regression tests for security fixes in auth, agent tools and the proxy."""

from __future__ import annotations

from pathlib import Path


def test_auth_middleware_rejects_dns_rebinding_host(monkeypatch) -> None:
    """A loopback socket with a foreign Host header is a DNS-rebinding page:
    it must neither receive the UI cookie nor reach the API."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from palimind.security import auth as auth_mod

    monkeypatch.setattr(auth_mod, "auth_disabled", lambda: False)
    monkeypatch.setattr(auth_mod, "allow_remote", lambda: False)

    app = FastAPI()

    @app.get("/api/secret")
    async def secret() -> dict:
        return {"ok": True}

    @app.get("/ui")
    async def ui() -> dict:
        return {"ui": True}

    auth_mod.install_auth(app, token_provider=lambda: "test-token", cookie_path_prefix="/ui")
    client = TestClient(app, client=("127.0.0.1", 50000))

    evil = {"Host": "evil.example:8000"}
    ui_response = client.get("/ui", headers=evil)
    assert ui_response.status_code == 403
    assert "palimind_token" not in ui_response.headers.get("set-cookie", "")
    assert client.get("/api/secret", headers=evil).status_code == 403

    for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000", "localhost"):
        resp = client.get(
            "/api/secret", headers={"Host": host, "Authorization": "Bearer test-token"}
        )
        assert resp.status_code == 200, host
    assert "palimind_token" in client.get("/ui", headers={"Host": "127.0.0.1:8000"}).headers.get(
        "set-cookie", ""
    )


def test_csv_query_rejects_code_execution(tmp_path: Path) -> None:
    from palimind.llm.mixture_of_expert.tools import (
        TOOL_REGISTRY,
        _register_plugin_tools,
        set_tool_context,
    )

    _register_plugin_tools()
    csv_query = TOOL_REGISTRY["csv_query"]["fn"]
    (tmp_path / "t.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    marker = tmp_path / "pwned"
    set_tool_context(tmp_path)
    try:
        for query in (
            f"@pd.io.common.os.system('touch {marker}') >= 0",
            f"a.to_csv('{marker}') == 0",
            "a.__class__ == 0",
            "a @ b",
        ):
            out = csv_query("t.csv", query)
            assert out.startswith("Error"), (query, out)
        assert not marker.exists()
        assert '"a": 3' in csv_query("t.csv", "a > 1")
    finally:
        set_tool_context(None)


def test_proxy_stream_reports_upstream_auth_rejection(monkeypatch) -> None:
    """A 401 from upstream while streaming must arrive as an NDJSON error line,
    not as an aborted body (which clients treat as a transient drop)."""
    import asyncio
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpx

    from palimind import opencode_proxy

    class _Reject(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            body = json.dumps({"error": {"message": "invalid api key"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Reject)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(opencode_proxy, "BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")

    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=opencode_proxy.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/chat",
                json={
                    "model": "m",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            )

    try:
        resp = asyncio.run(run())
    finally:
        server.shutdown()
        thread.join(timeout=5)
    lines = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert lines and "401" in lines[0]["error"] and "invalid api key" in lines[0]["error"]


def test_browser_guard_refuses_redirect_to_loopback() -> None:
    import pytest

    from palimind.agents.tools.browser import tool as bt

    class _Page:
        def __init__(self) -> None:
            self.url = "about:blank"

        def goto(self, url: str, **_: object) -> None:
            # Simulate an external URL that 302-redirects to a local service.
            self.url = "http://127.0.0.1:11434/api/tags" if url != "about:blank" else url

        def title(self) -> str:
            return "t"

        def inner_text(self, _sel: str) -> str:
            return "secret local data"

    worker = object.__new__(bt._BrowserWorker)
    worker._page = _Page()
    with pytest.raises(PermissionError):
        worker.op_goto("http://93.184.216.34/", "domcontentloaded")
    assert worker._page.url == "about:blank"

    worker._page.url = "http://127.0.0.1:8000/api/fs/list"  # e.g. JS navigation
    with pytest.raises(PermissionError):
        worker.op_extract(100)


def test_media_stream_range_edge_cases(monkeypatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    (tmp_path / "a.mp3").write_bytes(bytes(range(100)))
    monkeypatch.setattr(server.state, "active_field", tmp_path)
    client = TestClient(server.app)

    resp = client.get("/api/media/stream?path=a.mp3", headers={"Range": "bytes=500-"})
    assert resp.status_code == 416
    assert resp.headers["content-range"] == "bytes */100"

    resp = client.get("/api/media/stream?path=a.mp3", headers={"Range": "bytes=-10"})
    assert resp.status_code == 206
    assert resp.content == bytes(range(90, 100))
    assert resp.headers["content-range"] == "bytes 90-99/100"

    resp = client.get("/api/media/stream?path=a.mp3", headers={"Range": "bytes=10-19"})
    assert resp.status_code == 206 and resp.content == bytes(range(10, 20))


def test_sandbox_handles_binary_and_unbounded_output(tmp_path: Path) -> None:
    import pytest

    from palimind.security.sandbox import bwrap_path, run_shell_isolated

    if not bwrap_path():
        pytest.skip("bubblewrap is not installed")
    # Non-UTF-8 bytes used to raise UnicodeDecodeError out of the tool.
    assert "abc" in run_shell_isolated(r"printf '\377\376abc'", root=tmp_path)
    # Unbounded output is capped by the child's file-size limit instead of
    # being buffered in the server's memory until the timeout.
    out = run_shell_isolated("yes", root=tmp_path, timeout_s=20)
    assert out.startswith("Error") and len(out) < 10_000
    # stdin is closed: `cat` must not block on the server's stdin.
    assert "timed out" not in run_shell_isolated("cat", root=tmp_path, timeout_s=5)
