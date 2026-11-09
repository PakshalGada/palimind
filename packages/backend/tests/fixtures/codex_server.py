#!/usr/bin/env python3
"""Deterministic Codex App Server transcript fixture.

Newline-delimited JSON. No model, network, or Codex install is used.
"""

from __future__ import annotations

import json
import sys

NEXT_ID = 0


def read_message():
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        value = json.loads(line)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def write(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def result(request_id, value):
    write({"jsonrpc": "2.0", "id": request_id, "result": value})


def notify(method, params):
    write({"jsonrpc": "2.0", "method": method, "params": params})


def main() -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            result(request_id, {})
        elif method == "initialized":
            continue
        elif method == "model/list":
            result(
                request_id, {"data": [{"model": "fixture-codex", "displayName": "Fixture Codex"}]}
            )
        elif method == "thread/start":
            result(request_id, {"thread": {"id": "thread-1", "turns": []}})
        elif method == "thread/resume":
            result(
                request_id,
                {"thread": {"id": message.get("params", {}).get("threadId", "thread-1")}},
            )
        elif method == "turn/start":
            result(request_id, {"turn": {"id": "turn-1", "status": "inProgress"}})
            notify(
                "turn/started",
                {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "inProgress"}},
            )
            notify(
                "item/started",
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {"id": "item-1", "type": "agentMessage"},
                },
            )
            notify(
                "item/agentMessage/delta",
                {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "hello "},
            )
            notify(
                "item/agentMessage/delta",
                {"threadId": "thread-1", "turnId": "turn-1", "itemId": "item-1", "delta": "world"},
            )
            notify(
                "item/completed",
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {"id": "item-1", "type": "agentMessage", "text": "hello world"},
                },
            )
            notify(
                "item/started",
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {"id": "item-2", "type": "commandExecution", "command": "echo ok"},
                },
            )
            notify(
                "item/completed",
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {
                        "id": "item-2",
                        "type": "commandExecution",
                        "status": "completed",
                        "aggregatedOutput": "ok",
                    },
                },
            )
            notify(
                "thread/tokenUsage/updated",
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "tokenUsage": {"total": {"inputTokens": 12, "outputTokens": 5}},
                },
            )
            notify(
                "turn/completed",
                {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
            )
        elif method == "turn/interrupt":
            result(request_id, {})
        elif request_id is not None:
            result(request_id, {})


if __name__ == "__main__":
    raise SystemExit(main())
