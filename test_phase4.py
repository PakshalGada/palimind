from __future__ import annotations

import asyncio
import json
import sys

import httpx
import websockets

HOST_IP = sys.argv[1] if len(sys.argv) > 1 else "172.22.218.202"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
BASE = f"http://{HOST_IP}:{PORT}"
WS = f"ws://{HOST_IP}:{PORT}"


async def main() -> None:
    from core.teams.codes import decode_invite_code

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BASE}/api/teams/create", json={"field_path": "/home/pakshal/Work/apple_data"})
        resp.raise_for_status()
        data = resp.json()
    print(f"[host] invite code: {data['code'][:40]}...")
    print(f"[host] session_id:  {data['session_id']}")

    decoded = decode_invite_code(data["code"])
    print(f"[guest] decoded -> session={decoded['session_id']} host={decoded['host_ip']} port={decoded['port']}")
    token = decoded["token"]

    uri = f"{WS}/ws/team/{decoded['session_id']}?token={token}"
    print(f"[guest] connecting to {uri}")
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "join", "display_name": "LAN-Guest", "permission": "query"}))
        joined = json.loads(await ws.recv())
        print(f"[guest] join reply -> {joined}")

        await ws.send(json.dumps({"type": "query", "text": "Hello from across the LAN"}))
        while True:
            msg = json.loads(await ws.recv())
            print(f"[guest] <- {msg}")
            if msg.get("type") == "stream_end":
                break
    print("\nLAN ROUND-TRIP OK")


if __name__ == "__main__":
    asyncio.run(main())