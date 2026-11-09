#!/usr/bin/env python3
"""Deterministic ACP fixture server for tests.

It speaks JSON-RPC 2.0 over stdio with Content-Length framing.  No model, no
network, no provider CLI.
"""

from __future__ import annotations

import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, _, value = line.decode("ascii", "replace").partition(":")
        headers[name.strip().lower()] = value.strip()
    try:
        length = int(headers.get("content-length", "0"))
    except ValueError:
        return None
    body = sys.stdin.buffer.read(length)
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def write_message(message):
    body = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()


def respond(request_id, result):
    write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def notify(update):
    write_message({"jsonrpc": "2.0", "method": "session/update", "params": {"update": update}})


def main() -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            respond(request_id, {"protocolVersion": 1, "serverInfo": {"name": "fixture"}})
        elif method == "models/list":
            respond(
                request_id,
                {
                    "models": [
                        {
                            "id": "fixture-1",
                            "name": "Fixture One",
                            "effortLevels": ["minimal", "standard", "high"],
                            "defaultEffort": "standard",
                        }
                    ]
                },
            )
        elif method == "session/new":
            respond(request_id, {"sessionId": "sess-1"})
        elif method == "session/load":
            respond(request_id, {"sessionId": message.get("params", {}).get("sessionId", "sess-1")})
        elif method == "session/prompt":
            notify({"sessionUpdate": "agent_message_chunk", "content": "hello "})
            notify({"sessionUpdate": "agent_message_chunk", "content": "world"})
            notify(
                {
                    "sessionUpdate": "tool_call",
                    "toolCallId": "call-1",
                    "title": "read_file",
                    "rawInput": {"path": "a.txt"},
                }
            )
            notify(
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call-1",
                    "status": "completed",
                    "content": "file text",
                }
            )
            notify(
                {
                    "sessionUpdate": "usage_update",
                    "usage": {"inputTokens": 7, "outputTokens": 3},
                }
            )
            respond(request_id, {"stopReason": "end_turn"})
        elif method == "session/cancel":
            respond(request_id, {})
        elif request_id is not None:
            respond(request_id, {})
        else:
            # Ignore unknown notifications.
            pass


if __name__ == "__main__":
    raise SystemExit(main())
