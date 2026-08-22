from __future__ import annotations

import base64
import json
import logging
import secrets
import time

logger = logging.getLogger(__name__)

PREFIX = "PALI-"
DEFAULT_EXPIRY_SECONDS = 900


def generate_invite_code(
    session_id: str,
    host_ip: str,
    port: int,
    expiry_seconds: int = DEFAULT_EXPIRY_SECONDS,
) -> tuple[str, str]:
    """Build a one-time invite code.

    Returns (code, token) where ``code`` is the shareable PALI- prefixed
    string the guest types in, and ``token`` is the raw hex secret that must
    be stored server-side for validation.
    """
    logger.debug("[TEAMS] generate_invite_code entry (session=%s ip=%s)", session_id, host_ip)
    token = secrets.token_hex(16)
    payload = {
        "session_id": session_id,
        "host_ip": host_ip,
        "port": int(port),
        "token": token,
        "expires": int(time.time()) + int(expiry_seconds),
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    code = PREFIX + raw
    logger.debug("[TEAMS] generate_invite_code -> code len=%d", len(code))
    return code, token


def decode_invite_code(code: str) -> dict:
    """Reverse ``generate_invite_code``.

    Raises ValueError if the code is malformed, expired, or missing fields.
    """
    logger.debug("[TEAMS] decode_invite_code entry")
    if not isinstance(code, str) or not code.startswith(PREFIX):
        raise ValueError("Invite code must start with 'PALI-'")
    raw = code[len(PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Malformed invite code: {e}") from e

    required = {"session_id", "host_ip", "port", "token", "expires"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Invite code missing fields: {sorted(missing)}")

    if time.time() > int(data["expires"]):
        raise ValueError("Invite code has expired")

    logger.debug("[TEAMS] decode_invite_code -> session=%s", data.get("session_id"))
    return data