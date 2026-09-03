from __future__ import annotations

from palimind.agents.service import (
    agent_sse,
    agent_sse_stream,
    stream_agent,
)

# Backward-compatible aliases — new code should import from
# palimind.agents.service directly.
agent_event_stream = stream_agent
agent_mode_stream = agent_sse_stream

__all__ = [
    "agent_event_stream",
    "agent_mode_stream",
    "agent_sse",
    "agent_sse_stream",
]
