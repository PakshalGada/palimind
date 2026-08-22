from __future__ import annotations

import asyncio
import json

import httpx
import websockets

HOST = "127.0.0.1"
Q = "Apple fiscal year 2024 ended on what date?"


async def create_session(port: int, field: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"http://{HOST}:{port}/api/teams/create", json={"field_path": field})
        r.raise_for_status()
        d = r.json()
    from core.teams.codes import decode_invite_code
    return d["session_id"], decode_invite_code(d["code"])["token"]


async def connect(port: int, sid: str, token: str, name: str, permission: str = "query"):
    uri = f"ws://{HOST}:{port}/ws/team/{sid}?token={token}"
    ws = await websockets.connect(uri)
    await ws.send(json.dumps({"type": "join", "display_name": name, "permission": permission}))
    joined = json.loads(await ws.recv())
    return ws, joined


async def send_query(ws, text: str) -> str:
    await ws.send(json.dumps({"type": "query", "text": text}))
    full = ""
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("type") == "error":
            return f"ERROR: {msg['message']}"
        if msg.get("type") == "stream_chunk":
            full += msg.get("text", "")
        elif msg.get("type") == "stream_end":
            return full


async def test_multiguest_and_kick(port: int = 8001) -> None:
    print("=== MULTI-GUEST + KICK (port 8001) ===")
    sid, tok_a = await create_session(port, "/home/pakshal/Work/apple_data")
    ws_a, joined_a = await connect(port, sid, tok_a, "Alice")
    print(f"Alice joined: {joined_a}")

    # second invite for the SAME session via /api/teams/{id}/invite
    from core.teams.codes import decode_invite_code
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"http://{HOST}:{port}/api/teams/{sid}/invite")
        r.raise_for_status()
        d = r.json()
    tok_b = decode_invite_code(d["code"])["token"]
    ws_b, joined_b = await connect(port, sid, tok_b, "Bob")
    print(f"Bob joined same session: {joined_b}")
    assert joined_b["field_name"] == "/home/pakshal/Work/apple_data"

    # near-simultaneous queries from both guests — should serialize (lock)
    ans_a, ans_b = await asyncio.gather(
        send_query(ws_a, Q),
        send_query(ws_b, Q),
    )
    print(f"Alice answer (first 90): {ans_a[:90]!r}")
    print(f"Bob answer (first 90):   {ans_b[:90]!r}")
    assert "September 28, 2024" in ans_a
    assert "September 28, 2024" in ans_b
    print("Both guests got correct sequential answers.")

    # guest list should show both
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"http://{HOST}:{port}/api/teams/{sid}/guests")
        d = r.json()
    names = {g["display_name"] for g in d["guests"]}
    print(f"Guest list: {d['guests']}")
    assert "Alice" in names and "Bob" in names

    # kick Alice from the host side
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"http://{HOST}:{port}/api/teams/{sid}/kick/{tok_a}")
        print(f"Kick Alice -> {r.json()}")

    kicked = await asyncio.wait_for(ws_a.recv(), timeout=5)
    print(f"Alice received: {kicked}")
    assert json.loads(kicked)["type"] == "kicked"

    # Alice should be disconnected now; Bob still alive
    try:
        await ws_a.recv()
        alice_gone = False
    except websockets.exceptions.ConnectionClosed:
        alice_gone = True
    assert alice_gone, "Alice's websocket should be closed after kick"
    print("Alice disconnected after kick.")

    await ws_b.send(json.dumps({"type": "ping"}))
    pong = json.loads(await ws_b.recv())
    print(f"Bob ping after Alice kick -> {pong}")
    assert pong["type"] == "pong"
    print("Bob unaffected after kick.\n")


async def test_rate_limit(port: int = 8003) -> None:
    print("=== RATE LIMIT (port 8003, max 1/min) ===")
    sid, tok = await create_session(port, "/home/pakshal/Work/apple_data")
    ws, joined = await connect(port, sid, tok, "Speedy")
    print(f"joined: {joined}")

    a1 = await send_query(ws, Q)
    print(f"Query 1 (allowed): {a1[:70]!r}...")
    a2 = await send_query(ws, Q)
    print(f"Query 2: {a2[:100]!r}")
    assert a2.startswith("ERROR"), "2nd query must be rejected"
    assert "per minute" in a2
    print("Rate limit enforced: 2nd query rejected with clear error.\n")


async def main() -> None:
    await test_multiguest_and_kick(8001)
    await test_rate_limit(8003)
    print("ALL PHASE 6 CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())