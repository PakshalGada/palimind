#!/usr/bin/env python3
"""Deterministic Claude stream-json transcript fixture.

It reads user/control messages as newline JSON and emits the assistant, tool,
usage and result records that the real CLI emits. No model is used.
"""

from __future__ import annotations

import json
import sys


def write(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> int:
    write(
        {"type": "system", "subtype": "init", "session_id": "session-1", "model": "fixture-claude"}
    )
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        if message.get("type") == "control_request":
            write(
                {
                    "type": "control_response",
                    "request_id": message.get("request_id"),
                    "response": {"subtype": "success"},
                }
            )
            continue
        if message.get("type") != "user":
            continue
        write(
            {
                "type": "assistant",
                "session_id": "session-1",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "hello world"},
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Read",
                            "input": {"file_path": "a.txt"},
                        },
                    ],
                    "usage": {"input_tokens": 9, "output_tokens": 4},
                },
            }
        )
        write(
            {
                "type": "user",
                "session_id": "session-1",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "content": [{"type": "text", "text": "file text"}],
                        }
                    ],
                },
            }
        )
        write(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "session-1",
                "result": "hello world",
                "usage": {"input_tokens": 9, "output_tokens": 4},
            }
        )


if __name__ == "__main__":
    raise SystemExit(main())
