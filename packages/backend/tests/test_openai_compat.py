"""Tests for the OpenAI-compatible local API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from palimind import openai_compat


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    # Keep model routing local and deterministic in tests.
    monkeypatch.setattr(
        "palimind.opencode.router.resolve_model_url",
        lambda model, url: url,
    )
    monkeypatch.setattr(
        openai_compat,
        "_models",
        lambda cfg=None: [
            {"id": "local-model", "object": "model", "created": 0, "owned_by": "local"}
        ],
    )
    yield


def test_models_endpoint() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "local-model"

    one = client.get("/v1/models/local-model")
    assert one.status_code == 200
    assert one.json()["id"] == "local-model"


def test_chat_completions_non_stream_maps_messages_and_tools(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    captured: dict = {}

    def fake_chat(messages, model, url, **kwargs):
        captured.update({"messages": messages, "model": model, "url": url, "kwargs": kwargs})
        return {
            "content": "hello",
            "tool_calls": [],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }

    monkeypatch.setattr(openai_compat, "llm_chat", fake_chat)
    client = TestClient(server.app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "local-model",
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q":"x"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "result"},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "search",
                        "description": "Search",
                        "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                    },
                }
            ],
            "temperature": 0.2,
            "max_tokens": 10,
            "stream": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hello"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 2,
        "total_tokens": 7,
    }
    assert captured["messages"][0] == {"role": "system", "content": "be brief"}
    assert captured["messages"][1] == {"role": "user", "content": "hi"}
    assert captured["messages"][2]["tool_calls"][0]["function"]["arguments"] == {"q": "x"}
    assert captured["messages"][3]["content"].startswith("Tool result (c1):")
    assert captured["kwargs"]["tools"][0]["function"]["name"] == "search"
    assert captured["kwargs"]["temperature"] == 0.2
    assert captured["kwargs"]["num_predict"] == 10


def test_chat_completions_maps_tool_calls(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    def fake_chat(messages, model, url, **kwargs):
        return {
            "content": "",
            "tool_calls": [{"name": "search", "arguments": {"q": "x"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }

    monkeypatch.setattr(openai_compat, "llm_chat", fake_chat)
    client = TestClient(server.app)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "local-model", "messages": [{"role": "user", "content": "hi"}]},
    )
    body = response.json()
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    call = body["choices"][0]["message"]["tool_calls"][0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "search"
    assert json.loads(call["function"]["arguments"]) == {"q": "x"}


def test_chat_completions_stream(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    def fake_stream(messages, model, url, **kwargs):
        yield {"type": "token", "text": "hel"}
        yield {"type": "token", "text": "lo"}
        yield {"type": "usage", "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
        yield {"type": "done"}

    monkeypatch.setattr(openai_compat, "llm_chat_stream", fake_stream)
    client = TestClient(server.app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "local-model",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    )
    assert response.status_code == 200
    text = response.text
    assert "chat.completion.chunk" in text
    assert '"content": "hel"' in text
    assert '"content": "lo"' in text
    assert '"finish_reason": "stop"' in text
    assert '"total_tokens": 5' in text
    assert text.endswith("data: [DONE]\n\n")


def test_embeddings(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    def fake_embeddings(texts, url, model, root=None):
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(openai_compat, "generate_embeddings_batch", fake_embeddings)
    client = TestClient(server.app)
    response = client.post(
        "/v1/embeddings",
        json={"model": "embed", "input": ["one", "two"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert [item["index"] for item in body["data"]] == [0, 1]
    assert body["data"][0]["embedding"] == [0.1, 0.2, 0.3]
    assert body["usage"]["prompt_tokens"] >= 2


def test_v1_requires_bearer_token(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    monkeypatch.setenv("PALIMIND_API_TOKEN", "secret-token")
    monkeypatch.delenv("PALIMIND_AUTH_DISABLED", raising=False)
    monkeypatch.setattr("palimind.security.auth.auth_disabled", lambda: False)

    client = TestClient(server.app)
    assert client.get("/v1/models").status_code == 401
    assert (
        client.get("/v1/models", headers={"Authorization": "Bearer secret-token"}).status_code
        == 200
    )


def test_real_openai_sdk_client(monkeypatch) -> None:
    """Exercise the endpoint with the actual OpenAI Python client."""
    import asyncio

    import httpx
    from openai import AsyncOpenAI

    import palimind.api_server as server

    def fake_chat(messages, model, url, **kwargs):
        return {
            "content": "sdk says hi",
            "tool_calls": [],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3},
        }

    monkeypatch.setattr(openai_compat, "llm_chat", fake_chat)

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            client = AsyncOpenAI(
                api_key="local-test",
                base_url="http://test/v1",
                http_client=http_client,
            )
            models = await client.models.list()
            assert models.data[0].id == "local-model"

            result = await client.chat.completions.create(
                model="local-model",
                messages=[{"role": "user", "content": "hello"}],
            )
            assert result.choices[0].message.content == "sdk says hi"
            assert result.usage.total_tokens == 7

    asyncio.run(scenario())
