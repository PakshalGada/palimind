"""Hidden skill prompts must not leak into the stored conversation."""

from __future__ import annotations

import asyncio
from pathlib import Path

from palimind.llm import stream as stream_mod
from palimind.memory.session_store import add_new_session, load_sessions


def test_skill_prompt_is_hidden_but_query_is_persisted(tmp_path: Path, monkeypatch) -> None:
    from palimind.generative import responder

    sessions = add_new_session(tmp_path, "skill turn")
    session_id = sessions["active_session_id"]

    def fake_generate_response_stream(**_kwargs):
        return iter(["Here is your document."])

    async def fake_background_memory(*_args, **_kwargs):
        return None

    monkeypatch.setattr(responder, "generate_response_stream", fake_generate_response_stream)
    monkeypatch.setattr(stream_mod, "background_update_memory", fake_background_memory)

    async def consume() -> None:
        response = await stream_mod.llm_mode_stream(
            "You are the /docx skill. Return one fenced markdown block.\n\nUSER REQUEST\nQ3 review",
            session_id,
            [],
            "",
            None,
            "http://localhost:11434",
            "test-model",
            tmp_path,
            "false",
            display_text="Q3 review",
        )
        async for _chunk in response.body_iterator:
            pass

    asyncio.run(consume())

    stored = load_sessions(tmp_path)
    messages = stored["sessions"][0]["messages"]
    user_messages = [message["content"] for message in messages if message["role"] == "user"]
    assert user_messages == ["Q3 review"]
    assert "docx skill" not in user_messages[0]
    assert any(message["role"] == "system" for message in messages)
