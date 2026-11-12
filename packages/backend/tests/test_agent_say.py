"""Tests for the agent's short chat messages (`say`)."""

from __future__ import annotations


def test_say_emits_a_chat_message(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import tools

    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        tools,
        "_get_context",
        lambda: {"emit_event": lambda kind, payload: emitted.append((kind, payload))},
    )

    result = tools.say("  On it —   checking the three filings.  ")

    assert result == "Message sent."
    assert emitted == [("agent:message", {"text": "On it — checking the three filings."})]


def test_say_trims_and_rejects_empty(monkeypatch) -> None:
    from palimind.llm.mixture_of_expert import tools

    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        tools,
        "_get_context",
        lambda: {"emit_event": lambda kind, payload: emitted.append((kind, payload))},
    )

    assert tools.say("   ").startswith("Error:")
    assert emitted == []


def test_say_is_always_available() -> None:
    from palimind.agents.catalog import AgentDefinition
    from palimind.llm.mixture_of_expert.tools import TOOL_REGISTRY

    assert "say" in TOOL_REGISTRY
    definition = AgentDefinition.new("plain", tool_pack="custom")
    definition.tools = ["read_file"]
    from palimind.llm.mixture_of_expert.agents import _tool_allowed

    assert _tool_allowed("say", {"tools": ["read_file"]}, definition) is True
    assert _tool_allowed("write_file", {"tools": ["read_file"]}, definition) is False


def test_team_chat_style_keeps_replies_short() -> None:
    from palimind.agents.catalog import AgentDefinition
    from palimind.agents.service import chat_style_for

    style = chat_style_for(AgentDefinition.new("teammate", personality_style="Warm"), team=True)
    assert "TEAM CHAT" in style
    assert "one or two sentences" in style
    assert "Warm" in style
