from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class PendingTokens:
    """In-memory single-use token store for invite validation."""

    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, int]] = {}
        logger.debug("[TEAMS] PendingTokens created")

    def add(
        self,
        token: str,
        session_id: str,
        expiry: int | None = None,
        expiry_seconds: int | None = None,
    ) -> None:
        """Store a token against a session_id.

        Pass either ``expiry`` (absolute unix ts) or ``expiry_seconds``
        (seconds from now). Exactly one must be given.
        """
        if (expiry is None) == (expiry_seconds is None):
            raise ValueError("Pass exactly one of expiry or expiry_seconds")
        if expiry is None:
            expiry = int(time.time()) + int(expiry_seconds)
        logger.debug("[TEAMS] add token (session=%s)", session_id)
        self._tokens[token] = (session_id, int(expiry))

    def validate_and_consume(self, token: str) -> str | None:
        """Return the session_id if the token is valid, then delete it.

        Tokens are single-use: consuming deletes immediately. Expired or
        unknown tokens return None.
        """
        logger.debug("[TEAMS] validate_and_consume entry")
        entry = self._tokens.pop(token, None)
        if entry is None:
            logger.debug("[TEAMS] token not found or already consumed")
            return None
        session_id, expiry = entry
        if time.time() > expiry:
            logger.debug("[TEAMS] token expired")
            return None
        logger.debug("[TEAMS] token consumed -> session=%s", session_id)
        return session_id

    def cleanup_expired(self) -> int:
        """Drop expired tokens; returns the number removed."""
        now = time.time()
        expired = [t for t, (_, exp) in self._tokens.items() if now > exp]
        for t in expired:
            del self._tokens[t]
        if expired:
            logger.debug("[TEAMS] cleanup_expired removed %d", len(expired))
        return len(expired)

    def __len__(self) -> int:
        return len(self._tokens)


# Process-wide token store used by the teams API/websocket routes.
pending_tokens = PendingTokens()