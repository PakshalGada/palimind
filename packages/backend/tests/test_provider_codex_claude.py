"""Codex App Server and Claude stream-json transcript tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from palimind.agents.providers.claude import ClaudeProvider
from palimind.agents.providers.codex import CodexProvider

FIXTURES = Path(__file__).parent / "fixtures"


def test_codex_transcript_maps_items_and_usage() -> None:
    async def run():
        provider = CodexProvider(
            command=sys.executable,
            args=[str(FIXTURES / "codex_server.py")],
            request_timeout=10.0,
        )
        try:
            models = await provider.list_models()
            assert [m.id for m in models] == ["fixture-codex"]
            session = await provider.start_session("thread-key", model="fixture-codex")
            assert session == "thread-1"
            events = [
                event
                async for event in provider.send_turn(
                    session,
                    [{"role": "user", "content": "hi"}],
                    model="fixture-codex",
                    effort="medium",
                )
            ]
            types = [event.type for event in events]
            assert types[0] == "turn_started"
            deltas = [e.payload["text"] for e in events if e.type == "message_delta"]
            assert deltas == ["hello ", "world"]
            assert any(e.type == "message" and e.payload["text"] == "hello world" for e in events)
            assert any(e.type == "tool_call" and e.payload["name"] == "commandExecution" for e in events)
            assert any(e.type == "tool_result" and e.payload["content"] == "ok" for e in events)
            assert any(e.type == "usage" and e.payload["prompt_tokens"] == 12 for e in events)
            assert types[-1] == "turn_completed"
            await provider.interrupt(session)
        finally:
            await provider.close()

    asyncio.run(run())


def test_claude_transcript_maps_text_tool_and_result() -> None:
    async def run():
        provider = ClaudeProvider(
            command=sys.executable,
            args=[str(FIXTURES / "claude_server.py")],
            request_timeout=10.0,
        )
        try:
            session = await provider.start_session("thread-key")
            assert session == "session-1"
            events = [
                event
                async for event in provider.send_turn(
                    session, [{"role": "user", "content": "read a.txt"}]
                )
            ]
            types = [event.type for event in events]
            assert types[0] == "turn_started"
            assert any(e.type == "message" and e.payload["text"] == "hello world" for e in events)
            assert any(e.type == "tool_call" and e.payload["name"] == "Read" for e in events)
            assert any(e.type == "tool_result" and e.payload["content"] == "file text" for e in events)
            assert any(e.type == "usage" and e.payload["prompt_tokens"] == 9 for e in events)
            assert types[-1] == "turn_completed"
            await provider.interrupt(session)
        finally:
            await provider.close()

    asyncio.run(run())
