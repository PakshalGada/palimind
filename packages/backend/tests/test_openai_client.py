"""Tests for the native OpenAI-compatible hosted baseline client."""

from __future__ import annotations

import json

import httpx

from palimind.agents.openai_client import is_openai_endpoint, openai_chat_safe
from palimind.llm.mixture_of_expert.llm import _normalize_tool_calls


def test_openai_client_sends_native_tools_and_tool_roles() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.update(payload)
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "I will search.",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"query": "benchmark"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            },
        )

    result = openai_chat_safe(
        [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_0",
                        "type": "function",
                        "function": {"name": "todo_write", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_0", "content": "ok"},
        ],
        "grok-4.7",
        "https://example.test/v1",
        api_key="test-key",
        tools=[{"type": "function", "function": {"name": "web_search", "parameters": {}}}],
        transport=httpx.MockTransport(handler),
    )
    assert seen["model"] == "grok-4.7"
    assert seen["tool_choice"] == "auto"
    assert seen["messages"][-1] == {"role": "tool", "tool_call_id": "call_0", "content": "ok"}
    assert result["content"] == "I will search."
    assert result["tool_calls"][0]["id"] == "call_1"
    assert result["tool_calls"][0]["openai"] is True
    assert result["tool_calls"][0]["name"] == "web_search"
    assert result["tool_calls"][0]["arguments"] == {"query": "benchmark"}
    assert result["usage"] == {"prompt_tokens": 12, "completion_tokens": 7}


def test_openai_client_returns_errors_as_content() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    result = openai_chat_safe(
        [{"role": "user", "content": "hi"}],
        "grok-4.7",
        "https://example.test/v1",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    assert result["tool_calls"] == []
    assert "HTTP 429" in result["content"]


def test_openai_client_preserves_json_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    result = openai_chat_safe(
        [{"role": "user", "content": "json please"}],
        "grok-4.7",
        "https://example.test/v1",
        api_key="test-key",
        format="json",
        transport=httpx.MockTransport(handler),
    )
    assert result["content"] == "{}"


def test_normalize_tool_calls_keeps_ollama_format_compact() -> None:
    # Ollama may include an id, but its chat API expects the compact transcript.
    calls = _normalize_tool_calls(
        {
            "tool_calls": [
                {
                    "id": "call_9",
                    "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'},
                }
            ]
        }
    )
    assert calls == [{"name": "read_file", "arguments": {"path": "a.txt"}}]


def test_is_openai_endpoint_skips_local_ollama() -> None:
    assert is_openai_endpoint("https://opencode.ai/zen/go/v1")
    assert not is_openai_endpoint("http://127.0.0.1:11434")
    assert not is_openai_endpoint("http://localhost:11434")
