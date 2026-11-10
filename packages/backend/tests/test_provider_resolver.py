"""Provider resolver tests. No network, no model, no key required."""

from __future__ import annotations

from palimind.agents.catalog import AgentDefinition
from palimind.agents.providers import resolver


def _agent(**kwargs) -> AgentDefinition:
    base = AgentDefinition.new("resolver-test", display_name="Resolver")
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base


def test_local_provider(monkeypatch) -> None:
    monkeypatch.setattr(resolver, "_opencode_key", lambda: "key")
    resolved = resolver.resolve_agent_model(
        _agent(provider="ollama", model="qwen3.5:4b"),
        global_chat_model="llama3",
        ollama_url="http://localhost:11434",
    )
    assert resolved.ok
    assert resolved.provider == "ollama"
    assert resolved.base_url == "http://localhost:11434"


def test_opencode_with_key(monkeypatch) -> None:
    monkeypatch.setattr(resolver, "_opencode_key", lambda: "key")
    monkeypatch.setattr("palimind.opencode.router.opencode_model_ids", lambda: {"grok-4.7"})
    resolved = resolver.resolve_agent_model(
        _agent(provider="opencode", model="grok-4.7"),
        global_chat_model="llama3",
    )
    assert resolved.ok
    assert resolved.provider == "opencode"
    assert resolved.api_key == "key"


def test_opencode_missing_key_is_actionable(monkeypatch) -> None:
    monkeypatch.setattr(resolver, "_opencode_key", lambda: "")
    resolved = resolver.resolve_agent_model(
        _agent(provider="opencode", model="grok-4.7"),
        global_chat_model="llama3",
    )
    assert not resolved.ok
    assert resolved.error == "missing_key"
    assert resolved.action == "add-key"


def test_legacy_agent_infers_provider(monkeypatch) -> None:
    monkeypatch.setattr(resolver, "_opencode_key", lambda: "key")
    monkeypatch.setattr("palimind.opencode.router.opencode_model_ids", lambda: {"grok-4.7"})
    monkeypatch.setattr(
        "palimind.opencode.router.resolve_model_url",
        lambda model, url: "http://localhost:11435",
    )
    resolved = resolver.resolve_agent_model(
        _agent(provider="", model="grok-4.7"),
        global_chat_model="llama3",
    )
    assert resolved.provider == "opencode"
    assert resolved.base_url == "http://localhost:11435"
