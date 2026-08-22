from __future__ import annotations

import asyncio
import json

import httpx
import websockets

PORT = 8001
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"


async def host_side() -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE}/api/teams/create",
            json={"field_path": "/home/pakshal/Work/apple_data"},
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"[host] POST /api/teams/create -> {data}")
        return data["code"], data["session_id"]


async def guest_side(code: str, session_id: str) -> None:
    from core.teams.codes import decode_invite_code

    decoded = decode_invite_code(code)
    print(f"[guest] decoded invite: session_id={decoded['session_id']} host={decoded['host_ip']} port={decoded['port']}")
    token = decoded["token"]

    uri = f"{WS}/ws/team/{session_id}?token={token}"
    async with websockets.connect(uri) as ws:
        print(f"[guest] connected to {uri}")

        await ws.send(json.dumps({"type": "join", "display_name": "Alice", "permission": "query"}))
        joined = json.loads(await ws.recv())
        print(f"[guest] join reply -> {joined}")

        await ws.send(json.dumps({"type": "query", "text": "What is in this folder?"}))
        while True:
            msg = json.loads(await ws.recv())
            print(f"[guest] <- {msg}")
            if msg.get("type") == "stream_end":
                break

        await ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await ws.recv())
        print(f"[guest] ping reply -> {pong}")

        # join a second time is not required; confirm a non-join query path by skipping.
        assert joined["type"] == "joined"
        assert joined["permission"] == "query"
        print("\nALL PHASE 3 CHECKS PASSED")


async def main() -> None:
    code, session_id = await host_side()
    await guest_side(code, session_id)


if __name__ == "__main__":
    asyncio.run(main())