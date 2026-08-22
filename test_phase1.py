from __future__ import annotations

import time

from core.teams.codes import decode_invite_code, generate_invite_code
from core.teams.network import get_lan_ip
from core.teams.pending_tokens import PendingTokens


def main() -> None:
    ip = get_lan_ip()
    print(f"LAN IP: {ip}")
    assert ip and not ip.startswith("127."), "expected a real LAN IP"

    code, token = generate_invite_code("sess-123", ip, 8000, expiry_seconds=900)
    print(f"Generated code: {code}")
    print(f"Raw token:      {token}")
    assert code.startswith("PALI-"), "code must carry PALI- prefix"
    assert len(token) == 32, "token must be 32 hex chars (16 bytes)"

    decoded = decode_invite_code(code)
    print(f"Decoded payload: {decoded}")
    assert decoded["session_id"] == "sess-123"
    assert decoded["host_ip"] == ip
    assert decoded["port"] == 8000
    assert decoded["token"] == token
    print("Round-trip OK: code decodes back to the original payload\n")

    # Expired code must raise
    code_exp, _ = generate_invite_code("sess-exp", ip, 8000, expiry_seconds=-1)
    try:
        decode_invite_code(code_exp)
        raise AssertionError("expected ValueError for expired code")
    except ValueError as e:
        print(f"Expired code correctly rejected: {e}\n")

    # Malformed code must raise
    try:
        decode_invite_code("PALI-%%%%not-base64")
        raise AssertionError("expected ValueError for malformed code")
    except ValueError as e:
        print(f"Malformed code correctly rejected: {e}\n")

    # Single-use enforcement
    store = PendingTokens()
    store.add(token, "sess-123", int(time.time()) + 900)
    first = store.validate_and_consume(token)
    second = store.validate_and_consume(token)
    print(f"First consume -> {first!r}")
    print(f"Second consume -> {second!r}")
    assert first == "sess-123", "first consume must return session_id"
    assert second is None, "second consume must be None (single use)"
    print("Single-use enforcement OK: token consumed once, rejected after\n")

    # Expired token in store must be rejected
    code3, token3 = generate_invite_code("sess-3", ip, 8000)
    store.add(token3, "sess-3", int(time.time()) - 5)
    res = store.validate_and_consume(token3)
    assert res is None, "expired stored token must be rejected"
    print("Expired stored token rejected OK")

    # cleanup_expired
    code4, token4 = generate_invite_code("sess-4", ip, 8000)
    store.add(token4, "sess-4", int(time.time()) + 300)
    removed = store.cleanup_expired()
    print(f"cleanup_expired removed {removed} token(s); store size {len(store)}")
    print("\nALL PHASE 1 CHECKS PASSED")


if __name__ == "__main__":
    main()