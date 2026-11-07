"""ACP protocol fixture tests. No provider CLI or model is started."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from palimind.agents.providers.acp import ACPProvider

FIXTURE = Path(__file__).parent / "fixtures" / "acp_server.py"


def test_acp_models_session_and_stream() -> None:
    async def run():
        provider = ACPProvider(
            "acp-fixture",
            command=sys.executable,
            args=[str(FIXTURE)],
            request_timeout=10.0,
        )
        try:
            models = await provider.list_models()
            assert [m.id for m in models] == ["fixture-1"]
            session_id = await provider.start_session("thread-1")
            assert session_id == "sess-1"
            events = [
                event
                async for event in provider.send_turn(
                    session_id, [{"role": "user", "content": "hi"}]
                )
            ]
            types = [event.type for event in events]
            assert types[0] == "turn_started"
            assert "message_delta" in types
            assert "tool_call" in types
            assert "tool_result" in types
            assert "usage" in types
            assert types[-1] == "turn_completed"
            await provider.interrupt(session_id)
        finally:
            await provider.close()

    asyncio.run(run())


def test_acp_requires_a_command() -> None:
    async def run():
        provider = ACPProvider("acp-empty", command="")
        try:
            await provider.start_session("thread-1")
        except Exception as exc:  # noqa: BLE001
            assert "PALIMIND_ACP_COMMAND" in str(exc)
        else:
            raise AssertionError("expected a missing-command error")
        finally:
            await provider.close()

    asyncio.run(run())
