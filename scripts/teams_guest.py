#!/usr/bin/env python3
"""Paliteams guest client — run this on a SECOND device on the same WiFi/LAN.

Usage:
    python teams_guest.py <PALI-...invite-code>

Requirements: Python 3.10+ and the `websockets` package (pip install websockets).
No other Palimind code is needed; the invite code carries everything.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys

try:
    import websockets
except ImportError:
    print("Missing dependency: run `pip install websockets` first")
    sys.exit(1)

PREFIX = "PALI-"


def decode_invite_code(code: str) -> dict:
    if not code.startswith(PREFIX):
        raise ValueError("Invite code must start with 'PALI-'")
    raw = code[len(PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Malformed invite code: {e}") from e
    return data


async def main(code: str, query: str) -> None:
    payload = decode_invite_code(code)
    host, port, token = payload["host_ip"], payload["port"], payload["token"]
    uri = f"ws://{host}:{port}/ws/team/{payload['session_id']}?token={token}"
    print(f"Connecting to {uri}")

    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "join", "display_name": "LAN-Guest", "permission": "query"}))
        joined = json.loads(await ws.recv())
        print("join reply ->", joined)

        await ws.send(json.dumps({"type": "query", "text": query}))
        print(f"query -> {query}")
        while True:
            msg = json.loads(await ws.recv())
            print("<-", msg)
            if msg.get("type") == "stream_end":
                break
    print("\nLAN ROUND-TRIP OK")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    code = sys.argv[1]
    query = " ".join(sys.argv[2:]) or "What can you tell me about this field?"
    asyncio.run(main(code, query))