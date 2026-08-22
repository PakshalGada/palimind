from __future__ import annotations

import logging

from core.teams.session import TeamSession

logger = logging.getLogger(__name__)


class TeamSessionManager:
    """Singleton holding all active shared sessions, keyed by session_id."""

    def __init__(self) -> None:
        self._sessions: dict[str, TeamSession] = {}

    def create_session(self, field_path: str) -> TeamSession:
        """Create and store a TeamSession for the given Palispace folder."""
        session_id = TeamSession.new_session_id()
        session = TeamSession(session_id=session_id, field_path=field_path)
        self._sessions[session_id] = session
        logger.debug("[TEAMS] session created (id=%s field=%s)", session_id, field_path)
        return session

    def get_session(self, session_id: str) -> TeamSession | None:
        return self._sessions.get(session_id)

    def end_session(self, session_id: str) -> None:
        """Fully tear down a shared session and all its guests."""
        removed = self._sessions.pop(session_id, None)
        if removed is None:
            logger.warning("[TEAMS] end_session: unknown id %s", session_id)
        else:
            logger.debug("[TEAMS] session ended (id=%s)", session_id)


_manager: TeamSessionManager | None = None


def get_manager() -> TeamSessionManager:
    """Return the process-wide TeamSessionManager singleton."""
    global _manager
    if _manager is None:
        _manager = TeamSessionManager()
        logger.debug("[TEAMS] TeamSessionManager singleton created")
    return _manager