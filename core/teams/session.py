from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Permissions a guest can hold. "view" guests may watch; "query" guests may
# also send chat queries. ("agent" permission is reserved for a later phase.)
ALLOWED_PERMISSIONS = ("view", "query")

# Sliding window (seconds) used by the per-guest query rate limiter.
RATE_LIMIT_WINDOW = 60


@dataclass
class GuestConnection:
    token: str
    display_name: str
    permission: str = "view"
    websocket: object | None = None  # starlette WebSocket; None until attached
    connected_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    query_count: int = 0
    query_timestamps: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.permission not in ALLOWED_PERMISSIONS:
            raise ValueError(
                f"permission must be one of {ALLOWED_PERMISSIONS}, got {self.permission!r}"
            )
        logger.debug(
            "[TEAMS] GuestConnection created (token=%s name=%s perm=%s)",
            self.token, self.display_name, self.permission,
        )

    def touch(self) -> None:
        """Mark the guest as active right now."""
        self.last_active = time.time()

    def check_rate(self, max_per_minute: int) -> bool:
        """Rate-limit check: record a query if under the limit.

        Returns True if the query is allowed (and recorded), False if the
        guest has already sent ``max_per_minute`` queries in the last 60s.
        """
        now = time.time()
        self.query_timestamps = [
            t for t in self.query_timestamps if now - t < RATE_LIMIT_WINDOW
        ]
        if len(self.query_timestamps) >= max_per_minute:
            logger.debug("[TEAMS] rate limited (token=%s)", self.token)
            return False
        self.query_timestamps.append(now)
        return True


@dataclass
class TeamSession:
    session_id: str
    field_path: str
    created_at: float = field(default_factory=time.time)
    guests: dict[str, GuestConnection] = field(default_factory=dict)
    message_history: list[dict] = field(default_factory=list)
    _inference_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def add_guest(
        self, token: str, display_name: str, permission: str = "view"
    ) -> GuestConnection:
        """Add a guest (defaults to "view" permission) and return it."""
        guest = GuestConnection(token=token, display_name=display_name, permission=permission)
        self.guests[token] = guest
        logger.debug("[TEAMS] guest added (session=%s token=%s)", self.session_id, token)
        return guest

    def remove_guest(self, token: str) -> None:
        removed = self.guests.pop(token, None)
        if removed is None:
            logger.warning(
                "[TEAMS] remove_guest: unknown token %s (session=%s)",
                token, self.session_id,
            )
        else:
            logger.debug("[TEAMS] guest removed (session=%s token=%s)", self.session_id, token)

    def get_guest(self, token: str) -> GuestConnection | None:
        return self.guests.get(token)

    def append_message(self, sender_type: str, sender_name: str, content: str) -> dict:
        """Record a chat message. sender_type is "host" or "guest"."""
        if sender_type not in ("host", "guest"):
            raise ValueError(f"sender_type must be 'host' or 'guest', got {sender_type!r}")
        entry = {
            "sender_type": sender_type,
            "sender_name": sender_name,
            "content": content,
            "timestamp": time.time(),
        }
        self.message_history.append(entry)
        logger.debug(
            "[TEAMS] message appended (session=%s from=%s)", self.session_id, sender_type
        )
        return entry

    def touch_guest(self, token: str) -> None:
        guest = self.get_guest(token)
        if guest is not None:
            guest.touch()

    def new_session_id() -> str:
        """Generate a unique session id for a shared Palispace."""
        return str(uuid.uuid4())