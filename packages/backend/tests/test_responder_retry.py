"""Tests for resilient streaming in palimind.generative.responder.

No network / no Ollama: a local HTTP server simulates a model backend whose
streaming endpoint drops the chunked body mid-response ("peer closed connection
without sending complete message body"), the failure the retry/fallback logic
is built for.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from palimind.generative.responder import generate_response_stream


class _AbortStreamHandler(BaseHTTPRequestHandler):
    """Streaming requests always abort mid-chunk; non-streaming succeed."""

    protocol_version = "HTTP/1.1"
    streaming_requests = 0  # shared counter across handler instances

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length)
        req = json.loads(body)

        if req.get("stream"):
            type(self).streaming_requests += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            # Promise a 16-byte chunk but send nothing, then drop the socket:
            # the client sees an incomplete chunked read.
            try:
                self.wfile.write(b"10\r\n")
                self.wfile.flush()
            except OSError:
                pass
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return

        content = "complete non-streaming answer"
        payload = json.dumps(
            {"message": {"role": "assistant", "content": content}, "done": True}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def log_message(self, *args: object) -> None:
        pass


def test_stream_abort_recovers_via_non_streaming_fallback() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AbortStreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _AbortStreamHandler.streaming_requests = 0
    port = server.server_address[1]
    try:
        tokens = list(
            generate_response_stream(
                query="hello",
                context="",
                image_paths=[],
                ollama_url=f"http://127.0.0.1:{port}",
                chat_model="test-model",
                system_prompt="",
                is_chat_only=True,
            )
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    # 1 initial + 2 retries (default PALIMIND_LLM_RETRIES), then the fallback.
    assert _AbortStreamHandler.streaming_requests == 3
    assert "".join(tokens) == "complete non-streaming answer"
