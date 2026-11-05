"""Tests for persisted SSE events and Last-Event-ID replay."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from palimind.events import hub, store
from palimind.events.sse import format_event, parse_data


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    yield


def test_store_assigns_monotonic_ids_and_replays_after_id() -> None:
    first = store.append("global", {"type": "one"})
    second = store.append("global", {"type": "two"})
    third = store.append("global", {"type": "three"})
    assert first["event_id"] < second["event_id"] < third["event_id"]

    missed = store.replay("global", second["event_id"])
    assert [event["type"] for event in missed] == ["three"]
    assert store.latest_id("global") == third["event_id"]


def test_hub_persists_and_fans_out() -> None:
    async def scenario() -> int:
        queue = await hub.subscribe("probe")
        try:
            published = await hub.publish("probe", {"type": "hello"})
            received = await asyncio.wait_for(queue.get(), timeout=2)
            assert received["event_id"] == published["event_id"]
            return published["event_id"]
        finally:
            await hub.unsubscribe("probe", queue)

    event_id = asyncio.run(scenario())
    assert store.replay("probe", 0)[0]["event_id"] == event_id


def test_format_and_parse_roundtrip() -> None:
    frame = format_event({"event_id": 7, "type": "token", "text": "hi"})
    assert frame.startswith("id: 7\n")
    assert parse_data(frame) == {"type": "token", "text": "hi"}


def test_global_events_replay_with_last_event_id() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    async def publish_all() -> list[int]:
        ids = []
        for i in range(3):
            event = await asyncio.to_thread(
                store.append, "global", {"type": "indexing_progress", "n": i}
            )
            ids.append(event["event_id"])
        return ids

    ids = asyncio.run(publish_all())
    client = TestClient(server.app)
    response = client.get(
        "/api/events?once=true",
        headers={"Last-Event-ID": str(ids[0])},
    )
    assert response.status_code == 200
    body = response.text
    assert f"id: {ids[1]}" in body
    assert f"id: {ids[2]}" in body
    assert f"id: {ids[0]}" not in body


def test_stream_events_replay_after_missed_frames() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    async def publish() -> tuple[int, int]:
        first = await hub.publish("chat:abc", {"type": "session", "id": "s1", "stream_id": "abc"})
        second = await hub.publish("chat:abc", {"type": "token", "text": "hello"})
        return first["event_id"], second["event_id"]

    first_id, second_id = asyncio.run(publish())
    client = TestClient(server.app)
    response = client.get(
        "/api/streams/abc/events?tail=false",
        headers={"Last-Event-ID": str(first_id)},
    )
    assert response.status_code == 200
    assert f"id: {second_id}" in response.text
    assert '"text": "hello"' in response.text
    assert f"id: {first_id}" not in response.text


def test_chat_frames_are_persisted_for_replay() -> None:
    import json

    import palimind.api_server as server

    async def inner():
        yield 'data: {"type": "token", "text": "hi"}\n\n'

    async def scenario() -> list[str]:
        entry = server._ChatStreamEntry(stream_id="chatreplay")
        frames = []
        async for frame in server._tracked_chat_sse(entry, inner()):
            frames.append(frame)
        return frames

    frames = asyncio.run(scenario())
    assert any(frame.startswith("id: ") for frame in frames)
    events = store.replay("chat:chatreplay", 0)
    assert [event["type"] for event in events] == ["session", "token"]
    assert events[1]["text"] == "hi"
    assert events[1]["event_id"] > events[0]["event_id"]

    # A reconnect from the session event receives only the token frame.
    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    response = client.get(
        "/api/streams/chatreplay/events?tail=false",
        headers={"Last-Event-ID": str(events[0]["event_id"])},
    )
    assert response.status_code == 200
    assert json.dumps("hi", ensure_ascii=False) in response.text
    assert f"id: {events[1]['event_id']}" in response.text
