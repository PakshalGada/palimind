"""Tests for the in-memory agent activity feed."""

from __future__ import annotations

from palimind.agents import activity


def setup_function() -> None:
    activity.clear()


def test_activity_lifecycle() -> None:
    activity.start("a1", "Nova", "run1", "_scheduled")
    snap = activity.snapshot()
    assert snap["running"][0]["agent_id"] == "a1"
    assert snap["running"][0]["source"] == "scheduled"

    activity.step("a1", "Searching web: 'x'", "tool")
    assert activity.snapshot()["running"][0]["step"].startswith("Searching")

    activity.finish("a1", "success", "done")
    snap = activity.snapshot()
    assert snap["running"] == []
    assert any(e["type"] == "finish" for e in snap["recent"])


def test_step_without_start_does_not_create_running() -> None:
    activity.step("ghost", "hello")
    snap = activity.snapshot()
    assert snap["running"] == []
    assert any(e["type"] == "step" for e in snap["recent"])


def test_recent_wire_is_bounded() -> None:
    for i in range(activity._RECENT_LIMIT + 25):
        activity.step("a2", f"step {i}")
    assert len(activity.snapshot()["recent"]) <= activity._RECENT_LIMIT


def test_activity_endpoint() -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    client = TestClient(server.app)
    resp = client.get("/api/agents/activity")
    assert resp.status_code == 200
    body = resp.json()
    assert "running" in body
    assert "recent" in body
