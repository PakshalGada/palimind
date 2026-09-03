"""Stable session id for OpenCode Go upstream requests.

OpenCode Go requires every upstream request to carry an
``x-opencode-session`` header with a stable id so it can correlate the
requests of one conversation. The app is local-first and the proxy is
stateless, so we default to one stable id per process (overridable via
``OPENCODE_SESSION_ID``). Callers that want per-conversation ids may pass
their own ``x-opencode-session`` value through the proxy, which forwards it
upstream instead of the process default.
"""

from __future__ import annotations

import os
import uuid

SESSION_HEADER = "x-opencode-session"

_session_id: str | None = None


def opencode_session_id() -> str:
    """Return the stable session id for this process.

    The env override is checked on every call so tests and deployments can
    pin a deterministic value without restarting.
    """
    global _session_id
    override = os.environ.get("OPENCODE_SESSION_ID")
    if override:
        return override
    if _session_id is None:
        _session_id = uuid.uuid4().hex
    return _session_id
