"""Side-by-side model comparison stream (/api/compare/stream)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest


class FakeResponder:
    """Deterministic two-model responder injected into the compare stream."""

    def __init__(self):
        self.calls = []

    def stream(self, query, chat_model, system_prompt):
        self.calls.append((query, chat_model, system_prompt))
        if chat_model == "model-broken":
            raise RuntimeError("model exploded")

        def gen():
            yield f"[{chat_model}] part one "
            yield f"[{chat_model}] part two"

        return gen()


@pytest.fixture()
def responder(monkeypatch):
    fake = FakeResponder()

    def fake_generate(**kwargs):
        return fake.stream(
            kwargs["query"], kwargs["chat_model"], kwargs.get("system_prompt", "")
        )

    async def fake_aiter(stream):
        for token in stream:
            yield token

    import palimind.api_server as api_server

    monkeypatch.setattr(
        "palimind.generative.responder.generate_response_stream", fake_generate
    )
    monkeypatch.setattr("palimind.generative.responder.aiter_stream", fake_aiter)
    return fake


def _parse_events(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


def test_compare_streams_both_models(responder) -> None:
    from palimind.api_server import compare_stream

    async def body_iter():
        response = await compare_stream(q="hello", model="model-a", model2="model-b")
        async for chunk in response.body_iterator:
            yield chunk

    async def collect():
        return "".join([chunk async for chunk in body_iter()])

    body = asyncio.run(collect())
    events = _parse_events(body)
    types = [e["type"] for e in events]
    assert types.count("done") == 1
    assert events[-1]["type"] == "done"
    left_text = "".join(e["text"] for e in events if e["type"] == "left" and "text" in e)
    right_text = "".join(e["text"] for e in events if e["type"] == "right" and "text" in e)
    assert left_text == "[model-a] part one [model-a] part two"
    assert right_text == "[model-b] part one [model-b] part two"
    assert {(call[1]) for call in responder.calls} == {"model-a", "model-b"}
    assert all(call[2] for call in responder.calls), "system prompt is used"


def test_compare_reports_model_error_without_killing_the_other(responder, monkeypatch) -> None:
    from palimind.api_server import compare_stream

    async def run():
        response = await compare_stream(q="hi", model="model-broken", model2="model-b")
        return "".join([chunk async for chunk in response.body_iterator])

    events = _parse_events(asyncio.run(run()))
    left_error = next(e for e in events if e["type"] == "left" and "error" in e)
    assert "model-broken" in left_error["error"]
    right_text = "".join(e["text"] for e in events if e["type"] == "right" and "text" in e)
    assert "[model-b]" in right_text
