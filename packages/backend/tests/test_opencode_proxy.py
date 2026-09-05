"""Regression tests for the OpenCode proxy.

No network: the proxy's upstream (BASE_URL) is pointed at a local fake
OpenAI-compatible server, and the proxy app is driven via httpx ASGITransport.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from palimind import opencode_proxy
from palimind.opencode_proxy import app


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/models":
            payload = json.dumps({"data": [{"id": "zen-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length)
        req = json.loads(body)

        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            events = [
                {"choices": [{"delta": {"content": "hello"}}]},
                {"choices": [{"delta": {"content": " world"}}]},
                "[DONE]",
            ]
            for ev in events:
                payload = ev if isinstance(ev, str) else json.dumps(ev)
                line = f"data: {payload}\n\n".encode()
                self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return

        content = "non-streaming reply"
        payload = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": content}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def fake_upstream(monkeypatch: pytest.MonkeyPatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        opencode_proxy,
        "BASE_URL",
        f"http://127.0.0.1:{server.server_address[1]}",
    )
    yield
    server.shutdown()
    thread.join(timeout=5)


def _post(transport: httpx.ASGITransport, path: str, payload: dict) -> httpx.Response:
    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=payload)

    return asyncio.run(run())


def test_proxy_chat_non_streaming_uses_request_headers(fake_upstream) -> None:
    transport = httpx.ASGITransport(app=app)
    resp = _post(
        transport,
        "/api/chat",
        {"model": "zen-model", "messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["done"] is True
    assert data["message"]["content"] == "non-streaming reply"


def test_proxy_chat_streaming_converts_sse_to_ndjson(fake_upstream) -> None:
    transport = httpx.ASGITransport(app=app)
    resp = _post(
        transport,
        "/api/chat",
        {
            "model": "zen-model",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert resp.status_code == 200, resp.text
    lines = [ln for ln in resp.text.splitlines() if ln.strip()]
    contents = [
        json.loads(ln)["message"]["content"] for ln in lines if json.loads(ln).get("message")
    ]
    assert "".join(contents) == "hello world"
    assert json.loads(lines[-1])["done"] is True
