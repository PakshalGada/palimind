"""Deterministic provider used by contract and lifecycle tests.

It never opens a socket and never runs a model.  Tests script the exact events
they need.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from palimind.agents.providers.base import (
    ProviderCapabilities,
    ProviderEvent,
    ProviderModel,
)


class FakeProvider:
    id = "fake"
    capabilities = ProviderCapabilities(
        tools=True,
        vision=False,
        reasoning=True,
        streaming=True,
        usage=True,
        accounts=False,
        attachments=True,
        concurrent_turns=True,
        steering=True,
        context_window=8192,
    )

    def __init__(self, *, events: list[ProviderEvent] | None = None) -> None:
        self.events = list(events or [])
        self.last_messages: list[dict[str, Any]] = []
        self.last_model = ""
        self.interrupted: list[str] = []
        self.closed = False
        self.sessions: set[str] = set()

    async def list_models(self) -> list[ProviderModel]:
        return [
            ProviderModel(
                id="fake-large",
                provider=self.id,
                name="Fake Large",
                capabilities=self.capabilities,
                effort_levels=("minimal", "standard", "high"),
                default_effort="standard",
            )
        ]

    async def start_session(
        self,
        thread_id: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        session_id = f"fake:{thread_id}"
        self.sessions.add(session_id)
        return session_id

    async def resume_session(
        self,
        thread_id: str,
        session_id: str,
        *,
        model: str = "",
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.sessions.add(session_id)
        return session_id

    async def send_turn(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        model: str = "",
        effort: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        self.last_messages = list(messages)
        self.last_model = model
        yield ProviderEvent("turn_started", {"session_id": session_id})
        for event in self.events:
            yield event
        if not self.events:
            yield ProviderEvent("message", {"text": "fake answer"})
        yield ProviderEvent("turn_completed", {"session_id": session_id})

    async def interrupt(self, session_id: str) -> None:
        self.interrupted.append(session_id)

    async def read_usage(self, session_id: str) -> dict[str, Any]:
        return {"prompt_tokens": 1, "completion_tokens": 1}

    async def close(self) -> None:
        self.closed = True
