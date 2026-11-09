"""Normalized provider boundary for agent harnesses.

A provider adapter owns one process or wire protocol (Ollama, OpenCode, ACP,
Codex, Claude, an OpenAI-compatible endpoint, ...).  It converts native traffic
into the small event set defined here.  The agent runtime then applies PaliMind
policy: approvals, tool routing, sandboxing, task limits, hold reasons, secret
redaction and persistence.

The protocol is intentionally narrow.  It is a contract for adapters, not a
second agent loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """A provider failure with a stable classification for failover policy."""

    CAUSES = (
        "billing",
        "provider_unavailable",
        "rate_limit",
        "authentication",
        "network",
        "timeout",
        "protocol",
        "unknown",
    )

    def __init__(self, message: str, *, cause: str = "unknown", retryable: bool = False):
        super().__init__(message)
        self.cause = cause if cause in self.CAUSES else "unknown"
        self.retryable = bool(retryable)


@dataclass(frozen=True)
class ProviderCapabilities:
    """What a provider can do.  Unknown values stay conservative."""

    tools: bool = False
    vision: bool = False
    reasoning: bool = False
    streaming: bool = True
    usage: bool = False
    accounts: bool = False
    attachments: bool = False
    concurrent_turns: bool = False
    steering: bool = False
    context_window: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tools": self.tools,
            "vision": self.vision,
            "reasoning": self.reasoning,
            "streaming": self.streaming,
            "usage": self.usage,
            "accounts": self.accounts,
            "attachments": self.attachments,
            "concurrent_turns": self.concurrent_turns,
            "steering": self.steering,
            "context_window": self.context_window,
        }


@dataclass(frozen=True)
class ProviderModel:
    """One model in a provider catalog."""

    id: str
    provider: str
    name: str = ""
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    effort_levels: tuple[str, ...] = ()
    default_effort: str = ""
    free: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "name": self.name or self.id,
            "capabilities": self.capabilities.as_dict(),
            "effort_levels": list(self.effort_levels),
            "default_effort": self.default_effort,
            "free": self.free,
            "metadata": dict(self.metadata),
        }


@dataclass
class ProviderEvent:
    """A normalized event emitted while a turn runs.

    ``type`` is one of ``turn_started``, ``message_delta``, ``message``,
    ``thought``, ``tool_call``, ``tool_result``, ``question``, ``approval``,
    ``usage``, ``error`` and ``turn_completed``.
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.payload}


@runtime_checkable
class ProviderClient(Protocol):
    """The one interface every provider adapter implements."""

    id: str
    capabilities: ProviderCapabilities

    async def list_models(self) -> list[ProviderModel]: ...

    async def start_session(
        self,
        thread_id: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str: ...

    async def resume_session(
        self,
        thread_id: str,
        session_id: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str: ...

    def send_turn(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        model: str = "",
        effort: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]: ...

    async def interrupt(self, session_id: str) -> None: ...

    async def read_usage(self, session_id: str) -> dict[str, Any]: ...

    async def close(self) -> None: ...
